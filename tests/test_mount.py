"""Tests for the mount geometry: which side of the meridian, and which way up."""

import pytest

from sattransit.mount import (
    declination_deg,
    describe,
    hour_angle_deg,
    is_turned_over,
    meridian_side,
    pointing_offset,
)

DARMSTADT = 49.8775
SYDNEY = -33.87


# --- the hour angle ----------------------------------------------------------


def test_a_target_due_south_is_on_the_meridian():
    # Upper culmination for a northern observer: azimuth 180, hour angle zero.
    assert hour_angle_deg(45.0, 180.0, DARMSTADT) == pytest.approx(0.0, abs=1e-9)


def test_a_target_due_north_is_on_the_meridian_from_the_south():
    # And for a southern observer the upper meridian is north instead.
    assert hour_angle_deg(45.0, 0.0, SYDNEY) == pytest.approx(0.0, abs=1e-9)


def test_the_hour_angle_is_negative_in_the_east_and_positive_in_the_west():
    assert hour_angle_deg(30.0, 90.0, DARMSTADT) < 0.0
    assert hour_angle_deg(30.0, 270.0, DARMSTADT) > 0.0


def test_the_hour_angle_grows_as_the_target_moves_west():
    morning = hour_angle_deg(20.0, 100.0, DARMSTADT)
    noon = hour_angle_deg(45.0, 180.0, DARMSTADT)
    evening = hour_angle_deg(20.0, 260.0, DARMSTADT)
    assert morning < noon < evening


def test_a_target_below_the_pole_is_twelve_hours_from_the_meridian():
    """The case that makes the exact transform worth having.

    At lower culmination a circumpolar target sits due north — azimuth 0 — and
    is a full twelve hours from the meridian. Reading the azimuth alone would
    call it "nearly on the meridian" and put the mount on the wrong side.

    The sign is a genuine wrap there rather than a side, but it cannot bite in
    practice: the Sun and Moon at that hour angle are far below the horizon,
    and the search will not have produced an event.
    """
    assert abs(hour_angle_deg(5.0, 0.0, 60.0)) == pytest.approx(180.0, abs=1e-6)
    # Either side of due north the answer is well defined, and it is the
    # antimeridian being crossed, not the meridian.
    assert meridian_side(5.0, 359.0, 60.0) == "west"
    assert meridian_side(5.0, 1.0, 60.0) == "east"


def test_the_hour_angle_matches_an_independent_calculation():
    # Skyfield's own hadec() for the Sun from Darmstadt, 2026-07-20 09:00 UTC.
    assert hour_angle_deg(48.15, 120.37, DARMSTADT) == pytest.approx(-37.95, abs=0.02)


# --- which side ---------------------------------------------------------------


@pytest.mark.parametrize(
    "azimuth,expected",
    [(80.0, "east"), (120.0, "east"), (179.0, "east"), (181.0, "west"), (280.0, "west")],
)
def test_the_side_follows_the_meridian(azimuth, expected):
    assert meridian_side(40.0, azimuth, DARMSTADT) == expected


# --- whether the camera is turned over ---------------------------------------


@pytest.mark.parametrize("side", ["east", "west"])
def test_the_reference_side_is_the_one_drawn_as_configured(side):
    assert not is_turned_over(side, side)


def test_the_other_side_of_the_meridian_is_turned_over():
    assert is_turned_over("west", "east")
    assert is_turned_over("east", "west")


@pytest.mark.parametrize("side", ["east", "west"])
def test_any_means_the_orientation_never_changes(side):
    # A fork, an alt-az mount with a derotator, or nobody matching a camera.
    assert not is_turned_over(side, "any")


# --- how it reads -------------------------------------------------------------


def test_the_hour_angle_reads_as_hours_and_minutes():
    # A degree of hour angle is four minutes of time.
    assert describe(-82.75) == "5h 31m east"
    assert describe(15.0) == "1h 00m west"


def test_on_the_meridian_reads_as_zero():
    assert describe(0.0).startswith("0h 00m")


# --- declination --------------------------------------------------------------


def test_the_zenith_sits_at_the_observer_s_latitude():
    assert declination_deg(90.0, 0.0, DARMSTADT) == pytest.approx(DARMSTADT, abs=1e-9)


def test_on_the_meridian_declination_follows_the_altitude():
    # Due south at altitude a, a northern observer sees dec = a + lat - 90.
    for altitude in (20.0, 45.0, 60.0):
        assert declination_deg(altitude, 180.0, DARMSTADT) == pytest.approx(
            altitude + DARMSTADT - 90.0, abs=1e-9
        )


def test_declination_matches_an_independent_calculation():
    # The Sun from Darmstadt, 2026-06-15 12:00 UTC: Skyfield's altaz() in,
    # its own hadec() declination out.
    assert declination_deg(62.6200, 197.2186, 49.8728) == pytest.approx(23.3190, abs=0.002)


# --- the pointing offset ------------------------------------------------------

RADIUS = 960.0  # a round solar radius, in arcseconds


def test_a_centred_track_is_one_radius_above_the_low_limb():
    offset = pointing_offset(0.0, 0.0, RADIUS, 0.0, north_is_down=False)
    assert offset == (pytest.approx(0.0), pytest.approx(RADIUS / 3600.0))


def test_turning_the_view_over_moves_the_reference_to_the_other_limb():
    # The lowest thing on screen is now the north edge, so the slew is southwards.
    _, delta_dec = pointing_offset(0.0, 0.0, RADIUS, 0.0, north_is_down=True)
    assert delta_dec == pytest.approx(-RADIUS / 3600.0)


def test_a_track_across_the_top_of_the_disk_is_two_radii_up():
    # Position angle 0 is due north, so this grazes the far limb.
    _, delta_dec = pointing_offset(RADIUS, 0.0, RADIUS, 0.0, north_is_down=False)
    assert delta_dec == pytest.approx(2 * RADIUS / 3600.0)


def test_the_east_west_offset_does_not_care_which_way_up_the_view_is():
    # The lowest point of a disk is directly below its centre either way.
    up = pointing_offset(500.0, 90.0, RADIUS, 20.0, north_is_down=False)
    down = pointing_offset(500.0, 90.0, RADIUS, 20.0, north_is_down=True)
    assert up[0] == pytest.approx(down[0])


def test_position_angle_ninety_is_due_east():
    delta_ra, delta_dec = pointing_offset(600.0, 90.0, RADIUS, 0.0, north_is_down=False)
    assert delta_ra > 0  # east is increasing right ascension
    assert delta_dec == pytest.approx(RADIUS / 3600.0)  # no north-south component


def test_the_ra_offset_carries_the_cosine_of_the_declination():
    """Degrees of RA, not an angle on the sky.

    A mount given an RA to move to needs the coordinate difference, which runs
    1/cos(dec) times faster than the angle subtended.
    """
    import math

    on_sky = 600.0 / 3600.0
    for dec in (0.0, 23.4, -23.4):
        delta_ra, _ = pointing_offset(600.0, 90.0, RADIUS, dec, north_is_down=False)
        assert delta_ra == pytest.approx(on_sky / math.cos(math.radians(dec)))


def test_near_the_pole_there_is_no_answer_to_give():
    # cos(dec) vanishes and right ascension stops meaning anything. Cannot
    # happen for the Sun or Moon, but better than dividing by nearly zero.
    assert pointing_offset(100.0, 0.0, RADIUS, 89.95, north_is_down=False) is None
