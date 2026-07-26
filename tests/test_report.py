"""Tests for the result document."""

import json
import math
from datetime import datetime, timezone

import pytest

from sattransit.config import load_config
from sattransit.elements import Catalog
from sattransit.report import build_report

START = datetime(2026, 7, 16, 4, 0, tzinfo=timezone.utc)
END = datetime(2026, 7, 16, 20, 0, tzinfo=timezone.utc)


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        '{"observatory": {"name": "T", "latitude_deg": 48.0, "longitude_deg": 11.0},'
        ' "celestrak": {"groups": ["stations"]}}'
    )
    return load_config(path)


def _report(config):
    catalog = Catalog(entries=[], sources=[], skipped_stale=0)
    return build_report(config, catalog, [], START, END, 1.0)


def test_the_age_limit_is_recorded(config):
    assert _report(config)["search"]["max_element_age_days"] == 14.0


def test_an_ignored_age_limit_is_recorded_as_null(config):
    # --ignore-element-age lifts the limit to infinity internally.
    config.search.max_element_age_days = math.inf
    assert _report(config)["search"]["max_element_age_days"] is None


def test_the_document_stays_valid_json_when_the_limit_is_ignored(config):
    # json.dumps writes infinity as the bare token Infinity, which is not in
    # the JSON spec: a strict reader elsewhere would reject the whole file.
    config.search.max_element_age_days = math.inf
    text = json.dumps(_report(config))
    assert "Infinity" not in text
    json.loads(
        text,
        parse_constant=lambda name: (_ for _ in ()).throw(ValueError(name)),
    )


# --- the element-age uncertainty ---------------------------------------------


def _event():
    """A stand-in Event carrying only what the uncertainty block reads."""
    from types import SimpleNamespace

    entry = SimpleNamespace(
        satellite=SimpleNamespace(name="AQUA"),
        norad_id=27424,
        groups=["visual"],
        international_designator="2002-022A",
        epoch_utc=datetime(2026, 7, 13, 14, 43, 55, tzinfo=timezone.utc),  # 3 days old
    )
    return SimpleNamespace(
        entry=entry,
        is_transit=True,
        closest_time=datetime(2026, 7, 16, 14, 43, 55, tzinfo=timezone.utc),
        separation_deg=0.05,
        target_radius_deg=0.2625,
        position_angle_deg=48.0,
        satellite_altitude_deg=41.0,
        satellite_azimuth_deg=255.0,
        target_altitude_deg=41.0,
        target_azimuth_deg=255.0,
        range_km=600.0,
        angular_velocity_deg_per_s=0.44,
        motion_position_angle_deg=318.0,
        size=None,
        illumination=None,
        start_time=None,
        end_time=None,
        duration_seconds=None,
        path=[],
    )


def _one_event_report(config):
    catalog = Catalog(entries=[], sources=[], skipped_stale=0)
    return build_report(config, catalog, [_event()], START, END, 1.0)


def test_each_event_carries_its_uncertainty(config):
    doubt = _one_event_report(config)["events"][0]["uncertainty"]
    assert doubt["element_age_days"] == pytest.approx(3.0, abs=0.01)
    assert doubt["cross_track_arcsec"] > 0
    assert doubt["timing_seconds"] > 0
    assert doubt["could_miss"] is False  # well inside the disk


def test_the_uncertainty_can_be_switched_off(config):
    config.uncertainty.enabled = False
    assert _one_event_report(config)["events"][0]["uncertainty"] is None


def test_raising_the_rates_widens_the_band(config):
    narrow = _one_event_report(config)["events"][0]["uncertainty"]["cross_track_arcsec"]
    config.uncertainty.cross_track_km_per_day *= 10
    wide = _one_event_report(config)["events"][0]["uncertainty"]["cross_track_arcsec"]
    # The report rounds to a tenth of an arcsecond, so ten times a rounded
    # value is not exactly the rounded ten-times value.
    assert wide == pytest.approx(narrow * 10, abs=5.0)
