"""Tests for the Target abstraction and its illumination helpers."""

from types import SimpleNamespace

import pytest

from sattransit.target import (
    MOON_RADIUS_KM,
    SUN_RADIUS_KM,
    Target,
    bright_limb_angle_deg,
    limb_side,
)


class FakeEphemeris:
    """Stands in for a loaded ephemeris: only __getitem__ is used here."""

    def __getitem__(self, name):
        return SimpleNamespace(name=name)


# --- construction and radius -------------------------------------------------


def test_sun_and_moon_carry_the_right_radius():
    eph = FakeEphemeris()
    assert Target("sun", eph).radius_km == SUN_RADIUS_KM
    assert Target("moon", eph).radius_km == MOON_RADIUS_KM


def test_only_the_moon_is_reflective():
    eph = FakeEphemeris()
    assert Target("moon", eph).reflective is True
    assert Target("sun", eph).reflective is False


def test_the_sun_is_always_available_even_on_a_lunar_target():
    # The Moon's phase and a satellite's eclipse both need the Sun.
    assert Target("moon", FakeEphemeris()).sun.name == "sun"


def test_an_unknown_target_is_rejected():
    with pytest.raises(ValueError, match="unknown target"):
        Target("mars", FakeEphemeris())


def test_apparent_radius_matches_known_sizes():
    sun = Target("sun", FakeEphemeris())
    # At 1 au the Sun's apparent radius is close to 16 arcminutes.
    assert sun.apparent_radius_deg(1.0) * 60.0 == pytest.approx(15.99, abs=0.02)
    # Aphelion in July gives a slightly smaller disk than perihelion in January.
    assert sun.apparent_radius_deg(1.017) < sun.apparent_radius_deg(1.0)

    moon = Target("moon", FakeEphemeris())
    # The Moon at its mean distance (~0.00257 au) is also about 15-16 arcmin.
    mean_moon_au = 384400.0 / 149597870.7
    assert moon.apparent_radius_deg(mean_moon_au) * 60.0 == pytest.approx(15.5, abs=0.6)


def test_the_gate_radius_covers_each_disk_at_its_largest():
    # The Moon at perigee is slightly larger than the Sun ever gets.
    assert Target("moon", FakeEphemeris()).max_radius_deg > Target("sun", FakeEphemeris()).max_radius_deg


# --- the bright limb ---------------------------------------------------------


def _apparent(ra_deg, dec_deg):
    """A minimal stand-in for a Skyfield apparent position, for radec()."""
    return SimpleNamespace(
        radec=lambda: (
            SimpleNamespace(_degrees=ra_deg),
            SimpleNamespace(degrees=dec_deg),
            None,
        )
    )


def test_bright_limb_points_toward_the_sun():
    # Sun due north of the target (same RA, higher dec) -> bright limb at PA 0.
    target = _apparent(100.0, 10.0)
    assert bright_limb_angle_deg(target, _apparent(100.0, 20.0)) == pytest.approx(0.0, abs=1e-6)
    # Sun due east (higher RA) -> PA 90.
    assert bright_limb_angle_deg(target, _apparent(101.0, 10.0)) == pytest.approx(90.0, abs=0.5)


@pytest.mark.parametrize(
    "pa,bright,expected",
    [
        (0.0, 0.0, "lit"),      # straight toward the Sun
        (80.0, 0.0, "lit"),     # within 90 deg
        (100.0, 0.0, "dark"),   # past the terminator
        (180.0, 0.0, "dark"),   # anti-sunward
        (10.0, 350.0, "lit"),   # wraps across 0
        (350.0, 10.0, "lit"),
    ],
)
def test_limb_side_splits_at_the_terminator(pa, bright, expected):
    assert limb_side(pa, bright) == expected
