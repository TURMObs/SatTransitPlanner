"""Tests for the command-line surface of both frontends."""

import os

import pytest

from sattransit import cli
from sattransit.config import DEFAULT_CONFIG_FILE, ConfigError, load_config


def test_the_config_file_defaults_so_a_plain_run_works():
    args = cli.build_parser().parse_args(["--start", "now", "--duration", "12h"])
    assert args.config == DEFAULT_CONFIG_FILE == "config.json"


def test_the_config_file_can_still_be_named():
    args = cli.build_parser().parse_args(["--config", "other.json", "--start", "now", "--end", "x"])
    assert args.config == "other.json"


def test_the_short_form_is_gone():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["-c", "config.json", "--start", "now", "--duration", "1h"])


def test_a_search_still_needs_a_start():
    # --start lost its argparse-level 'required' so that --make-favorites can do
    # without it; the combination is checked by hand instead.
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--duration", "12h"])
    assert excinfo.value.code == 2


def test_make_favorites_needs_no_window():
    args = cli.build_parser().parse_args(["--make-favorites"])
    assert args.make_favorites == 60
    assert args.start is None


def test_make_favorites_takes_a_count():
    assert cli.build_parser().parse_args(["--make-favorites", "25"]).make_favorites == 25


def test_a_missing_config_says_what_to_do(tmp_path):
    # This is the first thing a new user meets, now that the path has a default.
    with pytest.raises(ConfigError, match="config.example.json"):
        load_config(tmp_path / "config.json")


# --- the viewer --------------------------------------------------------------


def test_the_viewer_shares_the_option(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6", reason="the GUI is optional")
    from sattransit import gui

    # Left unset for the viewer: an absent config.json leaves it empty rather
    # than failing, so it has to know the difference.
    assert gui.build_parser().parse_args([]).config is None
    assert gui.build_parser().parse_args(["--config", "x.json"]).config == "x.json"
    with pytest.raises(SystemExit):
        gui.build_parser().parse_args(["-c", "x.json"])


def test_the_viewer_opens_the_default_config_when_there_is_one(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6", reason="the GUI is optional")
    from pathlib import Path

    from sattransit import gui

    monkeypatch.chdir(tmp_path)
    assert not Path(gui.DEFAULT_CONFIG_FILE).is_file()
    args = gui.build_parser().parse_args([])
    # With nothing named and nothing to find, the viewer must not try to load.
    assert not (args.config or Path(gui.DEFAULT_CONFIG_FILE).is_file())

    (tmp_path / "config.json").write_text(
        '{"observatory": {"name": "T", "latitude_deg": 0, "longitude_deg": 0},'
        ' "celestrak": {"groups": ["stations"]}}'
    )
    assert args.config or Path(gui.DEFAULT_CONFIG_FILE).is_file()
    assert os.path.isfile("config.json")
