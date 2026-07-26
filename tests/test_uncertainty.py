"""Tests for the element-age uncertainty model."""

import math

import pytest

from sattransit.uncertainty import (
    ALONG_TRACK_KM_PER_DAY,
    CROSS_TRACK_KM_PER_DAY,
    estimate,
)

# A typical low-orbit transit: ~600 km away, crossing the sky at ~0.44 deg/s.
RANGE_KM = 600.0
RATE_DEG_PER_S = 0.44
SOLAR_RADIUS_ARCSEC = 945.0


def test_fresh_elements_carry_no_doubt():
    fresh = estimate(0.0, RANGE_KM, RATE_DEG_PER_S)
    assert fresh.cross_track_arcsec == 0.0
    assert fresh.timing_seconds == 0.0


def test_the_band_grows_with_the_age_of_the_elements():
    widths = [estimate(age, RANGE_KM, RATE_DEG_PER_S).cross_track_arcsec for age in (1, 3, 7)]
    assert widths == sorted(widths)
    # Linear in age, as the model states.
    assert widths[2] == pytest.approx(widths[0] * 7.0, rel=1e-9)


def test_the_band_matches_the_geometry_it_claims():
    # A cross-track error of d km at range R subtends d/R radians.
    age = 4.0
    band = estimate(age, RANGE_KM, RATE_DEG_PER_S)
    expected_km = CROSS_TRACK_KM_PER_DAY * age
    assert band.cross_track_km == pytest.approx(expected_km)
    assert band.cross_track_arcsec == pytest.approx(
        math.degrees(expected_km / RANGE_KM) * 3600.0, rel=1e-6
    )


def test_a_nearer_satellite_gets_a_wider_band():
    # The same error in kilometres subtends a larger angle when closer.
    near = estimate(3.0, 400.0, RATE_DEG_PER_S).cross_track_arcsec
    far = estimate(3.0, 1200.0, RATE_DEG_PER_S).cross_track_arcsec
    assert near > far
    assert near == pytest.approx(far * 3.0, rel=1e-9)


def test_along_track_becomes_a_timing_error():
    # Being 1.1 km along its own track, at LEO speed, is a fraction of a second.
    one_day = estimate(1.0, RANGE_KM, RATE_DEG_PER_S)
    assert one_day.along_track_km == pytest.approx(ALONG_TRACK_KM_PER_DAY)
    assert 0.05 < one_day.timing_seconds < 1.0


def test_timing_dominates_the_error_budget():
    # The measured rates make along-track ~20x cross-track; that is why a
    # predicted transit is usually missed by mistiming, not by sideways drift.
    band = estimate(3.0, RANGE_KM, RATE_DEG_PER_S)
    assert band.along_track_km > 10 * band.cross_track_km


def test_a_slower_satellite_takes_longer_to_cover_its_error():
    slow = estimate(3.0, RANGE_KM, 0.05).timing_seconds
    fast = estimate(3.0, RANGE_KM, 0.50).timing_seconds
    assert slow > fast


def test_a_motionless_satellite_gets_no_timing_estimate():
    # Nothing to divide by; better than an infinity.
    assert estimate(3.0, RANGE_KM, 0.0).timing_seconds == 0.0


@pytest.mark.parametrize(
    "age,range_km",
    [(math.inf, RANGE_KM), (math.nan, RANGE_KM), (-1.0, RANGE_KM), (3.0, 0.0), (3.0, -5.0)],
)
def test_nonsense_inputs_give_no_estimate(age, range_km):
    assert estimate(age, range_km, RATE_DEG_PER_S) is None


# --- what the band means for the verdict -------------------------------------


def test_a_near_miss_just_outside_the_limb_could_be_a_transit():
    band = estimate(30.0, RANGE_KM, RATE_DEG_PER_S)  # a month old: a wide band
    assert band.could_be_transit(1000.0, SOLAR_RADIUS_ARCSEC)


def test_a_near_miss_far_outside_stays_a_near_miss():
    band = estimate(2.0, RANGE_KM, RATE_DEG_PER_S)
    assert not band.could_be_transit(3000.0, SOLAR_RADIUS_ARCSEC)


def test_a_central_transit_is_safe():
    band = estimate(3.0, RANGE_KM, RATE_DEG_PER_S)
    assert not band.could_miss(100.0, SOLAR_RADIUS_ARCSEC)


def test_a_grazing_transit_could_miss_once_the_elements_are_old():
    # 20" inside the limb, with a band wider than that.
    band = estimate(30.0, RANGE_KM, RATE_DEG_PER_S)
    assert band.cross_track_arcsec > 20.0
    assert band.could_miss(SOLAR_RADIUS_ARCSEC - 20.0, SOLAR_RADIUS_ARCSEC)


def test_the_rates_can_be_overridden():
    # A cautious observer may raise them; the measured spread is wide.
    default = estimate(5.0, RANGE_KM, RATE_DEG_PER_S)
    cautious = estimate(
        5.0, RANGE_KM, RATE_DEG_PER_S,
        cross_track_km_per_day=CROSS_TRACK_KM_PER_DAY * 4,
        along_track_km_per_day=ALONG_TRACK_KM_PER_DAY * 4,
    )
    assert cautious.cross_track_arcsec == pytest.approx(default.cross_track_arcsec * 4)
    assert cautious.timing_seconds == pytest.approx(default.timing_seconds * 4)
