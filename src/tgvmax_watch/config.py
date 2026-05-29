"""Load cities.yaml into typed structures."""

from __future__ import annotations

import dataclasses
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
    friday_out_windows: tuple[tuple[str, str], ...]
    saturday_out_windows: tuple[tuple[str, str], ...]
    return_windows: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Config:
    origins: tuple[str, ...]
    cities: tuple[City, ...]
    scheduling: dict[str, Scheduling] = field(default_factory=dict)
    max_paid_price: float = 30.0
    paid_lookup_min_weight: int = 80


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
            friday_out_windows=tuple(tuple(w) for w in s["friday_out_windows"]),
            saturday_out_windows=tuple(tuple(w) for w in s["saturday_out_windows"]),
            return_windows=tuple(tuple(w) for w in s["return_windows"]),
        )
        for region, s in raw["scheduling"].items()
    }
    return Config(
        origins=origins,
        cities=cities,
        scheduling=scheduling,
        max_paid_price=float(raw.get("max_paid_price", 30.0)),
        paid_lookup_min_weight=int(raw.get("paid_lookup_min_weight", 80)),
    )


def replace_max_paid_price(cfg: Config, value: float) -> Config:
    return dataclasses.replace(cfg, max_paid_price=value)


def all_destination_stations(cfg: Config) -> list[str]:
    """Flattened, deduplicated list of every TGV station that matters to us."""
    seen: dict[str, None] = {}
    for c in cfg.cities:
        for s in c.stations:
            seen[s] = None
    return list(seen)
