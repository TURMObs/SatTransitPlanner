"""Physical satellite dimensions, for estimating apparent angular size.

Sizes come from GCAT, Jonathan McDowell's General Catalog of Artificial Space
Objects (https://planet4589.org/space/gcat, CC-BY-4.0), which lists a length,
a diameter and a span for essentially every catalogued object.

Two things are worth knowing about the numbers:

* A satellite does not have one size. What it shows during a transit is a
  silhouette whose extent depends on its attitude, which is not predictable
  here, so a range is reported rather than a single figure.
* GCAT describes each catalogued object *as launched*. For an assembled
  structure the entry is the individual piece: object 25544 is the Zarya
  module, span 23.9 m, not the 109 m station. Such cases need an override in
  the configuration.
"""

from __future__ import annotations

import csv
import fnmatch
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

GCAT_URL = "https://planet4589.org/space/gcat/tsv/cat/satcat.tsv"
GCAT_CITATION = "GCAT (J. McDowell, planet4589.org/space/gcat), CC-BY-4.0"

# GCAT marks uncertain or approximate values with a leading symbol.
_QUALIFIERS = "<>~?*"


class SizeError(RuntimeError):
    """Raised when the size catalogue cannot be obtained."""


@dataclass
class Size:
    """A satellite's dimensions, in metres."""

    min_m: float
    max_m: float
    source: str
    shape: str | None = None

    def angular_arcsec(self, range_km: float) -> tuple[float, float]:
        """Angular extent of the smallest and largest dimension, in arcsec."""
        return (
            _angular_arcsec(self.min_m, range_km),
            _angular_arcsec(self.max_m, range_km),
        )


def _angular_arcsec(size_m: float, range_km: float) -> float:
    return math.degrees(2.0 * math.atan2(size_m / 2.0, range_km * 1000.0)) * 3600.0


def _number(value: str | None) -> float | None:
    text = (value or "").strip().lstrip(_QUALIFIERS).strip()
    if not text or text == "-":
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if number > 0 else None


def parse_gcat(lines) -> dict[int, Size]:
    """Read GCAT's satcat TSV into NORAD id -> Size.

    Rows without a usable dimension are skipped rather than guessed at.
    """
    catalogue: dict[int, Size] = {}
    for row in csv.DictReader(lines, delimiter="\t"):
        number = (row.get("Satcat") or "").strip()
        if not number.isdigit():
            continue  # GCAT also carries unnumbered and analyst objects

        dimensions = [
            value
            for value in (
                _number(row.get("Length")),
                _number(row.get("Diameter")),
                _number(row.get("Span")),
            )
            if value is not None
        ]
        if not dimensions:
            continue

        shape = (row.get("Shape") or "").strip() or None
        catalogue[int(number)] = Size(
            min_m=min(dimensions),
            max_m=max(dimensions),
            source="gcat",
            shape=shape,
        )
    return catalogue


def _age_days(path: Path) -> float:
    return (time.time() - path.stat().st_mtime) / 86400.0


def load_catalogue(
    cache_dir: Path,
    max_age_days: float,
    url: str = GCAT_URL,
    offline: bool = False,
    force_refresh: bool = False,
    log=lambda message: None,
) -> dict[int, Size]:
    """Load GCAT, downloading it only when the cached copy has gone stale."""
    cache_file = cache_dir / "gcat_satcat.tsv"
    age = _age_days(cache_file) if cache_file.exists() else float("inf")

    if force_refresh or age > max_age_days:
        if offline and cache_file.exists():
            log(f"  sizes: offline, using cached GCAT ({age:.1f} d old)")
        elif offline:
            raise SizeError(f"offline mode: no cached size catalogue at {cache_file}")
        else:
            log("  sizes: downloading GCAT")
            _download(url, cache_file)
    else:
        log(f"  sizes: using cached GCAT ({age:.1f} d old)")

    with cache_file.open("r", encoding="utf-8", errors="replace") as handle:
        catalogue = parse_gcat(handle)
    if not catalogue:
        raise SizeError(f"no usable dimensions parsed from {cache_file}")
    return catalogue


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "SatTransitPlanner"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise SizeError(f"GCAT returned HTTP {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise SizeError(f"could not reach GCAT at {url}: {exc.reason}") from exc

    text = payload.decode("utf-8", errors="replace")
    if "Satcat" not in text.split("\n", 1)[0]:
        raise SizeError(f"the file at {url} does not look like GCAT's satcat table")

    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(destination)


def parse_overrides(raw: dict) -> list[tuple[str, Size]]:
    """Read the configured sizes into (pattern, Size) pairs, in order.

    A key is either a NORAD id or a glob matched against the satellite's name
    (``STARLINK-*``). A value is one number, or ``[min, max]`` when the two
    differ.
    """
    overrides = []
    for key, value in raw.items():
        if isinstance(value, (int, float)):
            low = high = float(value)
        elif isinstance(value, (list, tuple)) and len(value) == 2:
            low, high = float(value[0]), float(value[1])
        else:
            raise ValueError(
                f"satellite_sizes_m[{key!r}]: expected a number or [min, max], got {value!r}"
            )
        if low <= 0 or high <= 0:
            raise ValueError(f"satellite_sizes_m[{key!r}]: sizes must be positive")
        overrides.append(
            (str(key), Size(min_m=min(low, high), max_m=max(low, high), source="config"))
        )
    return overrides


def resolve(
    norad_id: int,
    name: str | None,
    overrides: list[tuple[str, Size]],
    catalogue: dict[int, Size],
) -> Size | None:
    """Find a satellite's size: the configuration wins, then GCAT."""
    for pattern, size in overrides:
        if pattern == str(norad_id):
            return size
        if name and fnmatch.fnmatch(name.upper(), pattern.upper()):
            return size
    return catalogue.get(norad_id)
