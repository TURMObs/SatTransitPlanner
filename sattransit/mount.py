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
from dataclasses import dataclass

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


def declination_deg(altitude_deg: float, azimuth_deg: float, latitude_deg: float) -> float:
    """The target's declination, from the same rotation as the hour angle.

    Needed to turn an east-west angle on the sky into degrees of right
    ascension, which run 1/cos(dec) times faster.
    """
    altitude = math.radians(altitude_deg)
    azimuth = math.radians(azimuth_deg)
    latitude = math.radians(latitude_deg)

    sine = (
        math.sin(altitude) * math.sin(latitude)
        + math.cos(altitude) * math.cos(latitude) * math.cos(azimuth)
    )
    return math.degrees(math.asin(max(-1.0, min(1.0, sine))))


@dataclass(frozen=True)
class Offset:
    """Where to move, from one point on the sky to another.

    Right ascension in hours and declination in degrees — the units each is
    conventionally written in. Named rather than returned as a bare pair,
    because a tuple of two different units is asking to be read the wrong way
    round.
    """

    ra_hours: float
    dec_deg: float


def pointing_offset(
    separation_arcsec: float,
    position_angle_deg: float,
    radius_arcsec: float,
    dec_deg: float,
    north_is_down: bool,
) -> Offset | None:
    """Offset from the disk's lowest drawn point to the track's mid-point.

    At a long focal length the disk does not fit in the frame, so the limb is
    the only landmark there is to start from: put the bottom edge of the disk
    on the sensor, apply this, and the mid-point of the chord is centred.

    "Lowest" means lowest *as drawn* — the flips and the meridian rotation are
    already in it — so the screen and the camera agree about which edge to use.

    The RA offset is a difference in right ascension, not an angle on the sky:
    it carries the 1/cos(dec) factor already, so it can be added straight to a
    right ascension, in the hours such a coordinate is written in.
    """
    if abs(dec_deg) > 89.9:  # cos(dec) vanishes and RA stops meaning anything
        return None

    angle = math.radians(position_angle_deg)
    east = separation_arcsec * math.sin(angle)
    north = separation_arcsec * math.cos(angle)

    # The lowest drawn point lies one radius from the centre, towards whichever
    # pole is being drawn downwards.
    low_limb_north = radius_arcsec if north_is_down else -radius_arcsec

    delta_dec = (north - low_limb_north) / 3600.0
    # Degrees of RA first, then hours: 15 degrees of right ascension is an hour.
    delta_ra = east / 3600.0 / math.cos(math.radians(dec_deg))
    return Offset(ra_hours=delta_ra / 15.0, dec_deg=delta_dec)


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
