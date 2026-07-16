"""Optional extra elements from Space-Track: the LEO rocket bodies CelesTrak omits.

CelesTrak's groups are payload-oriented — there is no rocket-body group — so
879 spent stages in low orbit are out of reach through it, 212 of them 5 m or
larger. They are among the best transit targets there are: a CZ-2F second stage
is 15.5 m at a 340 km perigee, some 9 arcseconds, where a Starlink v2-mini
gives about four.

Only rocket bodies are fetched. Space-Track also carries about ten thousand
LEO debris fragments, but their median span is under a metre — 0.077" at
800 km, against ~4" for a Starlink — and their high area-to-mass ratio makes
elements go off quickly, so a prediction for one would not be worth acting on.

Space-Track has no API tokens, only an account password, so the credentials are
read from the environment and never from the configuration file:

    export SPACETRACK_IDENTITY='you@example.org'
    export SPACETRACK_PASSWORD='...'

Their user agreement restricts passing the data on; the cache is kept out of
the repository, and results derived from it need the usual citation.
"""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from skyfield.api import Timescale

from . import __version__
from .config import SpaceTrackConfig
from .elements import CatalogEntry, GroupSource, _build_satellite, parse_records

USER_AGENT = f"SatTransitPlanner/{__version__} (+satellite solar transit prediction)"

ENV_IDENTITY = "SPACETRACK_IDENTITY"
ENV_PASSWORD = "SPACETRACK_PASSWORD"

SOURCE_NAME = "space-track:rocket-bodies"
CACHE_FILE = "spacetrack_rocket_bodies.json"

# Space-Track throttles GP queries to one an hour, so a cache younger than this
# cannot be refreshed anyway.
MIN_REFRESH_DAYS = 1.0 / 24.0


class SpaceTrackError(RuntimeError):
    """Raised when Space-Track elements cannot be obtained."""


def credentials() -> tuple[str, str]:
    """Read the account from the environment.

    Space-Track authenticates with the account password itself, so it is never
    taken from the configuration file, which people commit by accident.
    """
    identity = os.environ.get(ENV_IDENTITY, "").strip()
    password = os.environ.get(ENV_PASSWORD, "")
    if not identity or not password:
        raise SpaceTrackError(
            "space-track is enabled but its credentials are not set.\n"
            f"  export {ENV_IDENTITY}='you@example.org'\n"
            f"  export {ENV_PASSWORD}='...'\n"
            "  Register free at https://www.space-track.org/. Set spacetrack.enabled to "
            "false to search without it."
        )
    return identity, password


def query_path(config: SpaceTrackConfig) -> str:
    """The GP query: rocket bodies still in orbit, in low orbit.

    A mean motion above 11.25 revolutions a day is a period under about 128
    minutes, the usual cut for low Earth orbit.

    The space and the ``>`` are left as they are. This whole string is sent as
    the value of a form field, so urlencode escapes it once on the way out;
    escaping it here too would deliver the literal text "ROCKET%20BODY".
    """
    return (
        "/basicspacedata/query/class/gp"
        "/OBJECT_TYPE/ROCKET BODY"
        "/DECAY_DATE/null-val"
        f"/MEAN_MOTION/>{config.min_mean_motion}"
        "/orderby/NORAD_CAT_ID/format/json"
    )


