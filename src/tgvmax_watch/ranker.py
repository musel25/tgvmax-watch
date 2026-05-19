"""Score and rank weekend round-trip options."""

from __future__ import annotations

from dataclasses import dataclass

from .config import City, Config
from .routing import Journey, Weekend, duration_min, in_window


@dataclass(frozen=True)
class Pairing:
    city: City
    out: Journey
    back: Journey
    score: float


def _score_pair(cfg: Config, city: City, out: Journey, back: Journey) -> float:
    sched = cfg.scheduling.get(city.region, cfg.scheduling["east"])
    s = float(city.base_weight)

    # time-window fit (very important)
    out_fit = in_window(out.train.dep, sched.out_windows)
    back_fit = in_window(back.train.dep, sched.return_windows)
    s += 25 if out_fit else -15
    s += 25 if back_fit else -15

    # ride length penalty (very long rides are fine for far destinations, bad for close ones)
    total_min = duration_min(out.train) + duration_min(back.train)
    s -= total_min / 60  # 1pt per ride-hour

    # nights-on-site: huge driver. Same-day round trip = bad. 1 night = OK. 2 nights = great.
    nights = (back.train.date - out.train.date).days
    if nights == 0:
        s -= 40  # day trip — not a weekend
    elif nights == 1:
        s += 10  # one Saturday night
    else:  # 2+ nights
        s += 30

    # within the chosen nights, prefer later returns (more daylight on site)
    s += _to_min(back.train.dep) / 90

    # penalize extra TER leg
    if city.needs_extra_leg:
        s -= 8

    # visited cities pushed way down
    if city.visited:
        s -= 60

    # bonus when out is Friday evening and city is south (sleep-friendly)
    if city.region == "south" and out.train.date.weekday() == 4 and _to_min(out.train.dep) >= 17 * 60:
        s += 8
    # bonus when back is Sunday late-evening (sleep on train)
    if city.region == "south" and back.train.date.weekday() == 6 and _to_min(back.train.dep) >= 19 * 60:
        s += 8

    return s


def _to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _is_valid_pair(o: Journey, b: Journey) -> bool:
    """Return must be at least 6h after outbound arrival (no phantom same-day pairs)."""
    if b.train.date < o.train.date:
        return False
    if b.train.date == o.train.date:
        gap = _to_min(b.train.dep) - _to_min(o.train.arr)
        return gap >= 360  # 6h minimum on-site
    return True


def rank_weekend(
    cfg: Config,
    weekend: Weekend,
    grouped: dict[str, dict[str, list[Journey]]],
    top_n_per_city: int = 4,
    top_n_total: int = 15,
) -> list[Pairing]:
    """For each city build the best (out, back) pairings, then take the global top N."""
    pairings: list[Pairing] = []
    by_name = {c.name: c for c in cfg.cities}
    for city_name, legs in grouped.items():
        city = by_name[city_name]
        outs = legs["out"]
        backs = legs["back"]
        if not outs or not backs:
            continue
        scored = [
            Pairing(city, o, b, _score_pair(cfg, city, o, b))
            for o in outs
            for b in backs
            if _is_valid_pair(o, b)
        ]
        scored.sort(key=lambda p: p.score, reverse=True)
        pairings.extend(scored[:top_n_per_city])
    pairings.sort(key=lambda p: p.score, reverse=True)
    return pairings[:top_n_total]
