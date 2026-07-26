"""How much to distrust a prediction, given the age of its element set.

The arithmetic elsewhere is good to a millisecond. The elements are not: an
SGP4 element set drifts from reality as it ages, and for a one-second transit
that drift is the whole error budget. Reporting a razor-sharp centre line
without it overstates what is known.

The drift splits into two components that matter quite differently here:

* **Cross-track** — sideways, perpendicular to the motion. This shifts the
  chord across the disk, so it decides *whether* the satellite crosses at all.
  It is small and well behaved.
* **Along-track** — forwards or backwards along the orbit. This leaves the
  chord where it is and makes the satellite arrive early or late, so it decides
  *when*. It is one to two orders of magnitude larger, and is usually the
  reason a predicted transit is missed.

The rates were measured, not assumed. Where two of the cached CelesTrak groups
carry element sets of different ages for the same satellite, propagating the
older one forward to the newer one's epoch and comparing gives the accumulated
error directly. Over 38 low-orbit satellites, at element ages around ten days:

    component     median   75th pct   90th pct      max
    along-track   1.11      5.40      20.78       357.26   km/day
    cross-track   0.049     0.084      0.188        0.32   km/day

The defaults below are the medians — a typical satellite, not a worst case.
The spread is wide, especially along-track, where a manoeuvring or
high-drag satellite is far worse than the median; ``uncertainty`` in the
configuration exists so a cautious observer can raise them.

Two honest limitations. The rates come from measurements at around ten days and
are applied linearly, which is reasonable for cross-track but optimistic for
along-track, where atmospheric drag makes the error grow faster than linearly.
And SGP4 publishes no covariances, so this is a calibrated rule of thumb rather
than a formal error bar. It is offered as a band to think with, not a number to
quote.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

ARCSEC_PER_RADIAN = 206264.806

# Measured medians, in kilometres of error per day of element age. See above.
CROSS_TRACK_KM_PER_DAY = 0.05
ALONG_TRACK_KM_PER_DAY = 1.1


@dataclass
class Uncertainty:
    """What an element set's age costs, for one event."""

    element_age_days: float
    cross_track_km: float
    along_track_km: float
    # Sideways on the disk: how far the chord could really lie from where it is
    # drawn, in arcseconds.
    cross_track_arcsec: float
    # How early or late the satellite could arrive, in seconds.
    timing_seconds: float

    def could_be_transit(self, separation_arcsec: float, radius_arcsec: float) -> bool:
        """Whether the disk could be crossed after all, within the band.

        A near miss whose closest approach is further out than the target's
        radius may still be a transit if the chord really lies a band-width to
        the side.
        """
        return separation_arcsec - self.cross_track_arcsec <= radius_arcsec

    def could_miss(self, separation_arcsec: float, radius_arcsec: float) -> bool:
        """Whether a predicted transit could in truth pass by the disk."""
        return separation_arcsec + self.cross_track_arcsec > radius_arcsec


def estimate(
    element_age_days: float,
    range_km: float,
    angular_velocity_deg_per_s: float,
    cross_track_km_per_day: float = CROSS_TRACK_KM_PER_DAY,
    along_track_km_per_day: float = ALONG_TRACK_KM_PER_DAY,
) -> Uncertainty | None:
    """Estimate the uncertainty for one event, or None if it cannot be judged."""
    if not math.isfinite(element_age_days) or element_age_days < 0:
        return None
    if not math.isfinite(range_km) or range_km <= 0:
        return None

    cross_km = cross_track_km_per_day * element_age_days
    along_km = along_track_km_per_day * element_age_days

    # A displacement of d km at range R subtends d/R radians.
    cross_arcsec = (cross_km / range_km) * ARCSEC_PER_RADIAN
    along_arcsec = (along_km / range_km) * ARCSEC_PER_RADIAN

    # Being that far along its own track, at the rate it is moving across the
    # sky, means arriving that much early or late.
    rate_arcsec_per_s = angular_velocity_deg_per_s * 3600.0
    timing = along_arcsec / rate_arcsec_per_s if rate_arcsec_per_s > 0 else 0.0

    return Uncertainty(
        element_age_days=element_age_days,
        cross_track_km=cross_km,
        along_track_km=along_km,
        cross_track_arcsec=cross_arcsec,
        timing_seconds=timing,
    )
