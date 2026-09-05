"""Tests for the viewer. Rendering runs on Qt's offscreen platform."""

import json
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6", reason="the GUI is optional")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sattransit.compute import PRESETS  # noqa: E402
from sattransit.config import FieldOfView, InstrumentConfig  # noqa: E402
from sattransit.gui import (  # noqa: E402
    COLUMNS,
    THEMES,
    DiskView,
    ReportError,
    SkyView,
    ViewerWindow,
    _detail_values,
    _fov_corners,
    _local_time,
    _offsets,
    _spans_days,
    apply_theme,
    load_report,
)

MINIMAL_CONFIG = {
    "observatory": {"name": "Test", "latitude_deg": 48.0, "longitude_deg": 11.0},
    "celestrak": {"groups": ["stations"]},
}

TRANSIT = {
    "event_id": "2026-07-16T14:43:55.699Z_27424",
    "type": "disk_transit",
    "satellite": {
        "name": "AQUA",
        "norad_id": 27424,
        "international_designator": "2002-022A",
        "groups": ["visual"],
        "epoch_utc": "2026-07-14T12:07:11.762Z",
        "element_age_days": 2.109,
    },
    "closest_approach": {
        "time_utc": "2026-07-16T14:43:55.699Z",
        "time_local": "2026-07-16T16:43:55.699+02:00",
        "separation_arcsec": 260.9,
        "separation_deg": 0.072481,
        "target_radius_arcsec": 943.8,
        "chord_offset_fraction": 0.2765,
        "position_angle_deg": 48.83,
    },
    "transit": {
        "start_utc": "2026-07-16T14:43:55.123Z",
        "end_utc": "2026-07-16T14:43:56.274Z",
        "start_local": "2026-07-16T16:43:55.123+02:00",
        "end_local": "2026-07-16T16:43:56.274+02:00",
        "duration_seconds": 1.1515,
    },
    "geometry": {
        "satellite_altitude_deg": 41.4847,
        "satellite_azimuth_deg": 254.9898,
        "target_altitude_deg": 41.4125,
        "target_azimuth_deg": 254.9986,
        "range_km": 986.738,
        "angular_velocity_deg_per_s": 0.43752,
        "motion_position_angle_deg": 318.77,
        "satellite_angular_size_arcsec": None,
    },
    "path": [
        {"offset_seconds": -0.58, "time_utc": "...", "dx_arcsec": 793.1, "dy_arcsec": -510.4},
        {"offset_seconds": 0.0, "time_utc": "...", "dx_arcsec": 196.4, "dy_arcsec": 171.8},
        {"offset_seconds": 0.58, "time_utc": "...", "dx_arcsec": -400.0, "dy_arcsec": 854.0},
    ],
}

NEAR_MISS = {
    **TRANSIT,
    "type": "near_miss",
    "transit": None,
    "closest_approach": {**TRANSIT["closest_approach"], "separation_arcsec": 2909.0},
    "path": [],
}

REPORT = {
    "schema_version": 2,
    "target": "sun",
    "observatory": {"name": "Example Observatory", "timezone": "Europe/Berlin"},
    "observation_window": {
        "start_local": "2026-07-16T04:00:00+02:00",
        "end_local": "2026-07-16T20:00:00+02:00",
    },
    "statistics": {"disk_transits": 1, "near_misses": 1},
    "events": [TRANSIT, NEAR_MISS],
}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# --- pure helpers ------------------------------------------------------------


def test_local_time_formats():
    assert _local_time("2026-07-16T16:43:55.699+02:00") == "2026-07-16 16:43:55.6"
    assert _local_time("2026-07-16T16:43:55.699+02:00", subsecond=False) == "2026-07-16 16:43:55"


def test_local_time_passes_through_what_it_cannot_parse():
    assert _local_time("not a time") == "not a time"


def test_offsets_follow_position_angle():
    # Position angle is measured east of north.
    east, north = _offsets(100.0, 0.0)
    assert (round(east, 6), round(north, 6)) == (0.0, 100.0)
    east, north = _offsets(100.0, 90.0)
    assert (round(east, 6), round(north, 6)) == (100.0, 0.0)


def test_detail_values_cover_a_transit():
    values = _detail_values(TRANSIT)
    assert values["Name"] == "AQUA"
    assert values["Designator"] == "2002-022A"
    assert values["Duration"] == "1.151 s"
    assert "260.9″" in values["Separation"]


def test_detail_values_leave_transit_fields_blank_for_a_near_miss():
    values = _detail_values(NEAR_MISS)
    assert values["Ingress"] is None
    assert values["Egress"] is None
    assert values["Duration"] is None
    assert values["Apparent size"] is None  # no size configured for this satellite


# --- report loading ----------------------------------------------------------


def test_load_report_reads_a_result(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps(REPORT))
    assert load_report(path)["events"][0]["satellite"]["name"] == "AQUA"


