"""Tests for the observing window: the countdown logic, and that it paints."""

import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6", reason="the GUI is optional")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from sattransit.gui import THEMES, apply_theme  # noqa: E402
from sattransit.observe import (  # noqa: E402
    Moments,
    ObservingWindow,
    TimelineView,
    countdown_text,
    moments_of,
    phase_at,
    recording_start,
    timeline_span_seconds,
    urgency,
)
from tests.test_gui import NEAR_MISS, TRANSIT  # noqa: E402

INGRESS = datetime(2026, 7, 16, 14, 43, 55, 123000, tzinfo=timezone.utc)
EGRESS = datetime(2026, 7, 16, 14, 43, 56, 274000, tzinfo=timezone.utc)
CLOSEST = datetime(2026, 7, 16, 14, 43, 55, 699000, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# --- reading the times off an event ------------------------------------------


def test_a_transit_yields_ingress_and_egress():
    moments = moments_of(TRANSIT)
    assert moments.ingress == INGRESS
    assert moments.egress == EGRESS
    assert moments.is_transit
    assert moments.duration_seconds == pytest.approx(1.151, abs=0.001)


def test_a_near_miss_counts_to_closest_approach():
    # Nothing touches the disk, so there is no ingress: the countdown runs to
    # the closest approach instead.
    moments = moments_of(NEAR_MISS)
    assert moments.ingress is None
    assert not moments.is_transit
    assert moments.start == moments.end == CLOSEST
    assert moments.duration_seconds == 0.0


def test_an_event_without_a_timestamp_is_reported_as_none():
    assert moments_of({"closest_approach": {}}) is None
    assert moments_of({"closest_approach": {"time_utc": "not a time"}}) is None


# --- the countdown -----------------------------------------------------------


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0.0, "T− 00:00.0"),
        (4.0, "T− 00:04.0"),
        (52.0, "T− 00:52.0"),
        (244.0, "T− 04:04.0"),
        (3671.5, "T− 1:01:11.5"),   # hours only appear when there are some
        (-8.0, "T+ 00:08.0"),       # after the event
    ],
)
def test_countdown_formatting(seconds, expected):
    assert countdown_text(seconds) == expected


def test_the_countdown_always_shows_tenths():
    # A sub-second transit is worth nothing without them.
    assert countdown_text(3.14).endswith(".1")


# --- phase and urgency -------------------------------------------------------


def test_phase_before_during_and_after():
    moments = Moments(closest=CLOSEST, ingress=INGRESS, egress=EGRESS)
    assert phase_at(INGRESS - timedelta(seconds=1), moments) == "before"
    assert phase_at(INGRESS, moments) == "during"
    assert phase_at(CLOSEST, moments) == "during"
    assert phase_at(EGRESS, moments) == "during"
    assert phase_at(EGRESS + timedelta(milliseconds=1), moments) == "after"


@pytest.mark.parametrize(
    "phase,remaining,expected",
    [
        ("before", 600.0, "waiting"),
        ("before", 60.0, "soon"),
        ("before", 11.0, "soon"),
        ("before", 10.0, "imminent"),
        ("before", 0.5, "imminent"),
        ("during", 0.0, "now"),
        ("after", -5.0, "past"),
    ],
)
def test_urgency_escalates_as_the_moment_nears(phase, remaining, expected):
    assert urgency(phase, remaining) == expected


def test_every_urgency_has_a_colour_in_both_themes():
    from sattransit.observe import _URGENCY_COLOUR

    for key in _URGENCY_COLOUR.values():
        assert key in THEMES["dark"] and key in THEMES["light"]


# --- the timeline zoom -------------------------------------------------------


def test_the_timeline_zooms_in_as_the_event_approaches():
    far = timeline_span_seconds(600.0, 1.0)
    near = timeline_span_seconds(30.0, 1.0)
    closer = timeline_span_seconds(2.0, 1.0)
    assert far > near > closer


def test_the_timeline_never_collapses_below_the_transit_itself():
    # A long transit still has to fit inside the strip at the moment it starts.
    assert timeline_span_seconds(0.0, 50.0) >= 100.0
    # And a very short one keeps a usable few seconds of context.
    assert timeline_span_seconds(0.0, 0.2) >= 5.0


def test_the_timeline_is_bounded_for_a_distant_event():
    assert timeline_span_seconds(86400.0, 1.0) == 600.0


# --- painting ----------------------------------------------------------------


@pytest.mark.parametrize("offset", [-3600.0, -244.0, -52.0, -4.0, 0.5, 30.0])
def test_the_window_paints_at_every_stage(app, offset):
    now = INGRESS + timedelta(seconds=offset)
    window = ObservingWindow(
        THEMES["dark"], apply_theme(app, "dark"), TRANSIT, now_provider=lambda: now
    )
    window.resize(520, 400)
    assert not window.grab().isNull()
    window.close()


def test_the_window_paints_for_a_near_miss(app):
    window = ObservingWindow(
        THEMES["dark"],
        apply_theme(app, "dark"),
        NEAR_MISS,
        now_provider=lambda: CLOSEST - timedelta(seconds=30),
    )
    assert "closest approach" in window._caption.text()
    assert not window.grab().isNull()
    window.close()


