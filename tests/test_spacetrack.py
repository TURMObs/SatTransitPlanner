"""Tests for the Space-Track source.

The live request cannot be exercised here — it needs an account — so these
cover everything up to and including what would go on the wire.
"""

import json
import urllib.parse
from datetime import datetime, timezone

import pytest
from skyfield.api import load

from sattransit import spacetrack
from sattransit.config import SpaceTrackConfig
from sattransit.elements import CatalogEntry
from sattransit.spacetrack import (
    ENV_IDENTITY,
    ENV_PASSWORD,
    SOURCE_NAME,
    SpaceTrackError,
    credentials,
    load_rocket_bodies,
    merge,
    query_path,
)

# A Space-Track 'gp' record: the same OMM field names CelesTrak uses, but every
# value is a string.
RECORD = {
    "OBJECT_NAME": "SL-16 R/B",
    "OBJECT_ID": "1993-016B",
    "EPOCH": "2026-07-15T09:06:13.253184",
    "MEAN_MOTION": "14.63054768",
    "ECCENTRICITY": "0.00021340",
    "INCLINATION": "71.0058",
    "RA_OF_ASC_NODE": "150.6377",
    "ARG_OF_PERICENTER": "110.4362",
    "MEAN_ANOMALY": "249.7028",
    "EPHEMERIS_TYPE": "0",
    "CLASSIFICATION_TYPE": "U",
    "NORAD_CAT_ID": "22566",
    "ELEMENT_SET_NO": "999",
    "REV_AT_EPOCH": "12345",
    "BSTAR": "0.00012345",
    "MEAN_MOTION_DOT": "0.00000123",
    "MEAN_MOTION_DDOT": "0",
    "OBJECT_TYPE": "ROCKET BODY",
}
REFERENCE = datetime(2026, 7, 16, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def ts():
    return load.timescale()


@pytest.fixture
def config():
    return SpaceTrackConfig(enabled=True)


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch):
    monkeypatch.delenv(ENV_IDENTITY, raising=False)
    monkeypatch.delenv(ENV_PASSWORD, raising=False)


# --- the query ---------------------------------------------------------------


def test_the_query_asks_only_for_rocket_bodies_in_low_orbit(config):
    path = urllib.parse.unquote(query_path(config))
    assert "/OBJECT_TYPE/ROCKET BODY" in path
    assert "/MEAN_MOTION/>11.25" in path  # a period under ~128 min
    assert "/DECAY_DATE/null-val" in path  # still in orbit
    assert "/class/gp" in path


def test_the_low_orbit_cut_is_configurable(config):
    config.min_mean_motion = 12.0
    assert "/MEAN_MOTION/>12.0" in urllib.parse.unquote(query_path(config))


def test_the_query_is_a_well_formed_url(config):
    # Space-Track answered 400 when this carried a raw space and a raw '>'.
    path = query_path(config)
    assert " " not in path
    assert "ROCKET%20BODY" in path
    assert "%3E11.25" in path
    assert "%25" not in path  # escaped once, not twice


def test_login_and_query_are_separate_requests(config, monkeypatch):
    # Passing the query alongside the login nests a URL inside a form field,
    # where it has to survive being escaped twice. Fetch the URL instead.
    calls = []

    class FakeOpener:
        addheaders = []

        def open(self, url, data=None, timeout=None):
            calls.append((url, data))
            raise AssertionError("stop here")

    monkeypatch.setattr(spacetrack.urllib.request, "build_opener", lambda *a: FakeOpener())
    with pytest.raises(AssertionError):
        spacetrack._fetch(config, "someone", "secret")

    url, data = calls[0]
    assert url.endswith("/ajaxauth/login")
    assert "password=secret" in data.decode()
    assert "query=" not in data.decode()  # no URL nested in the form


def test_the_password_never_reaches_the_url(config, monkeypatch):
    calls = []

    class FakeOpener:
        addheaders = []

        def open(self, url, data=None, timeout=None):
            calls.append(url)
            raise AssertionError("stop here")

    monkeypatch.setattr(spacetrack.urllib.request, "build_opener", lambda *a: FakeOpener())
    with pytest.raises(AssertionError):
        spacetrack._fetch(config, "someone@example.org", "hunter2")
    assert all("hunter2" not in url for url in calls)


def test_an_error_repeats_what_space_track_said(config, monkeypatch):
    # Their message is the only thing that explains a 400, so it must survive.
    import io
    import urllib.error

    class FakeOpener:
        addheaders = []

        def open(self, url, data=None, timeout=None):
            raise urllib.error.HTTPError(
                url, 400, "Bad Request", {}, io.BytesIO(b"invalid predicate for class gp")
            )

    monkeypatch.setattr(spacetrack.urllib.request, "build_opener", lambda *a: FakeOpener())
    with pytest.raises(SpaceTrackError, match="invalid predicate"):
        spacetrack._fetch(config, "someone", "hunter2")


def test_an_error_body_cannot_leak_the_password(config, monkeypatch):
    # A 400 can echo the request back, password and all.
    import io
    import urllib.error

    class FakeOpener:
        addheaders = []

        def open(self, url, data=None, timeout=None):
            raise urllib.error.HTTPError(
                url, 400, "Bad", {}, io.BytesIO(b"bad request: password=hunter2 rejected")
            )

    monkeypatch.setattr(spacetrack.urllib.request, "build_opener", lambda *a: FakeOpener())
    with pytest.raises(SpaceTrackError) as excinfo:
        spacetrack._fetch(config, "someone", "hunter2")
    assert "hunter2" not in str(excinfo.value)
    assert "***" in str(excinfo.value)


