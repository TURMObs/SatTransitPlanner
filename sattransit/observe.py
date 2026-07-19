"""A window to keep open at the telescope while a transit happens.

The list and the disk view answer "is this worth shooting?". This answers the
only question left once you have decided: *when*, right now, to the second.

A transit lasts well under a second for anything in low orbit, so the useful
display is not the event itself but the approach to it: a large countdown, and
a timeline that zooms in as the moment arrives, from minutes out down to the
fractions of a second that matter at ingress.

The clock is the observer's own. A prediction good to a millisecond is no help
if the machine's clock is a second out, so keep it synchronised.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPen,
    QPolygonF,
)
from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

# The countdown ticks at this rate: fast enough to show tenths smoothly,
# far too slow to matter for the CPU.
TICK_MS = 100

# How long before mid-transit to start recording. Enough to have the camera
# rolling and settled before anything crosses.
RECORDING_LEAD_SECONDS = 5.0


def _parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class Moments:
    """When an event starts, peaks and ends, in UTC.

    A near miss never touches the disk, so it has no ingress or egress: only
    the closest approach, which is then what the countdown runs to.
    """

    closest: datetime
    ingress: datetime | None = None
    egress: datetime | None = None

    @property
    def start(self) -> datetime:
        """What the countdown runs to."""
        return self.ingress or self.closest

    @property
    def end(self) -> datetime:
        return self.egress or self.closest

    @property
    def duration_seconds(self) -> float:
        if self.ingress and self.egress:
            return (self.egress - self.ingress).total_seconds()
        return 0.0

    @property
    def is_transit(self) -> bool:
        return self.ingress is not None and self.egress is not None


def moments_of(event: dict) -> Moments | None:
    """Read an event's times, or None if it carries no usable timestamp."""
    closest = _parse((event.get("closest_approach") or {}).get("time_utc"))
    if closest is None:
        return None
    transit = event.get("transit") or {}
    return Moments(
        closest=closest,
        ingress=_parse(transit.get("start_utc")),
        egress=_parse(transit.get("end_utc")),
    )


def phase_at(now: datetime, moments: Moments) -> str:
    """Where ``now`` sits: before the event, inside it, or past it."""
    if now < moments.start:
        return "before"
    if now <= moments.end:
        return "during"
    return "after"


def countdown_text(seconds: float) -> str:
    """A signed countdown, tenths always, hours only when there are any."""
    sign = "−" if seconds >= 0 else "+"
    seconds = abs(seconds)
    hours, rest = divmod(seconds, 3600.0)
    minutes, secs = divmod(rest, 60.0)
    if hours >= 1:
        return f"T{sign} {int(hours)}:{int(minutes):02d}:{secs:04.1f}"
    return f"T{sign} {int(minutes):02d}:{secs:04.1f}"


def timeline_span_seconds(remaining: float, duration: float) -> float:
    """Half-width of the timeline, zooming in as the event approaches.

    Wide while the event is minutes away, tightening continuously until it is
    just a few multiples of the transit's own length.
    """
    return max(2.0 * duration, min(600.0, max(5.0, abs(remaining) * 1.4)))


def countdown_font(point_size: int) -> QFont:
    """A fixed-pitch font, so a ticking countdown does not jitter.

    Every digit has to occupy the same width or the ones beside a changing
    digit shift about. macOS's nominal "fixed font" is not actually one — it
    resolves to American Typewriter, whose ``1`` is narrow — so the family is
    named explicitly, most-preferred first. Qt falls back through the list and,
    guided by the style hint, lands on a real monospace face on any platform.
    """
    font = QFont()
    font.setFamilies(
        [
            "Menlo",  # macOS
            "SF Mono",
            "Consolas",  # Windows
            "DejaVu Sans Mono",  # Linux
            "Liberation Mono",
            "Courier New",  # near-universal last resort
            "monospace",
        ]
    )
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    font.setPointSize(point_size)
    font.setBold(True)
    return font


