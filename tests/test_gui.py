"""Tests for the viewer. Rendering runs on Qt's offscreen platform."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6", reason="the GUI is optional")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sattransit.gui import (  # noqa: E402
    COLUMNS,
    THEMES,
    DiskView,
    ReportError,
    SkyView,
    ViewerWindow,
    _detail_values,
    _local_time,
    _offsets,
    _spans_days,
    apply_theme,
    load_report,
)

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
        "sun_radius_arcsec": 943.8,
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
        "sun_altitude_deg": 41.4125,
        "sun_azimuth_deg": 254.9986,
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
    "schema_version": 1,
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
