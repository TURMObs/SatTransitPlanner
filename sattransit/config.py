"""Configuration file loading and validation."""

from __future__ import annotations

import dataclasses
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .mount import SIDES
from .sizes import parse_overrides
from .uncertainty import ALONG_TRACK_KM_PER_DAY, CROSS_TRACK_KM_PER_DAY

# Both frontends fall back to this when no configuration file is named.
DEFAULT_CONFIG_FILE = "config.json"


class ConfigError(ValueError):
    """Raised when the configuration file is missing or malformed."""


@dataclass
class Observatory:
    name: str
    latitude_deg: float
    longitude_deg: float
    elevation_m: float = 0.0
    timezone: str = "UTC"

    def zoneinfo(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ConfigError(f"observatory.timezone: unknown timezone {self.timezone!r}") from exc


@dataclass
class CelestrakConfig:
    groups: list[str]
    base_url: str = "https://celestrak.org/NORAD/elements/gp.php"
    max_age_days: float = 1.0
    offline: bool = False


@dataclass
class SearchConfig:
    # Angular radius around the target's center within which an approach is
    # reported. null/None means "the target's limb", i.e. only true disk
    # transits are reported.
    max_separation_deg: float | None = 1.0
    min_target_altitude_deg: float = 5.0
    min_satellite_altitude_deg: float = 5.0
    coarse_step_seconds: float = 60.0
    fine_step_seconds: float = 1.0
    # Safety factor applied to the observed per-step angular travel when deciding
    # whether a sampled minimum is worth refining. Larger = slower but safer.
    gate_factor: float = 3.0
    refine_tolerance_seconds: float = 0.001
    max_element_age_days: float = 14.0
    path_samples: int = 15
    # NORAD id or name glob -> size in metres, as a number or [min, max].
    # Overrides the size catalogue; use it where the catalogue describes the
    # launched piece rather than the assembled object (e.g. the ISS).
    satellite_sizes_m: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutputConfig:
    file: str = "transits.json"
    indent: int = 2
    include_path: bool = True


@dataclass
class SizesConfig:
    """Where physical satellite dimensions come from."""

    enabled: bool = True
    url: str = "https://planet4589.org/space/gcat/tsv/cat/satcat.tsv"
    max_age_days: float = 30.0


@dataclass
class SpaceTrackConfig:
    """Extra elements for the LEO rocket bodies CelesTrak has no group for.

    Off unless asked for: it needs an account. The credentials come from the
    environment, never from here.
    """

    enabled: bool = False
    base_url: str = "https://www.space-track.org"
    max_age_days: float = 1.0
    # Above 11.25 revolutions a day is a period under ~128 min: low Earth orbit.
    min_mean_motion: float = 11.25


@dataclass
class IlluminationConfig:
    """Which illumination conditions to keep in the result list.

    Only bites for the Moon: a satellite transiting the Sun is always sunlit,
    and the whole solar disk is lit, so both filters pass everything for a
    solar run. The defaults report every event, flagged, and let the
    configuration exclude what a given observer cannot use.
    """

    satellite: str = "any"  # any | sunlit | eclipsed
    limb: str = "any"  # any | lit | dark


@dataclass
class UncertaintyConfig:
    """How far an element set's age is taken to move a prediction.

    Rates in kilometres of error per day of element age; the defaults are
    medians measured from real element sets. See sattransit/uncertainty.py.
    """

    enabled: bool = True
    cross_track_km_per_day: float = CROSS_TRACK_KM_PER_DAY
    along_track_km_per_day: float = ALONG_TRACK_KM_PER_DAY


@dataclass
class FavoritesConfig:
    file: str = "favorites.json"


@dataclass
class FieldOfView:
    """One camera or eyepiece field, drawn over the disk as a framing guide.

    Either a rectangle (``width_arcmin`` with ``height_arcmin``) or a circle
    (``diameter_arcmin``). ``position_angle_deg`` turns the rectangle east of
    north, the convention a camera rotator already uses.
    """

    name: str
    width_arcmin: float | None = None
    height_arcmin: float | None = None
    diameter_arcmin: float | None = None
    position_angle_deg: float = 0.0

    @property
    def is_circle(self) -> bool:
        return self.diameter_arcmin is not None

    def extent_arcsec(self) -> float:
        """How far the field reaches from its centre, in arcseconds."""
        if self.is_circle:
            return self.diameter_arcmin * 30.0  # half of it, in arcsec
        return math.hypot(self.width_arcmin, self.height_arcmin) * 30.0


@dataclass
class InstrumentConfig:
    """What the telescope shows: which way round, and how much of the sky.

    A star diagonal — or any odd number of mirrors — turns the image over. The
    flips put the disk view the same way round as the camera, so what is on the
    screen matches what is on the chip.
    """

    flip_horizontal: bool = False
    flip_vertical: bool = False
    # Which side of the meridian the flips above describe. A German equatorial
    # mount swings to the other side of the pier there and holds the camera
    # turned over, so the other side is drawn rotated by 180 degrees. "any"
    # (the default) means the orientation never changes: a fork, an alt-az
    # mount with a derotator, or a view no one is matching to a camera.
    meridian_side: str = "any"
    fields_of_view: list[FieldOfView] = field(default_factory=list)


@dataclass
class GuiConfig:
    theme: str = "dark"
    # How long before mid-transit the observing window says to start recording.
    recording_lead_seconds: float = 5.0


@dataclass
class Config:
    observatory: Observatory
    celestrak: CelestrakConfig
    # Which body the satellites transit: "sun" (default) or "moon".
    target: str = "sun"
    search: SearchConfig = field(default_factory=SearchConfig)
    illumination: IlluminationConfig = field(default_factory=IlluminationConfig)
    uncertainty: UncertaintyConfig = field(default_factory=UncertaintyConfig)
    sizes: SizesConfig = field(default_factory=SizesConfig)
    spacetrack: SpaceTrackConfig = field(default_factory=SpaceTrackConfig)
    favorites: FavoritesConfig = field(default_factory=FavoritesConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    instrument: InstrumentConfig = field(default_factory=InstrumentConfig)
    gui: GuiConfig = field(default_factory=GuiConfig)
    cache_dir: str = "cache"
    ephemeris: str = "de421.bsp"
    source_path: Path | None = None

    @property
    def cache_path(self) -> Path:
        path = Path(self.cache_dir).expanduser()
        if not path.is_absolute() and self.source_path is not None:
            path = self.source_path.parent / path
        return path

    def resolve_favorites(self, override: str | None) -> Path:
        """Where the favourites live: the override, else the configured file."""
        path = Path(override if override else self.favorites.file).expanduser()
        if not path.is_absolute() and override is None and self.source_path is not None:
            path = self.source_path.parent / path
        return path

    def resolve_output(self, override: str | None) -> Path:
        path = Path(override if override else self.output.file).expanduser()
        if not path.is_absolute() and override is None and self.source_path is not None:
            path = self.source_path.parent / path
        return path


def _build(cls: type, data: Any, section: str):
    """Instantiate a dataclass from a dict, rejecting unknown and missing keys."""
    if not isinstance(data, dict):
        raise ConfigError(f"{section}: expected an object, got {type(data).__name__}")

    fields = {f.name: f for f in dataclasses.fields(cls)}
    unknown = set(data) - set(fields)
    if unknown:
        known = ", ".join(sorted(fields))
        raise ConfigError(
            f"{section}: unknown option(s) {', '.join(sorted(unknown))}. Known options: {known}"
        )

    missing = [
        name
        for name, f in fields.items()
        if name not in data
        and f.default is dataclasses.MISSING
        and f.default_factory is dataclasses.MISSING  # type: ignore[misc]
    ]
    if missing:
        raise ConfigError(f"{section}: missing required option(s) {', '.join(missing)}")

    return cls(**data)


def _build_instrument(data: Any, section: str) -> InstrumentConfig:
    """Like ``_build``, but the fields of view are a list of nested objects."""
    if not isinstance(data, dict):
        raise ConfigError(f"{section}: expected an object, got {type(data).__name__}")

    raw_fields = data.get("fields_of_view", [])
    if not isinstance(raw_fields, list):
        raise ConfigError(
            f"{section}.fields_of_view: expected a list of fields, "
            f"got {type(raw_fields).__name__}"
        )

    instrument = _build(
        InstrumentConfig,
        {key: value for key, value in data.items() if key != "fields_of_view"},
        section,
    )
    instrument.fields_of_view = [
        _build(FieldOfView, entry, f"{section}.fields_of_view[{index}]")
        for index, entry in enumerate(raw_fields)
    ]
    return instrument


def load_config(path: str | Path) -> Config:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ConfigError(
            f"configuration file not found: {path}\n"
            "  Copy config.example.json to config.json and edit it for your site."
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: invalid JSON ({exc})") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top level must be a JSON object")

    known_top = {
        "observatory", "celestrak", "target", "search", "illumination", "uncertainty",
        "sizes", "spacetrack", "favorites", "output", "instrument", "gui",
        "cache_dir", "ephemeris",
    }
    unknown = set(raw) - known_top
    if unknown:
        raise ConfigError(
            f"{path}: unknown top-level key(s) {', '.join(sorted(unknown))}. "
            f"Known keys: {', '.join(sorted(known_top))}"
        )

    for required in ("observatory", "celestrak"):
        if required not in raw:
            raise ConfigError(f"{path}: missing required section {required!r}")

    config = Config(
        observatory=_build(Observatory, raw["observatory"], "observatory"),
        celestrak=_build(CelestrakConfig, raw["celestrak"], "celestrak"),
        target=raw.get("target", "sun"),
        search=_build(SearchConfig, raw.get("search", {}), "search"),
        illumination=_build(IlluminationConfig, raw.get("illumination", {}), "illumination"),
        uncertainty=_build(UncertaintyConfig, raw.get("uncertainty", {}), "uncertainty"),
        sizes=_build(SizesConfig, raw.get("sizes", {}), "sizes"),
        spacetrack=_build(SpaceTrackConfig, raw.get("spacetrack", {}), "spacetrack"),
        favorites=_build(FavoritesConfig, raw.get("favorites", {}), "favorites"),
        output=_build(OutputConfig, raw.get("output", {}), "output"),
        instrument=_build_instrument(raw.get("instrument", {}), "instrument"),
        gui=_build(GuiConfig, raw.get("gui", {}), "gui"),
        cache_dir=raw.get("cache_dir", "cache"),
        ephemeris=raw.get("ephemeris", "de421.bsp"),
        source_path=path,
    )
    _validate(config)
    return config


def _validate(config: Config) -> None:
    obs = config.observatory
    if not -90.0 <= obs.latitude_deg <= 90.0:
        raise ConfigError(f"observatory.latitude_deg: {obs.latitude_deg} is outside [-90, 90]")
    if not -180.0 <= obs.longitude_deg <= 360.0:
        raise ConfigError(f"observatory.longitude_deg: {obs.longitude_deg} is outside [-180, 360]")
    obs.zoneinfo()

    if not config.celestrak.groups:
        raise ConfigError("celestrak.groups: at least one group is required")
    if not all(isinstance(g, str) and g.strip() for g in config.celestrak.groups):
        raise ConfigError("celestrak.groups: must be a list of non-empty strings")

    search = config.search
    if search.max_separation_deg is not None and search.max_separation_deg <= 0:
        raise ConfigError("search.max_separation_deg: must be positive or null")
    if search.coarse_step_seconds <= 0:
        raise ConfigError("search.coarse_step_seconds: must be positive")
    if search.fine_step_seconds <= 0:
        raise ConfigError("search.fine_step_seconds: must be positive")
    if search.fine_step_seconds >= search.coarse_step_seconds:
        raise ConfigError("search.fine_step_seconds: must be smaller than coarse_step_seconds")
    if search.gate_factor < 1.0:
        raise ConfigError("search.gate_factor: must be at least 1.0")
    if search.path_samples < 2:
        raise ConfigError("search.path_samples: must be at least 2")
    if not isinstance(search.satellite_sizes_m, dict):
        raise ConfigError("search.satellite_sizes_m: must be an object of norad_id -> metres")
    try:
        parse_overrides(search.satellite_sizes_m)
    except ValueError as exc:
        raise ConfigError(f"search.{exc}") from exc

    if config.sizes.max_age_days <= 0:
        raise ConfigError("sizes.max_age_days: must be positive")

    if config.spacetrack.max_age_days <= 0:
        raise ConfigError("spacetrack.max_age_days: must be positive")
    if config.spacetrack.min_mean_motion <= 0:
        raise ConfigError("spacetrack.min_mean_motion: must be positive")

    if config.target not in ("sun", "moon"):
        raise ConfigError(f"target: must be 'sun' or 'moon', not {config.target!r}")
    if config.search.min_target_altitude_deg < -90 or config.search.min_target_altitude_deg > 90:
        raise ConfigError("search.min_target_altitude_deg: must be within [-90, 90]")

    if config.illumination.satellite not in ("any", "sunlit", "eclipsed"):
        raise ConfigError(
            f"illumination.satellite: must be 'any', 'sunlit' or 'eclipsed', "
            f"not {config.illumination.satellite!r}"
        )
    if config.illumination.limb not in ("any", "lit", "dark"):
        raise ConfigError(
            f"illumination.limb: must be 'any', 'lit' or 'dark', not {config.illumination.limb!r}"
        )

    if config.uncertainty.cross_track_km_per_day < 0:
        raise ConfigError("uncertainty.cross_track_km_per_day: must not be negative")
    if config.uncertainty.along_track_km_per_day < 0:
        raise ConfigError("uncertainty.along_track_km_per_day: must not be negative")

    if config.instrument.meridian_side not in SIDES:
        raise ConfigError(
            f"instrument.meridian_side: must be one of {', '.join(SIDES)}, "
            f"not {config.instrument.meridian_side!r}"
        )

    for index, fov in enumerate(config.instrument.fields_of_view):
        where = f"instrument.fields_of_view[{index}]"
        if not isinstance(fov.name, str) or not fov.name.strip():
            raise ConfigError(f"{where}.name: must be a non-empty string")
        sided = fov.width_arcmin is not None or fov.height_arcmin is not None
        if sided and fov.is_circle:
            raise ConfigError(
                f"{where}: give either width_arcmin and height_arcmin, or diameter_arcmin"
            )
        if fov.is_circle:
            if fov.diameter_arcmin <= 0:
                raise ConfigError(f"{where}.diameter_arcmin: must be positive")
        elif fov.width_arcmin is None or fov.height_arcmin is None:
            raise ConfigError(
                f"{where}: needs width_arcmin with height_arcmin, or diameter_arcmin"
            )
        elif fov.width_arcmin <= 0 or fov.height_arcmin <= 0:
            raise ConfigError(f"{where}: width_arcmin and height_arcmin must be positive")

    if config.gui.theme not in ("dark", "light"):
        raise ConfigError(f"gui.theme: must be 'dark' or 'light', not {config.gui.theme!r}")
    if config.gui.recording_lead_seconds <= 0:
        raise ConfigError("gui.recording_lead_seconds: must be positive")
