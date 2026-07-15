"""Command line interface."""

from __future__ import annotations

import argparse
import json
import sys
import time

from skyfield.api import Loader

from . import __version__
from .config import ConfigError, load_config
from .finder import TransitFinder
from .report import build_report
from .sizes import SizeError, load_catalogue
from .timeutil import TimeError, resolve_window
from .elements import ElementsError, load_catalog


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sattransit",
        description="Predict satellites transiting the solar disk from an observatory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  sattransit -c config.json --start 2026-07-16T05:00 --duration 12h\n"
            "  sattransit -c config.json --start now --duration 2d -o today.json\n"
            "  sattransit -c config.json --start 2026-07-16T05:00 --end 2026-07-16T20:00\n"
        ),
    )
    parser.add_argument("-c", "--config", required=True, help="path to the JSON configuration file")
    parser.add_argument(
        "--start",
        required=True,
        help="start of the observation window (ISO 8601, or 'now'); "
        "naive times use the observatory timezone",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--end", help="end of the observation window (ISO 8601)")
    group.add_argument("--duration", help="length of the window, e.g. 12h, 90min, 2d")

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
    args = build_parser().parse_args(argv)

    def log(message: str = "") -> None:
        if not args.quiet:
            print(message, file=sys.stderr)

    try:
        config = load_config(args.config)
        if args.offline:
            config.celestrak.offline = True

        tz = config.observatory.zoneinfo()
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
    log(
        f"Window      : {start_dt.astimezone(tz).isoformat(timespec='seconds')} .. "
        f"{end_dt.astimezone(tz).isoformat(timespec='seconds')} "
        f"({(end_dt - start_dt).total_seconds() / 3600.0:.2f} h)"
    )
    log("Elements    :")

    try:
        reference = start_dt + (end_dt - start_dt) / 2
        catalog = load_catalog(
            config.celestrak,
            cache,
            timescale,
            reference=reference,
            max_element_age_days=config.search.max_element_age_days,
            force_refresh=args.refresh,
            log=log,
        )
        ephemeris = loader(config.ephemeris)
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
    except (ElementsError, SizeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except OSError as exc:
        print(f"error: could not load ephemeris {config.ephemeris!r}: {exc}", file=sys.stderr)
        return 3

    log(
        f"Satellites  : {len(catalog.entries)} searched"
        + (
            f", {catalog.skipped_stale} skipped (elements older than "
            f"{config.search.max_element_age_days} d)"
            if catalog.skipped_stale
            else ""
        )
    )

    finder = TransitFinder(config, ephemeris, timescale, sizes)
    events = finder.search(
        catalog.entries,
        timescale.from_datetime(start_dt),
        timescale.from_datetime(end_dt),
        progress=_progress(args.quiet),
    )
    if not args.quiet:
        print(file=sys.stderr)

    runtime = time.monotonic() - started
    report = build_report(config, catalog, events, start_dt, end_dt, runtime)

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

    print(file=sys.stderr)
    header = f"{'local time':<30} {'type':<12} {'satellite':<26} {'sep':>9} {'dur':>7} {'alt':>6}"
    print(header, file=sys.stderr)
    print("-" * len(header), file=sys.stderr)
    for event in events:
        transit = event["transit"]
        duration = f"{transit['duration_seconds']:.2f}s" if transit else "-"
        print(
            f"{event['closest_approach']['time_local']:<30} "
            f"{event['type']:<12} "
            f"{event['satellite']['name'][:25]:<26} "
            f"{event['closest_approach']['separation_arcsec']:>8.0f}\" "
            f"{duration:>7} "
            f"{event['geometry']['satellite_altitude_deg']:>5.1f}°",
            file=sys.stderr,
        )


if __name__ == "__main__":
    sys.exit(main())