def _fetch(config: SpaceTrackConfig, identity: str, password: str) -> str:
    """One request: Space-Track accepts a query alongside the login."""
    url = config.base_url.rstrip("/") + "/ajaxauth/login"
    payload = urllib.parse.urlencode(
        {
            "identity": identity,
            "password": password,
            "query": config.base_url.rstrip("/") + query_path(config),
        }
    ).encode()
    request = urllib.request.Request(url, data=payload, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        # The body may echo the request, so it is not repeated here.
        raise SpaceTrackError(
            f"Space-Track returned HTTP {exc.code}."
            + (
                "  The credentials were rejected; check "
                f"{ENV_IDENTITY} and {ENV_PASSWORD}."
                if exc.code in (401, 403)
                else "  Their limit is 30 requests a minute and one GP query an hour."
                if exc.code == 429
                else ""
            )
        ) from exc
    except urllib.error.URLError as exc:
        raise SpaceTrackError(f"could not reach Space-Track: {exc.reason}") from exc


def _age_days(path: Path) -> float:
    return (time.time() - path.stat().st_mtime) / 86400.0


def _load_cache(path: Path) -> list[dict]:
    records = parse_records(path.read_text(encoding="utf-8"))
    if records is None:
        raise SpaceTrackError(
            f"cached Space-Track elements are not valid OMM JSON: {path}\n"
            "  Delete the file and run again, or use --refresh."
        )
    return records


def load_rocket_bodies(
    config: SpaceTrackConfig,
    cache_dir: Path,
    timescale: Timescale,
    reference: datetime,
    max_element_age_days: float,
    offline: bool = False,
    force_refresh: bool = False,
    log=lambda message: None,
) -> tuple[list[CatalogEntry], GroupSource, list[int]]:
    """Fetch (or reuse) the LEO rocket bodies, as catalogue entries."""
    cache_file = cache_dir / CACHE_FILE
    age = _age_days(cache_file) if cache_file.exists() else float("inf")
    stale = age > max(config.max_age_days, MIN_REFRESH_DAYS)

    if not (force_refresh or stale):
        log(f"  space-track: using cached rocket bodies ({age:.2f} d old)")
        records = _load_cache(cache_file)
    elif offline:
        if not cache_file.exists():
            raise SpaceTrackError(f"offline mode: no cached Space-Track elements at {cache_file}")
        log(f"  space-track: offline, using cached rocket bodies ({age:.2f} d old)")
        records = _load_cache(cache_file)
    else:
        log("  space-track: downloading LEO rocket bodies")
        identity, password = credentials()
        text = _fetch(config, identity, password)
        records = parse_records(text)
        if records is None:
            notice = " ".join(text.split())[:200]
            raise SpaceTrackError(
                "Space-Track did not return orbital elements.\n"
                f"  it said: {notice or '(nothing)'}\n"
                f"  Check {ENV_IDENTITY} and {ENV_PASSWORD}, and that the account is active."
            )
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(cache_file.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(cache_file)

    entries: list[CatalogEntry] = []
    stale_ids: list[int] = []
    for record in records:
        satellite = _build_satellite(record, timescale, SOURCE_NAME)
        norad = int(record["NORAD_CAT_ID"])
        age_days = abs((satellite.epoch.utc_datetime() - reference).total_seconds()) / 86400.0
        if age_days > max_element_age_days:
            stale_ids.append(norad)
            continue
        entries.append(
            CatalogEntry(
                satellite=satellite,
                groups=[SOURCE_NAME],
                norad_id=norad,
                international_designator=(record.get("OBJECT_ID") or "").strip() or None,
            )
        )

    source = GroupSource(
        group=SOURCE_NAME,
        url=config.base_url.rstrip("/") + query_path(config),
        cache_file=str(cache_file),
        retrieved_utc=datetime.fromtimestamp(cache_file.stat().st_mtime, tz=timezone.utc),
        from_cache=not (force_refresh or stale) or offline,
        satellite_count=len(records),
    )
    return entries, source, stale_ids


def merge(entries: list[CatalogEntry], extra: list[CatalogEntry]) -> int:
    """Add the ones CelesTrak did not already carry. Returns how many were new."""
    known = {e.norad_id for e in entries}
    added = 0
    for entry in extra:
        if entry.norad_id in known:
            continue  # CelesTrak's copy wins: it is the same object
        entries.append(entry)
        known.add(entry.norad_id)
        added += 1
    entries.sort(key=lambda e: e.norad_id)
    return added
