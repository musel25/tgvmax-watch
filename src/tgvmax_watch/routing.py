"""Build weekend journey candidates from raw Train records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .api import Train
from .config import City, Config


@dataclass(frozen=True)
class Journey:
    """A one-way TGVmax trip toward (or away from) a city."""
    city: City
    train: Train
    direction: str  # "out" | "back"


@dataclass(frozen=True)
class Weekend:
    friday: date
    saturday: date
    sunday: date

    @classmethod
    def containing(cls, d: date) -> "Weekend":
        # d aligned to Friday of its weekend
        delta = (d.weekday() - 4) % 7
        fri = d - timedelta(days=delta)
        return cls(fri, fri + timedelta(days=1), fri + timedelta(days=2))


def weekends_in_range(start: date, end: date) -> list[Weekend]:
    """All weekends whose Friday falls within [start, end]."""
    out: list[Weekend] = []
    # find first Friday >= start
    cur = start + timedelta(days=(4 - start.weekday()) % 7)
    while cur <= end:
        out.append(Weekend.containing(cur))
        cur += timedelta(days=7)
    return out


def _hhmm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _duration_min(dep: str, arr: str) -> int:
    d = _hhmm(arr) - _hhmm(dep)
    return d if d >= 0 else d + 24 * 60  # overnight


def journeys_for_weekend(
    cfg: Config,
    weekend: Weekend,
    out_trains: list[Train],
    back_trains: list[Train],
) -> dict[str, dict[str, list[Journey]]]:
    """Group trains by city → {"out": [...], "back": [...]}.

    out_trains: Paris → destination on Fri/Sat
    back_trains: destination → Paris on Sat/Sun
    """
    by_station_dest = {s: c for c in cfg.cities for s in c.stations}
    result: dict[str, dict[str, list[Journey]]] = {
        c.name: {"out": [], "back": []} for c in cfg.cities
    }
    for t in out_trains:
        if t.date not in (weekend.friday, weekend.saturday):
            continue
        city = by_station_dest.get(t.destination)
        if not city:
            continue
        result[city.name]["out"].append(Journey(city=city, train=t, direction="out"))
    for t in back_trains:
        if t.date not in (weekend.saturday, weekend.sunday):
            continue
        # for the return, the train's *origin* is the city station
        city = by_station_dest.get(t.origin)
        if not city:
            continue
        result[city.name]["back"].append(Journey(city=city, train=t, direction="back"))
    return result


def in_window(hhmm: str, windows: tuple[tuple[str, str], ...]) -> bool:
    m = _hhmm(hhmm)
    return any(_hhmm(a) <= m <= _hhmm(b) for a, b in windows)


def duration_min(t: Train) -> int:
    return _duration_min(t.dep, t.arr)
