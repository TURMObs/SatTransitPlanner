"""Assembly of the JSON result document."""

from __future__ import annotations

import dataclasses
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import __version__
from .config import Config
from .finder import Event
from .elements import Catalog
from .favorites import Favorites
from .sizes import GCAT_CITATION
from .uncertainty import estimate as estimate_uncertainty


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _local(value: datetime, tz: ZoneInfo) -> str:
    return value.astimezone(tz).isoformat(timespec="milliseconds")


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def build_report(
    config: Config,
    catalog: Catalog,
    events: list[Event],
    start: datetime,
    end: datetime,
    runtime_seconds: float,
    favorites: Favorites | None = None,
    missing_favorites: list[int] | None = None,
) -> dict:
    tz = config.observatory.zoneinfo()
    transits = [e for e in events if e.is_transit]

    return {
        "schema_version": 2,
        "generator": {
            "name": "SatTransitPlanner",
            "version": __version__,
            "generated_utc": _iso(datetime.now(timezone.utc)),
        },
        "target": config.target,
        "observatory": dataclasses.asdict(config.observatory),
        "observation_window": {
            "start_utc": _iso(start),
            "end_utc": _iso(end),
            "start_local": _local(start, tz),
            "end_local": _local(end, tz),
            "duration_hours": round((end - start).total_seconds() / 3600.0, 4),
        },
        "search": {
            "max_separation_deg": config.search.max_separation_deg,
            "separation_reference": (
                "target_limb" if config.search.max_separation_deg is None else "target_center"
            ),
            "min_target_altitude_deg": config.search.min_target_altitude_deg,
            "min_satellite_altitude_deg": config.search.min_satellite_altitude_deg,
            "illumination": {
                "satellite": config.illumination.satellite,
                "limb": config.illumination.limb,
            },
            "sizes": ("gcat" if config.sizes.enabled else "off"),
            "coarse_step_seconds": config.search.coarse_step_seconds,
            "fine_step_seconds": config.search.fine_step_seconds,
            # null rather than Infinity: the latter is not valid JSON, and a
            # missing limit is exactly what null means.
            "max_element_age_days": (
                None
                if math.isinf(config.search.max_element_age_days)
                else config.search.max_element_age_days
            ),
            "ephemeris": config.ephemeris,
        },
        "attribution": [
            "Orbital elements: CelesTrak (celestrak.org)",
            "Satellite dimensions: " + GCAT_CITATION,
        ],
        "catalog": {
            "groups": config.celestrak.groups,
            "satellites_searched": len(catalog.entries),
            "satellites_skipped_stale_elements": catalog.skipped_stale,
            "format": "omm-json",
            "favorites": (
                None
                if favorites is None
                else {
                    "file": str(favorites.path),
                    "name": favorites.name,
                    "requested": len(favorites.norad_ids),
                    "searched": len(catalog.entries),
                    # Favourites that could not be searched, and why.
                    "not_in_groups": [
                        n for n in (missing_favorites or []) if n not in set(catalog.stale_ids)
                    ],
                    "stale_elements": [
                        n for n in (missing_favorites or []) if n in set(catalog.stale_ids)
                    ],
                }
            ),
            "sources": [
                {
                    "group": source.group,
                    "url": source.url,
                    "cache_file": source.cache_file,
                    "retrieved_utc": _iso(source.retrieved_utc),
                    "from_cache": source.from_cache,
                    "satellite_count": source.satellite_count,
                }
                for source in catalog.sources
            ],
        },
        "statistics": {
            "events": len(events),
            "disk_transits": len(transits),
            "near_misses": len(events) - len(transits),
            "runtime_seconds": round(runtime_seconds, 2),
        },
        "events": [_event_to_dict(event, tz, config) for event in events],
    }


def _size_to_dict(event: Event) -> dict | None:
    """The satellite's dimensions, and what they subtend at this range.

    A range rather than one figure: the silhouette depends on the satellite's
    attitude, which is not predicted here.
    """
    if event.size is None:
        return None
    low, high = event.size.angular_arcsec(event.range_km)
    return {
        "min_m": _round(event.size.min_m, 2),
        "max_m": _round(event.size.max_m, 2),
        "shape": event.size.shape,
        "source": event.size.source,
        "angular_min_arcsec": _round(low, 2),
        "angular_max_arcsec": _round(high, 2),
    }


