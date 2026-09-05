"""Running a search from the viewer.

The viewer shells out to ``python -m sattransit`` rather than searching in its
own process. A full-catalogue search takes minutes, and a separate process can
be cancelled the instant the button is pressed, cannot take the window down
with it, and keeps the engine's imports — Skyfield, numpy, an ephemeris — out
of a viewer that should open immediately.

The cost of that choice is this module: the progress the CLI writes for a
person to read has to be read back by a machine. ``parse_progress`` is the
whole of that coupling, and a test pins it against the CLI's real output.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# The bodies a satellite can be caught in front of.
TARGETS = ("sun", "moon")

try:
    from PyQt6.QtCore import QObject, QProcess, pyqtSignal
except ImportError:  # pragma: no cover - the presets stay usable without Qt
    QObject = object  # type: ignore[assignment,misc]
    QProcess = None  # type: ignore[assignment]
    pyqtSignal = None  # type: ignore[assignment]


@dataclass(frozen=True)
class Preset:
    """One of the searches the viewer offers: a window over a target."""

    key: str
    label: str
    days: int
    target: str = "sun"
    favorites: bool = False

    @property
    def title(self) -> str:
        """Names the target too, for a status line read out of context."""
        return f"{self.target.capitalize()}: {self.label.lower()}"

    @property
    def tooltip(self) -> str:
        span = "one day" if self.days == 1 else f"{self.days} days"
        who = "the favourites" if self.favorites else "every configured group"
        return f"Search {span} from midnight for {who}, transiting the {self.target.capitalize()}"


# A day's search over the full catalogue takes minutes, so the long window is
# offered only for the favourites, where it is a few satellites and quick.
_WINDOWS = (
    ("today", "Today", 1, False),
    ("two-days", "Today and tomorrow", 2, False),
    ("week-favorites", "Week ahead — favourites", 7, True),
)

# Grouped by target, which is how the menu presents them.
PRESETS = tuple(
    Preset(f"{target}-{key}", label, days, target, favorites)
    for target in TARGETS
    for key, label, days, favorites in _WINDOWS
)


def output_path(config, preset: Preset) -> Path:
    """Where this preset writes its results.

    The configured output file belongs to the configured target; a search of
    the other one gets a sibling beside it. Otherwise a lunar run would quietly
    overwrite the solar plan, which is the sort of thing you find out at dusk.
    """
    path = config.resolve_output(None)
    if preset.target == config.target:
        return path
    return path.with_name(f"{path.stem}-{preset.target}{path.suffix}")


def window_start(now: datetime) -> datetime:
    """Midnight beginning the day ``now`` falls in.

    "Today" is the calendar day, not the next 24 hours: a plan made at noon
    should still show the whole day, including what has already passed.
    """
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def command(
    preset: Preset,
    config_path: Path | str,
    now: datetime,
    python: str | None = None,
    output: Path | str | None = None,
) -> list[str]:
    """The command line that runs this preset's search.

    The start is written without an offset so the CLI reads it in the
    observatory's own timezone, which is the one the observer is thinking in.
    The target and the output file are always named rather than left to the
    configuration, so what the menu says is what runs.
    """
    start = window_start(now)
    argv = [
        python or sys.executable,
        "-m",
        "sattransit",
        "--config",
        str(config_path),
        "--start",
        start.strftime("%Y-%m-%dT%H:%M:%S"),
        "--duration",
        f"{preset.days}d",
        "--target",
        preset.target,
    ]
    if output is not None:
        argv += ["--output", str(output)]
    if preset.favorites:
        argv.append("--favorites")
    return argv


# The CLI's progress line, e.g. "Searching   : [###...] 812/16334 satellites, 4 event(s)".
_PROGRESS = re.compile(r"(\d+)/(\d+) satellites, (\d+) event")


def parse_progress(chunk: str) -> tuple[int, int, int] | None:
    """The most recent (done, total, events) in a chunk of the search's output.

    A chunk can hold several updates — they are written with a carriage return
    rather than a newline — and only the last one is still true.
    """
    matches = _PROGRESS.findall(chunk)
    if not matches:
        return None
    done, total, events = matches[-1]
    return int(done), int(total), int(events)


def progress_text(done: int, total: int, events: int) -> str:
    percent = 100.0 * done / total if total else 0.0
    return f"Searching… {percent:.0f}%  ·  {done:,} of {total:,} satellites  ·  {events} event(s)"


def error_text(stderr: str) -> str:
    """What the CLI said went wrong, without the progress bar around it."""
    lines = [
        line.rstrip()
        for line in stderr.replace("\r", "\n").splitlines()
        if line.strip() and not _PROGRESS.search(line)
    ]
    marker = next((i for i, line in enumerate(lines) if line.startswith("error:")), None)
    if marker is not None:
        return "\n".join(lines[marker:]).replace("error: ", "", 1)
    # No "error:" line at all — a crash, or a signal. The tail is the best clue.
    return "\n".join(lines[-6:]) or "the search failed without saying why"


class SearchRunner(QObject):
    """Runs one search at a time in its own process.

    ``progressed`` carries a line for the status bar; ``finished`` carries
    whether it worked and, if not, why.
    """

    progressed = pyqtSignal(str) if pyqtSignal else None
    finished = pyqtSignal(bool, str) if pyqtSignal else None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process: QProcess | None = None
        self._stderr = ""
        self._cancelled = False

    @property
    def running(self) -> bool:
        return self._process is not None

    def start(
        self,
        preset: Preset,
        config_path: Path | str,
        now: datetime,
        python: str | None = None,
        output: Path | str | None = None,
    ) -> None:
        if self.running:
            raise RuntimeError("a search is already running")

        argv = command(preset, config_path, now, python, output)
        self._stderr = ""
        self._cancelled = False
        self._process = QProcess(self)
        self._process.readyReadStandardError.connect(self._on_stderr)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)
        self._process.start(argv[0], argv[1:])

    def cancel(self) -> None:
        if self._process is not None:
            self._cancelled = True
            self._process.kill()

    # --- process plumbing ----------------------------------------------------

    def _on_stderr(self) -> None:
        chunk = bytes(self._process.readAllStandardError()).decode("utf-8", "replace")
        self._stderr += chunk
        numbers = parse_progress(chunk)
        if numbers is not None:
            self.progressed.emit(progress_text(*numbers))

    def _on_error(self, error) -> None:
        # A process that never starts emits no finished(), so without this the
        # run would never end: the button would sit on "Cancel" for good.
        if error != QProcess.ProcessError.FailedToStart or self._process is None:
            return
        self._process = None
        self.finished.emit(False, "could not run python -m sattransit")

    def _on_finished(self, code: int, _status) -> None:
        if self._process is None:
            return  # already reported, as a failure to start
        self._process = None
        if self._cancelled:
            self.finished.emit(False, "")  # the user knows why; no dialog
        elif code == 0:
            self.finished.emit(True, "")
        else:
            self.finished.emit(False, error_text(self._stderr))