def test_load_report_rejects_invalid_json(tmp_path):
    path = tmp_path / "r.json"
    path.write_text("{oops")
    with pytest.raises(ReportError, match="not valid JSON"):
        load_report(path)


def test_load_report_rejects_an_unrelated_json_file(tmp_path):
    path = tmp_path / "r.json"
    path.write_text('{"hello": "world"}')
    with pytest.raises(ReportError, match="does not look like"):
        load_report(path)


def test_load_report_reports_a_missing_file(tmp_path):
    with pytest.raises(ReportError, match="could not read"):
        load_report(tmp_path / "absent.json")


# --- theming -----------------------------------------------------------------


@pytest.mark.parametrize("name", ["dark", "light"])
def test_every_theme_supplies_all_stylesheet_keys(app, name):
    # Template.substitute raises KeyError if a theme is missing an entry.
    assert apply_theme(app, name).strip()


def test_both_themes_define_the_same_keys():
    assert set(THEMES["dark"]) == set(THEMES["light"])


# --- rendering ---------------------------------------------------------------


def test_track_points_use_the_sampled_path(app):
    view = DiskView(THEMES["dark"])
    assert view._track_points(TRANSIT)[1] == (196.4, 171.8)


def test_track_points_fall_back_to_the_direction_of_travel(app):
    # With output.include_path off there is no path, but closest approach and
    # motion still fix the chord.
    view = DiskView(THEMES["dark"])
    points = view._track_points(NEAR_MISS)
    assert len(points) == 2
    assert points[0] != points[1]


@pytest.mark.parametrize("event", [TRANSIT, NEAR_MISS, None])
def test_disk_view_paints_without_error(app, event):
    view = DiskView(THEMES["dark"])
    view.resize(400, 360)
    view.set_event(event)
    assert not view.grab().isNull()


def test_window_shows_a_report_and_paints(app):
    window = ViewerWindow(THEMES["dark"], apply_theme(app, "dark"), REPORT, "r.json")
    window.resize(1120, 720)
    assert window._table.rowCount() == 2
    assert not window.grab().isNull()


def test_events_are_listed_oldest_first(app):
    window = ViewerWindow(THEMES["dark"], apply_theme(app, "dark"), REPORT, None)
    times = [window._table.item(r, 0).text() for r in range(window._table.rowCount())]
    assert times == sorted(times)


def test_selection_survives_sorting(app):
    # The event travels with its row, so re-sorting must not show the details of
    # a different satellite.
    window = ViewerWindow(THEMES["dark"], apply_theme(app, "dark"), REPORT, None)
    window._table.sortItems(3, window._table.horizontalHeader().sortIndicatorOrder())
    window._table.selectRow(0)
    anchor = window._table.item(0, 0)
    event = anchor.data(0x0100)  # Qt.ItemDataRole.UserRole
    assert event["satellite"]["name"] == window._table.item(0, 1).text()


def test_empty_report_clears_the_view(app):
    window = ViewerWindow(THEMES["dark"], apply_theme(app, "dark"), {**REPORT, "events": []}, None)
    assert window._table.rowCount() == 0
    assert not window.grab().isNull()


# --- filters -----------------------------------------------------------------


def _event(
    name,
    kind="near_miss",
    range_km=1600.0,
    altitude=20.0,
    separation=1500.0,
    hour=16,
    apparent=3.7,
):
    event = json.loads(json.dumps(TRANSIT))  # deep copy
    event["satellite"]["name"] = name
    event["size"] = (
        None
        if apparent is None
        else {
            "min_m": 0.3,
            "max_m": 29.0,
            "shape": "Box + pan",
            "source": "gcat",
            "angular_min_arcsec": 0.04,
            "angular_max_arcsec": apparent,
        }
    )
    event["closest_approach"]["time_local"] = f"2026-07-16T{hour:02d}:43:55.699+02:00"
    event["closest_approach"]["time_utc"] = f"2026-07-16T{hour - 2:02d}:43:55.699Z"
    event["type"] = kind
    event["transit"] = TRANSIT["transit"] if kind == "disk_transit" else None
    event["geometry"]["range_km"] = range_km
    event["geometry"]["satellite_altitude_deg"] = altitude
    event["closest_approach"]["separation_arcsec"] = separation
    return event


MIXED = {
    **REPORT,
    "events": [
        _event("LOW-NEAR", range_km=1600.0, altitude=11.0, separation=2900.0, hour=10,
               apparent=3.70),
        # A big satellite, but so far away that it looks tiny.
        _event("GPS", "disk_transit", range_km=24384.0, altitude=41.0, separation=302.0, hour=11,
               apparent=0.16),
        _event("HIGH-LEO", "disk_transit", range_km=1594.0, altitude=55.0, separation=114.0,
               hour=12, apparent=3.75),
        _event("NO-SIZE", "disk_transit", range_km=700.0, altitude=60.0, separation=100.0,
               hour=13, apparent=None),
    ],
}


