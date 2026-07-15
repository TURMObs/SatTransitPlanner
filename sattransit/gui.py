#!/usr/bin/env python3
"""Qt viewer for predicted solar transits.

Reads the JSON written by ``python -m sattransit`` and shows one event at a
time: the list on the left, the Sun's disk with the satellite's chord across it
on the right.

    python -m sattransit.gui results.json
    python -m sattransit.gui -c config.json          # uses output.file
    python -m sattransit.gui results.json --theme light
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from string import Template

try:
    from PyQt6.QtCore import QPointF, QRectF, Qt
    from PyQt6.QtGui import (
        QBrush,
        QColor,
        QFontInfo,
        QPainter,
        QPainterPath,
        QPalette,
        QPen,
        QPolygonF,
        QRadialGradient,
    )
    from PyQt6.QtWidgets import (
        QAbstractSpinBox,
        QApplication,
        QDoubleSpinBox,
        QFileDialog,
        QFrame,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSplitter,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    sys.exit("PyQt6 is required for the GUI: pip install PyQt6")

from . import __version__
from .config import ConfigError, load_config

# --- Themes ------------------------------------------------------------------
#
# Palettes copied from the TURM Control GUI (turmcontrol/gui.py) so the
# observatory tools share one look: a warm dark theme, plus a cool neutral
# light pair. The sun_* and track_* keys are new here, for the disk view.

THEMES = {
    "dark": {
        # palette
        "window": "#1c1b1a", "window_text": "#e4e0da", "base": "#151413",
        "alt_base": "#222120", "tooltip_base": "#2e2d2b", "text": "#e4e0da",
        "button": "#282725", "button_text": "#e4e0da", "bright_text": "#ff7060",
        "link": "#b09070", "highlight": "#5a4e40", "highlight_text": "#ede8e0",
        "mid": "#222120", "dark": "#0c0b0b", "shadow": "#070606", "light": "#353330",
        "disabled": "#625e58",
        # status indicators / accents
        "col_text": "#e4e0da", "col_subtle": "#8c8880", "col_accent": "#b09070",
        "col_on": "#7fb069", "col_off": "#5a5650", "col_unknown": "#c9a227",
        # stylesheet extras
        "btn_border": "#3a3733", "btn_border_bottom": "#4a463f", "btn_hover": "#322f2c",
        "btn_pressed": "#3a3733", "danger": "#c25a48", "expert_bg": "#232220",
        "expert_text": "#c9c4bc", "expert_hover": "#2a2825", "expert_checked_bg": "#3a2f24",
        "expert_checked_text": "#ede0cd", "row_hover": "#222120", "hr": "#2a2825",
        "disabled_border": "#2a2825",
        # disk view
        "plot_bg": "#151413", "sun_core": "#f2c14e", "sun_limb": "#c9902a",
        "sun_rim": "#8a6320", "track": "#171615", "track_outside": "#8c8880",
        "marker_ring": "#e4e0da",
        "macos_dark_titlebar": True,
    },
    "light": {
        # palette (cool neutral grey, slate-blue accent)
        "window": "#eceeee", "window_text": "#191a1d", "base": "#f7f8fa",
        "alt_base": "#e0e3e7", "tooltip_base": "#ffffff", "text": "#23262b",
        "button": "#e1e5e9", "button_text": "#23262b", "bright_text": "#c0392b",
        "link": "#23465f", "highlight": "#c3d3df", "highlight_text": "#23262b",
        "mid": "#d3d7dc", "dark": "#a7adb4", "shadow": "#969ca3", "light": "#ffffff",
        "disabled": "#a0a6ad",
        "col_text": "#23262b", "col_subtle": "#6b7178", "col_accent": "#46708e",
        "col_on": "#3f8a5e", "col_off": "#aab0b7", "col_unknown": "#b08a2a",
        "btn_border": "#c6ccd2", "btn_border_bottom": "#aeb5bd", "btn_hover": "#e8ebee",
        "btn_pressed": "#d5dade", "danger": "#c0392b", "expert_bg": "#e5e9ec",
        "expert_text": "#535960", "expert_hover": "#dce0e4", "expert_checked_bg": "#d2dde7",
        "expert_checked_text": "#2b4659", "row_hover": "#e3e7ea", "hr": "#ccd1d6",
        "disabled_border": "#d3d7dc",
        "plot_bg": "#f7f8fa", "sun_core": "#ffd45c", "sun_limb": "#e3a72c",
        "sun_rim": "#b3821f", "track": "#23262b", "track_outside": "#6b7178",
        "marker_ring": "#23262b",
        "macos_dark_titlebar": False,
    },
}

_STYLE_TEMPLATE = Template("""
QPushButton#expert {
    background: $expert_bg; color: $expert_text; border: 1px solid $btn_border;
    border-radius: 6px; padding: 7px 10px;
}
QPushButton#expert:hover { background: $expert_hover; }
QPushButton#expert:checked { background: $expert_checked_bg; border-color: $col_accent; color: $expert_checked_text; }
QLabel#title  { color: $col_text; font-weight: bold; font-size: ${title_pt}pt; }
QLabel#status { color: $col_subtle; }
QLabel#group  { color: $col_accent; font-weight: bold; font-size: 8pt; }
QLabel#sval   { color: $col_text; }
QLabel#sname  { color: $col_subtle; }
QFrame#row    { border-radius: 4px; }
QFrame#hr     { color: $hr; }
QTableWidget {
    background: $base; alternate-background-color: $alt_base;
    gridline-color: $hr; border: 1px solid $btn_border; border-radius: 4px;
}
QTableWidget::item { padding: 3px 4px; }
QTableWidget::item:selected { background: $highlight; color: $highlight_text; }
QHeaderView::section {
    background: $button; color: $col_subtle; border: none;
    border-bottom: 1px solid $btn_border; padding: 5px 4px; font-weight: bold;
}
QDoubleSpinBox {
    background: $base; color: $col_text; border: 1px solid $btn_border;
    border-radius: 4px; padding: 3px 6px;
}
QDoubleSpinBox:disabled { color: $disabled; }
QPushButton#step {
    background: $button; color: $col_text; border: 1px solid $btn_border;
    border-radius: 4px; padding: 0; font-weight: bold; font-size: ${title_pt}pt;
}
QPushButton#step:hover { background: $btn_hover; }
QPushButton#step:pressed { background: $btn_pressed; }
QScrollArea { border: none; }
""")


def _palette(theme):
    p = QPalette()
    c = QColor
    p.setColor(QPalette.ColorRole.Window,          c(theme["window"]))
    p.setColor(QPalette.ColorRole.WindowText,      c(theme["window_text"]))
    p.setColor(QPalette.ColorRole.Base,            c(theme["base"]))
    p.setColor(QPalette.ColorRole.AlternateBase,   c(theme["alt_base"]))
    p.setColor(QPalette.ColorRole.ToolTipBase,     c(theme["tooltip_base"]))
    p.setColor(QPalette.ColorRole.ToolTipText,     c(theme["text"]))
    p.setColor(QPalette.ColorRole.Text,            c(theme["text"]))
    p.setColor(QPalette.ColorRole.Button,          c(theme["button"]))
    p.setColor(QPalette.ColorRole.ButtonText,      c(theme["button_text"]))
    p.setColor(QPalette.ColorRole.BrightText,      c(theme["bright_text"]))
    p.setColor(QPalette.ColorRole.Link,            c(theme["link"]))
    p.setColor(QPalette.ColorRole.Highlight,       c(theme["highlight"]))
    p.setColor(QPalette.ColorRole.HighlightedText, c(theme["highlight_text"]))
    p.setColor(QPalette.ColorRole.Mid,             c(theme["mid"]))
    p.setColor(QPalette.ColorRole.Dark,            c(theme["dark"]))
    p.setColor(QPalette.ColorRole.Shadow,          c(theme["shadow"]))
    p.setColor(QPalette.ColorRole.Light,           c(theme["light"]))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,       c(theme["disabled"]))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, c(theme["disabled"]))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, c(theme["disabled"]))
    return p


def apply_theme(app, name):
    """Apply the named theme to the app; return its stylesheet string."""
    theme = THEMES.get(name, THEMES["dark"])
    app.setPalette(_palette(theme))
    if theme.get("macos_dark_titlebar"):
        _force_macos_dark_titlebar()

    # Nothing may be set smaller than the platform's default size, which is what
    # the figures in the details panel use. Reading it back beats hardcoding a
    # number that would be wrong on some other machine.
    base = app.font().pointSize()
    if base <= 0:
        base = QFontInfo(app.font()).pointSize() or 9
    return _STYLE_TEMPLATE.substitute(theme, font_pt=base, title_pt=base + 3)


def _force_macos_dark_titlebar():
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApp, NSAppearance  # type: ignore

        NSApp.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua"))
    except Exception:
        pass


# --- Report loading ----------------------------------------------------------


class ReportError(ValueError):
    """Raised when a file is not a usable SatTransitPlanner result."""


def load_report(path: Path) -> dict:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReportError(f"could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ReportError(f"{path} is not valid JSON ({exc})") from exc

    if not isinstance(raw, dict) or "events" not in raw or "observatory" not in raw:
        raise ReportError(
            f"{path} does not look like a SatTransitPlanner result.\n"
            "Generate one with: python -m sattransit -c config.json --start ... --duration ..."
        )
    return raw


# --- Small helpers -----------------------------------------------------------


def _hr():
    line = QFrame()
    line.setObjectName("hr")
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    return line


def _local_time(iso: str, subsecond: bool = True, date: bool = True) -> str:
    """'2026-07-16T16:43:55.699+02:00' -> '2026-07-16 16:43:55.7'."""
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    text = moment.strftime("%Y-%m-%d %H:%M:%S" if date else "%H:%M:%S")
    if subsecond:
        text += f".{moment.microsecond // 100000:d}"
    return text


def _spans_days(window: dict) -> bool:
    """True if the observation window covers more than one local date."""
    try:
        start = datetime.fromisoformat(window["start_local"])
        end = datetime.fromisoformat(window["end_local"])
    except (KeyError, ValueError):
        return True
    return start.date() != end.date()


def _offsets(separation_arcsec: float, position_angle_deg: float) -> tuple[float, float]:
    """Position angle (east of north) and separation back to east/north offsets."""
    angle = math.radians(position_angle_deg)
    return separation_arcsec * math.sin(angle), separation_arcsec * math.cos(angle)


def _limit_box(suffix: str, maximum: float, step: float, tip: str) -> QDoubleSpinBox:
    """A numeric filter limit. Its minimum, 0, reads as 'any' and filters nothing."""
    box = QDoubleSpinBox()
    box.setDecimals(0)
    box.setRange(0.0, maximum)
    box.setSingleStep(step)
    box.setSuffix(suffix)
    box.setSpecialValueText("any")
    box.setToolTip(tip)
    # Re-filtering on every keystroke would be wasted work on a long list.
    box.setKeyboardTracking(False)
    box.setMinimumHeight(34)
    # The native arrows are a few pixels tall and do not grow with the widget,
    # so the field carries its own buttons (see _limit_field).
    box.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    return box


def _limit_field(box: QDoubleSpinBox, tip: str) -> QWidget:
    """A limit box with step buttons big enough to hit without aiming."""
    field = QWidget()
    lay = QHBoxLayout(field)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(3)
    lay.addWidget(box, stretch=1)

    for text, step, what in (("\u2212", box.stepDown, "Decrease"), ("+", box.stepUp, "Increase")):
        button = QPushButton(text)
        button.setObjectName("step")
        button.setFixedWidth(34)
        button.setMinimumHeight(34)
        button.setToolTip(f"{what} by {box.singleStep():.0f}{box.suffix()} — {tip}")
        button.setAutoRepeat(True)
        button.setAutoRepeatDelay(350)
        button.setAutoRepeatInterval(160)
        button.clicked.connect(step)
        lay.addWidget(button)
    return field


class _Item(QTableWidgetItem):
    """A table cell that sorts on a supplied key rather than on its text."""

    def __init__(self, text: str, key):
        super().__init__(text)
        self._key = key
        self.setFlags(self.flags() & ~Qt.ItemFlag.ItemIsEditable)

    def __lt__(self, other):
        if isinstance(other, _Item):
            return self._key < other._key
        return super().__lt__(other)


class DetailRow(QFrame):
    """One read-only figure: name on the left, value on the right."""

    def __init__(self, name: str):
        super().__init__()
        self.setObjectName("row")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(8)
        self._name = QLabel(name)
        self._name.setObjectName("sname")
        self._value = QLabel("--")
        self._value.setObjectName("sval")
        self._value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self._name)
        lay.addStretch(1)
        lay.addWidget(self._value)

    def set_value(self, value):
        self._value.setText("--" if value is None else str(value))


# --- Disk view ---------------------------------------------------------------


class DiskView(QWidget):
    """Draws the Sun's disk and the satellite's path across it.

    Orientation is the usual view of the sky: north up, east left. The chord is
    drawn dark where it crosses the disk, because that is what an observer sees
    — the satellite is backlit, a silhouette against the photosphere.
    """

    def __init__(self, theme: dict):
        super().__init__()
        self._theme = theme
        self._event = None
        self.setMinimumSize(320, 280)

    def set_event(self, event: dict | None):
        self._event = event
        self.update()

    def _track_points(self, event: dict) -> list[tuple[float, float]]:
        path = event.get("path") or []
        if path:
            return [(s["dx_arcsec"], s["dy_arcsec"]) for s in path]

        # No sampled path in the file (output.include_path was false). The
        # closest approach and the direction of travel still fix the chord.
        approach = event["closest_approach"]
        x, y = _offsets(approach["separation_arcsec"], approach["position_angle_deg"])
        angle = math.radians(event["geometry"]["motion_position_angle_deg"])
        reach = approach["sun_radius_arcsec"] * 1.5
        dx, dy = math.sin(angle) * reach, math.cos(angle) * reach
        return [(x - dx, y - dy), (x + dx, y + dy)]

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        painter.fillRect(rect, QColor(self._theme["plot_bg"]))

        if self._event is None:
            painter.setPen(QColor(self._theme["col_subtle"]))
            painter.drawText(
                rect, Qt.AlignmentFlag.AlignCenter, "Select an event to see its path across the Sun."
            )
            return

        approach = self._event["closest_approach"]
        sun_radius = approach["sun_radius_arcsec"]
        points = self._track_points(self._event)

        # Fit the disk and the whole track, whichever reaches further.
        extent = max([sun_radius * 1.15] + [math.hypot(x, y) * 1.08 for x, y in points])
        margin = 34
        span = min(rect.width(), rect.height()) - 2 * margin
        if span <= 0 or extent <= 0:
            return
        scale = (span / 2.0) / extent
        cx, cy = rect.center().x(), rect.center().y()

        def to_screen(x, y):
            # East is left and north is up, as when looking at the sky.
            return QPointF(cx - x * scale, cy - y * scale)

        radius_px = sun_radius * scale
        self._draw_sun(painter, cx, cy, radius_px)
        self._draw_track(painter, to_screen, points, cx, cy, radius_px)
        self._draw_marker(painter, to_screen, approach)
        self._draw_annotations(painter, rect, sun_radius)

    def _draw_sun(self, painter, cx, cy, radius_px):
        gradient = QRadialGradient(cx, cy, radius_px)
        gradient.setColorAt(0.0, QColor(self._theme["sun_core"]))
        gradient.setColorAt(0.86, QColor(self._theme["sun_limb"]))
        gradient.setColorAt(1.0, QColor(self._theme["sun_rim"]))
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), radius_px, radius_px)

    def _draw_track(self, painter, to_screen, points, cx, cy, radius_px):
        polygon = QPolygonF([to_screen(x, y) for x, y in points])
        clip = QPainterPath()
        clip.addEllipse(QPointF(cx, cy), radius_px, radius_px)

        # Two passes: faint and dashed where the satellite is off the disk and
        # invisible, a solid silhouette where it crosses the photosphere.
        # Clipping to the disk saves working out where the chord meets the limb.
        for inside in (False, True):
            painter.save()
            if inside:
                painter.setClipPath(clip)
                colour = QColor(self._theme["track"])
                width, dot, style = 2.2, 3.0, Qt.PenStyle.SolidLine
            else:
                colour = QColor(self._theme["track_outside"])
                width, dot, style = 1.4, 2.2, Qt.PenStyle.DashLine

            painter.setPen(QPen(colour, width, style))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolyline(polygon)

            # Samples are equally spaced in time, so their spacing shows the
            # speed. They must sit proud of the line to be legible.
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(colour))
            for point in polygon:
                painter.drawEllipse(point, dot, dot)

            if len(polygon) >= 2:
                self._draw_arrow(painter, polygon[-2], polygon[-1], colour)
            painter.restore()

    def _draw_arrow(self, painter, start: QPointF, end: QPointF, colour: QColor):
        angle = math.atan2(end.y() - start.y(), end.x() - start.x())
        size = 7.0
        wings = [
            end,
            QPointF(
                end.x() - size * math.cos(angle - math.pi / 7),
                end.y() - size * math.sin(angle - math.pi / 7),
            ),
            QPointF(
                end.x() - size * math.cos(angle + math.pi / 7),
                end.y() - size * math.sin(angle + math.pi / 7),
            ),
        ]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(colour))
        painter.drawPolygon(QPolygonF(wings))

    def _draw_marker(self, painter, to_screen, approach):
        x, y = _offsets(approach["separation_arcsec"], approach["position_angle_deg"])
        centre = to_screen(x, y)
        painter.setBrush(QBrush(QColor(self._theme["track"])))
        painter.setPen(QPen(QColor(self._theme["marker_ring"]), 1.2))
        painter.drawEllipse(centre, 3.4, 3.4)

    def _draw_annotations(self, painter, rect, sun_radius):
        painter.setPen(QColor(self._theme["col_subtle"]))

        painter.drawText(10, 18, f"solar radius {sun_radius:.0f}″  ·  disk ⌀ {sun_radius / 30:.1f}′")
        painter.drawText(10, rect.height() - 8, "dots mark equal time steps")

        # Compass, bottom right so it stays clear of the captions.
        ox, oy, arm = rect.width() - 30, rect.height() - 30, 16
        painter.drawLine(ox, oy, ox, oy - arm)
        painter.drawLine(ox, oy, ox - arm, oy)
        painter.drawText(ox - 4, oy - arm - 4, "N")
        painter.drawText(ox - arm - 14, oy + 4, "E")


# --- Sky view ----------------------------------------------------------------


class SkyView(QWidget):
    """Where in the sky the events happen.

    Zenith at the centre, horizon at the rim, north up and east left — the same
    orientation as the disk view. Every listed event is a dot, so the run of
    dots also traces the Sun's path across the sky during the window.
    """

    def __init__(self, theme: dict):
        super().__init__()
        self._theme = theme
        self._events: list[dict] = []
        self._selected = None
        self.setMinimumSize(260, 260)

    def set_events(self, events: list[dict]):
        self._events = list(events)
        self.update()

    def set_selected(self, event: dict | None):
        self._selected = event
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        painter.fillRect(rect, QColor(self._theme["plot_bg"]))

        margin = 30
        radius = (min(rect.width(), rect.height()) - 2 * margin) / 2.0
        if radius <= 10:
            return
        cx, cy = rect.center().x(), rect.center().y()

        def to_screen(altitude, azimuth):
            r = (90.0 - altitude) / 90.0 * radius
            angle = math.radians(azimuth)
            return QPointF(cx - r * math.sin(angle), cy - r * math.cos(angle))

        self._draw_grid(painter, cx, cy, radius, to_screen)
        self._draw_events(painter, to_screen)
        painter.setPen(QColor(self._theme["col_subtle"]))
        painter.drawText(10, rect.height() - 8, "zenith centre · rings 30°/60°")

    def _draw_grid(self, painter, cx, cy, radius, to_screen):
        centre = QPointF(cx, cy)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        painter.setPen(QPen(QColor(self._theme["hr"]), 1.0))
        for altitude in (30.0, 60.0):
            ring = (90.0 - altitude) / 90.0 * radius
            painter.drawEllipse(centre, ring, ring)
        painter.drawLine(QPointF(cx - radius, cy), QPointF(cx + radius, cy))
        painter.drawLine(QPointF(cx, cy - radius), QPointF(cx, cy + radius))

        painter.setPen(QPen(QColor(self._theme["col_subtle"]), 1.4))
        painter.drawEllipse(centre, radius, radius)

        for label, azimuth in (("N", 0.0), ("E", 90.0), ("S", 180.0), ("W", 270.0)):
            point = to_screen(-7.0, azimuth)  # just outside the horizon
            box = QRectF(point.x() - 11, point.y() - 9, 22, 18)
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label)

    def _draw_events(self, painter, to_screen):
        for event in self._events:
            geometry = event["geometry"]
            point = to_screen(
                geometry["satellite_altitude_deg"], geometry["satellite_azimuth_deg"]
            )
            transit = event["type"] == "disk_transit"
            colour = self._theme["sun_core"] if transit else self._theme["col_subtle"]
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(colour)))
            painter.drawEllipse(point, 3.0 if transit else 2.2, 3.0 if transit else 2.2)

        if self._selected is None:
            return
        geometry = self._selected["geometry"]
        point = to_screen(geometry["satellite_altitude_deg"], geometry["satellite_azimuth_deg"])
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(self._theme["marker_ring"]), 1.6))
        painter.drawEllipse(point, 7.0, 7.0)


# --- Main window -------------------------------------------------------------

COLUMNS = ["Local time", "Satellite", "Type", "Sep (″)", "Dur (s)", "Alt (°)", "Range (km)"]


class ViewerWindow(QWidget):

    def __init__(self, theme: dict, stylesheet: str = "", report: dict | None = None, path=None):
        super().__init__()
        self._theme = theme
        self._report = None
        self._events: list[dict] = []
        self._detail_rows: dict[str, DetailRow] = {}
        self._status_base = "No results loaded."
        self._multiday = False

        self.setWindowTitle("Solar Transits")
        self.setStyleSheet(stylesheet)
        self._build_ui()
        self.resize(1460, 880)

        if report is not None:
            self.set_report(report, path)

    # --- construction --------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(6)
        self._title = QLabel("Solar Transits")
        self._title.setObjectName("title")
        header.addWidget(self._title)
        header.addStretch(1)
        open_btn = QPushButton("Open…")
        open_btn.setObjectName("expert")
        open_btn.setToolTip("Open a results file written by python -m sattransit")
        open_btn.clicked.connect(self._on_open)
        header.addWidget(open_btn)
        root.addLayout(header)

        self._status = QLabel("No results loaded.")
        self._status.setObjectName("status")
        root.addWidget(self._status)
        root.addWidget(_hr())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_list())
        splitter.addWidget(self._build_detail())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([810, 630])
        root.addWidget(splitter, stretch=1)

    def _build_list(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        range_tip = "hides satellites further away than this"
        altitude_tip = "hides events lower in the sky than this"
        separation_tip = "hides events further from the Sun's centre than this"
        self._max_range = _limit_box(" km", 100000.0, 100.0, range_tip)
        self._min_altitude = _limit_box(" °", 90.0, 5.0, altitude_tip)
        self._max_separation = _limit_box(" ″", 7200.0, 100.0, separation_tip)
        for box in (self._max_range, self._min_altitude, self._max_separation):
            box.valueChanged.connect(lambda _: self._apply_filters())

        reset = QPushButton("Reset")
        reset.setObjectName("expert")
        reset.setToolTip("Clear every filter")
        reset.clicked.connect(self._reset_filters)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        for text, box, tip in (
            ("Range ≤", self._max_range, range_tip),
            ("Alt ≥", self._min_altitude, altitude_tip),
            ("Sep ≤", self._max_separation, separation_tip),
        ):
            label = QLabel(text)
            label.setObjectName("sname")
            filters.addWidget(label)
            filters.addWidget(_limit_field(box, tip), stretch=1)
        filters.addWidget(reset)
        lay.addLayout(filters)

        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setShowGrid(False)
        self._table.itemSelectionChanged.connect(self._on_selection)

        head = self._table.horizontalHeader()
        # Not ResizeToContents: that re-measures every row on each cell change,
        # which turns filling the table into O(rows^2) work. The widths are
        # computed once, after the rows are in.
        head.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        head.sortIndicatorChanged.connect(lambda *_: self._apply_filters())
        lay.addWidget(self._table, stretch=1)
        return panel

    def _build_detail(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        rows = QWidget()
        rl = QVBoxLayout(rows)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(1)
        for group, names in _DETAIL_LAYOUT:
            rl.addSpacing(6)
            header = QLabel(group)
            header.setObjectName("group")
            rl.addWidget(header)
            for name in names:
                row = DetailRow(name)
                self._detail_rows[name] = row
                rl.addWidget(row)
        rl.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(rows)

        self._disk = DiskView(self._theme)
        self._sky = SkyView(self._theme)
        plots = QSplitter(Qt.Orientation.Horizontal)
        plots.addWidget(self._disk)
        plots.addWidget(self._sky)
        plots.setStretchFactor(0, 3)
        plots.setStretchFactor(1, 2)
        plots.setSizes([350, 275])

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(plots)
        split.addWidget(scroll)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([400, 280])
        lay.addWidget(split, stretch=1)
        return panel

    # --- data ----------------------------------------------------------------

    def set_report(self, report: dict, path=None):
        self._report = report
        self._events = list(report.get("events", []))

        observatory = report.get("observatory", {})
        self.setWindowTitle(f"Solar Transits — {observatory.get('name', 'Observatory')}")
        self._title.setText(observatory.get("name", "Observatory"))

        window = report.get("observation_window", {})
        stats = report.get("statistics", {})
        self._multiday = _spans_days(window)
        start = _local_time(window.get("start_local", ""))
        end = _local_time(window.get("end_local", ""))
        source = f"  ·  {Path(path).name}" if path else ""
        self._status_base = (
            f"{start} → {end}   ·   "
            f"{stats.get('disk_transits', 0)} disk transit(s), "
            f"{stats.get('near_misses', 0)} near miss(es){source}"
        )
        self._build_rows()
        self._apply_filters()

    def _passes(self, event: dict) -> bool:
        """Whether an event survives the current filters.

        A limit sitting at its minimum reads "any" and filters nothing.
        """
        if self._max_range.value() > 0:
            if event["geometry"]["range_km"] > self._max_range.value():
                return False
        if self._min_altitude.value() > 0:
            if event["geometry"]["satellite_altitude_deg"] < self._min_altitude.value():
                return False
        if self._max_separation.value() > 0:
            if event["closest_approach"]["separation_arcsec"] > self._max_separation.value():
                return False
        return True

    def _event_at(self, row: int) -> dict | None:
        anchor = self._table.item(row, 0)
        return anchor.data(Qt.ItemDataRole.UserRole) if anchor else None

    def _shown_rows(self) -> list[int]:
        return [r for r in range(self._table.rowCount()) if not self._table.isRowHidden(r)]

    def _reset_filters(self):
        for box in (self._max_range, self._min_altitude, self._max_separation):
            box.blockSignals(True)
            box.setValue(0.0)
            box.blockSignals(False)
        self._apply_filters()

    def _apply_filters(self):
        """Hide the rows that the filters exclude.

        Hiding rows rather than rebuilding the table keeps a filter change cheap
        no matter how many events survive it, and leaves the sort order and the
        column widths alone.
        """
        table = self._table
        first_shown = None
        sky = []
        for row in range(table.rowCount()):
            event = self._event_at(row)
            keep = event is not None and self._passes(event)
            table.setRowHidden(row, not keep)
            if keep:
                sky.append(event)
                if first_shown is None:
                    first_shown = row

        shown = f"   ·   showing {len(sky)} of {len(self._events)}"
        self._status.setText(self._status_base + (shown if self._events else ""))
        self._sky.set_events(sky)

        current = table.currentRow()
        if first_shown is None:
            table.clearSelection()
            self._show_event(None)
            return
        if current < 0 or table.isRowHidden(current):
            table.selectRow(first_shown)
        # selectRow emits nothing when that row was already current, so the
        # details would still describe an event the filter has just hidden.
        self._on_selection()

    def _build_rows(self):
        table = self._table
        head = table.horizontalHeader()
        table.setSortingEnabled(False)
        table.setRowCount(len(self._events))

        for row, event in enumerate(self._events):
            approach = event["closest_approach"]
            geometry = event["geometry"]
            transit = event.get("transit")
            duration = transit["duration_seconds"] if transit else None

            cells = [
                _Item(
                    _local_time(approach["time_local"], subsecond=False, date=self._multiday),
                    approach["time_utc"],
                ),
                _Item(event["satellite"]["name"] or "?", (event["satellite"]["name"] or "").lower()),
                _Item(
                    "transit" if event["type"] == "disk_transit" else "near miss",
                    0 if event["type"] == "disk_transit" else 1,
                ),
                _Item(f"{approach['separation_arcsec']:.0f}", approach["separation_arcsec"]),
                _Item("—" if duration is None else f"{duration:.2f}", duration or -1.0),
                _Item(
                    f"{geometry['satellite_altitude_deg']:.1f}", geometry["satellite_altitude_deg"]
                ),
                _Item(f"{geometry['range_km']:,.0f}", geometry["range_km"]),
            ]
            cells[1].setToolTip(
                f"{event['satellite']['name']}  ·  NORAD {event['satellite']['norad_id']}"
            )
            for column, cell in enumerate(cells):
                if column >= 3:
                    cell.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                table.setItem(row, column, cell)
            # Remember the event itself, so sorting cannot desynchronise the
            # table from the data behind it.
            table.item(row, 0).setData(Qt.ItemDataRole.UserRole, event)

        # Size the columns from their contents once, then let the satellite
        # column take whatever room is left.
        table.resizeColumnsToContents()
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.setSortingEnabled(True)
        table.sortItems(0, Qt.SortOrder.AscendingOrder)

    def _on_selection(self):
        row = self._table.currentRow()
        if row < 0 or self._table.isRowHidden(row):
            self._show_event(None)
            return
        self._show_event(self._event_at(row))

    def _show_event(self, event: dict | None):
        self._disk.set_event(event)
        self._sky.set_selected(event)
        values = _detail_values(event) if event else {}
        for name, row in self._detail_rows.items():
            row.set_value(values.get(name))

    # --- actions -------------------------------------------------------------

    def _on_open(self):
        start_dir = str(Path.cwd())
        name, _ = QFileDialog.getOpenFileName(
            self, "Open transit results", start_dir, "JSON files (*.json);;All files (*)"
        )
        if not name:
            return
        try:
            report = load_report(Path(name))
        except ReportError as exc:
            QMessageBox.warning(self, "Could not open file", str(exc))
            return
        self.set_report(report, name)


_DETAIL_LAYOUT = [
    ("SATELLITE", ["Name", "NORAD id", "Designator", "Groups", "Element epoch", "Element age"]),
    ("CLOSEST APPROACH", ["Local time", "UTC", "Separation", "Chord offset", "Position angle"]),
    ("TRANSIT", ["Ingress", "Egress", "Duration"]),
    (
        "GEOMETRY",
        [
            "Satellite alt/az",
            "Sun alt/az",
            "Range",
            "Angular speed",
            "Direction of travel",
        ],
    ),
    ("SIZE", ["Dimensions", "Shape", "Apparent size", "Size source"]),
]


def _detail_values(event: dict) -> dict:
    satellite = event["satellite"]
    approach = event["closest_approach"]
    geometry = event["geometry"]
    transit = event.get("transit")

    offset = approach.get("chord_offset_fraction")
    size = event.get("size")
    values = {
        "Name": satellite["name"],
        "NORAD id": satellite["norad_id"],
        "Designator": satellite.get("international_designator"),
        "Groups": ", ".join(satellite.get("groups", [])),
        "Element epoch": _local_time(satellite["epoch_utc"].replace("Z", "+00:00")) + " UTC",
        "Element age": f"{satellite['element_age_days']:.2f} d",
        "Local time": _local_time(approach["time_local"]),
        "UTC": _local_time(approach["time_utc"].replace("Z", "+00:00")),
        "Separation": (
            f"{approach['separation_arcsec']:.1f}″ "
            f"(disk radius {approach['sun_radius_arcsec']:.0f}″)"
        ),
        "Chord offset": None if offset is None else f"{offset:.3f} of the radius",
        "Position angle": f"{approach['position_angle_deg']:.1f}°",
        "Ingress": _local_time(transit["start_local"]) if transit else None,
        "Egress": _local_time(transit["end_local"]) if transit else None,
        "Duration": f"{transit['duration_seconds']:.3f} s" if transit else None,
        "Satellite alt/az": (
            f"{geometry['satellite_altitude_deg']:.2f}° / "
            f"{geometry['satellite_azimuth_deg']:.2f}°"
        ),
        "Sun alt/az": (
            f"{geometry['sun_altitude_deg']:.2f}° / {geometry['sun_azimuth_deg']:.2f}°"
        ),
        "Range": f"{geometry['range_km']:.1f} km",
        "Angular speed": f"{geometry['angular_velocity_deg_per_s']:.3f}°/s",
        "Direction of travel": f"{geometry['motion_position_angle_deg']:.1f}° (east of north)",
        # A range, not a figure: the silhouette depends on the satellite's
        # attitude, which the prediction says nothing about.
        "Dimensions": None if size is None else f"{size['min_m']:g} – {size['max_m']:g} m",
        "Shape": None if size is None else size.get("shape"),
        "Apparent size": (
            None
            if size is None
            else f"{size['angular_min_arcsec']:.2f}″ – {size['angular_max_arcsec']:.2f}″"
        ),
        "Size source": None if size is None else size.get("source"),
    }
    return values


# --- Entry point -------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sattransit.gui",
        description="View predicted solar transits produced by sattransit.",
    )
    parser.add_argument("results", nargs="?", help="results JSON to open")
    parser.add_argument(
        "-c",
        "--config",
        help="configuration file; its output.file is opened when no results file is given, "
        "and its gui.theme selects the theme",
    )
    parser.add_argument("--theme", choices=("dark", "light"), help="override the configured theme")
    parser.add_argument("--version", action="version", version=f"SatTransitPlanner {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    theme_name = args.theme or "dark"
    results = Path(args.results) if args.results else None

    if args.config:
        try:
            config = load_config(args.config)
        except ConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if args.theme is None:
            theme_name = config.gui.theme
        if results is None:
            results = config.resolve_output(None)

    report = None
    if results is not None:
        try:
            report = load_report(results)
        except ReportError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    app = QApplication(sys.argv)
    app.setApplicationName("Solar Transits")
    app.setOrganizationName("Observatory")
    app.setStyle("Fusion")
    stylesheet = apply_theme(app, theme_name)

    window = ViewerWindow(THEMES[theme_name], stylesheet, report, results)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
