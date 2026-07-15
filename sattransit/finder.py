"""Search for satellite passages in front of (or close to) the solar disk.

The search runs in three stages so that it stays both fast and safe for
low-Earth-orbit satellites, whose apparent motion can exceed 1 deg/s:

1. Coarse scan   - one vectorised SGP4 evaluation per satellite over the whole
                   window. Local minima of the satellite-Sun separation are
                   located. Because the separation is unimodal within a single
                   pass, every close approach is bracketed by a sampled minimum
                   even when the coarse step is far larger than the event.
2. Fine scan     - each bracket is re-sampled at a small step, again in a single
                   vectorised call per satellite.
3. Refinement    - the few survivors are polished with a golden-section search
                   for the closest approach, then bisection for limb contacts.

Between stages, candidates are discarded using a gate derived from the observed
angular travel per step, so the expensive stages only ever see real candidates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from skyfield.api import EarthSatellite, Timescale, wgs84
from skyfield.jpllib import SpiceKernel
from skyfield.vectorlib import VectorSum

from .config import Config
from .elements import CatalogEntry
from .sizes import Size, parse_overrides, resolve

SUN_RADIUS_KM = 695700.0
GOLDEN_RATIO_INV = (math.sqrt(5.0) - 1.0) / 2.0
DEG_TO_ARCSEC = 3600.0


@dataclass
class PathSample:
    offset_seconds: float
    time_utc: datetime
    dx_arcsec: float
    dy_arcsec: float
    separation_arcsec: float


@dataclass
class Event:
    entry: CatalogEntry
    is_transit: bool
    closest_time: datetime
    separation_deg: float
    sun_radius_deg: float
    position_angle_deg: float
    satellite_altitude_deg: float
    satellite_azimuth_deg: float
    sun_altitude_deg: float
    sun_azimuth_deg: float
    range_km: float
    angular_velocity_deg_per_s: float
    motion_position_angle_deg: float
    size: Size | None
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_seconds: float | None = None
    path: list[PathSample] = field(default_factory=list)


class TransitFinder:
    """Finds solar transits and near misses for a fixed observing site."""

    def __init__(
        self,
        config: Config,
        ephemeris: SpiceKernel,
        timescale: Timescale,
        sizes: dict[int, Size] | None = None,
    ):
        self.config = config
        self.sizes = sizes or {}
        self.size_overrides = parse_overrides(config.search.satellite_sizes_m)
        self.ts = timescale
        self.eph = ephemeris
        self.sun = ephemeris["sun"]
        obs = config.observatory
        self.site = wgs84.latlon(
            latitude_degrees=obs.latitude_deg,
            longitude_degrees=obs.longitude_deg,
            elevation_m=obs.elevation_m,
        )
        self.observer: VectorSum = ephemeris["earth"] + self.site

    # ------------------------------------------------------------------ Sun

    def _sun_apparent(self, t):
        return self.observer.at(t).observe(self.sun).apparent()

    def sun_radius_deg(self, distance_au: float) -> float:
        distance_km = distance_au * 149597870.7
        return math.degrees(math.asin(SUN_RADIUS_KM / distance_km))

    # --------------------------------------------------------- separations

    def _separation_deg(self, satellite: EarthSatellite, t) -> np.ndarray:
        topocentric = (satellite - self.site).at(t)
        return topocentric.separation_from(self._sun_apparent(t)).degrees

    def _separation_at_jd(self, satellite: EarthSatellite, jd: float) -> float:
        return float(self._separation_deg(satellite, self.ts.tt_jd(jd)))

    # -------------------------------------------------------------- search

    def search(
        self,
        entries: list[CatalogEntry],
        start,
        end,
        progress=lambda done, total, events: None,
    ) -> list[Event]:
        search = self.config.search

        coarse = self._coarse_grid(start, end, search.coarse_step_seconds)
        sun_apparent = self._sun_apparent(coarse)
        sun_alt, sun_az, sun_distance = sun_apparent.altaz()
        sun_up = sun_alt.degrees >= search.min_sun_altitude_deg

        events: list[Event] = []
        if not sun_up.any():
            progress(len(entries), len(entries), 0)
            return events

        coarse_jd = coarse.tt
        for index, entry in enumerate(entries, start=1):
            events.extend(self._search_one(entry, coarse, coarse_jd, sun_apparent, sun_up))
            progress(index, len(entries), len(events))

        events.sort(key=lambda e: e.closest_time)
        return events

    def _coarse_grid(self, start, end, step_seconds: float):
        span_seconds = (end.tt - start.tt) * 86400.0
        count = max(int(math.ceil(span_seconds / step_seconds)) + 1, 2)
        jd = start.tt + np.linspace(0.0, span_seconds / 86400.0, count)
        return self.ts.tt_jd(jd)

    def _search_one(
        self,
        entry: CatalogEntry,
        coarse,
        coarse_jd: np.ndarray,
        sun_apparent,
        sun_up: np.ndarray,
    ) -> list[Event]:
        search = self.config.search
        satellite = entry.satellite

        topocentric = (satellite - self.site).at(coarse)
        alt, _, _ = topocentric.altaz()
        separation = topocentric.separation_from(sun_apparent).degrees

        visible = sun_up & (alt.degrees >= search.min_satellite_altitude_deg)
        if not visible.any():
            return []

        brackets = self._candidate_brackets(
            separation, _dilate(visible), coarse_jd, self._threshold_gate()
        )
        if not brackets:
            return []

        fine_brackets = self._refine_brackets(satellite, brackets, search.fine_step_seconds)
        if not fine_brackets:
            return []

        events = []
        for lo, mid, hi in fine_brackets:
            event = self._build_event(entry, lo, mid, hi)
            if event is not None:
                events.append(event)
        return events

    def _threshold_gate(self) -> float:
        """Upper bound on the separation that could still yield an event."""
        limit = self.config.search.max_separation_deg
        # The Sun's apparent radius never exceeds ~0.28 deg; use it when the
        # configuration asks for limb-defined transits only.
        return limit if limit is not None else 0.28

    def _candidate_brackets(
        self,
        separation: np.ndarray,
        visible: np.ndarray,
        jd: np.ndarray,
        threshold: float,
    ) -> list[tuple[float, float, float]]:
        masked = np.where(visible, separation, np.inf)
        if masked.size < 3:
            return []

        previous, current, following = masked[:-2], masked[1:-1], masked[2:]
        is_minimum = (current < previous) & (current <= following) & np.isfinite(current)
        if not is_minimum.any():
            return []

        # How far the satellite moved relative to the Sun during one step tells
        # us how much closer than the sample the true minimum could possibly be.
        # Masked neighbours contribute nothing; `where` also keeps inf - inf out
        # of the subtraction.
        drop_before = np.zeros_like(current)
        np.subtract(previous, current, out=drop_before, where=np.isfinite(previous))
        drop_after = np.zeros_like(current)
        np.subtract(following, current, out=drop_after, where=np.isfinite(following))
        reach = np.maximum(drop_before, drop_after) * self.config.search.gate_factor
        keep = is_minimum & (current <= threshold + reach)

        indices = np.nonzero(keep)[0] + 1
        return [(float(jd[i - 1]), float(jd[i]), float(jd[i + 1])) for i in indices]

    def _refine_brackets(
        self,
        satellite: EarthSatellite,
        brackets: list[tuple[float, float, float]],
        step_seconds: float,
    ) -> list[tuple[float, float, float]]:
        """Re-sample every coarse bracket at a fine step in one vectorised call."""
        step_jd = step_seconds / 86400.0
        grids = []
        for lo, _, hi in brackets:
            count = max(int(math.ceil((hi - lo) / step_jd)) + 1, 3)
            grids.append(np.linspace(lo, hi, count))

        sizes = [len(g) for g in grids]
        all_jd = np.concatenate(grids)
        separation = np.atleast_1d(self._separation_deg(satellite, self.ts.tt_jd(all_jd)))

        threshold = self._threshold_gate()
        result = []
        offset = 0
        for size, grid in zip(sizes, grids):
            values = separation[offset : offset + size]
            offset += size

            j = int(np.argmin(values))
            lo_index = max(j - 1, 0)
            hi_index = min(j + 1, size - 1)
            if lo_index == hi_index:
                continue

            reach = max(values[lo_index] - values[j], values[hi_index] - values[j])
            if values[j] > threshold + reach * self.config.search.gate_factor:
                continue
            result.append((float(grid[lo_index]), float(grid[j]), float(grid[hi_index])))
        return result

    def _build_event(
        self,
        entry: CatalogEntry,
        lo_jd: float,
        mid_jd: float,
        hi_jd: float,
    ) -> Event | None:
        search = self.config.search
        satellite = entry.satellite

        tolerance_jd = search.refine_tolerance_seconds / 86400.0
        best_jd = _golden_section_min(
            lambda jd: self._separation_at_jd(satellite, jd), lo_jd, hi_jd, tolerance_jd
        )
        separation_deg = self._separation_at_jd(satellite, best_jd)

        t = self.ts.tt_jd(best_jd)
        sun_apparent = self._sun_apparent(t)
        sun_alt, sun_az, sun_distance = sun_apparent.altaz()
        sun_radius = self.sun_radius_deg(float(sun_distance.au))

        limit = search.max_separation_deg if search.max_separation_deg is not None else sun_radius
        if separation_deg > limit:
            return None

        topocentric = (satellite - self.site).at(t)
        sat_alt, sat_az, sat_range = topocentric.altaz()

        # The refined minimum may have drifted outside the visibility window.
        if float(sun_alt.degrees) < search.min_sun_altitude_deg:
            return None
        if float(sat_alt.degrees) < search.min_satellite_altitude_deg:
            return None

        dx, dy = self._offsets_arcsec(satellite, t, sun_apparent)
        position_angle = _position_angle(dx, dy)
        velocity, motion_pa = self._motion(satellite, best_jd, sun_apparent)

        is_transit = separation_deg <= sun_radius
        event = Event(
            entry=entry,
            is_transit=is_transit,
            closest_time=t.utc_datetime(),
            separation_deg=separation_deg,
            sun_radius_deg=sun_radius,
            position_angle_deg=position_angle,
            satellite_altitude_deg=float(sat_alt.degrees),
            satellite_azimuth_deg=float(sat_az.degrees),
            sun_altitude_deg=float(sun_alt.degrees),
            sun_azimuth_deg=float(sun_az.degrees),
            range_km=float(sat_range.km),
            angular_velocity_deg_per_s=velocity,
            motion_position_angle_deg=motion_pa,
            size=resolve(entry.norad_id, satellite.name, self.size_overrides, self.sizes),
        )

        if is_transit:
            self._add_contacts(event, satellite, best_jd, sun_radius)
        if self.config.output.include_path:
            self._add_path(event, satellite, best_jd)
        return event

    def _add_contacts(
        self,
        event: Event,
        satellite: EarthSatellite,
        best_jd: float,
        sun_radius: float,
    ) -> None:
        """Locate the limb crossings on either side of the closest approach."""
        if event.angular_velocity_deg_per_s <= 0:
            return

        tolerance_jd = self.config.search.refine_tolerance_seconds / 86400.0
        # Time the satellite needs to cover one solar radius, generously padded:
        # the true half-duration cannot exceed this by much even for a central
        # crossing of a slow, high-orbit satellite.
        half_span_seconds = event.sun_radius_deg / event.angular_velocity_deg_per_s
        max_span_jd = (5.0 * half_span_seconds + 1.0) / 86400.0

        def limb(jd: float) -> float:
            return self._separation_at_jd(satellite, jd) - sun_radius

        ingress = _limb_contact(limb, best_jd, -1.0, max_span_jd, tolerance_jd)
        egress = _limb_contact(limb, best_jd, +1.0, max_span_jd, tolerance_jd)
        if ingress is None or egress is None:
            return

        event.start_time = self.ts.tt_jd(ingress).utc_datetime()
        event.end_time = self.ts.tt_jd(egress).utc_datetime()
        event.duration_seconds = (egress - ingress) * 86400.0

    def _add_path(self, event: Event, satellite: EarthSatellite, best_jd: float) -> None:
        samples = self.config.search.path_samples
        if event.duration_seconds:
            half_span = event.duration_seconds / 2.0
        elif event.angular_velocity_deg_per_s > 0:
            # For a near miss, show a window wide enough to cross the disk.
            half_span = event.sun_radius_deg / event.angular_velocity_deg_per_s
        else:
            half_span = 30.0

        offsets = np.linspace(-half_span, half_span, samples)
        jd = best_jd + offsets / 86400.0
        t = self.ts.tt_jd(jd)
        sun_apparent = self._sun_apparent(t)
        dx, dy = self._offsets_arcsec(satellite, t, sun_apparent)

        event.path = [
            PathSample(
                offset_seconds=float(offset),
                time_utc=time.utc_datetime(),
                dx_arcsec=float(x),
                dy_arcsec=float(y),
                separation_arcsec=float(math.hypot(x, y)),
            )
            for offset, time, x, y in zip(offsets, t, np.atleast_1d(dx), np.atleast_1d(dy))
        ]

    def _offsets_arcsec(self, satellite: EarthSatellite, t, sun_apparent):
        """Satellite position relative to the Sun's center, east/north in arcsec."""
        sat_ra, sat_dec, _ = (satellite - self.site).at(t).radec()
        sun_ra, sun_dec, _ = sun_apparent.radec()

        d_ra = _wrap_degrees(sat_ra._degrees - sun_ra._degrees)
        dx = d_ra * math.cos(math.radians(float(np.mean(sun_dec.degrees)))) * DEG_TO_ARCSEC
        dy = (sat_dec.degrees - sun_dec.degrees) * DEG_TO_ARCSEC
        return dx, dy

    def _motion(self, satellite: EarthSatellite, jd: float, sun_apparent):
        """Apparent angular speed and direction of travel at the given instant."""
        delta_jd = 0.05 / 86400.0
        t = self.ts.tt_jd(np.array([jd - delta_jd, jd + delta_jd]))
        position = (satellite - self.site).at(t)
        ra, dec, _ = position.radec()

        mean_dec = math.radians(float(np.mean(dec.degrees)))
        d_ra = _wrap_degrees(float(ra._degrees[1] - ra._degrees[0])) * math.cos(mean_dec)
        d_dec = float(dec.degrees[1] - dec.degrees[0])

        distance = math.hypot(d_ra, d_dec)
        speed = distance / (2.0 * delta_jd * 86400.0)
        return speed, _position_angle(d_ra, d_dec)


