from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from sattransit.timeutil import TimeError, parse_datetime, parse_duration, resolve_window

BERLIN = ZoneInfo("Europe/Berlin")


def test_naive_time_uses_observatory_timezone():
    # 05:30 Berlin in July (CEST, UTC+2) is 03:30 UTC.
    parsed = parse_datetime("2026-07-16T05:30:00", BERLIN)
    assert parsed.tzinfo == timezone.utc
    assert parsed.hour == 3 and parsed.minute == 30


def test_explicit_offset_is_respected():
    assert parse_datetime("2026-07-16T05:30:00Z", BERLIN).hour == 5
    assert parse_datetime("2026-07-16T05:30:00+04:00", BERLIN).hour == 1


def test_now_is_accepted():
    assert parse_datetime("now", BERLIN).tzinfo == timezone.utc


def test_bad_datetime_reports_clearly():
    with pytest.raises(TimeError, match="ISO 8601"):
        parse_datetime("next tuesday", BERLIN)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("12h", timedelta(hours=12)),
        ("90min", timedelta(minutes=90)),
        ("2d", timedelta(days=2)),
        ("1d6h", timedelta(days=1, hours=6)),
        ("30s", timedelta(seconds=30)),
        ("1.5h", timedelta(hours=1.5)),
    ],
)
def test_duration_forms(text, expected):
    assert parse_duration(text) == expected


@pytest.mark.parametrize("text", ["", "12", "h", "12 furlongs", "0h", "-3h"])
def test_bad_durations_rejected(text):
    with pytest.raises(TimeError):
        parse_duration(text)


def test_window_from_duration():
    start, end = resolve_window("2026-07-16T05:00:00Z", None, "6h", BERLIN)
    assert (end - start) == timedelta(hours=6)


def test_window_requires_exactly_one_of_end_or_duration():
    with pytest.raises(TimeError, match="exactly one"):
        resolve_window("2026-07-16T05:00:00Z", "2026-07-16T06:00:00Z", "6h", BERLIN)
    with pytest.raises(TimeError, match="exactly one"):
        resolve_window("2026-07-16T05:00:00Z", None, None, BERLIN)


def test_end_must_follow_start():
    with pytest.raises(TimeError, match="must be after"):
        resolve_window("2026-07-16T05:00:00Z", "2026-07-16T04:00:00Z", None, BERLIN)