def _window(app, report=MIXED):
    return ViewerWindow(THEMES["dark"], apply_theme(app, "dark"), report, None)


def _names(window):
    """Satellite names of the rows the user can actually see."""
    return [window._table.item(row, _col("Satellite")).text() for row in window._shown_rows()]


def _col(name):
    """Index of a column by name, so inserting one cannot break the tests."""
    return COLUMNS.index(name)


def _shown(window, column):
    return {
        window._table.item(r, _col("Satellite")).text(): window._table.item(r, _col(column)).text()
        for r in window._shown_rows()
    }


def test_range_filter_hides_distant_satellites(app):
    window = _window(app)
    window._max_range.setValue(2000.0)
    assert set(_names(window)) == {"LOW-NEAR", "HIGH-LEO", "NO-SIZE"}  # GPS at 24384 km is gone


def test_altitude_filter_hides_low_events(app):
    window = _window(app)
    window._min_altitude.setValue(30.0)
    assert set(_names(window)) == {"GPS", "HIGH-LEO", "NO-SIZE"}


def test_separation_filter_hides_distant_approaches(app):
    window = _window(app)
    window._max_separation.setValue(500.0)
    assert set(_names(window)) == {"GPS", "HIGH-LEO", "NO-SIZE"}


def test_separation_filter_stands_in_for_a_transits_only_switch(app):
    # There is no "disk transits only" button: a separation under the solar
    # radius is the same thing, and says so in the units the user is reading.
    window = _window(app)
    window._max_separation.setValue(944.0)
    assert set(_names(window)) == {"GPS", "HIGH-LEO", "NO-SIZE"}  # all disk transits


def test_filters_combine(app):
    window = _window(app)
    window._max_separation.setValue(944.0)  # drops nothing here
    window._max_range.setValue(2000.0)      # drops GPS
    window._min_altitude.setValue(30.0)     # drops LOW-NEAR
    window._min_size.setValue(1.0)          # drops NO-SIZE
    assert _names(window) == ["HIGH-LEO"]


def test_a_limit_of_zero_means_any(app):
    window = _window(app)
    window._max_range.setValue(0.0)
    window._min_altitude.setValue(0.0)
    window._max_separation.setValue(0.0)
    assert len(window._shown_rows()) == 4
    assert window._max_range.text() == "any"


def test_range_steps_in_hundreds_of_km(app):
    window = _window(app)
    assert window._max_range.singleStep() == 100.0
    window._max_range.setValue(1500.0)
    window._max_range.stepUp()
    assert window._max_range.value() == 1600.0


def test_reset_restores_every_event(app):
    window = _window(app)
    window._max_range.setValue(1000.0)
    window._min_altitude.setValue(80.0)
    assert window._shown_rows() == []
    window._reset_filters()
    assert len(window._shown_rows()) == 4
    assert window._max_range.value() == 0.0


def test_status_reports_how_many_are_shown(app):
    window = _window(app)
    window._max_range.setValue(2000.0)
    assert "showing 3 of 4" in window._status.text()


def test_sky_view_follows_the_filter_and_the_selection(app):
    window = _window(app)
    window._max_range.setValue(2000.0)
    assert len(window._sky._events) == 3
    window._table.selectRow(0)
    assert window._sky._selected is not None


def test_range_is_in_the_table(app):
    window = _window(app)
    assert _shown(window, "Range (km)")["GPS"] == "24,384"


# --- date handling -----------------------------------------------------------


def test_single_day_window_drops_the_date_from_the_list(app):
    window = _window(app)
    assert window._table.item(0, 0).text() == "10:43:55"


def test_filters_still_hold_after_re_sorting(app):
    # Sorting rearranges the items, but "hidden" is a property of the row index.
    # Every row must still agree with the filter afterwards.
    window = _window(app)
    window._min_altitude.setValue(30.0)
    window._table.sortItems(_col("Range (km)"))
    for row in range(window._table.rowCount()):
        hidden = window._table.isRowHidden(row)
        assert hidden != window._passes(window._event_at(row))
    assert set(_names(window)) == {"GPS", "HIGH-LEO", "NO-SIZE"}


def test_multi_day_window_keeps_the_date(app):
    report = {
        **MIXED,
        "observation_window": {
            "start_local": "2026-07-16T04:00:00+02:00",
            "end_local": "2026-07-18T20:00:00+02:00",
        },
    }
    window = _window(app, report)
    assert window._table.item(0, 0).text() == "2026-07-16 10:43:55"


def test_spans_days_is_defensive_about_bad_windows():
    assert _spans_days({}) is True
    assert _spans_days({"start_local": "nonsense", "end_local": "nonsense"}) is True


# --- sky view ----------------------------------------------------------------


