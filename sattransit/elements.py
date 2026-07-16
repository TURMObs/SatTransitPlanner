"""Fetching and caching of orbital elements from CelesTrak.

Elements are requested as OMM in JSON (``FORMAT=json``) rather than as TLEs.
The TLE format identifies a satellite with five digits, and that space is now
exhausted; CelesTrak's stop-gap is the Alpha-5 encoding, which merely postpones
the problem. OMM carries the catalog number as a plain integer, states the
epoch as an ISO timestamp rather than a two-digit year, and gives the full
international designator (``1998-067A`` instead of ``98067A``).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from skyfield.api import EarthSatellite, Timescale

from . import __version__
from .config import CelestrakConfig

USER_AGENT = f"SatTransitPlanner/{__version__} (+satellite solar transit prediction)"

# Fields sgp4's OMM initialiser requires. OBJECT_NAME is optional.
REQUIRED_FIELDS = frozenset(
    {
        "OBJECT_ID",
        "EPOCH",
        "MEAN_MOTION",
        "ECCENTRICITY",
        "INCLINATION",
        "RA_OF_ASC_NODE",
        "ARG_OF_PERICENTER",
        "MEAN_ANOMALY",
        "EPHEMERIS_TYPE",
        "CLASSIFICATION_TYPE",
        "NORAD_CAT_ID",
        "ELEMENT_SET_NO",
        "REV_AT_EPOCH",
        "BSTAR",
        "MEAN_MOTION_DOT",
        "MEAN_MOTION_DDOT",
    }
)

# CelesTrak refuses a repeat download with a plain-text notice and HTTP 200.
# It means the cached copy is already the current one.
_NOT_UPDATED = "has not updated since your last successful"


class ElementsError(RuntimeError):
    """Raised when orbital elements cannot be obtained."""


@dataclass
class CatalogEntry:
    satellite: EarthSatellite
    groups: list[str]
    norad_id: int
    international_designator: str | None

    @property
    def epoch_utc(self) -> datetime:
        return self.satellite.epoch.utc_datetime()


@dataclass
class GroupSource:
    group: str
    url: str
    cache_file: str
    retrieved_utc: datetime
    from_cache: bool
    satellite_count: int


@dataclass
class Catalog:
    entries: list[CatalogEntry]
    sources: list[GroupSource]
    skipped_stale: int
    # Satellites the groups carry, but with elements too old to trust. Kept so a
    # caller can tell "stale" from "not in these groups at all".
    stale_ids: list[int] = field(default_factory=list)


def _group_url(config: CelestrakConfig, group: str) -> str:
    query = urllib.parse.urlencode({"GROUP": group, "FORMAT": "json"})
    return f"{config.base_url}?{query}"


def parse_records(text: str) -> list[dict] | None:
    """Return the OMM records in ``text``, or None if it is not OMM JSON.

    CelesTrak reports problems as prose with a 200 status, so the body has to
    be inspected rather than the HTTP code.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, list) or not payload:
        return None
    if not all(isinstance(record, dict) for record in payload):
        return None
    if not REQUIRED_FIELDS.issubset(payload[0]):
        return None
    return payload