def _dilate(mask: np.ndarray) -> np.ndarray:
    """Grow a boolean mask by one sample on each side.

    This guarantees that a minimum sitting at the edge of the visibility window
    still has finite neighbours, so its bracket is well defined. Refined events
    are re-checked against the real visibility limits afterwards.
    """
    grown = mask.copy()
    grown[:-1] |= mask[1:]
    grown[1:] |= mask[:-1]
    return grown


def _wrap_degrees(value):
    return (value + 180.0) % 360.0 - 180.0


def _position_angle(dx, dy) -> float:
    """Position angle in degrees, measured east of north."""
    return math.degrees(math.atan2(float(np.mean(dx)), float(np.mean(dy)))) % 360.0


def _golden_section_min(f, lo: float, hi: float, tolerance: float) -> float:
    a, b = lo, hi
    c = b - GOLDEN_RATIO_INV * (b - a)
    d = a + GOLDEN_RATIO_INV * (b - a)
    fc, fd = f(c), f(d)

    while (b - a) > tolerance:
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - GOLDEN_RATIO_INV * (b - a)
            fc = f(c)
        else:
            a, c, fc = c, d, fd
            d = a + GOLDEN_RATIO_INV * (b - a)
            fd = f(d)
    return (a + b) / 2.0


def _limb_contact(
    f,
    inside: float,
    direction: float,
    max_span: float,
    tolerance: float,
) -> float | None:
    """Find where f changes sign, walking outwards from a point where f <= 0.

    ``f`` is the separation minus the solar radius, so it is negative on the
    disk and positive outside it. The step doubles until the satellite has
    cleared the limb, which keeps the number of evaluations logarithmic no
    matter how fast or slow the satellite crosses.
    """
    if f(inside) > 0:
        return None

    span = max(tolerance * 4.0, max_span / 1024.0)
    outside = None
    while span <= max_span:
        probe = inside + direction * span
        if f(probe) > 0:
            outside = probe
            break
        span *= 2.0
    if outside is None:
        return None

    lo, hi = outside, inside  # f(lo) > 0, f(hi) <= 0
    while abs(hi - lo) > tolerance:
        mid = (lo + hi) / 2.0
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0