@pytest.mark.parametrize("report", [MIXED, {**MIXED, "events": []}])
def test_sky_view_paints_without_error(app, report):
    view = SkyView(THEMES["dark"])
    view.resize(320, 320)
    view.set_events(report["events"])
    view.set_selected(report["events"][0] if report["events"] else None)
    assert not view.grab().isNull()


def test_sky_view_survives_being_tiny(app):
    # Dragging the splitter shut must not divide by a zero radius.
    view = SkyView(THEMES["dark"])
    view.resize(8, 8)
    view.set_events(MIXED["events"])
    assert not view.grab().isNull()


# --- fonts -------------------------------------------------------------------


def test_nothing_in_the_list_is_smaller_than_the_figures(app):
    """The list and the top line must not be set below the default size."""
    sheet = apply_theme(app, "dark")
    for rule in ("QTableWidget {", "QHeaderView::section {", "QLabel#status {"):
        block = sheet.split(rule, 1)[1].split("}", 1)[0]
        assert "font-size" not in block, f"{rule} pins a font size"


# --- the details must never describe a different event than the list ----------


def _shown_name(window):
    return window._disk._event["satellite"]["name"] if window._disk._event else None


def test_details_follow_the_selected_row(app):
    window = _window(app)
    assert _shown_name(window) == _names(window)[0] == "LOW-NEAR"
    window._table.selectRow(2)
    assert _shown_name(window) == window._table.item(2, 1).text() == "HIGH-LEO"


def test_details_refresh_when_a_filter_replaces_the_selected_row(app):
    # Filtering out the event at row 0 leaves the selection on row 0, which is
    # now a different satellite. Qt emits no signal for that, so the details
    # would otherwise still describe the event that has just been hidden.
    window = _window(app)
    assert _shown_name(window) == "LOW-NEAR"
    window._min_altitude.setValue(30.0)  # drops LOW-NEAR
    assert _names(window)[0] == "GPS"
    assert _shown_name(window) == "GPS"
    assert window._sky._selected["satellite"]["name"] == "GPS"


def test_details_clear_when_a_filter_empties_the_list(app):
    window = _window(app)
    window._max_range.setValue(100.0)
    assert window._shown_rows() == []
    assert _shown_name(window) is None
    assert window._sky._selected is None


# --- size --------------------------------------------------------------------

SIZED = {
    **TRANSIT,
    "size": {
        "min_m": 0.2,
        "max_m": 9.0,
        "shape": "Box + pan",
        "source": "gcat",
        "angular_min_arcsec": 0.04,
        "angular_max_arcsec": 1.88,
    },
}


def test_size_is_shown_as_a_range():
    values = _detail_values(SIZED)
    assert values["Dimensions"] == "0.2 – 9 m"
    assert values["Apparent size"] == "0.04″ – 1.88″"
    assert values["Shape"] == "Box + pan"
    assert values["Size source"] == "gcat"


def test_a_satellite_without_a_size_shows_blanks_not_zeros():
    values = _detail_values({**TRANSIT, "size": None})
    for row in ("Dimensions", "Shape", "Apparent size", "Size source"):
        assert values[row] is None


def test_an_older_report_without_the_size_field_still_opens(app):
    # Results written before sizes existed carry no "size" key at all.
    values = _detail_values(TRANSIT)
    assert values["Apparent size"] is None
    window = _window(app, {**REPORT, "events": [TRANSIT]})
    assert not window.grab().isNull()


# --- apparent size in the list ------------------------------------------------


def test_the_list_carries_apparent_size_next_to_the_name(app):
    # Apparent size is what decides whether an event is worth shooting, so it
    # sits beside the satellite rather than at the far end of the row.
    assert COLUMNS[2] == "Size (″)"
    shown = _shown(_window(app), "Size (″)")
    assert shown["HIGH-LEO"] == "3.75"
    assert shown["GPS"] == "0.16"  # 19 m across, but at 24000 km
    assert shown["NO-SIZE"] == "—"


def test_apparent_size_sorts_numerically_not_as_text(app):
    window = _window(app)
    window._table.sortItems(_col("Size (″)"), Qt.SortOrder.AscendingOrder)
    values = [window._table.item(r, _col("Size (″)")).text() for r in window._shown_rows()]
    assert values == ["—", "0.16", "3.70", "3.75"]  # the unknown sorts below the rest


def test_size_filter_keeps_only_satellites_that_look_big_enough(app):
    window = _window(app)
    window._min_size.setValue(1.0)
    # The GPS satellite is physically the second largest here but subtends 0.16".
    assert set(_names(window)) == {"LOW-NEAR", "HIGH-LEO"}


def test_size_filter_hides_satellites_of_unknown_size(app):
    # An unknown size cannot be shown to pass the test, so it is hidden.
    window = _window(app)
    assert "NO-SIZE" in _names(window)
    window._min_size.setValue(0.5)
    assert "NO-SIZE" not in _names(window)


