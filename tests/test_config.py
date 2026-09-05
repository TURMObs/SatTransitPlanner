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


# --- target and illumination (lunar transits) --------------------------------


def test_target_defaults_to_sun(tmp_path):
    assert load_config(write(tmp_path, MINIMAL)).target == "sun"


def test_target_can_be_moon(tmp_path):
    assert load_config(write(tmp_path, {**MINIMAL, "target": "moon"})).target == "moon"


def test_an_unknown_target_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="target"):
        load_config(write(tmp_path, {**MINIMAL, "target": "mars"}))


def test_illumination_defaults_to_any(tmp_path):
    c = load_config(write(tmp_path, MINIMAL))
    assert c.illumination.satellite == "any"
    assert c.illumination.limb == "any"


@pytest.mark.parametrize("value", ["sunlit", "eclipsed", "any"])
def test_illumination_satellite_values(tmp_path, value):
    data = {**MINIMAL, "illumination": {"satellite": value}}
    assert load_config(write(tmp_path, data)).illumination.satellite == value


def test_bad_illumination_satellite_is_rejected(tmp_path):
    data = {**MINIMAL, "illumination": {"satellite": "glowing"}}
    with pytest.raises(ConfigError, match="illumination.satellite"):
        load_config(write(tmp_path, data))


def test_bad_illumination_limb_is_rejected(tmp_path):
    data = {**MINIMAL, "illumination": {"limb": "edge"}}
    with pytest.raises(ConfigError, match="illumination.limb"):
        load_config(write(tmp_path, data))


def test_the_altitude_key_was_renamed_off_the_sun(tmp_path):
    # min_sun_altitude_deg became min_target_altitude_deg; the old name is now
    # an unknown option, reported as such.
    data = {**MINIMAL, "search": {"min_sun_altitude_deg": 5.0}}
    with pytest.raises(ConfigError, match="unknown option"):
        load_config(write(tmp_path, data))
    ok = {**MINIMAL, "search": {"min_target_altitude_deg": 8.0}}
    assert load_config(write(tmp_path, ok)).search.min_target_altitude_deg == 8.0


def test_recording_lead_defaults_to_five_seconds(tmp_path):
    assert load_config(write(tmp_path, MINIMAL)).gui.recording_lead_seconds == 5.0


def test_recording_lead_can_be_changed(tmp_path):
    data = {**MINIMAL, "gui": {"recording_lead_seconds": 30}}
    assert load_config(write(tmp_path, data)).gui.recording_lead_seconds == 30


@pytest.mark.parametrize("bad", [0, -5])
def test_a_non_positive_recording_lead_is_rejected(tmp_path, bad):
    data = {**MINIMAL, "gui": {"recording_lead_seconds": bad}}
    with pytest.raises(ConfigError, match="recording_lead_seconds"):
        load_config(write(tmp_path, data))


# --- the instrument ----------------------------------------------------------


def test_no_instrument_section_means_no_flips_and_no_fields(tmp_path):
    config = load_config(write(tmp_path, MINIMAL))
    assert config.instrument.flip_horizontal is False
    assert config.instrument.flip_vertical is False
    assert config.instrument.fields_of_view == []


def test_a_rectangular_field_is_read(tmp_path):
    raw = {
        **MINIMAL,
        "instrument": {
            "flip_horizontal": True,
            "fields_of_view": [
                {"name": "ASI2600MM", "width_arcmin": 27.5, "height_arcmin": 18.4}
            ],
        },
    }
    instrument = load_config(write(tmp_path, raw)).instrument
    assert instrument.flip_horizontal is True
    field = instrument.fields_of_view[0]
    assert field.name == "ASI2600MM"
    assert field.is_circle is False
    assert field.position_angle_deg == 0.0


def test_a_circular_field_is_read(tmp_path):
    raw = {**MINIMAL, "instrument": {"fields_of_view": [{"name": "f", "diameter_arcmin": 60.0}]}}
    field = load_config(write(tmp_path, raw)).instrument.fields_of_view[0]
    assert field.is_circle
    # Half of 60' in arcseconds: how far it reaches from the centre.
    assert field.extent_arcsec() == pytest.approx(1800.0)


def test_a_rectangle_reaches_to_its_corner():
    from sattransit.config import FieldOfView

    field = FieldOfView(name="f", width_arcmin=8.0, height_arcmin=6.0)
    assert field.extent_arcsec() == pytest.approx(300.0)  # hypot(8,6)/2 = 5' = 300"


@pytest.mark.parametrize(
    "field,expected",
    [
        ({"name": "f"}, "needs width_arcmin"),
        ({"name": "f", "width_arcmin": 10.0}, "needs width_arcmin"),
        ({"name": "f", "width_arcmin": 10.0, "diameter_arcmin": 5.0}, "either"),
        ({"name": "f", "diameter_arcmin": 0.0}, "must be positive"),
        ({"name": " ", "diameter_arcmin": 5.0}, "non-empty"),
        ({"name": "f", "width_arcmin": -1.0, "height_arcmin": 2.0}, "must be positive"),
    ],
)
def test_a_field_that_describes_nothing_is_rejected(tmp_path, field, expected):
    raw = {**MINIMAL, "instrument": {"fields_of_view": [field]}}
    with pytest.raises(ConfigError, match=expected):
        load_config(write(tmp_path, raw))


def test_a_field_without_a_name_is_rejected(tmp_path):
    raw = {**MINIMAL, "instrument": {"fields_of_view": [{"diameter_arcmin": 30.0}]}}
    with pytest.raises(ConfigError, match="name"):
        load_config(write(tmp_path, raw))


def test_the_offending_field_is_identified_by_position(tmp_path):
    raw = {
        **MINIMAL,
        "instrument": {
            "fields_of_view": [
                {"name": "ok", "diameter_arcmin": 30.0},
                {"name": "bad", "diameter_arcmin": -1.0},
            ]
        },
    }
    with pytest.raises(ConfigError, match=r"fields_of_view\[1\]"):
        load_config(write(tmp_path, raw))


def test_fields_of_view_must_be_a_list(tmp_path):
    raw = {**MINIMAL, "instrument": {"fields_of_view": {"name": "f"}}}
    with pytest.raises(ConfigError, match="expected a list"):
        load_config(write(tmp_path, raw))


def test_an_unknown_instrument_option_is_rejected(tmp_path):
    raw = {**MINIMAL, "instrument": {"flip_diagonal": True}}
    with pytest.raises(ConfigError, match="flip_diagonal"):
        load_config(write(tmp_path, raw))


def test_the_meridian_side_defaults_to_any(tmp_path):
    assert load_config(write(tmp_path, MINIMAL)).instrument.meridian_side == "any"


@pytest.mark.parametrize("side", ["any", "east", "west"])
def test_a_meridian_side_is_accepted(tmp_path, side):
    raw = {**MINIMAL, "instrument": {"meridian_side": side}}
    assert load_config(write(tmp_path, raw)).instrument.meridian_side == side


def test_a_nonsense_meridian_side_is_rejected(tmp_path):
    raw = {**MINIMAL, "instrument": {"meridian_side": "sometimes"}}
    with pytest.raises(ConfigError, match="meridian_side"):
        load_config(write(tmp_path, raw))
