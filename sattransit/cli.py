"""Command line interface."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone

from skyfield.api import Loader

from . import __version__
from .config import DEFAULT_CONFIG_FILE, ConfigError, load_config
from .finder import TransitFinder
from .target import Target
from .report import build_report
from .sizes import SizeError, load_catalogue
from .spacetrack import SpaceTrackError, load_rocket_bodies, merge
from .timeutil import TimeError, resolve_window
from .elements import ElementsError, load_catalog
from .favorites import FavoritesError, build_favorites, load_favorites, write_favorites


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sattransit",
        description="Predict satellites transiting the solar disk from an observatory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  sattransit --start 2026-07-16T05:00 --duration 12h\n"
            "  sattransit --start now --duration 2d -o today.json\n"
            "  sattransit --start 2026-07-16T05:00 --end 2026-07-16T20:00\n"
            "  sattransit --start now --duration 7d --favorites\n"
            "  sattransit --make-favorites 60\n"
            "  sattransit --config other-site.json --start now --duration 12h\n"
        ),
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_FILE,
        metavar="FILE",
        help=f"JSON configuration file (default: {DEFAULT_CONFIG_FILE})",
    )
    parser.add_argument(
        "--start",
        help="start of the observation window (ISO 8601, or 'now'); "
        "naive times use the observatory timezone",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--end", help="end of the observation window (ISO 8601)")
    group.add_argument("--duration", help="length of the window, e.g. 12h, 90min, 2d")

    parser.add_argument(
        "--target",
        choices=("sun", "moon"),
        help="the body the satellites transit (default: the config's target, else sun)",
    )

    parser.add_argument(
        "--ignore-element-age",
        action="store_true",
        help="search satellites whose elements are older than "
        "search.max_element_age_days, instead of skipping them. Their positions "
        "will be correspondingly less trustworthy",
    )
    parser.add_argument(
        "--favorites",
        nargs="?",
        const=True,
        metavar="FILE",
        help="search only the satellites listed in a favourites file, instead of every "
        "satellite in the configured groups; without FILE, uses favorites.file from the config",
    )
    parser.add_argument(
        "--make-favorites",
        nargs="?",
        const=60,
        type=int,
        metavar="N",
        help="regenerate the favourites file with the N largest distinct objects in low "
        "Earth orbit (default 60) and exit, without searching; writes to the file given "
        "by --favorites, else favorites.file from the config",
    )
    parser.add_argument("-o", "--output", help="output file (overrides output.file in the config)")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="re-download orbital elements even if the cache is still fresh",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="never contact CelesTrak; use the cached elements as they are",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress progress output")
    parser.add_argument("--version", action="version", version=f"SatTransitPlanner {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    making = args.make_favorites is not None
    if making:
        if args.make_favorites < 1:
            parser.error("--make-favorites needs a positive count")
    elif not args.start:
        parser.error("--start is required (or use --make-favorites)")

    def log(message: str = "") -> None:
        if not args.quiet:
            print(message, file=sys.stderr)

    start_dt = end_dt = None
    try:
        config = load_config(args.config)
        if args.offline:
            config.celestrak.offline = True
        if args.target:
            config.target = args.target
        if args.ignore_element_age:
            # Every age test is a comparison against this, so lifting it here
            # is enough; nothing downstream has to know.
            config.search.max_element_age_days = math.inf

        tz = config.observatory.zoneinfo()
        if not making:
            start_dt, end_dt = resolve_window(args.start, args.end, args.duration, tz)
    except (ConfigError, TimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    started = time.monotonic()
    cache = config.cache_path
    cache.mkdir(parents=True, exist_ok=True)
    loader = Loader(str(cache), verbose=not args.quiet)
    timescale = loader.timescale()

    log(f"Observatory : {config.observatory.name}")
    if not making:
        log(f"Target      : {config.target}")
        log(
            f"Window      : {start_dt.astimezone(tz).isoformat(timespec='seconds')} .. "
            f"{end_dt.astimezone(tz).isoformat(timespec='seconds')} "
            f"({(end_dt - start_dt).total_seconds() / 3600.0:.2f} h)"
        )
    log("Elements    :")
    if args.ignore_element_age:
        log("              age limit ignored: old element sets are searched too")

    try:
        # Regenerating the list has no window, so judge element age against now.
        reference = datetime.now(timezone.utc) if making else start_dt + (end_dt - start_dt) / 2
        catalog = load_catalog(
            config.celestrak,
            cache,
            timescale,
            reference=reference,
            max_element_age_days=config.search.max_element_age_days,
            force_refresh=args.refresh,
            log=log,
        )
        if config.spacetrack.enabled:
            extra, source, stale = load_rocket_bodies(
                config.spacetrack,
                cache,
                timescale,
                reference=reference,
                max_element_age_days=config.search.max_element_age_days,
                offline=config.celestrak.offline,
                force_refresh=args.refresh,
                log=log,
            )
            added = merge(catalog.entries, extra)
            catalog.sources.append(source)
            catalog.stale_ids = sorted(set(catalog.stale_ids) | set(stale))
            catalog.skipped_stale += len(stale)
            log(f"              {added} rocket bodies CelesTrak does not carry")

        ephemeris = None if making else loader(config.ephemeris)
        sizes = {}
        if config.sizes.enabled:
            sizes = load_catalogue(
                cache,
                max_age_days=config.sizes.max_age_days,
                url=config.sizes.url,
                offline=config.celestrak.offline,
                force_refresh=args.refresh,
                log=log,
            )
        favorites = None
        if args.favorites and not making:
            path = config.resolve_favorites(None if args.favorites is True else args.favorites)
            favorites = load_favorites(path)
    except (ElementsError, SizeError, FavoritesError, SpaceTrackError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except OSError as exc:
        print(f"error: could not load ephemeris {config.ephemeris!r}: {exc}", file=sys.stderr)
        return 3

    if making:
        return _make_favorites(config, args, catalog, sizes, log)

    missing: list[int] = []
    if favorites is not None:
        wanted = set(favorites.norad_ids)
        found = {e.norad_id for e in catalog.entries}
        missing = sorted(wanted - found)
        catalog.entries = [e for e in catalog.entries if e.norad_id in wanted]
        label = favorites.name or favorites.path.name
        log(f"Favourites  : {label} — {len(catalog.entries)} of {len(wanted)} found")
        if missing:
            # A favourite is only searchable if one of the configured groups
            # carries usable elements for it. Silently dropping it would look
            # like the satellite simply had no transits, so say which reason
            # applies: too old is a different problem from not carried at all.
            stale = [n for n in missing if n in set(catalog.stale_ids)]
            absent = [n for n in missing if n not in set(catalog.stale_ids)]
            if absent:
                shown = ", ".join(str(n) for n in absent[:8])
                more = f" and {len(absent) - 8} more" if len(absent) > 8 else ""
                log(f"              {len(absent)} not in the configured groups: {shown}{more}")
                log(f"              {_group_advice(config)}")
            if stale:
                shown = ", ".join(str(n) for n in stale[:8])
                more = f" and {len(stale) - 8} more" if len(stale) > 8 else ""
                log(
                    f"              {len(stale)} with elements older than "
                    f"{config.search.max_element_age_days} d: {shown}{more}"
                )
        if not catalog.entries:
            print(
                f"error: none of the {len(wanted)} favourites are in the configured groups "
                f"({', '.join(config.celestrak.groups)}).\n"
                f"  {_group_advice(config)}",
                file=sys.stderr,
            )
            return 3

    # The stale count covers the whole catalogue, so it would only confuse when
    # the search has been narrowed to favourites; those are reported above.
    log(
        f"Satellites  : {len(catalog.entries)} searched"
        + (
            f", {catalog.skipped_stale} skipped (elements older than "
            f"{config.search.max_element_age_days} d)"
            if catalog.skipped_stale and favorites is None
            else ""
        )
    )
    if args.ignore_element_age and catalog.entries:
        oldest = max(
            abs((entry.epoch_utc - reference).total_seconds()) / 86400.0
            for entry in catalog.entries
        )
        log(f"              oldest element set in the search: {oldest:.1f} d")

    target = Target(config.target, ephemeris)
    finder = TransitFinder(config, ephemeris, timescale, target, sizes)
    events = finder.search(
        catalog.entries,
        timescale.from_datetime(start_dt),
        timescale.from_datetime(end_dt),
        progress=_progress(args.quiet),
    )
    if not args.quiet:
        print(file=sys.stderr)

    runtime = time.monotonic() - started
    report = build_report(config, catalog, events, start_dt, end_dt, runtime, favorites, missing)

    output = config.resolve_output(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=config.output.indent, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    transits = report["statistics"]["disk_transits"]
    near = report["statistics"]["near_misses"]
    log(f"Result      : {transits} disk transit(s), {near} near miss(es) in {runtime:.1f} s")
    log(f"Written     : {output}")

    if not args.quiet:
        _print_summary(report)
    return 0


def _make_favorites(config, args, catalog, sizes, log) -> int:
    if not sizes:
        print(
            "error: --make-favorites needs the size catalogue, but sizes.enabled is false",
            file=sys.stderr,
        )
        return 3

    target = config.resolve_favorites(args.favorites if isinstance(args.favorites, str) else None)
    document = build_favorites(catalog.entries, sizes, count=args.make_favorites)
    satellites = document["satellites"]
    if not satellites:
        print(
            "error: no satellite in the configured groups has a usable size",
            file=sys.stderr,
        )
        return 3

    existed = target.exists()
    write_favorites(target, document, indent=config.output.indent)
    log(
        f"Favourites  : {len(satellites)} of {args.make_favorites} requested"
        + ("" if len(satellites) == args.make_favorites else " (no more were found)")
    )
    for entry in satellites[:5]:
        log(f"              {entry['max_m']:6.1f} m  {entry['norad_id']:>6}  {entry['name']}")
    if len(satellites) > 5:
        log(f"              … and {len(satellites) - 5} more")
    log(f"{'Replaced' if existed else 'Written'}    : {target}")
    return 0


def _group_advice(config) -> str:
    """What to try when a favourite has no elements.

    Telling someone to add a group they already have would send them chasing
    the wrong problem: by then the id itself is the likely culprit.
    """
    if "active" not in config.celestrak.groups:
        return 'add a broader group (e.g. "active") to celestrak.groups'
    return "check the NORAD ids; CelesTrak carries no elements for these"


def _progress(quiet: bool):
    if quiet:
        return lambda done, total, events: None

    def report(done: int, total: int, events: int) -> None:
        if done % 25 and done != total:
            return
        width = 30
        filled = int(width * done / total)
        bar = "#" * filled + "." * (width - filled)
        print(
            f"\rSearching   : [{bar}] {done}/{total} satellites, {events} event(s)",
            end="",
            file=sys.stderr,
            flush=True,
        )

    return report


def _print_summary(report: dict) -> None:
    events = report["events"]
    if not events:
        return

    # For the Moon, an extra column says which limb and whether the satellite
    # is lit — the difference between a workable pass and an invisible one.
    lunar = report.get("target") == "moon"
    print(file=sys.stderr)
    header = (
        f"{'local time':<30} {'type':<12} {'satellite':<26} "
        f"{'size':>7} {'sep':>9} {'dur':>7} {'alt':>6}"
        + (f"  {'lunar':<14}" if lunar else "")
    )
    print(header, file=sys.stderr)
    print("-" * len(header), file=sys.stderr)
    for event in events:
        transit = event["transit"]
        duration = f"{transit['duration_seconds']:.2f}s" if transit else "-"
        # What the satellite's longest dimension subtends: how big it looks.
        size = event.get("size")
        apparent = f"{size['angular_max_arcsec']:.2f}\"" if size else "-"
        lunar_col = ""
        lit = event.get("illumination")
        if lunar and lit:
            sat = "sunlit" if lit["satellite_sunlit"] else "eclipsed"
            lunar_col = f"  {lit['limb'] + ' limb':<8} {sat}"
        print(
            f"{event['closest_approach']['time_local']:<30} "
            f"{event['type']:<12} "
            f"{event['satellite']['name'][:25]:<26} "
            f"{apparent:>7} "
            f"{event['closest_approach']['separation_arcsec']:>8.0f}\" "
            f"{duration:>7} "
            f"{event['geometry']['satellite_altitude_deg']:>5.1f}°"
            f"{lunar_col}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    sys.exit(main())