def test_size_filter_has_a_decimal_place(app):
    # The others step in whole units; apparent sizes are fractions of an arcsec.
    window = _window(app)
    assert window._min_size.decimals() == 1
    assert window._min_size.singleStep() == 0.5
    window._min_size.setValue(0.5)
    assert window._min_size.value() == 0.5
    assert window._max_range.decimals() == 0


def test_size_filter_is_cleared_by_reset(app):
    window = _window(app)
    window._min_size.setValue(3.0)
    assert len(_names(window)) == 2
    window._reset_filters()
    assert len(_names(window)) == 4
    assert window._min_size.text() == "any"


# --- schema upgrade and lunar reports ----------------------------------------

MOON_TRANSIT = {
    **TRANSIT,
    "closest_approach": {**TRANSIT["closest_approach"], "target_radius_arcsec": 940.0},
    "illumination": {
        "phase_deg": 98.0, "illuminated_fraction": 0.44,
        "bright_limb_angle_deg": 294.0, "limb": "dark", "satellite_sunlit": True,
    },
}
MOON_REPORT = {**REPORT, "target": "moon", "events": [MOON_TRANSIT]}


def test_an_old_v1_report_is_upgraded_on_load(tmp_path):
    # Version 1 named the disk after the Sun; the loader renames those fields.
    v1 = {
        "schema_version": 1,
        "observatory": {"name": "Old", "timezone": "UTC"},
        "observation_window": {"start_local": "2026-07-16T04:00:00Z",
                               "end_local": "2026-07-16T20:00:00Z"},
        "statistics": {"disk_transits": 1, "near_misses": 0},
        "events": [{
            **TRANSIT,
            "closest_approach": {k: v for k, v in TRANSIT["closest_approach"].items()
                                 if k != "target_radius_arcsec"} | {"sun_radius_arcsec": 943.8},
            "geometry": {k: v for k, v in TRANSIT["geometry"].items()
                         if k not in ("target_altitude_deg", "target_azimuth_deg")}
                        | {"sun_altitude_deg": 41.4, "sun_azimuth_deg": 255.0},
        }],
    }
    path = tmp_path / "old.json"
    path.write_text(json.dumps(v1))
    report = load_report(path)

    assert report["target"] == "sun"  # defaulted
    ca = report["events"][0]["closest_approach"]
    assert "target_radius_arcsec" in ca and "sun_radius_arcsec" not in ca
    geo = report["events"][0]["geometry"]
    assert geo["target_altitude_deg"] == 41.4 and "sun_altitude_deg" not in geo


def test_a_lunar_report_opens_and_paints(app):
    window = ViewerWindow(THEMES["dark"], apply_theme(app, "dark"), MOON_REPORT, "moon.json")
    window.resize(1120, 720)
    assert window._table.rowCount() == 1
    assert not window.grab().isNull()


def test_the_disk_view_paints_a_lunar_event(app):
    view = DiskView(THEMES["dark"])
    view.resize(400, 360)
    view.set_event(MOON_TRANSIT)
    assert not view.grab().isNull()


# --- Phase B: Moon rendering -------------------------------------------------

from PyQt6.QtGui import QColor  # noqa: E402


def _dark_limb_sunlit():
    return {**MOON_TRANSIT, "illumination": {**MOON_TRANSIT["illumination"],
                                             "limb": "dark", "satellite_sunlit": True}}


def test_the_window_titles_a_lunar_report(app):
    window = ViewerWindow(THEMES["dark"], apply_theme(app, "dark"), MOON_REPORT, None)
    assert "Lunar" in window.windowTitle()
    assert window._disk._target == "moon"


def test_a_solar_report_stays_solar(app):
    window = ViewerWindow(THEMES["dark"], apply_theme(app, "dark"), REPORT, None)
    assert "Solar" in window.windowTitle()
    assert window._disk._target == "sun"


def test_the_chord_is_a_silhouette_over_the_sun(app):
    # No illumination: always the dark silhouette colour.
    view = DiskView(THEMES["dark"])
    assert view._point_colour(0.0, 100.0, None).name() == QColor(THEMES["dark"]["track"]).name()


def test_the_chord_is_bright_over_the_dark_limb_when_sunlit(app):
    view = DiskView(THEMES["dark"])
    lit = {"bright_limb_angle_deg": 0.0, "satellite_sunlit": True}
    # A point opposite the bright limb (PA 180) is over the dark face -> bright.
    assert view._point_colour(0.0, -100.0, lit).name() == QColor(THEMES["dark"]["sat_bright"]).name()
    # A point toward the bright limb (PA 0) is over the lit face -> silhouette.
    assert view._point_colour(0.0, 100.0, lit).name() == QColor(THEMES["dark"]["track"]).name()