def recording_start(mid: datetime, lead_seconds: float = RECORDING_LEAD_SECONDS) -> datetime:
    """When to hit record: a lead before mid-transit, on a whole second.

    Rounded down so the moment is a round number that can be read off a clock
    and acted on, and so the lead is never shortened by the rounding.
    """
    return (mid - timedelta(seconds=lead_seconds)).replace(microsecond=0)


def urgency(phase: str, remaining: float) -> str:
    """A coarse state the display colours itself by."""
    if phase == "during":
        return "now"
    if phase == "after":
        return "past"
    if remaining <= 10.0:
        return "imminent"
    if remaining <= 60.0:
        return "soon"
    return "waiting"


_URGENCY_COLOUR = {
    "waiting": "col_text",
    "soon": "col_unknown",
    "imminent": "bright_text",
    "now": "col_on",
    "past": "col_subtle",
}


class TimelineView(QWidget):
    """A strip of time centred on the event, with a marker for now.

    The transit itself is a sliver — a second at most — so it is drawn with a
    floor on its width, and the strip zooms in as the moment approaches rather
    than showing a fixed span in which nothing appears to move.
    """

    def __init__(self, theme: dict):
        super().__init__()
        self._theme = theme
        self._moments: Moments | None = None
        self._now: datetime | None = None
        self.setMinimumHeight(84)

    def update_state(self, moments: Moments | None, now: datetime):
        self._moments = moments
        self._now = now
        self.update()

    @staticmethod
    def _band_label(moments: Moments) -> str:
        """What the band is. It spans ingress to egress, so it is the whole
        transit rather than the instant it begins; a near miss is one moment."""
        return "transit" if moments.is_transit else "closest"

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        painter.fillRect(rect, QColor(self._theme["plot_bg"]))
        if self._moments is None or self._now is None:
            return

        moments, now = self._moments, self._now
        remaining = (moments.start - now).total_seconds()
        span = timeline_span_seconds(remaining, moments.duration_seconds)

        margin = 18
        width = rect.width() - 2 * margin
        if width <= 10:
            return
        axis_y = rect.height() * 0.58
        centre = moments.start + (moments.end - moments.start) / 2

        def to_x(when: datetime) -> float:
            offset = (when - centre).total_seconds()
            return margin + width * (0.5 + max(-1.0, min(1.0, offset / span)) / 2.0)

        # The axis.
        painter.setPen(QPen(QColor(self._theme["hr"]), 1.4))
        painter.drawLine(QPointF(margin, axis_y), QPointF(margin + width, axis_y))

        # The event itself: a band from ingress to egress, never thinner than a
        # few pixels or a sub-second transit would be invisible.
        left, right = to_x(moments.start), to_x(moments.end)
        if right - left < 4.0:
            middle = (left + right) / 2.0
            left, right = middle - 2.0, middle + 2.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(self._theme["col_accent"])))
        painter.drawRect(int(left), int(axis_y - 16), max(int(right - left), 4), 32)

        # Now.
        phase = phase_at(now, moments)
        colour = QColor(self._theme[_URGENCY_COLOUR[urgency(phase, remaining)]])
        x_now = to_x(now)
        painter.setPen(QPen(colour, 2.0))
        painter.drawLine(QPointF(x_now, axis_y - 26), QPointF(x_now, axis_y + 26))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(colour))
        painter.drawPolygon(
            QPolygonF([
                QPointF(x_now, axis_y - 26),
                QPointF(x_now - 5, axis_y - 34),
                QPointF(x_now + 5, axis_y - 34),
            ])
        )

        # Scale: the half-width either side, and the event at the centre.
        # Aligned inside rectangles rather than placed by eye, so a wider label
        # such as "+10 min" cannot run off the edge.
        painter.setPen(QColor(self._theme["col_subtle"]))
        baseline = rect.height() - 20
        painter.drawText(
            QRectF(margin - 8, baseline, 90, 18),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            _span_label(-span),
        )
        painter.drawText(
            QRectF(margin + width - 82, baseline, 90, 18),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            "+" + _span_label(span),
        )
        label = self._band_label(moments)
        painter.drawText(
            QRectF((left + right) / 2 - 50, axis_y - 38, 100, 16),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            label,
        )


