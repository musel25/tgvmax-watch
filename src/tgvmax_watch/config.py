"""Load cities.yaml into typed structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class City:
    name: str
    region: str
    stations: tuple[str, ...]
    base_weight: int = 50
    needs_extra_leg: bool = False
    extra_leg: str = ""
    visited: bool = False


@dataclass(frozen=True)
class Scheduling:
    out_windows: tuple[tuple[str, str], ...]
    return_windows: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Config:
    origins: tuple[str, ...]
    cities: tuple[City, ...]
    scheduling: dict[str, Scheduling] = field(default_factory=dict)


def load(path: Path | str = "cities.yaml") -> Config:
    raw = yaml.safe_load(Path(path).read_text())
    origins = tuple(raw["origins"]["paris"])
    cities = tuple(
        City(
            name=c["name"],
            region=c["region"],
            stations=tuple(c["stations"]),
            base_weight=c.get("base_weight", 50),
            needs_extra_leg=c.get("needs_extra_leg", False),
            extra_leg=c.get("extra_leg", ""),
            visited=c.get("visited", False),
        )
        for c in raw["cities"]
    )
    scheduling = {
        region: Scheduling(
            out_windows=tuple(tuple(w) for w in s["out_windows"]),
            return_windows=tuple(tuple(w) for w in s["return_windows"]),
        )
        for region, s in raw["scheduling"].items()
    }
    return Config(origins=origins, cities=cities, scheduling=scheduling)


def all_destination_stations(cfg: Config) -> list[str]:
    """Flattened, deduplicated list of every TGV station that matters to us."""
    seen: dict[str, None] = {}
    for c in cfg.cities:
        for s in c.stations:
            seen[s] = None
    return list(seen)
