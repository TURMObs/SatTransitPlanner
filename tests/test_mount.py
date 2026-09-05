"""Tests for the mount geometry: which side of the meridian, and which way up."""

import pytest

from sattransit.mount import describe, hour_angle_deg, is_turned_over, meridian_side

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