def test_a_refused_login_is_reported_before_the_query(config, monkeypatch):
    # Space-Track answers a bad login with 200 and a body saying so.
    class FakeOpener:
        addheaders = []

        def open(self, url, data=None, timeout=None):
            assert url.endswith("/ajaxauth/login"), "must not query after a refused login"
            return _Response(b'{"Login":"Failed"}')

    monkeypatch.setattr(spacetrack.urllib.request, "build_opener", lambda *a: FakeOpener())
    with pytest.raises(SpaceTrackError, match="refused the login"):
        spacetrack._fetch(config, "someone", "wrong")


class _Response:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# --- credentials -------------------------------------------------------------


def test_credentials_come_from_the_environment(monkeypatch):
    monkeypatch.setenv(ENV_IDENTITY, "someone@example.org")
    monkeypatch.setenv(ENV_PASSWORD, "secret")
    assert credentials() == ("someone@example.org", "secret")


@pytest.mark.parametrize("present", [{}, {ENV_IDENTITY: "x"}, {ENV_PASSWORD: "y"}])
def test_missing_credentials_say_what_to_set(monkeypatch, present):
    for key, value in present.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SpaceTrackError, match=ENV_IDENTITY):
        credentials()


# --- loading -----------------------------------------------------------------


def test_records_become_catalogue_entries(config, tmp_path, ts):
    (tmp_path / spacetrack.CACHE_FILE).write_text(json.dumps([RECORD]))
    entries, source, stale = load_rocket_bodies(config, tmp_path, ts, REFERENCE, 14.0)
    assert [e.norad_id for e in entries] == [22566]
    assert entries[0].satellite.name == "SL-16 R/B"
    assert entries[0].groups == [SOURCE_NAME]
    assert entries[0].international_designator == "1993-016B"
    assert source.satellite_count == 1
    assert stale == []


def test_old_elements_are_reported_not_searched(config, tmp_path, ts):
    (tmp_path / spacetrack.CACHE_FILE).write_text(json.dumps([RECORD]))
    entries, _, stale = load_rocket_bodies(config, tmp_path, ts, REFERENCE, max_element_age_days=0.1)
    assert entries == []
    assert stale == [22566]


def test_a_fresh_cache_is_not_downloaded_again(config, tmp_path, ts, monkeypatch):
    (tmp_path / spacetrack.CACHE_FILE).write_text(json.dumps([RECORD]))
    monkeypatch.setattr(
        spacetrack, "_fetch", lambda *a: pytest.fail("should not have contacted Space-Track")
    )
    entries, _, _ = load_rocket_bodies(config, tmp_path, ts, REFERENCE, 14.0)
    assert len(entries) == 1


def test_offline_without_a_cache_is_reported(config, tmp_path, ts):
    with pytest.raises(SpaceTrackError, match="offline"):
        load_rocket_bodies(config, tmp_path, ts, REFERENCE, 14.0, offline=True)


def test_a_corrupt_cache_is_reported(config, tmp_path, ts):
    (tmp_path / spacetrack.CACHE_FILE).write_text("{not json")
    with pytest.raises(SpaceTrackError, match="not valid OMM JSON"):
        load_rocket_bodies(config, tmp_path, ts, REFERENCE, 14.0)


def test_a_login_page_instead_of_elements_is_reported(config, tmp_path, ts, monkeypatch):
    # What a rejected login actually gives back: HTML, with a 200.
    monkeypatch.setenv(ENV_IDENTITY, "someone")
    monkeypatch.setenv(ENV_PASSWORD, "wrong")
    monkeypatch.setattr(spacetrack, "_fetch", lambda *a: "<html>Login</html>")
    with pytest.raises(SpaceTrackError, match="did not return orbital elements"):
        load_rocket_bodies(config, tmp_path, ts, REFERENCE, 14.0)
    assert not (tmp_path / spacetrack.CACHE_FILE).exists()  # never cache a refusal


def test_a_download_is_cached(config, tmp_path, ts, monkeypatch):
    monkeypatch.setenv(ENV_IDENTITY, "someone")
    monkeypatch.setenv(ENV_PASSWORD, "secret")
    monkeypatch.setattr(spacetrack, "_fetch", lambda *a: json.dumps([RECORD]))
    entries, source, _ = load_rocket_bodies(config, tmp_path, ts, REFERENCE, 14.0)
    assert len(entries) == 1
    assert json.loads((tmp_path / spacetrack.CACHE_FILE).read_text())[0]["NORAD_CAT_ID"] == "22566"
    assert source.from_cache is False


# --- merging -----------------------------------------------------------------


def _entry(norad, name="X"):
    return CatalogEntry(
        satellite=type("S", (), {"name": name})(),
        groups=["active"],
        norad_id=norad,
        international_designator=None,
    )


def test_merge_adds_only_what_celestrak_lacks():
    entries = [_entry(100), _entry(300)]
    extra = [_entry(200, "SL-16 R/B"), _entry(400, "CZ-2F R/B")]
    assert merge(entries, extra) == 2
    assert [e.norad_id for e in entries] == [100, 200, 300, 400]  # sorted


def test_merge_keeps_the_celestrak_copy_of_a_shared_object():
    # The same object from both sources: one entry, and CelesTrak's groups kept.
    entries = [_entry(100, "FROM CELESTRAK")]
    added = merge(entries, [_entry(100, "FROM SPACE-TRACK")])
    assert added == 0
    assert len(entries) == 1
    assert entries[0].groups == ["active"]


def test_merge_of_nothing_changes_nothing():
    entries = [_entry(100)]
    assert merge(entries, []) == 0
    assert len(entries) == 1
