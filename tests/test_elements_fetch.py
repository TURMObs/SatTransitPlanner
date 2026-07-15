"""Tests for the download/cache decisions, with CelesTrak stubbed out."""

import json

import pytest

from sattransit import elements
from sattransit.config import CelestrakConfig
from tests.test_elements import ISS

NOT_UPDATED_NOTICE = (
    "GP data has not updated since your last successful\n"
    "download of GROUP=stations at 2026-07-15 19:16:21 UTC.\n"
    "Data is updated once every 2 hours."
)
INVALID_QUERY_NOTICE = 'Invalid query: "GROUP=nope&FORMAT=json" (GROUP=nope not found)'


@pytest.fixture
def config():
    return CelestrakConfig(groups=["stations"], max_age_days=1.0)


def stub_fetch(monkeypatch, response):
    calls = []

    def fake(url):
        calls.append(url)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(elements, "_fetch", fake)
    return calls


def obtain(config, tmp_path, force_refresh=False):
    return elements._obtain(
        config,
        "stations",
        "https://example.invalid/gp.php?GROUP=stations&FORMAT=json",
        tmp_path / "stations.json",
        force_refresh,
        lambda message: None,
    )


def test_fresh_download_is_cached(config, tmp_path, monkeypatch):
    stub_fetch(monkeypatch, json.dumps([ISS]))
    records, from_cache = obtain(config, tmp_path)

    assert from_cache is False
    assert records == [ISS]
    assert json.loads((tmp_path / "stations.json").read_text()) == [ISS]


def test_fresh_cache_is_used_without_any_download(config, tmp_path, monkeypatch):
    (tmp_path / "stations.json").write_text(json.dumps([ISS]))
    calls = stub_fetch(monkeypatch, json.dumps([ISS]))

    records, from_cache = obtain(config, tmp_path)
    assert from_cache is True and records == [ISS]
    assert calls == []  # CelesTrak must not be bothered for a fresh cache


def test_stale_cache_triggers_a_download(config, tmp_path, monkeypatch):
    cache = tmp_path / "stations.json"
    cache.write_text(json.dumps([ISS]))
    import os
    import time

    old = time.time() - 5 * 86400
    os.utime(cache, (old, old))

    calls = stub_fetch(monkeypatch, json.dumps([ISS]))
    _, from_cache = obtain(config, tmp_path)
    assert from_cache is False and len(calls) == 1


def test_celestrak_refusing_a_repeat_download_keeps_the_cache(config, tmp_path, monkeypatch):
    # CelesTrak serves each element set once per update cycle. Being told the
    # data has not changed confirms the cache is current; it is not an error.
    import os
    import time

    cache = tmp_path / "stations.json"
    cache.write_text(json.dumps([ISS]))
    old = time.time() - 5 * 86400
    os.utime(cache, (old, old))

    stub_fetch(monkeypatch, NOT_UPDATED_NOTICE)
    records, from_cache = obtain(config, tmp_path, force_refresh=True)

    assert records == [ISS]
    assert from_cache is True
    # The cache is marked fresh so the next run does not ask again.
    assert elements._age_days(cache) < 0.01


def test_celestrak_refusal_without_a_cache_is_an_error(config, tmp_path, monkeypatch):
    stub_fetch(monkeypatch, NOT_UPDATED_NOTICE)
    with pytest.raises(elements.ElementsError, match="already up to date"):
        obtain(config, tmp_path)


def test_invalid_group_is_an_error_and_is_not_cached(config, tmp_path, monkeypatch):
    stub_fetch(monkeypatch, INVALID_QUERY_NOTICE)
    with pytest.raises(elements.ElementsError, match="did not return orbital elements"):
        obtain(config, tmp_path)
    assert not (tmp_path / "stations.json").exists()


def test_a_bad_response_never_overwrites_good_cache(config, tmp_path, monkeypatch):
    (tmp_path / "stations.json").write_text(json.dumps([ISS]))
    stub_fetch(monkeypatch, INVALID_QUERY_NOTICE)

    with pytest.raises(elements.ElementsError):
        obtain(config, tmp_path, force_refresh=True)
    assert json.loads((tmp_path / "stations.json").read_text()) == [ISS]


def test_offline_uses_cache_without_fetching(tmp_path, monkeypatch):
    config = CelestrakConfig(groups=["stations"], max_age_days=1.0, offline=True)
    (tmp_path / "stations.json").write_text(json.dumps([ISS]))
    calls = stub_fetch(monkeypatch, json.dumps([ISS]))

    records, from_cache = obtain(config, tmp_path, force_refresh=True)
    assert records == [ISS] and from_cache is True
    assert calls == []


def test_offline_without_cache_is_an_error(tmp_path, monkeypatch):
    config = CelestrakConfig(groups=["stations"], max_age_days=1.0, offline=True)
    stub_fetch(monkeypatch, json.dumps([ISS]))
    with pytest.raises(elements.ElementsError, match="offline"):
        obtain(config, tmp_path)


def test_corrupt_cache_is_reported_clearly(config, tmp_path, monkeypatch):
    (tmp_path / "stations.json").write_text("{truncated")
    stub_fetch(monkeypatch, json.dumps([ISS]))
    with pytest.raises(elements.ElementsError, match="not valid OMM JSON"):
        obtain(config, tmp_path)
