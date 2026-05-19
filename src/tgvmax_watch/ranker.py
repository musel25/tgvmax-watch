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


def _score_pair(cfg: Config, city: City, out: Journey, back: Journey) -> float | None:
    sched = cfg.scheduling.get(city.region, cfg.scheduling["east"])

    # HARD outbound rule: Fri must be in friday_out_windows (18:00-23:00),
    # Sat must be in saturday_out_windows (morning). Anything else is dropped.
    out_dow = out.train.date.weekday()
    if out_dow == 4:
        out_windows = sched.friday_out_windows
    elif out_dow == 5:
        out_windows = sched.saturday_out_windows
    else:
        return None
    if not in_window(out.train.dep, out_windows):
        return None

    s = float(city.base_weight)

    # return-window fit stays soft (user only made outbound a hard rule)
    back_fit = in_window(back.train.dep, sched.return_windows)
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
        scored: list[Pairing] = []
        for o in outs:
            for b in backs:
                if not _is_valid_pair(o, b):
                    continue
                score = _score_pair(cfg, city, o, b)
                if score is None:  # outbound failed the hard window filter
                    continue
                scored.append(Pairing(city, o, b, score))
        scored.sort(key=lambda p: p.score, reverse=True)
        pairings.extend(scored[:top_n_per_city])
    pairings.sort(key=lambda p: p.score, reverse=True)
    return pairings[:top_n_total]
