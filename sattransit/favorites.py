"""Favourite satellites: a short list to search in place of whole groups.

Searching every active satellite over a week takes minutes; searching a few
dozen chosen ones takes seconds. A favourites file is just the NORAD ids to
keep, so the elements still come from the configured CelesTrak groups — a
favourite that none of those groups carries cannot be searched, and is
reported rather than passed over.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .elements import CatalogEntry
from .sizes import GCAT_CITATION, Size

# sgp4 reports apogee and perigee as altitudes in Earth radii, on WGS-72.
EARTH_RADIUS_KM = 6378.135

# Taken at its word, "largest" turns up spans that belong to a tether or a wire
# antenna: TSS-1R measures 19.7 km, RAE 1 has 228 m of booms. They have a span
# but nothing to see, so the shapes naming one are left out.
_NOT_SOLID = ("tether", "ant", "wire", "boom")

# An assembled station is catalogued once per module, and CelesTrak tracks each
# of them, so a single pass would otherwise appear several times over. Keep the
# id people actually track.
CANONICAL_STATIONS = {"ISS": 25544, "CSS": 48274}

_STATION_NOTE = (
    "assembled station: the size catalogue describes this module alone, "
    "so set search.satellite_sizes_m for the whole structure"
)


class FavoritesError(ValueError):
    """Raised when a favourites file is missing or unusable."""


@dataclass
class Favorites:
    norad_ids: list[int]
    name: str | None
    path: Path


def _ids_from(entries, path: Path) -> list[int]:
    ids: list[int] = []
    for entry in entries:
        if isinstance(entry, bool):  # bool is an int; catch it before the int test
            raise FavoritesError(f"{path}: {entry!r} is not a NORAD id")
        elif isinstance(entry, int):
            value = entry
        elif isinstance(entry, dict):
            if "norad_id" not in entry:
                raise FavoritesError(f"{path}: an entry has no 'norad_id': {entry!r}")
            value = entry["norad_id"]
        else:
            raise FavoritesError(
                f"{path}: expected a NORAD id or an object with one, got {entry!r}"
            )
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise FavoritesError(f"{path}: {value!r} is not a NORAD id")
        if value not in ids:  # a repeated id would search the satellite twice
            ids.append(value)
    return ids


def load_favorites(path: str | Path) -> Favorites:
    """Read a favourites file.

    Accepts a bare list of ids, a list of objects carrying ``norad_id``, or an
    object with a ``satellites`` list of either. The extra fields exist to keep
    the file readable; only the ids are used.
    """
    path = Path(path).expanduser()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FavoritesError(f"could not read favourites file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise FavoritesError(f"{path} is not valid JSON ({exc})") from exc

    name = None
    if isinstance(raw, dict):
        if "satellites" not in raw:
            raise FavoritesError(f"{path}: expected a 'satellites' list")
        entries = raw["satellites"]
        name = raw.get("name")
    else:
        entries = raw

    if not isinstance(entries, list):
        raise FavoritesError(f"{path}: 'satellites' must be a list")
    ids = _ids_from(entries, path)
    if not ids:
        raise FavoritesError(f"{path}: no satellites listed")
    return Favorites(norad_ids=ids, name=name, path=path)


# --- generating a list -------------------------------------------------------


def _is_solid(shape: str | None) -> bool:
    text = (shape or "").lower()
    return not any(word in text for word in _NOT_SOLID)


def family(name: str) -> str:
    """The satellite's family, so constellation members collapse to one entry.

    Taken literally, the largest few dozen objects are near-identical Starlink
    v2-minis. Grouping keeps the list varied; a full search finds the rest.
    """
    stripped = re.sub(r"[\(\[][^)\]]*[\)\]]", "", name)  # drop (ZVEZDA), [DTC]
    stripped = re.sub(r"[-_ ]*\d+[A-Za-z]?\s*$", "", stripped).strip()  # trailing serial
    return (stripped or name).upper()


def apogee_km(satellite) -> float:
    return float(satellite.model.alta) * EARTH_RADIUS_KM


def build_favorites(
    entries: list[CatalogEntry],
    sizes: dict[int, Size],
    count: int = 60,
    max_apogee_km: float = 2000.0,
) -> dict:
    """Pick the largest distinct objects worth keeping as favourites.

    Only satellites whose elements are already loaded are considered, so every
    entry is one the configured groups can actually search. The orbit comes from
    those elements rather than the size catalogue, which records the orbit an
    object had at the epoch of its catalogue entry.
    """
    candidates = []
    for entry in entries:
        size = sizes.get(entry.norad_id)
        if size is None or not _is_solid(size.shape):
            continue
        if apogee_km(entry.satellite) > max_apogee_km:
            continue  # higher up, even a large satellite subtends almost nothing
        candidates.append(
            {
                "norad_id": entry.norad_id,
                "name": entry.satellite.name or str(entry.norad_id),
                "max_m": size.max_m,
                "shape": size.shape,
            }
        )
    candidates.sort(key=lambda c: (-c["max_m"], c["norad_id"]))
    by_id = {c["norad_id"]: c for c in candidates}

    picked: list[dict] = []
    seen: set[str] = set()
    stations: set[int] = set()
    for candidate in candidates:
        group = family(candidate["name"])
        if group in seen:
            continue
        canonical = CANONICAL_STATIONS.get(group)
        if canonical is not None:
            replacement = by_id.get(canonical)
            if replacement is None:
                continue  # the canonical id is not being tracked; skip the family
            candidate = replacement
            stations.add(canonical)
        seen.add(group)
        picked.append(candidate)
        if len(picked) >= count:
            break

    # A family enters on the rank of its largest member but reports the
    # canonical entry, whose span may be smaller, so re-sort before writing.
    picked.sort(key=lambda c: (-c["max_m"], c["norad_id"]))
    for candidate in picked:
        if candidate["norad_id"] in stations:
            candidate["note"] = _STATION_NOTE

    return {
        "name": f"Largest {len(picked)} distinct objects in low Earth orbit",
        "description": (
            f"The largest span among satellites the configured groups carry, below "
            f"{max_apogee_km:.0f} km, one per family. Spans belonging to a tether or a "
            "wire antenna are excluded, having nothing to see. max_m is informational: "
            "the search reads sizes from the size catalogue and search.satellite_sizes_m."
        ),
        "source": GCAT_CITATION,
        "generated_utc": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "satellites": picked,
    }


def write_favorites(path: str | Path, document: dict, indent: int = 2) -> None:
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=indent, ensure_ascii=False)
        handle.write("\n")
    tmp.replace(path)
