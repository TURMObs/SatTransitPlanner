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
from datetime import datetime, timezone

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

# The countdown ticks at this rate: fast enough to show tenths smoothly,
# far too slow to matter for the CPU.
TICK_MS = 100


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
        label = "ingress" if moments.is_transit else "closest"
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
                 now_provider=None):
        super().__init__()
        self._theme = theme
        self._event = event
        self._moments = moments_of(event)
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
        approach = event.get("closest_approach", {})
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
        # from arm's length in the dark.
        self._countdown = QLabel("—")
        countdown_font = QFont()
        countdown_font.setPointSize(max(self.font().pointSize(), 9) * 3)
        countdown_font.setBold(True)
        self._countdown.setFont(countdown_font)
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

        rows = QVBoxLayout()
        rows.setSpacing(2)
        transit = event.get("transit")
        entries = []
        if transit:
            entries.append(("Ingress", _clock(transit.get("start_local"))))
            entries.append(("Mid", _clock(approach.get("time_local"))))
            entries.append(("Egress", _clock(transit.get("end_local"))))
            entries.append(("Duration", f"{transit['duration_seconds']:.3f} s"))
        else:
            entries.append(("Closest", _clock(approach.get("time_local"))))
            entries.append(("Separation", f"{approach.get('separation_arcsec', 0):.0f}″"))
        entries.append(("Elements", f"{satellite.get('element_age_days', 0):.1f} d old"))
        for name, value in entries:
            row = QHBoxLayout()
            left = QLabel(name)
            left.setObjectName("sname")
            right = QLabel(value)
            right.setObjectName("sval")
            right.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row.addWidget(left)
            row.addStretch(1)
            row.addWidget(right)
            rows.addLayout(row)
        root.addLayout(rows)
        root.addStretch(1)

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


def _clock(local: str | None) -> str:
    """The local timestamp, to a tenth of a second."""
    if not local:
        return "—"
    moment = _parse(local)
    if moment is None:
        return local
    return moment.strftime("%H:%M:%S.") + f"{moment.microsecond // 100000:d}"
