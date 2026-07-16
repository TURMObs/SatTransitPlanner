"""Configuration file loading and validation."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .sizes import parse_overrides

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
    # Angular radius around the Sun's center within which an approach is reported.
    # null/None means "solar limb", i.e. only true disk transits are reported.
    max_separation_deg: float | None = 1.0
    min_sun_altitude_deg: float = 5.0
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
class FavoritesConfig:
    file: str = "favorites.json"


@dataclass
class GuiConfig:
    theme: str = "dark"


@dataclass
class Config:
    observatory: Observatory
    celestrak: CelestrakConfig
    search: SearchConfig = field(default_factory=SearchConfig)
    sizes: SizesConfig = field(default_factory=SizesConfig)
    favorites: FavoritesConfig = field(default_factory=FavoritesConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
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
        "observatory", "celestrak", "search", "sizes", "favorites", "output", "gui",
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
        search=_build(SearchConfig, raw.get("search", {}), "search"),
        sizes=_build(SizesConfig, raw.get("sizes", {}), "sizes"),
        favorites=_build(FavoritesConfig, raw.get("favorites", {}), "favorites"),
        output=_build(OutputConfig, raw.get("output", {}), "output"),
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

    if config.gui.theme not in ("dark", "light"):
        raise ConfigError(f"gui.theme: must be 'dark' or 'light', not {config.gui.theme!r}")
