import json

import pytest

from sattransit.config import ConfigError, load_config

MINIMAL = {
    "observatory": {"name": "Test", "latitude_deg": 48.0, "longitude_deg": 11.0},
    "celestrak": {"groups": ["stations"]},
}


def write(tmp_path, data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    return path


def test_minimal_config_gets_defaults(tmp_path):
    config = load_config(write(tmp_path, MINIMAL))
    assert config.observatory.timezone == "UTC"
    assert config.observatory.elevation_m == 0.0
    assert config.search.coarse_step_seconds == 60.0
    assert config.output.file == "transits.json"
    assert config.ephemeris == "de421.bsp"


def test_example_config_is_valid():
    config = load_config("config.example.json")
    assert config.celestrak.groups
    assert config.observatory.timezone == "Europe/Berlin"


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.json")


def test_invalid_json(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json")
    with pytest.raises(ConfigError, match="invalid JSON"):
        load_config(path)


def test_missing_required_section(tmp_path):
    with pytest.raises(ConfigError, match="celestrak"):
        load_config(write(tmp_path, {"observatory": MINIMAL["observatory"]}))


def test_missing_required_option(tmp_path):
    data = {**MINIMAL, "observatory": {"name": "Test", "latitude_deg": 48.0}}
    with pytest.raises(ConfigError, match="longitude_deg"):
        load_config(write(tmp_path, data))


def test_typo_in_option_is_caught(tmp_path):
    data = {**MINIMAL, "search": {"coarse_step_second": 30}}
    with pytest.raises(ConfigError, match="unknown option"):
        load_config(write(tmp_path, data))


def test_typo_in_section_is_caught(tmp_path):
    with pytest.raises(ConfigError, match="unknown top-level key"):
        load_config(write(tmp_path, {**MINIMAL, "serch": {}}))


def test_bad_latitude(tmp_path):
    data = {**MINIMAL, "observatory": {**MINIMAL["observatory"], "latitude_deg": 95.0}}
    with pytest.raises(ConfigError, match="latitude_deg"):
        load_config(write(tmp_path, data))


def test_bad_timezone(tmp_path):
    data = {**MINIMAL, "observatory": {**MINIMAL["observatory"], "timezone": "Mars/Olympus"}}
    with pytest.raises(ConfigError, match="unknown timezone"):
        load_config(write(tmp_path, data))


def test_empty_groups(tmp_path):
    with pytest.raises(ConfigError, match="at least one group"):
        load_config(write(tmp_path, {**MINIMAL, "celestrak": {"groups": []}}))


def test_null_separation_means_limb(tmp_path):
    config = load_config(write(tmp_path, {**MINIMAL, "search": {"max_separation_deg": None}}))
    assert config.search.max_separation_deg is None


def test_negative_separation_rejected(tmp_path):
    with pytest.raises(ConfigError, match="max_separation_deg"):
        load_config(write(tmp_path, {**MINIMAL, "search": {"max_separation_deg": -1}}))


def test_fine_step_must_be_smaller_than_coarse(tmp_path):
    data = {**MINIMAL, "search": {"coarse_step_seconds": 10.0, "fine_step_seconds": 20.0}}
    with pytest.raises(ConfigError, match="fine_step_seconds"):
        load_config(write(tmp_path, data))
