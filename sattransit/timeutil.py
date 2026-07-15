"""Parsing of the observation timeframe given on the command line."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_DURATION = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[a-z]+)", re.IGNORECASE)
_UNITS = {
    "s": 1.0,
    "sec": 1.0,
    "secs": 1.0,
    "second": 1.0,
    "seconds": 1.0,
    "m": 60.0,
    "min": 60.0,
    "mins": 60.0,
    "minute": 60.0,
    "minutes": 60.0,
    "h": 3600.0,
    "hr": 3600.0,
    "hrs": 3600.0,
    "hour": 3600.0,
    "hours": 3600.0,
    "d": 86400.0,
    "day": 86400.0,
    "days": 86400.0,
}


class TimeError(ValueError):
    """Raised when a timeframe argument cannot be understood."""


def parse_datetime(text: str, tz: ZoneInfo) -> datetime:
    """Parse an ISO 8601 timestamp; naive values are read in the given timezone.

    The literal ``now`` is also accepted.
    """
    value = text.strip()
    if value.lower() == "now":
        return datetime.now(timezone.utc)

    candidate = value.replace("Z", "+00:00").replace("z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise TimeError(
            f"could not parse {text!r} as a date/time. "
            "Use ISO 8601, for example 2026-07-16T05:30:00 or 2026-07-16T05:30:00Z"
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(timezone.utc)


def parse_duration(text: str) -> timedelta:
    """Parse a duration such as ``12h``, ``90min`` or ``1d6h``."""
    value = text.strip()
    matches = list(_DURATION.finditer(value))
    if not matches or "".join(m.group(0) for m in matches).replace(" ", "") != value.replace(
        " ", ""
    ):
        raise TimeError(
            f"could not parse {text!r} as a duration. Use forms like 12h, 90min, 2d or 1d6h"
        )

    seconds = 0.0
    for match in matches:
        unit = match.group("unit").lower()
        if unit not in _UNITS:
            raise TimeError(f"unknown duration unit {match.group('unit')!r} in {text!r}")
        seconds += float(match.group("value")) * _UNITS[unit]

    if seconds <= 0:
        raise TimeError(f"duration {text!r} must be positive")
    return timedelta(seconds=seconds)


def resolve_window(
    start_text: str,
    end_text: str | None,
    duration_text: str | None,
    tz: ZoneInfo,
) -> tuple[datetime, datetime]:
    if (end_text is None) == (duration_text is None):
        raise TimeError("specify exactly one of --end or --duration")

    start = parse_datetime(start_text, tz)
    if end_text is not None:
        end = parse_datetime(end_text, tz)
    else:
        end = start + parse_duration(duration_text)  # type: ignore[arg-type]

    if end <= start:
        raise TimeError("the end of the observation window must be after its start")
    return start, end
