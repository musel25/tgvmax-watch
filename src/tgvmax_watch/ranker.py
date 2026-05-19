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

    # on-site time is the real driver, not nights. A 12h Saturday day trip beats a
    # 2h-on-site ghost overnight; a full Fri-eve→Sun beats either. Smooth buckets:
    on_site_h = _on_site_minutes(out, back) / 60
    if on_site_h < 10:
        s -= 10                # short — only worth it for close cities
    elif on_site_h < 14:
        s += 5                 # real day trip
    elif on_site_h < 24:
        s += 15                # long day or short overnight
    elif on_site_h < 36:
        s += 25                # one solid night on site
    elif on_site_h < 50:
        s += 35                # full Fri-eve → Sun
    else:
        s += 40                # extra day

    # tiebreaker within a bucket: prefer later returns (more daylight before leaving)
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


def _on_site_minutes(o: Journey, b: Journey) -> int:
    """Minutes between outbound arrival and return departure, spanning days."""
    day_diff = (b.train.date - o.train.date).days
    return day_diff * 24 * 60 + _to_min(b.train.dep) - _to_min(o.train.arr)


def _is_valid_pair(o: Journey, b: Journey) -> bool:
    """At least 6h on site — drops phantom same-day pairs and ghost overnights alike."""
    if b.train.date < o.train.date:
        return False
    return _on_site_minutes(o, b) >= 360


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