def _fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise ElementsError(f"CelesTrak returned HTTP {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise ElementsError(f"could not reach CelesTrak at {url}: {exc.reason}") from exc

    text = payload.decode("utf-8", errors="replace").strip()
    if not text:
        raise ElementsError(f"CelesTrak returned an empty response for {url}")
    return text


def _write_cache(destination: Path, text: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(destination)


def _load_cache(path: Path, group: str) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ElementsError(f"could not read cached elements for {group!r}: {exc}") from exc

    records = parse_records(text)
    if records is None:
        raise ElementsError(
            f"cached elements for group {group!r} are not valid OMM JSON: {path}\n"
            "  Delete the file and run again, or use --refresh."
        )
    return records


def _build_satellite(record: dict, timescale: Timescale, group: str) -> EarthSatellite:
    # sgp4's OMM reader parses EPOCH with a mandatory fractional part.
    epoch = record.get("EPOCH")
    if isinstance(epoch, str) and "." not in epoch:
        record = {**record, "EPOCH": epoch + ".000000"}

    try:
        return EarthSatellite.from_omm(timescale, record)
    except (KeyError, ValueError) as exc:
        name = record.get("OBJECT_NAME") or record.get("NORAD_CAT_ID") or "?"
        raise ElementsError(f"unusable elements for {name} in group {group!r}: {exc}") from exc


def _age_days(path: Path) -> float:
    return (time.time() - path.stat().st_mtime) / 86400.0


def load_catalog(
    config: CelestrakConfig,
    cache_dir: Path,
    timescale: Timescale,
    reference: datetime,
    max_element_age_days: float,
    force_refresh: bool = False,
    log=lambda message: None,
) -> Catalog:
    """Load every configured CelesTrak group, refreshing the local cache as needed.

    Satellites appearing in several groups are merged into a single entry that
    remembers all of the groups it came from.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)

    by_norad: dict[int, CatalogEntry] = {}
    sources: list[GroupSource] = []
    skipped_stale = 0

    for group in config.groups:
        url = _group_url(config, group)
        cache_file = cache_dir / f"{group.replace('/', '_')}.json"
        records, from_cache = _obtain(config, group, url, cache_file, force_refresh, log)

        for record in records:
            satellite = _build_satellite(record, timescale, group)
            norad = int(record["NORAD_CAT_ID"])
            existing = by_norad.get(norad)
            if existing is None:
                by_norad[norad] = CatalogEntry(
                    satellite=satellite,
                    groups=[group],
                    norad_id=norad,
                    international_designator=(record.get("OBJECT_ID") or "").strip() or None,
                )
            elif group not in existing.groups:
                existing.groups.append(group)
                # Keep whichever element set is closer to the observation window.
                if abs((satellite.epoch.utc_datetime() - reference).total_seconds()) < abs(
                    (existing.epoch_utc - reference).total_seconds()
                ):
                    existing.satellite = satellite

        sources.append(
            GroupSource(
                group=group,
                url=url,
                cache_file=str(cache_file),
                retrieved_utc=datetime.fromtimestamp(cache_file.stat().st_mtime, tz=timezone.utc),
                from_cache=from_cache,
                satellite_count=len(records),
            )
        )

    entries = []
    stale_ids = []
    for entry in by_norad.values():
        age_days = abs((entry.epoch_utc - reference).total_seconds()) / 86400.0
        if age_days > max_element_age_days:
            skipped_stale += 1
            stale_ids.append(entry.norad_id)
            continue
        entries.append(entry)

    if not entries:
        raise ElementsError(
            "every satellite was rejected as having stale elements; "
            "raise search.max_element_age_days or refresh the cache"
        )

    entries.sort(key=lambda e: e.norad_id)
    return Catalog(
        entries=entries,
        sources=sources,
        skipped_stale=skipped_stale,
        stale_ids=sorted(stale_ids),
    )


def _obtain(
    config: CelestrakConfig,
    group: str,
    url: str,
    cache_file: Path,
    force_refresh: bool,
    log,
) -> tuple[list[dict], bool]:
    """Return the group's records, downloading them only when worthwhile."""
    if cache_file.exists():
        age = _age_days(cache_file)
        stale = age > config.max_age_days
    else:
        age = float("inf")
        stale = True

    if not (force_refresh or stale):
        log(f"  {group}: using cached elements ({age:.2f} d old)")
        return _load_cache(cache_file, group), True

    if config.offline:
        if not cache_file.exists():
            raise ElementsError(f"offline mode: no cached elements for group {group!r}")
        log(f"  {group}: offline, using cached elements ({age:.2f} d old)")
        return _load_cache(cache_file, group), True

    log(f"  {group}: downloading from CelesTrak")
    text = _fetch(url)
    records = parse_records(text)

    if records is not None:
        _write_cache(cache_file, text)
        return records, False

    notice = text.splitlines()[0][:200] if text.splitlines() else text[:200]

    # CelesTrak publishes new elements every couple of hours and declines to
    # serve the same set twice. That is not an error: it confirms the cache is
    # current, so mark it fresh to avoid asking again on every run.
    if _NOT_UPDATED in text:
        if not cache_file.exists():
            raise ElementsError(
                f"CelesTrak says group {group!r} is already up to date, but nothing is cached "
                f"at {cache_file}.\n  Another tool on this network may have downloaded it. "
                "Wait for the next update, or fetch the group manually."
            )
        cache_file.touch()
        log(f"  {group}: already current at CelesTrak, keeping cached elements")
        return _load_cache(cache_file, group), True

    raise ElementsError(
        f"CelesTrak did not return orbital elements for {url}\n"
        f"  it said: {notice}\n"
        "  Check the group name against https://celestrak.org/NORAD/elements/"
    )
