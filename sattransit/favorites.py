"""Favourite satellites: a short list to search in place of whole groups.

Searching every active satellite over a week takes minutes; searching a few
dozen chosen ones takes seconds. A favourites file is just the NORAD ids to
keep, so the elements still come from the configured CelesTrak groups — a
favourite that none of those groups carries cannot be searched, and is
reported rather than passed over.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


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
