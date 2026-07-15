import json

import pytest
from skyfield.api import load

from sattransit.elements import _NOT_UPDATED, _build_satellite, parse_records

# A real CelesTrak OMM record (FORMAT=json), used verbatim as a shape reference.
ISS = {
    "OBJECT_NAME": "ISS (ZARYA)",
    "OBJECT_ID": "1998-067A",
    "EPOCH": "2026-07-15T09:06:13.253184",
    "MEAN_MOTION": 15.49014944,
    "ECCENTRICITY": 0.00067175,
    "INCLINATION": 51.631,
    "RA_OF_ASC_NODE": 160.5727,
    "ARG_OF_PERICENTER": 298.6245,
    "MEAN_ANOMALY": 61.4067,
    "EPHEMERIS_TYPE": 0,
    "CLASSIFICATION_TYPE": "U",
    "NORAD_CAT_ID": 25544,
    "ELEMENT_SET_NO": 999,
    "REV_AT_EPOCH": 57612,
    "BSTAR": 7.7082068e-05,
    "MEAN_MOTION_DOT": 3.801e-05,
    "MEAN_MOTION_DDOT": 0,
}


@pytest.fixture(scope="module")
def ts():
    return load.timescale()


def test_accepts_real_omm_json():
    assert parse_records(json.dumps([ISS])) == [ISS]


def test_rejects_celestrak_invalid_query_notice():
    # CelesTrak answers an unknown group with prose and HTTP 200.
    assert parse_records('Invalid query: "GROUP=nope&FORMAT=json" (GROUP=nope not found)') is None


def test_rejects_celestrak_not_updated_notice():
    # The other prose reply: a repeat download inside the two-hour update cycle.
    notice = (
        "GP data has not updated since your last successful\n"
        "download of GROUP=starlink at 2026-07-15 19:16:21 UTC.\n"
        "Data is updated once every 2 hours."
    )
    assert parse_records(notice) is None
    assert _NOT_UPDATED in notice  # the caller must recognise this and keep the cache


def test_rejects_tle_text():
    assert parse_records("1 25544U 98067A   24001.50000000  .00016717  00000-0  30777-3 0  9993") is None


def test_rejects_empty_and_wrong_shapes():
    assert parse_records("") is None
    assert parse_records("[]") is None
    assert parse_records("{}") is None
    assert parse_records('{"OBJECT_NAME": "ISS"}') is None
    assert parse_records('["not a record"]') is None


def test_rejects_records_missing_required_fields():
    incomplete = {k: v for k, v in ISS.items() if k != "MEAN_MOTION"}
    assert parse_records(json.dumps([incomplete])) is None


def test_builds_satellite_from_omm(ts):
    satellite = _build_satellite(ISS, ts, "stations")
    assert satellite.name == "ISS (ZARYA)"
    assert satellite.model.satnum == 25544
    epoch = satellite.epoch.utc_datetime()
    assert (epoch.year, epoch.month, epoch.day, epoch.hour) == (2026, 7, 15, 9)
    assert epoch.microsecond == pytest.approx(253184, abs=2)


def test_epoch_without_fractional_seconds_is_accepted(ts):
    # sgp4's OMM reader demands a fractional part; a whole-second epoch must not
    # blow up the whole run.
    record = {**ISS, "EPOCH": "2026-07-15T09:06:13"}
    satellite = _build_satellite(record, ts, "stations")
    assert satellite.epoch.utc_datetime().second == 13


def test_six_digit_catalog_number_survives(ts):
    # The point of moving off TLE: identifiers beyond five digits.
    satellite = _build_satellite({**ISS, "NORAD_CAT_ID": 270123}, ts, "stations")
    assert satellite.model.satnum == 270123


def test_unusable_record_names_the_satellite(ts):
    with pytest.raises(Exception, match="ISS"):
        _build_satellite({**ISS, "EPOCH": "not-a-date"}, ts, "stations")