def test_the_window_says_transit_while_it_is_happening(app):
    window = ObservingWindow(
        THEMES["dark"],
        apply_theme(app, "dark"),
        TRANSIT,
        now_provider=lambda: CLOSEST,
    )
    assert window._countdown.text() == "TRANSIT"
    assert "of 1.15 s" in window._caption.text()
    window.close()


def test_the_window_says_ended_afterwards(app):
    window = ObservingWindow(
        THEMES["dark"],
        apply_theme(app, "dark"),
        TRANSIT,
        now_provider=lambda: EGRESS + timedelta(seconds=8),
    )
    assert window._caption.text() == "ended"
    assert window._countdown.text().startswith("T+")
    window.close()


def test_an_event_without_times_does_not_crash_the_window(app):
    window = ObservingWindow(THEMES["dark"], apply_theme(app, "dark"), {"satellite": {}})
    assert window._countdown.text() == "no time"
    assert not window.grab().isNull()
    window.close()


def test_the_timeline_survives_being_tiny(app):
    view = TimelineView(THEMES["dark"])
    view.resize(6, 6)
    view.update_state(moments_of(TRANSIT), INGRESS)
    assert not view.grab().isNull()


def test_closing_stops_the_clock(app):
    window = ObservingWindow(THEMES["dark"], apply_theme(app, "dark"), TRANSIT)
    assert window._timer.isActive()
    window.close()
    assert not window._timer.isActive()


# --- when to start recording -------------------------------------------------


def test_recording_starts_a_lead_before_mid_on_a_whole_second():
    mid = datetime(2026, 7, 24, 20, 3, 15, 900000, tzinfo=timezone.utc)
    assert recording_start(mid) == datetime(2026, 7, 24, 20, 3, 10, tzinfo=timezone.utc)


def test_the_recording_lead_is_never_shortened_by_rounding():
    # Rounding down means you always get at least the full lead, never less.
    for micro in (0, 1, 200000, 500000, 999999):
        mid = datetime(2026, 7, 24, 20, 3, 15, micro, tzinfo=timezone.utc)
        lead = (mid - recording_start(mid)).total_seconds()
        assert 5.0 <= lead < 6.0


def test_recording_start_crosses_a_minute_boundary():
    mid = datetime(2026, 7, 24, 20, 3, 4, 200000, tzinfo=timezone.utc)
    assert recording_start(mid) == datetime(2026, 7, 24, 20, 2, 59, tzinfo=timezone.utc)


def test_the_recording_lead_is_configurable():
    mid = datetime(2026, 7, 24, 20, 3, 15, 0, tzinfo=timezone.utc)
    assert recording_start(mid, lead_seconds=30).second == 45
    assert recording_start(mid, lead_seconds=30).minute == 2


# --- the countdown font ------------------------------------------------------


def test_the_countdown_font_is_fixed_pitch(app):
    # Otherwise the digits jitter as they tick. macOS's nominal fixed font is
    # not actually monospaced, so the family list matters.
    from PyQt6.QtGui import QFontInfo, QFontMetrics

    from sattransit.observe import countdown_font

    font = countdown_font(39)
    assert QFontInfo(font).fixedPitch()
    metrics = QFontMetrics(font)
    widths = {metrics.horizontalAdvance(t) for t in
              ("T− 00:52.0", "T− 00:11.1", "T− 04:04.0", "T+ 00:08.8")}
    assert len(widths) == 1, "same-length countdowns must render the same width"


# --- local and UTC -----------------------------------------------------------


def _labels(window):
    from PyQt6.QtWidgets import QLabel

    return [w.text() for w in window.findChildren(QLabel)]


def test_the_window_shows_both_local_and_utc(app):
    window = ObservingWindow(
        THEMES["dark"], apply_theme(app, "dark"), TRANSIT, now_provider=lambda: INGRESS
    )
    labels = _labels(window)
    assert "local" in labels and "UTC" in labels
    # AQUA's transit: 16:43:55.1 local (+02:00) is 14:43:55.1 UTC.
    assert "16:43:55.1" in labels and "14:43:55.1" in labels
    window.close()


def test_the_window_offers_a_recording_time(app):
    window = ObservingWindow(
        THEMES["dark"], apply_theme(app, "dark"), TRANSIT, now_provider=lambda: INGRESS
    )
    labels = _labels(window)
    assert "Start recording" in labels
    # Mid is 14:43:55.699 UTC, so recording starts at 14:43:50 on the second.
    assert "14:43:50" in labels
    assert "16:43:50" in labels  # and the local equivalent
    window.close()


def test_a_near_miss_also_gets_a_recording_time(app):
    window = ObservingWindow(
        THEMES["dark"], apply_theme(app, "dark"), NEAR_MISS, now_provider=lambda: CLOSEST
    )
    labels = _labels(window)
    assert "Start recording" in labels
    assert "Closest" in labels
    assert "Ingress" not in labels  # it never touches the disk
    window.close()


def test_the_window_honours_a_configured_lead(app):
    window = ObservingWindow(
        THEMES["dark"], apply_theme(app, "dark"), TRANSIT,
        now_provider=lambda: INGRESS, lead_seconds=30.0,
    )
    # Mid is 14:43:55.699 UTC, so a 30 s lead starts recording at 14:43:25.
    assert "14:43:25" in _labels(window)
    window.close()
