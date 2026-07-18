"""The body a satellite transits: the Sun or the Moon.

The search is identical for both — same SGP4, same disk, same limb contacts.
Only two things differ, and both live here: the body's physical radius (which
sets its apparent disk), and its illumination.

The Sun is a self-luminous disk, always fully lit, and a satellite crossing it
is always a backlit silhouette. The Moon shows a phase: part of its disk is
lit and part dark, a satellite is a silhouette only against the lit limb, and
against the dark limb it is visible only if it is itself sunlit rather than in
Earth's shadow. That extra structure is reported per event so the observer can
tell a workable pass from an invisible one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Mean physical radii, in kilometres.
SUN_RADIUS_KM = 695700.0
MOON_RADIUS_KM = 1737.4

_RADIUS_KM = {"sun": SUN_RADIUS_KM, "moon": MOON_RADIUS_KM}


@dataclass
class Illumination:
    """How a lunar event is lit. ``None`` on the event for a solar transit."""

    phase_deg: float
    illuminated_fraction: float
    bright_limb_angle_deg: float
    limb: str  # "lit" | "dark": which side of the disk the crossing is on
    satellite_sunlit: bool


class Target:
    """A transit target: its ephemeris body, its size, and its light."""

    def __init__(self, name: str, ephemeris):
        if name not in _RADIUS_KM:
            raise ValueError(f"unknown target {name!r}; expected 'sun' or 'moon'")
        self.name = name
        self.radius_km = _RADIUS_KM[name]
        self.body = ephemeris[name]
        # The Moon's phase and a satellite's shadow both need the Sun, so it is
        # always available even on a lunar run.
        self.sun = ephemeris["sun"]
        self.reflective = name == "moon"

    def apparent_radius_deg(self, distance_au: float) -> float:
        distance_km = distance_au * 149597870.7
        return math.degrees(math.asin(self.radius_km / distance_km))

    # The largest the disk ever gets, for the gate that keeps limb-only searches
    # cheap. The Moon at perigee (~0.28 deg) is slightly larger than the Sun.
    @property
    def max_radius_deg(self) -> float:
        return 0.30 if self.reflective else 0.28


def bright_limb_angle_deg(target_apparent, sun_apparent) -> float:
    """Position angle of the target's sunward (bright) limb, east of north.

    The lit half of the disk is the hemisphere facing the Sun; this is the
    direction of the Sun projected onto the sky at the target's position.
    """
    t_ra, t_dec, _ = target_apparent.radec()
    s_ra, s_dec, _ = sun_apparent.radec()
    d_ra = ((s_ra._degrees - t_ra._degrees + 180.0) % 360.0 - 180.0) * math.cos(
        math.radians(float(t_dec.degrees))
    )
    d_dec = float(s_dec.degrees) - float(t_dec.degrees)
    return math.degrees(math.atan2(d_ra, d_dec)) % 360.0


def limb_side(position_angle_deg: float, bright_angle_deg: float) -> str:
    """Whether a point at ``position_angle_deg`` is on the lit or dark limb.

    A point within 90 deg of the bright-limb direction is on the sunward,
    illuminated hemisphere. This is exact at the limb, where grazing transits
    happen, and only fuzzy right at the terminator.
    """
    delta = abs((position_angle_deg - bright_angle_deg + 180.0) % 360.0 - 180.0)
    return "lit" if delta <= 90.0 else "dark"
