"""Tests for running a search from the viewer.

The presets and the output parsing are plain functions and are tested as such;
what needs Qt is covered in test_gui.py.
"""

import io
import sys
from contextlib import redirect_stderr
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from sattransit.compute import (
    PRESETS,
    TARGETS,
    command,
    output_path,
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


def test_every_preset_has_a_distinct_key():
    assert len({p.key for p in PRESETS}) == len(PRESETS)


def test_the_labels_repeat_across_targets_but_the_titles_do_not():
    # The menu groups them under a heading, so the same three windows can keep
    # their short names; the title is what a status line has to stand on.
    assert len({p.label for p in PRESETS}) == 3
    assert len({p.title for p in PRESETS}) == len(PRESETS)


def test_both_targets_get_the_same_three_windows():
    for target in TARGETS:
        windows = [p for p in PRESETS if p.target == target]
        assert sorted(w.days for w in windows) == [1, 2, 7]


def test_the_presets_are_grouped_by_target():
    # The menu adds a heading whenever the target changes, so a target that
    # appeared twice would get two headings.
    targets = [p.target for p in PRESETS]
    assert targets == sorted(targets, key=TARGETS.index)


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


@pytest.mark.parametrize("preset", PRESETS)
def test_the_command_always_names_its_target(preset):
    # Never left to the configuration: what the menu says is what runs.
    argv = command(preset, "site.json", AFTERNOON)
    assert argv[argv.index("--target") + 1] == preset.target


def test_the_command_names_its_output_file_when_given_one():
    argv = command(PRESETS[0], "site.json", AFTERNOON, output="/tmp/plan.json")
    assert argv[argv.index("--output") + 1] == "/tmp/plan.json"


def test_the_command_leaves_the_output_to_the_configuration_when_not():
    assert "--output" not in command(PRESETS[0], "site.json", AFTERNOON)


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


# --- where the results go ----------------------------------------------------


class _Config:
    """Just enough of a Config for output_path."""

    def __init__(self, target, path):
        self.target = target
        self._path = Path(path)

    def resolve_output(self, _override):
        return self._path


def test_the_configured_target_writes_to_the_configured_file():
    config = _Config("sun", "/plans/transits.json")
    sun = next(p for p in PRESETS if p.target == "sun")
    assert output_path(config, sun) == Path("/plans/transits.json")


def test_the_other_target_writes_beside_it():
    # Otherwise a lunar run would quietly overwrite the solar plan.
    config = _Config("sun", "/plans/transits.json")
    moon = next(p for p in PRESETS if p.target == "moon")
    assert output_path(config, moon) == Path("/plans/transits-moon.json")


def test_the_naming_follows_whichever_target_is_configured():
    # With the Moon configured it is the solar run that gets the sibling.
    config = _Config("moon", "/plans/transits.json")
    by_target = {p.target: output_path(config, p) for p in PRESETS}
    assert by_target["moon"] == Path("/plans/transits.json")
    assert by_target["sun"] == Path("/plans/transits-sun.json")


def test_the_sibling_keeps_the_suffix_and_the_directory():
    config = _Config("sun", "/plans/nightly/plan.result.json")
    moon = next(p for p in PRESETS if p.target == "moon")
    written = output_path(config, moon)
    assert written.parent == Path("/plans/nightly")
    assert written.name == "plan.result-moon.json"


def test_no_two_presets_of_different_targets_share_a_file():
    config = _Config("sun", "/plans/transits.json")
    paths = {p.target: output_path(config, p) for p in PRESETS}
    assert len(set(paths.values())) == len(TARGETS)
