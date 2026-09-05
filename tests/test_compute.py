"""Tests for running a search from the viewer.

The presets and the output parsing are plain functions and are tested as such;
what needs Qt is covered in test_gui.py.
"""

import io
import sys
from contextlib import redirect_stderr
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from sattransit.compute import (
    PRESETS,
    command,
    error_text,
    parse_progress,
    progress_text,
    window_start,
)

pytest.importorskip("PyQt6", reason="the runner needs Qt; the presets do not")

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

BERLIN = ZoneInfo("Europe/Berlin")
AFTERNOON = datetime(2026, 9, 5, 14, 30, 17, tzinfo=BERLIN)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


# --- the windows -------------------------------------------------------------


def test_the_window_starts_at_midnight_however_late_it_is():
    # "Today" means the calendar day: a plan made at half past two should still
    # show the morning's events, not start from now.
    start = window_start(AFTERNOON)
    assert (start.hour, start.minute, start.second, start.microsecond) == (0, 0, 0, 0)
    assert start.date() == AFTERNOON.date()


def test_the_window_keeps_the_observatory_timezone():
    assert window_start(AFTERNOON).tzinfo is BERLIN


def test_every_preset_has_a_distinct_key_and_label():
    assert len({p.key for p in PRESETS}) == len(PRESETS)
    assert len({p.label for p in PRESETS}) == len(PRESETS)


def test_the_presets_cover_a_day_two_days_and_a_week():
    assert sorted(p.days for p in PRESETS) == [1, 2, 7]


def test_only_the_long_window_is_limited_to_favourites():
    # A week over the whole catalogue would run for hours.
    for preset in PRESETS:
        assert preset.favorites == (preset.days == 7)


# --- the command line --------------------------------------------------------


def test_the_command_runs_the_module_with_the_configured_file():
    argv = command(PRESETS[0], "site.json", AFTERNOON, python="python3")
    assert argv[:4] == ["python3", "-m", "sattransit", "--config"]
    assert argv[4] == "site.json"


def test_the_start_carries_no_offset_so_the_cli_reads_it_as_local():
    # parse_datetime reads a naive value in the observatory's timezone, which
    # is the one the observer means.
    argv = command(PRESETS[0], "site.json", AFTERNOON)
    start = argv[argv.index("--start") + 1]
    assert start == "2026-09-05T00:00:00"
    assert "+" not in start and not start.endswith("Z")


@pytest.mark.parametrize("preset", PRESETS)
def test_every_preset_asks_for_its_own_duration(preset):
    argv = command(preset, "site.json", AFTERNOON)
    assert argv[argv.index("--duration") + 1] == f"{preset.days}d"


@pytest.mark.parametrize("preset", PRESETS)
def test_favourites_are_requested_only_where_the_preset_says_so(preset):
    assert ("--favorites" in command(preset, "site.json", AFTERNOON)) == preset.favorites


def test_the_command_defaults_to_the_running_interpreter():
    # A venv's python must be the one that gets the venv's packages.
    assert command(PRESETS[0], "site.json", AFTERNOON)[0] == sys.executable


# --- reading the search's progress -------------------------------------------


def test_progress_is_read_from_the_cli_line():
    assert parse_progress("Searching   : [###...] 812/16334 satellites, 4 event(s)") == (
        812,
        16334,
        4,
    )


def test_the_latest_of_several_updates_wins():
    # They arrive with carriage returns, so one read can hold many.
    chunk = "\r 25/900 satellites, 0 event(s)\r 50/900 satellites, 2 event(s)"
    assert parse_progress(chunk) == (50, 900, 2)


@pytest.mark.parametrize("chunk", ["", "Elements    : downloading active", "no numbers here"])
def test_output_that_is_not_progress_is_ignored(chunk):
    assert parse_progress(chunk) is None


def test_the_viewer_parses_what_the_cli_actually_prints():
    """The one real coupling between the two, so pin it.

    The viewer reads a line the CLI writes for a person. If that wording ever
    changes, this fails rather than the progress silently going blank.
    """
    from sattransit.cli import _progress

    captured = io.StringIO()
    with redirect_stderr(captured):
        _progress(quiet=False)(50, 900, 7)
    assert parse_progress(captured.getvalue()) == (50, 900, 7)


def test_the_progress_line_says_where_the_search_has_got_to():
    text = progress_text(812, 16334, 4)
    assert "5%" in text and "16,334" in text and "4 event" in text


def test_progress_before_anything_is_counted_does_not_divide_by_zero():
    assert progress_text(0, 0, 0).startswith("Searching… 0%")


# --- reporting a failure -----------------------------------------------------


def test_the_error_is_what_the_cli_said():
    stderr = "Observatory : Example\nerror: configuration file not found: /tmp/x.json\n"
    assert error_text(stderr) == "configuration file not found: /tmp/x.json"


def test_a_multi_line_error_is_kept_whole():
    stderr = "error: none of the 60 favourites are in the configured groups\n  Add 'active'.\n"
    message = error_text(stderr)
    assert message.startswith("none of the 60 favourites")
    assert "Add 'active'." in message


def test_the_progress_bar_is_not_mistaken_for_an_error():
    stderr = "\r[###...] 50/900 satellites, 2 event(s)\rerror: could not load ephemeris\n"
    assert error_text(stderr) == "could not load ephemeris"


def test_a_crash_without_an_error_line_still_says_something():
    message = error_text("Traceback (most recent call last):\n  ...\nZeroDivisionError\n")
    assert "ZeroDivisionError" in message


def test_silence_is_reported_rather_than_shown_as_an_empty_dialog():
    assert error_text("") == "the search failed without saying why"


# --- the process ------------------------------------------------------------


def test_a_search_that_cannot_be_started_still_ends(qt_app):
    """Otherwise the viewer's button sits on "Cancel" for good.

    Qt emits errorOccurred but no finished() when the program is missing, so
    the runner has to end the run itself.
    """
    from sattransit.compute import SearchRunner

    runner = SearchRunner()
    seen = []
    runner.finished.connect(lambda ok, message: seen.append((ok, message)))
    runner.start(PRESETS[0], "site.json", AFTERNOON, python="/nonexistent/python")

    for _ in range(200):  # the error arrives on the event loop, not inline
        qt_app.processEvents()
        if seen:
            break
    assert seen and seen[0][0] is False
    assert "could not run" in seen[0][1]
    assert not runner.running


def test_two_searches_at_once_are_refused(qt_app):
    from sattransit.compute import SearchRunner

    runner = SearchRunner()
    runner.start(PRESETS[0], "site.json", AFTERNOON, python=sys.executable)
    try:
        with pytest.raises(RuntimeError, match="already running"):
            runner.start(PRESETS[0], "site.json", AFTERNOON)
    finally:
        runner.cancel()