def test_an_eclipsed_satellite_is_drawn_faint_everywhere(app):
    view = DiskView(THEMES["dark"])
    lit = {"bright_limb_angle_deg": 0.0, "satellite_sunlit": False}
    faint = QColor(THEMES["dark"]["track_outside"]).name()
    assert view._point_colour(0.0, 100.0, lit).name() == faint   # over lit face
    assert view._point_colour(0.0, -100.0, lit).name() == faint  # over dark face


def test_the_details_show_illumination_for_the_moon():
    values = _detail_values(_dark_limb_sunlit())
    assert values["Illuminated"] == "44%"
    assert values["Crossing limb"] == "dark limb"
    assert values["Satellite lit"] == "sunlit"
    assert values["Moon phase"] == "98°"


def test_the_illumination_rows_are_blank_for_the_sun():
    values = _detail_values(TRANSIT)
    for row in ("Moon phase", "Illuminated", "Crossing limb", "Satellite lit"):
        assert values[row] is None


@pytest.mark.parametrize("fraction", [0.05, 0.5, 0.8, 1.0])
def test_the_moon_paints_at_every_phase(app, fraction):
    view = DiskView(THEMES["dark"])
    view.set_target("moon")
    view.resize(400, 360)
    view.set_event({**MOON_TRANSIT,
                    "illumination": {**MOON_TRANSIT["illumination"],
                                     "illuminated_fraction": fraction}})
    assert not view.grab().isNull()


# --- the macOS title bar -----------------------------------------------------

from sattransit.gui import _set_macos_appearance  # noqa: E402


def test_setting_the_appearance_is_a_no_op_off_macos(monkeypatch):
    # Nothing to do, and nothing to import, on Linux or Windows.
    monkeypatch.setattr(sys, "platform", "linux")
    called = []
    monkeypatch.setattr("ctypes.util.find_library", lambda name: called.append(name))
    _set_macos_appearance(True)
    _set_macos_appearance(False)
    assert called == []


def test_setting_the_appearance_never_raises(monkeypatch):
    # It runs for its side effect only; a missing runtime must not take the
    # viewer down with it.
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("ctypes.util.find_library", lambda name: "/no/such/library")
    _set_macos_appearance(True)  # must not raise


def test_both_themes_declare_a_titlebar_appearance():
    # apply_theme reads this to decide which appearance to set, so it has to be
    # present in every theme, not just the dark one.
    assert THEMES["dark"]["macos_dark_titlebar"] is True
    assert THEMES["light"]["macos_dark_titlebar"] is False


# --- opening the observing window --------------------------------------------


def test_the_observe_button_is_off_until_something_is_selected(app):
    window = ViewerWindow(THEMES["dark"], apply_theme(app, "dark"), {**REPORT, "events": []}, None)
    assert not window._observe_btn.isEnabled()
    window2 = ViewerWindow(THEMES["dark"], apply_theme(app, "dark"), REPORT, None)
    assert window2._observe_btn.isEnabled()  # a row is selected on load


def test_observing_opens_a_window_for_the_selected_event(app):
    window = ViewerWindow(THEMES["dark"], apply_theme(app, "dark"), REPORT, None)
    window._table.selectRow(0)
    window._on_observe()
    assert len(window._observing) == 1
    opened = window._observing[0]
    assert opened._event["satellite"]["name"] == window._table.item(0, 1).text()
    opened.close()


def test_several_observing_windows_can_be_open_at_once(app):
    # Back-to-back passes are common, so one window must not replace another.
    window = ViewerWindow(THEMES["dark"], apply_theme(app, "dark"), REPORT, None)
    window._table.selectRow(0)
    window._on_observe()
    window._table.selectRow(1)
    window._on_observe()
    assert len(window._observing) == 2
    for opened in window._observing:
        opened.close()


def test_observing_does_nothing_without_a_selection(app):
    window = ViewerWindow(THEMES["dark"], apply_theme(app, "dark"), {**REPORT, "events": []}, None)
    window._on_observe()  # must not raise
    assert getattr(window, "_observing", []) == []


def test_the_configured_recording_lead_reaches_the_observing_window(app):
    from PyQt6.QtWidgets import QLabel

    window = ViewerWindow(
        THEMES["dark"], apply_theme(app, "dark"), REPORT, None, recording_lead_seconds=30.0
    )
    window._table.selectRow(0)
    window._on_observe()
    opened = window._observing[0]
    assert opened._lead_seconds == 30.0
    assert "14:43:25" in [w.text() for w in opened.findChildren(QLabel)]
    opened.close()


def test_no_detail_row_name_is_used_twice():
    # The rows are held in a dict keyed by name, so a duplicate would mean one
    # of them silently never updated.
    import collections

    from sattransit.gui import _DETAIL_LAYOUT

    names = [name for _, rows in _DETAIL_LAYOUT for name in rows]
    assert [n for n, c in collections.Counter(names).items() if c > 1] == []


# --- the element-age uncertainty band ----------------------------------------