def _span_label(seconds: float) -> str:
    magnitude = abs(seconds)
    if magnitude >= 60:
        return f"{'-' if seconds < 0 else ''}{magnitude / 60:.0f} min"
    return f"{'-' if seconds < 0 else ''}{magnitude:.0f} s"


class ObservingWindow(QWidget):
    """Live countdown and timeline for one event."""

    def __init__(self, theme: dict, stylesheet: str, event: dict, target: str = "sun",
                 now_provider=None, lead_seconds: float = RECORDING_LEAD_SECONDS):
        super().__init__()
        self._theme = theme
        self._event = event
        self._moments = moments_of(event)
        self._lead_seconds = lead_seconds
        # Injectable so the display can be tested, and screenshotted, at any
        # moment relative to the event.
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

        satellite = event.get("satellite", {})
        self.setWindowTitle(f"Observing — {satellite.get('name', 'satellite')}")
        self.setStyleSheet(stylesheet)
        self._build_ui(event, target)
        self.resize(560, 420)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(TICK_MS)
        self._refresh()

    # --- construction --------------------------------------------------------

    def _build_ui(self, event: dict, target: str):
        satellite = event.get("satellite", {})
        geometry = event.get("geometry", {})
        size = event.get("size")
        lit = event.get("illumination")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        title = QLabel(satellite.get("name", "satellite"))
        title.setObjectName("title")
        root.addWidget(title)

        bits = ["disk transit" if event.get("type") == "disk_transit" else "near miss"]
        if size:
            bits.append(f"{size['angular_max_arcsec']:.1f}″ across")
        if geometry:
            bits.append(f"{geometry['satellite_altitude_deg']:.0f}° up")
            bits.append(f"az {geometry['satellite_azimuth_deg']:.0f}°")
        if lit:
            bits.append(f"{lit['limb']} limb")
            bits.append("sunlit" if lit["satellite_sunlit"] else "eclipsed")
        subtitle = QLabel("  ·  ".join(bits))
        subtitle.setObjectName("status")
        root.addWidget(subtitle)

        # The countdown, as large as the window allows: it has to be readable
        # from arm's length in the dark. Fixed pitch, or every digit that
        # changes shifts the ones beside it and the whole number jitters.
        self._countdown = QLabel("—")
        self._countdown.setFont(countdown_font(max(self.font().pointSize(), 9) * 3))
        self._countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._countdown)

        self._caption = QLabel("")
        self._caption.setObjectName("status")
        self._caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._caption)

        self._timeline = TimelineView(self._theme)
        root.addWidget(self._timeline)

        line = QFrame()
        line.setObjectName("hr")
        line.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(line)

        root.addLayout(self._build_times(event))
        root.addStretch(1)

    def _build_times(self, event: dict):
        """The times, local and UTC side by side, in the order they happen."""
        approach = event.get("closest_approach", {})
        transit = event.get("transit")
        satellite = event.get("satellite", {})
        moments = self._moments

        # The observatory's own zone, taken from the report's local stamp, so
        # the two columns can never disagree about the same instant.
        local_stamp = _parse(approach.get("time_local"))
        zone = local_stamp.tzinfo if local_stamp else timezone.utc

        def pair(moment: datetime | None, tenths: bool = True):
            if moment is None:
                return "—", "—"
            return _clock(moment.astimezone(zone), tenths), _clock(
                moment.astimezone(timezone.utc), tenths
            )

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(1, 1)

        header_local = QLabel("local")
        header_local.setObjectName("sname")
        header_local.setAlignment(Qt.AlignmentFlag.AlignRight)
        header_utc = QLabel("UTC")
        header_utc.setObjectName("sname")
        header_utc.setAlignment(Qt.AlignmentFlag.AlignRight)
        grid.addWidget(header_local, 0, 1)
        grid.addWidget(header_utc, 0, 2)

        entries = []
        if moments is not None:
            # Chronological: recording starts before anything else happens.
            entries.append(
                (
                    "Start recording",
                    *pair(recording_start(moments.closest, self._lead_seconds), tenths=False),
                    True,
                )
            )
        if transit and moments is not None:
            entries.append(("Ingress", *pair(moments.ingress), False))
            entries.append(("Mid", *pair(moments.closest), False))
            entries.append(("Egress", *pair(moments.egress), False))
        elif moments is not None:
            entries.append(("Closest", *pair(moments.closest), False))

        for row, (name, local, utc, accent) in enumerate(entries, start=1):
            label = QLabel(name)
            label.setObjectName("sval" if accent else "sname")
            if accent:
                label.setStyleSheet(f"color: {self._theme['col_accent']}; font-weight: bold;")
                label.setToolTip(
                    f"{self._lead_seconds:g} s before mid-transit, rounded down to a "
                    "whole second (gui.recording_lead_seconds)"
                )
            grid.addWidget(label, row, 0)
            for column, text in ((1, local), (2, utc)):
                value = QLabel(text)
                value.setObjectName("sval")
                value.setAlignment(Qt.AlignmentFlag.AlignRight)
                value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                if accent:
                    value.setStyleSheet(
                        f"color: {self._theme['col_accent']}; font-weight: bold;"
                    )
                grid.addWidget(value, row, column)

        # Figures that are not times sit underneath, spanning both columns.
        extras = []
        if transit:
            extras.append(("Duration", f"{transit['duration_seconds']:.3f} s"))
        else:
            extras.append(("Separation", f"{approach.get('separation_arcsec', 0):.0f}″"))
        extras.append(("Elements", f"{satellite.get('element_age_days', 0):.1f} d old"))
        for offset, (name, text) in enumerate(extras):
            row = len(entries) + 1 + offset
            label = QLabel(name)
            label.setObjectName("sname")
            value = QLabel(text)
            value.setObjectName("sval")
            value.setAlignment(Qt.AlignmentFlag.AlignRight)
            grid.addWidget(label, row, 0)
            grid.addWidget(value, row, 1, 1, 2)
        return grid

    # --- ticking -------------------------------------------------------------

    def _refresh(self):
        if self._moments is None:
            self._countdown.setText("no time")
            return
        now = self._now_provider()
        remaining = (self._moments.start - now).total_seconds()
        phase = phase_at(now, self._moments)
        state = urgency(phase, remaining)
        colour = self._theme[_URGENCY_COLOUR[state]]

        if phase == "during":
            self._countdown.setText("TRANSIT")
            elapsed = (now - self._moments.start).total_seconds()
            self._caption.setText(
                f"{elapsed:.1f} s in, of {self._moments.duration_seconds:.2f} s"
            )
        elif phase == "after":
            self._countdown.setText(countdown_text((self._moments.end - now).total_seconds()))
            self._caption.setText("ended")
        else:
            self._countdown.setText(countdown_text(remaining))
            self._caption.setText(
                "until ingress" if self._moments.is_transit else "until closest approach"
            )
        self._countdown.setStyleSheet(f"color: {colour};")
        self._timeline.update_state(self._moments, now)

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)


def _clock(moment: datetime | None, tenths: bool = True) -> str:
    """A wall-clock time, to a tenth of a second unless asked otherwise."""
    if moment is None:
        return "—"
    if not tenths:
        return moment.strftime("%H:%M:%S")
    return moment.strftime("%H:%M:%S.") + f"{moment.microsecond // 100000:d}"
