"""Which way round an equatorial mount holds the camera.

A German equatorial mount cannot follow a target past the meridian without
swinging to the other side of the pier, and that turns the camera over: the
same patch of sky lands on the chip rotated by 180°. So a chart that matched
the screen all morning stops matching it in the afternoon, which is an
expensive thing to discover during a one-second transit.

Which side counts as "not turned over" depends on how the camera happened to be
clocked, so the observatory says which side its configured flips describe and
the other side gets the rotation.

Nothing here needs the satellite: the mount follows the *target*, and both are
in the same place to within a degree.
"""

from __future__ import annotations

import math

SIDES = ("any", "east", "west")


def hour_angle_deg(altitude_deg: float, azimuth_deg: float, latitude_deg: float) -> float:
    """The target's hour angle, in degrees: negative east of the meridian.

    The exact horizontal-to-equatorial rotation, so it holds at any latitude
    and for a circumpolar target at lower culmination — where the naive test of
    "is the azimuth east or west" gets the answer backwards. Azimuth is
    measured from north through east.
    """
    altitude = math.radians(altitude_deg)
    azimuth = math.radians(azimuth_deg)
    latitude = math.radians(latitude_deg)

    y = -math.cos(altitude) * math.sin(azimuth)
    x = (
        math.sin(altitude) * math.cos(latitude)
        - math.cos(altitude) * math.sin(latitude) * math.cos(azimuth)
    )
    return math.degrees(math.atan2(y, x))


def meridian_side(altitude_deg: float, azimuth_deg: float, latitude_deg: float) -> str:
    """``"east"`` while the target is still rising to the meridian, else ``"west"``."""
    return "east" if hour_angle_deg(altitude_deg, azimuth_deg, latitude_deg) < 0.0 else "west"


def is_turned_over(side: str, reference_side: str) -> bool:
    """Whether the mount holds the camera upside down on this side.

    ``reference_side`` is the side the configured flips describe. ``"any"``
    means the orientation never changes — an alt-azimuth mount with a
    derotator, a fork, or a camera that simply is not on this pier.
    """
    if reference_side not in ("east", "west"):
        return False
    return side != reference_side


def describe(hour_angle: float) -> str:
    """The hour angle as a mount owner reads it: ``"1h 12m east"``."""
    side = "east" if hour_angle < 0.0 else "west"
    minutes = round(abs(hour_angle) * 4.0)  # 1 degree = 4 minutes of time
    return f"{minutes // 60}h {minutes % 60:02d}m {side}"