WITH_BAND = {
    **TRANSIT,
    "uncertainty": {
        "element_age_days": 3.0,
        "cross_track_km": 0.15,
        "along_track_km": 3.3,
        "cross_track_arcsec": 52.0,
        "timing_seconds": 0.36,
        "could_be_transit": True,
        "could_miss": False,
    },
}


def test_the_disk_view_paints_with_a_band(app):
    view = DiskView(THEMES["dark"])
    view.resize(400, 360)
    view.set_event(WITH_BAND)
    assert not view.grab().isNull()


def test_a_band_wider_than_the_disk_still_paints(app):
    # A very old element set: the band swamps everything, but must not break.
    view = DiskView(THEMES["dark"])
    view.resize(400, 360)
    view.set_event({**WITH_BAND, "uncertainty": {**WITH_BAND["uncertainty"],
                                                "cross_track_arcsec": 5000.0}})
    assert not view.grab().isNull()


def test_an_event_without_an_uncertainty_block_still_paints(app):
    # Results written before the band existed, or with uncertainty disabled.
    view = DiskView(THEMES["dark"])
    view.resize(400, 360)
    view.set_event(TRANSIT)
    assert not view.grab().isNull()


def test_the_details_report_the_band(app):
    values = _detail_values(WITH_BAND)
    assert values["Chord band"] == "± 52″ sideways"
    assert values["Timing"] == "± 0.36 s"
    assert values["Outcome"] == "transit is safe"


def test_the_details_warn_when_a_transit_could_miss():
    event = {**WITH_BAND, "uncertainty": {**WITH_BAND["uncertainty"], "could_miss": True}}
    assert _detail_values(event)["Outcome"] == "could miss"


def test_the_details_flag_a_near_miss_that_could_be_a_transit():
    event = {**WITH_BAND, "type": "near_miss", "transit": None}
    assert _detail_values(event)["Outcome"] == "could be a transit"


def test_the_details_are_blank_without_an_uncertainty_block():
    values = _detail_values(TRANSIT)
    for row in ("Chord band", "Timing", "Outcome"):
        assert values[row] is None


# --- the instrument: framing and orientation ---------------------------------

CAMERA = FieldOfView(name="ASI2600MM", width_arcmin=27.5, height_arcmin=18.4)
FINDER = FieldOfView(name="finder", diameter_arcmin=48.0)


def test_the_default_view_is_the_view_of_the_sky(app):
    view = DiskView(THEMES["dark"])
    assert view._flips == (1.0, 1.0)
    assert "north up, east left" in view.toolTip().lower()


@pytest.mark.parametrize(
    "horizontal,vertical,expected",
    [(False, False, (1.0, 1.0)), (True, False, (-1.0, 1.0)),
     (False, True, (1.0, -1.0)), (True, True, (-1.0, -1.0))],
)
def test_each_flip_turns_its_own_axis_over(app, horizontal, vertical, expected):
    view = DiskView(THEMES["dark"], InstrumentConfig(horizontal, vertical))
    assert view._flips == expected


def test_a_flipped_view_says_so(app):
    view = DiskView(THEMES["dark"], InstrumentConfig(flip_horizontal=True))
    assert "horizontally" in view.toolTip()
    assert "vertically" not in view.toolTip()


def test_the_instrument_can_be_changed_after_construction(app):
    view = DiskView(THEMES["dark"])
    view.set_instrument(InstrumentConfig(flip_vertical=True, fields_of_view=[CAMERA]))
    assert view._flips == (1.0, -1.0)
    view.set_event(TRANSIT)
    assert not view.grab().isNull()


@pytest.mark.parametrize(
    "instrument",
    [
        InstrumentConfig(fields_of_view=[CAMERA]),
        InstrumentConfig(fields_of_view=[FINDER]),
        InstrumentConfig(fields_of_view=[CAMERA, FINDER]),
        InstrumentConfig(flip_horizontal=True, flip_vertical=True, fields_of_view=[CAMERA]),
        # A field far larger than the disk, and one far smaller.
        InstrumentConfig(fields_of_view=[FieldOfView(name="wide", diameter_arcmin=600.0)]),
        InstrumentConfig(fields_of_view=[FieldOfView(name="tight", diameter_arcmin=0.5)]),
    ],
)
def test_the_disk_view_paints_with_any_field_of_view(app, instrument):
    view = DiskView(THEMES["dark"], instrument)
    view.resize(400, 360)
    view.set_event(TRANSIT)
    assert not view.grab().isNull()


def test_a_moon_event_paints_flipped(app):
    # The phase is drawn in screen space, so the flips reach further than the
    # coordinate transform does.
    view = DiskView(THEMES["dark"], InstrumentConfig(flip_horizontal=True))
    view.resize(400, 360)
    view.set_target("moon")
    view.set_event({**TRANSIT, "illumination": {
        "phase_deg": 100.0, "illuminated_fraction": 0.3,
        "bright_limb_angle_deg": 90.0, "limb": "lit", "satellite_sunlit": True}})
    assert not view.grab().isNull()