def _illumination_to_dict(event: Event) -> dict | None:
    """How a lunar event is lit; ``null`` for the Sun."""
    lit = event.illumination
    if lit is None:
        return None
    return {
        "phase_deg": _round(lit.phase_deg, 2),
        "illuminated_fraction": _round(lit.illuminated_fraction, 4),
        "bright_limb_angle_deg": _round(lit.bright_limb_angle_deg, 2),
        "limb": lit.limb,
        "satellite_sunlit": lit.satellite_sunlit,
    }


def _uncertainty_to_dict(event: Event, config: Config, element_age_days: float) -> dict | None:
    """What the element set's age costs this prediction.

    Cross-track decides whether the disk is crossed at all; along-track decides
    when. Both are reported, with the flags that say whether the predicted
    outcome could actually go the other way.
    """
    if not config.uncertainty.enabled:
        return None
    estimate = estimate_uncertainty(
        element_age_days,
        event.range_km,
        event.angular_velocity_deg_per_s,
        cross_track_km_per_day=config.uncertainty.cross_track_km_per_day,
        along_track_km_per_day=config.uncertainty.along_track_km_per_day,
    )
    if estimate is None:
        return None

    separation = event.separation_deg * 3600.0
    radius = event.target_radius_deg * 3600.0
    return {
        "element_age_days": _round(element_age_days, 3),
        "cross_track_km": _round(estimate.cross_track_km, 3),
        "along_track_km": _round(estimate.along_track_km, 3),
        # Sideways on the disk: how far the chord could really lie from where
        # it is drawn.
        "cross_track_arcsec": _round(estimate.cross_track_arcsec, 1),
        # How early or late the satellite could arrive.
        "timing_seconds": _round(estimate.timing_seconds, 3),
        "could_be_transit": estimate.could_be_transit(separation, radius),
        "could_miss": estimate.could_miss(separation, radius),
    }


def _event_to_dict(event: Event, tz: ZoneInfo, config: Config) -> dict:
    entry = event.entry
    satellite = entry.satellite
    reference = event.closest_time
    element_age_days = abs((entry.epoch_utc - reference).total_seconds()) / 86400.0

    data = {
        "event_id": f"{_iso(event.closest_time)}_{entry.norad_id}",
        "type": "disk_transit" if event.is_transit else "near_miss",
        "satellite": {
            "name": satellite.name,
            "norad_id": entry.norad_id,
            "international_designator": entry.international_designator,
            "groups": entry.groups,
            "epoch_utc": _iso(entry.epoch_utc),
            "element_age_days": round(element_age_days, 3),
        },
        "closest_approach": {
            "time_utc": _iso(event.closest_time),
            "time_local": _local(event.closest_time, tz),
            "separation_arcsec": _round(event.separation_deg * 3600.0, 1),
            "separation_deg": _round(event.separation_deg, 6),
            "target_radius_arcsec": _round(event.target_radius_deg * 3600.0, 1),
            "chord_offset_fraction": _round(event.separation_deg / event.target_radius_deg, 4),
            "position_angle_deg": _round(event.position_angle_deg, 2),
        },
        "transit": (
            {
                "start_utc": _iso(event.start_time),
                "end_utc": _iso(event.end_time),
                "start_local": _local(event.start_time, tz),
                "end_local": _local(event.end_time, tz),
                "duration_seconds": _round(event.duration_seconds, 4),
            }
            if event.start_time and event.end_time
            else None
        ),
        "geometry": {
            "satellite_altitude_deg": _round(event.satellite_altitude_deg, 4),
            "satellite_azimuth_deg": _round(event.satellite_azimuth_deg, 4),
            "target_altitude_deg": _round(event.target_altitude_deg, 4),
            "target_azimuth_deg": _round(event.target_azimuth_deg, 4),
            "range_km": _round(event.range_km, 3),
            "angular_velocity_deg_per_s": _round(event.angular_velocity_deg_per_s, 5),
            "motion_position_angle_deg": _round(event.motion_position_angle_deg, 2),
        },
        "illumination": _illumination_to_dict(event),
        "size": _size_to_dict(event),
        "uncertainty": _uncertainty_to_dict(event, config, element_age_days),
    }

    if config.output.include_path:
        data["path"] = [
            {
                "offset_seconds": _round(sample.offset_seconds, 4),
                "time_utc": _iso(sample.time_utc),
                "dx_arcsec": _round(sample.dx_arcsec, 1),
                "dy_arcsec": _round(sample.dy_arcsec, 1),
                "separation_arcsec": _round(sample.separation_arcsec, 1),
            }
            for sample in event.path
        ]
    return data
