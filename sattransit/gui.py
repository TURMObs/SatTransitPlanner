#!/usr/bin/env python3
"""Qt viewer for predicted solar transits.

Reads the JSON written by ``python -m sattransit`` and shows one event at a
time: the list on the left, the Sun's disk with the satellite's chord across it
on the right.

    python -m sattransit.gui                         # uses config.json's output.file
    python -m sattransit.gui results.json
    python -m sattransit.gui --config other-site.json
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
        QGridLayout,
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
from .config import DEFAULT_CONFIG_FILE, ConfigError, load_config
from .observe import RECORDING_LEAD_SECONDS

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
        # moon disk: lit surface, unlit earthshine, rim, and a sunlit satellite
        "moon_lit": "#d7d3ca", "moon_dark": "#39372f", "moon_rim": "#8a857b",
        "sat_bright": "#ffe6a8",
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
        "moon_lit": "#d5d8dd", "moon_dark": "#9aa0a8", "moon_rim": "#6f757d",
        "sat_bright": "#b5741d",
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
    # Set it either way, so the window frame follows the theme rather than the
    # operating system's own light/dark setting.
    _set_macos_appearance(bool(theme.get("macos_dark_titlebar")))

    # Nothing may be set smaller than the platform's default size, which is what
    # the figures in the details panel use. Reading it back beats hardcoding a
    # number that would be wrong on some other machine.
    base = app.font().pointSize()
    if base <= 0:
        base = QFontInfo(app.font()).pointSize() or 9
    return _STYLE_TEMPLATE.substitute(theme, font_pt=base, title_pt=base + 3)


def _set_macos_appearance(dark: bool) -> None:
    """Match the macOS window frame to the theme, whatever the OS is set to.

    Qt paints a window's contents but not its frame, so under a light-mode macOS
    the dark theme otherwise wears a white title bar (and the light theme wears a
    black one under dark mode). Setting the application's appearance fixes the
    frame to match.

    PyObjC is tried first, then the bare Objective-C runtime through ctypes.
    The fallback is what makes this work at all: PyObjC is an optional extra and
    is usually absent, so the import alone silently did nothing. Both paths need
    AppKit loaded, which the Qt application has already done by the time a theme
    is applied; messaging a class that is somehow missing is a no-op in
    Objective-C rather than a crash.
    """
    if sys.platform != "darwin":
        return
    name = "NSAppearanceNameDarkAqua" if dark else "NSAppearanceNameAqua"

    try:  # PyObjC, when it happens to be installed
        from AppKit import NSApp, NSAppearance  # type: ignore

        NSApp.setAppearance_(NSAppearance.appearanceNamed_(name))
        return
    except Exception:
        pass

    try:  # the Objective-C runtime directly, needing nothing extra
        import ctypes
        import ctypes.util

        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        objc.objc_msgSend.restype = ctypes.c_void_p

        def send(receiver, selector, *args, string=None):
            # objc_msgSend is variadic, so its prototype has to be declared for
            # each distinct call or the arguments arrive wrong on arm64.
            if string is not None:
                objc.objc_msgSend.argtypes = [
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                    ctypes.c_char_p,
                ]
                return objc.objc_msgSend(receiver, selector, string)
            objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [
                ctypes.c_void_p
            ] * len(args)
            return objc.objc_msgSend(receiver, selector, *args)

        def cls(name):
            return objc.objc_getClass(name.encode())

        def sel(name):
            return objc.sel_registerName(name.encode())

        ns_name = send(
            cls("NSString"),
            sel("stringWithUTF8String:"),
            string=name.encode(),
        )
        appearance = send(cls("NSAppearance"), sel("appearanceNamed:"), ns_name)
        application = send(cls("NSApplication"), sel("sharedApplication"))
        send(application, sel("setAppearance:"), appearance)
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
            "Generate one with: python -m sattransit --start ... --duration ..."
        )
    return _upgrade(raw)


def _upgrade(report: dict) -> dict:
    """Bring an older (schema 1, solar-only) result up to the current shape.

    Version 1 named the disk after the Sun (``sun_radius_arcsec`` and so on).
    Renaming those to ``target_*`` on load means the rest of the viewer only
    ever deals with one vocabulary.
    """
    report.setdefault("target", "sun")
    renames = {
        "closest_approach": {"sun_radius_arcsec": "target_radius_arcsec"},
        "geometry": {"sun_altitude_deg": "target_altitude_deg",
                     "sun_azimuth_deg": "target_azimuth_deg"},
    }
    for event in report.get("events", []):
        for section, mapping in renames.items():
            block = event.get(section) or {}
            for old, new in mapping.items():
                if old in block and new not in block:
                    block[new] = block.pop(old)
    return report


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


def _limit_box(
    suffix: str, maximum: float, step: float, tip: str, decimals: int = 0
) -> QDoubleSpinBox:
    """A numeric filter limit. Its minimum, 0, reads as 'any' and filters nothing."""
    box = QDoubleSpinBox()
    box.setDecimals(decimals)
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
        step_text = f"{box.singleStep():.{box.decimals()}f}"
        button.setToolTip(f"{what} by {step_text}{box.suffix()} — {tip}")
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
    """Draws the target's disk and the satellite's path across it.

    Orientation is the usual view of the sky: north up, east left. Over the Sun,
    or the lit face of the Moon, the satellite is a backlit silhouette and the
    chord is drawn dark. Over the Moon's dark face it is drawn bright when the
    satellite is sunlit, and faint when it is eclipsed and so invisible.
    """

    def __init__(self, theme: dict):
        super().__init__()
        self._theme = theme
        self._event = None
        self._target = "sun"
        self.setMinimumSize(320, 280)

    def set_event(self, event: dict | None):
        self._event = event
        self.update()

    def set_target(self, name: str):
        self._target = name
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
        reach = approach["target_radius_arcsec"] * 1.5
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
                rect, Qt.AlignmentFlag.AlignCenter, "Select an event to see its path across the disk."
            )
            return

        approach = self._event["closest_approach"]
        disk_radius = approach["target_radius_arcsec"]
        points = self._track_points(self._event)

        # Fit the disk and the whole track, whichever reaches further.
        extent = max([disk_radius * 1.15] + [math.hypot(x, y) * 1.08 for x, y in points])
        margin = 34
        span = min(rect.width(), rect.height()) - 2 * margin
        if span <= 0 or extent <= 0:
            return
        scale = (span / 2.0) / extent
        cx, cy = rect.center().x(), rect.center().y()

        def to_screen(x, y):
            # East is left and north is up, as when looking at the sky.
            return QPointF(cx - x * scale, cy - y * scale)

        radius_px = disk_radius * scale
        illumination = self._event.get("illumination")
        if self._target == "moon" and illumination:
            self._draw_moon(painter, cx, cy, radius_px, illumination)
        else:
            self._draw_sun(painter, cx, cy, radius_px)

        colours = [self._point_colour(x, y, illumination) for x, y in points]
        self._draw_track(painter, to_screen, points, cx, cy, radius_px, colours)
        self._draw_marker(painter, to_screen, approach, illumination)
        self._draw_annotations(painter, rect, disk_radius, illumination)

    def _draw_sun(self, painter, cx, cy, radius_px):
        gradient = QRadialGradient(cx, cy, radius_px)
        gradient.setColorAt(0.0, QColor(self._theme["sun_core"]))
        gradient.setColorAt(0.86, QColor(self._theme["sun_limb"]))
        gradient.setColorAt(1.0, QColor(self._theme["sun_rim"]))
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), radius_px, radius_px)

    def _draw_moon(self, painter, cx, cy, radius_px, illumination):
        """A grey disk with the phase drawn: the lit region bounded by the
        bright limb on one side and the terminator ellipse on the other.
        """
        centre = QPointF(cx, cy)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._theme["moon_dark"]))
        painter.drawEllipse(centre, radius_px, radius_px)

        fraction = illumination["illuminated_fraction"]
        # Rotate so the bright limb points along +x on screen. A sky direction
        # (east, north) maps to screen (-east, -north); the bright limb is at
        # position angle east of north.
        theta = math.radians(illumination["bright_limb_angle_deg"])
        screen_angle = math.degrees(math.atan2(-math.cos(theta), -math.sin(theta)))

        painter.save()
        painter.translate(cx, cy)
        painter.rotate(screen_angle)
        # The terminator is a half-ellipse; its x-extent is 0 at quarter phase
        # and ±R at new/full. b < 0 (gibbous) bulges past centre, b > 0 leaves
        # a crescent on the bright-limb side.
        b = radius_px * (1.0 - 2.0 * fraction)
        steps = 48
        limb = [
            QPointF(radius_px * math.cos(a), radius_px * math.sin(a))
            for a in (math.radians(-90 + 180 * i / steps) for i in range(steps + 1))
        ]
        terminator = [
            QPointF(b * math.cos(a), radius_px * math.sin(a))
            for a in (math.radians(90 - 180 * i / steps) for i in range(steps + 1))
        ]
        painter.setBrush(QColor(self._theme["moon_lit"]))
        painter.drawPolygon(QPolygonF(limb + terminator))
        painter.restore()

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(self._theme["moon_rim"]), 1.2))
        painter.drawEllipse(centre, radius_px, radius_px)

    def _point_colour(self, dx: float, dy: float, illumination: dict | None) -> QColor:
        """Colour for a chord point inside the disk.

        Over the Sun, or the lit face of the Moon, a dark silhouette. Over the
        Moon's dark face: bright if the satellite is sunlit, faint if eclipsed.
        """
        if illumination is None:  # the Sun: always a silhouette
            return QColor(self._theme["track"])
        if not illumination["satellite_sunlit"]:  # eclipsed: invisible
            return QColor(self._theme["track_outside"])
        position_angle = math.degrees(math.atan2(dx, dy)) % 360.0
        delta = abs((position_angle - illumination["bright_limb_angle_deg"] + 180.0) % 360.0 - 180.0)
        lit_face = delta <= 90.0
        return QColor(self._theme["track"] if lit_face else self._theme["sat_bright"])

    def _draw_track(self, painter, to_screen, points, cx, cy, radius_px, colours):
        polygon = QPolygonF([to_screen(x, y) for x, y in points])
        clip = QPainterPath()
        clip.addEllipse(QPointF(cx, cy), radius_px, radius_px)

        # Off the disk the satellite is not visible: a faint dashed line for the
        # whole chord, drawn first and overpainted inside the disk.
        faint = QColor(self._theme["track_outside"])
        painter.save()
        painter.setPen(QPen(faint, 1.4, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(polygon)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(faint))
        for point in polygon:
            painter.drawEllipse(point, 2.2, 2.2)
        if len(polygon) >= 2:
            self._draw_arrow(painter, polygon[-2], polygon[-1], faint)
        painter.restore()

        # Inside the disk, each segment takes the colour of its illumination, so
        # a chord that crosses the terminator changes from dark to bright. Dots
        # are equally spaced in time, so their spacing shows the speed.
        painter.save()
        painter.setClipPath(clip)
        for i in range(len(polygon) - 1):
            painter.setPen(QPen(colours[i], 2.6))
            painter.drawLine(polygon[i], polygon[i + 1])
        painter.setPen(Qt.PenStyle.NoPen)
        for point, colour in zip(polygon, colours):
            painter.setBrush(QBrush(colour))
            painter.drawEllipse(point, 3.0, 3.0)
        if len(polygon) >= 2:
            self._draw_arrow(painter, polygon[-2], polygon[-1], colours[-1])
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

    def _draw_marker(self, painter, to_screen, approach, illumination):
        x, y = _offsets(approach["separation_arcsec"], approach["position_angle_deg"])
        centre = to_screen(x, y)
        painter.setBrush(QBrush(self._point_colour(x, y, illumination)))
        painter.setPen(QPen(QColor(self._theme["marker_ring"]), 1.2))
        painter.drawEllipse(centre, 3.4, 3.4)

    def _draw_annotations(self, painter, rect, disk_radius, illumination):
        painter.setPen(QColor(self._theme["col_subtle"]))

        if self._target == "moon" and illumination:
            lit = illumination["illuminated_fraction"] * 100.0
            caption = f"lunar radius {disk_radius:.0f}″  ·  {lit:.0f}% lit"
        else:
            caption = f"solar radius {disk_radius:.0f}″  ·  ⌀ {disk_radius / 30:.1f}′"
        painter.drawText(10, 18, caption)
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

# Apparent size sits next to the name: it is what decides whether an event is
# worth shooting, and unlike the dimensions in metres it already accounts for
# how far away the satellite is.
COLUMNS = [
    "Local time", "Satellite", "Size (″)", "Type", "Sep (″)", "Dur (s)", "Alt (°)", "Range (km)",
]
_RIGHT_ALIGNED = {"Size (″)", "Sep (″)", "Dur (s)", "Alt (°)", "Range (km)"}


def _apparent_size(event: dict) -> float | None:
    """What the satellite's longest dimension subtends, in arcsec.

    The longest dimension sets how large the silhouette can get, so its angular
    extent is the figure the list and the filter use.
    """
    size = event.get("size")
    return None if not size else size.get("angular_max_arcsec")


class ViewerWindow(QWidget):

    def __init__(
        self,
        theme: dict,
        stylesheet: str = "",
        report: dict | None = None,
        path=None,
        recording_lead_seconds: float = RECORDING_LEAD_SECONDS,
    ):
        super().__init__()
        self._theme = theme
        self._recording_lead_seconds = recording_lead_seconds
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
        self._observe_btn = QPushButton("Observe…")
        self._observe_btn.setObjectName("expert")
        self._observe_btn.setToolTip(
            "Open a countdown window for the selected event (or double-click its row)"
        )
        self._observe_btn.clicked.connect(self._on_observe)
        self._observe_btn.setEnabled(False)
        header.addWidget(self._observe_btn)
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
        size_tip = "hides satellites that appear smaller than this"
        altitude_tip = "hides events lower in the sky than this"
        separation_tip = "hides events further from the Sun's centre than this"
        self._max_range = _limit_box(" km", 100000.0, 100.0, range_tip)
        self._min_altitude = _limit_box(" °", 90.0, 5.0, altitude_tip)
        self._max_separation = _limit_box(" ″", 7200.0, 100.0, separation_tip)
        # Apparent sizes run from a fraction of an arcsecond to tens, so this
        # one needs a decimal place where the others do not.
        self._min_size = _limit_box(" ″", 120.0, 0.5, size_tip, decimals=1)
        for box in (self._max_range, self._min_altitude, self._max_separation, self._min_size):
            box.valueChanged.connect(lambda _: self._apply_filters())

        reset = QPushButton("Reset")
        reset.setObjectName("expert")
        reset.setToolTip("Clear every filter")
        reset.clicked.connect(self._reset_filters)

        filters = QGridLayout()
        filters.setHorizontalSpacing(8)
        filters.setVerticalSpacing(4)
        for index, (text, box, tip) in enumerate(
            (
                ("Range ≤", self._max_range, range_tip),
                ("Sep ≤", self._max_separation, separation_tip),
                ("Alt ≥", self._min_altitude, altitude_tip),
                ("Size ≥", self._min_size, size_tip),
            )
        ):
            row, column = divmod(index, 2)
            label = QLabel(text)
            label.setObjectName("sname")
            filters.addWidget(label, row, column * 2)
            filters.addWidget(_limit_field(box, tip), row, column * 2 + 1)
        filters.setColumnStretch(1, 1)
        filters.setColumnStretch(3, 1)
        filters.addWidget(reset, 0, 4, 2, 1)  # spans both rows
        lay.addLayout(filters)

        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setShowGrid(False)
        self._table.itemSelectionChanged.connect(self._on_selection)
        self._table.itemDoubleClicked.connect(lambda _item: self._on_observe())

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

        target = report.get("target", "sun")
        self._disk.set_target(target)
        observatory = report.get("observatory", {})
        subject = "Lunar Transits" if target == "moon" else "Solar Transits"
        self.setWindowTitle(f"{subject} — {observatory.get('name', 'Observatory')}")
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
        if self._min_size.value() > 0:
            apparent = _apparent_size(event)
            # A satellite of unknown size cannot be shown to pass, so asking for
            # a minimum size hides it.
            if apparent is None or apparent < self._min_size.value():
                return False
        return True

    def _event_at(self, row: int) -> dict | None:
        anchor = self._table.item(row, 0)
        return anchor.data(Qt.ItemDataRole.UserRole) if anchor else None

    def _shown_rows(self) -> list[int]:
        return [r for r in range(self._table.rowCount()) if not self._table.isRowHidden(r)]

    def _reset_filters(self):
        for box in (self._max_range, self._min_altitude, self._max_separation, self._min_size):
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
            apparent = _apparent_size(event)

            cells = [
                _Item(
                    _local_time(approach["time_local"], subsecond=False, date=self._multiday),
                    approach["time_utc"],
                ),
                _Item(event["satellite"]["name"] or "?", (event["satellite"]["name"] or "").lower()),
                _Item(
                    "—" if apparent is None else f"{apparent:.2f}",
                    -1.0 if apparent is None else apparent,
                ),
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
                if COLUMNS[column] in _RIGHT_ALIGNED:
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
        self._observe_btn.setEnabled(event is not None)
        values = _detail_values(event) if event else {}
        for name, row in self._detail_rows.items():
            row.set_value(values.get(name))

    # --- actions -------------------------------------------------------------

    def _on_observe(self):
        """Open a countdown window for the selected event.

        Imported here rather than at the top so the two modules do not have to
        import each other, and because nothing is needed until it is asked for.
        """
        row = self._table.currentRow()
        if row < 0 or self._table.isRowHidden(row):
            return
        event = self._event_at(row)
        if event is None:
            return

        from .observe import ObservingWindow

        window = ObservingWindow(
            self._theme,
            self.styleSheet(),
            event,
            target=(self._report or {}).get("target", "sun"),
            lead_seconds=self._recording_lead_seconds,
        )
        # Several can be open at once, for back-to-back passes. Without a
        # reference they would be collected the moment this returns.
        self._observing = [w for w in getattr(self, "_observing", []) if w.isVisible()]
        self._observing.append(window)
        window.show()
        window.raise_()

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
            "Target alt/az",
            "Range",
            "Angular speed",
            "Direction of travel",
        ],
    ),
    # Blank for a solar event, whose disk is always full and satellites sunlit.
    ("ILLUMINATION", ["Moon phase", "Illuminated", "Crossing limb", "Satellite lit"]),
    ("SIZE", ["Dimensions", "Shape", "Apparent size", "Size source"]),
]


def _detail_values(event: dict) -> dict:
    satellite = event["satellite"]
    approach = event["closest_approach"]
    geometry = event["geometry"]
    transit = event.get("transit")

    offset = approach.get("chord_offset_fraction")
    size = event.get("size")
    lit = event.get("illumination")
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
            f"(disk radius {approach['target_radius_arcsec']:.0f}″)"
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
        "Target alt/az": (
            f"{geometry['target_altitude_deg']:.2f}° / {geometry['target_azimuth_deg']:.2f}°"
        ),
        "Range": f"{geometry['range_km']:.1f} km",
        "Angular speed": f"{geometry['angular_velocity_deg_per_s']:.3f}°/s",
        "Direction of travel": f"{geometry['motion_position_angle_deg']:.1f}° (east of north)",
        "Moon phase": None if lit is None else f"{lit['phase_deg']:.0f}°",
        "Illuminated": None if lit is None else f"{lit['illuminated_fraction'] * 100:.0f}%",
        "Crossing limb": None if lit is None else f"{lit['limb']} limb",
        "Satellite lit": (
            None if lit is None else ("sunlit" if lit["satellite_sunlit"] else "eclipsed")
        ),
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
        "--config",
        metavar="FILE",
        help="configuration file; its output.file is opened when no results file is given, "
        f"and its gui.theme selects the theme (default: {DEFAULT_CONFIG_FILE}, when present)",
    )
    parser.add_argument("--theme", choices=("dark", "light"), help="override the configured theme")
    parser.add_argument("--version", action="version", version=f"SatTransitPlanner {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    theme_name = args.theme or "dark"
    lead = RECORDING_LEAD_SECONDS
    results = Path(args.results) if args.results else None

    # A named configuration file must exist; the default is only a convenience,
    # so its absence leaves the viewer empty rather than failing.
    config_file = args.config or DEFAULT_CONFIG_FILE
    if args.config or Path(config_file).is_file():
        try:
            config = load_config(config_file)
        except ConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if args.theme is None:
            theme_name = config.gui.theme
        lead = config.gui.recording_lead_seconds
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

    window = ViewerWindow(
        THEMES[theme_name], stylesheet, report, results, recording_lead_seconds=lead
    )
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