def test_a_field_of_view_pulls_the_scale_out_to_fit(app):
    # A field wider than the disk is the honest picture of what the camera
    # sees, so the disk has to shrink to make room for it.
    plain = DiskView(THEMES["dark"])
    wide = DiskView(THEMES["dark"], InstrumentConfig(
        fields_of_view=[FieldOfView(name="wide", diameter_arcmin=120.0)]))
    for view in (plain, wide):
        view.resize(400, 360)
        view.set_event(TRANSIT)
    # The wider view draws the same disk over fewer pixels.
    assert _painted_disk_width(wide) < _painted_disk_width(plain)


def _painted_disk_width(view) -> int:
    """How many pixels across the target's disk is, measured off the render."""
    image = view.grab().toImage()
    row = image.height() // 2
    background = image.pixel(2, 2)
    return sum(1 for x in range(image.width()) if image.pixel(x, row) != background)


# --- the fields' geometry ----------------------------------------------------


def test_a_field_at_position_angle_zero_runs_north_and_east():
    corners = _fov_corners(FieldOfView(name="f", width_arcmin=60.0, height_arcmin=30.0))
    east = sorted({round(x) for x, _ in corners})
    north = sorted({round(y) for _, y in corners})
    assert east == [-1800, 1800]   # 60' wide, so +/- 30' in arcsec
    assert north == [-900, 900]    # 30' high


def test_position_angle_turns_the_field_east_of_north():
    # At PA 90 the field's height lies along east, so the extents swap.
    corners = _fov_corners(
        FieldOfView(name="f", width_arcmin=60.0, height_arcmin=30.0, position_angle_deg=90.0)
    )
    assert sorted({round(x) for x, _ in corners}) == [-900, 900]
    assert sorted({round(y) for _, y in corners}) == [-1800, 1800]


def test_a_field_keeps_its_size_whatever_the_position_angle():
    import math

    for angle in (0.0, 17.0, 45.0, 123.0):
        corners = _fov_corners(
            FieldOfView(name="f", width_arcmin=20.0, height_arcmin=10.0, position_angle_deg=angle)
        )
        side = math.dist(corners[0], corners[1])
        assert side == pytest.approx(20.0 * 60.0)  # the width, in arcsec


# --- computing from the viewer -----------------------------------------------


def test_the_compute_button_is_disabled_without_a_configuration(app):
    # Nothing to run: say why rather than failing when it is pressed.
    window = ViewerWindow(THEMES["dark"], apply_theme(app, "dark"), REPORT, None)
    assert not window._compute_btn.isEnabled()
    assert "configuration" in window._compute_btn.toolTip()


def test_the_menu_offers_every_preset(app, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps(MINIMAL_CONFIG))
    window = ViewerWindow(
        THEMES["dark"], apply_theme(app, "dark"), REPORT, None, config_path=config
    )
    assert window._compute_btn.isEnabled()
    assert [a.text() for a in window._compute_menu.actions()] == [p.label for p in PRESETS]


def test_a_running_search_turns_the_button_into_cancel(app, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps(MINIMAL_CONFIG))
    window = ViewerWindow(
        THEMES["dark"], apply_theme(app, "dark"), REPORT, None, config_path=config
    )
    window._set_computing(True)
    assert window._compute_btn.text() == "Cancel"
    # Opening another file mid-run would be replaced the moment it finished.
    assert not window._open_btn.isEnabled()
    window._set_computing(False)
    assert window._compute_btn.text() == "Compute…"
    assert window._open_btn.isEnabled()


def test_a_bad_configuration_is_reported_rather_than_run(app, tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text("{not json")
    window = ViewerWindow(
        THEMES["dark"], apply_theme(app, "dark"), REPORT, None, config_path=config
    )
    shown = []
    monkeypatch.setattr(
        "sattransit.gui.QMessageBox.warning", lambda *args, **kw: shown.append(args[1])
    )
    window._start_compute(PRESETS[0])
    assert shown and "configuration" in shown[0].lower()
    assert not window._runner.running


def test_a_cancelled_search_reports_nothing_and_restores_the_status(app, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps(MINIMAL_CONFIG))
    window = ViewerWindow(
        THEMES["dark"], apply_theme(app, "dark"), REPORT, None, config_path=config
    )
    window._set_computing(True)
    window._on_computed(False, "")  # how a cancellation arrives: no message
    assert window._compute_btn.text() == "Compute…"
    assert window._status.text() == window._status_base


def test_closing_the_window_stops_a_running_search(app, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps(MINIMAL_CONFIG))
    window = ViewerWindow(
        THEMES["dark"], apply_theme(app, "dark"), REPORT, None, config_path=config
    )
    stopped = []
    window._runner.cancel = lambda: stopped.append(True)
    window.close()
    assert stopped, "a search must not outlive the window that started it"
