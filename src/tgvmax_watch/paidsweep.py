"""Fault-tolerant paid-fare gathering for priority cities.

Queries the PriceProvider for each priority city x weekend x direction, keeps
only journeys priced 0 < price <= max_paid_price, and returns them already
converted into Train objects ready to merge into the free sweep's lists. Any
provider failure for one (city, day, direction) is logged and skipped — the
sweep must never fail because of paid lookups.
"""

from __future__ import annotations

import sys

from .config import Config
from .pricing import PriceProvider, priced_to_train, priority_cities
from .routing import Weekend


def _windows_for(cfg: Config, region: str):
    sched = cfg.scheduling.get(region) or next(iter(cfg.scheduling.values()))
    return sched


def gather_paid_trains(
    cfg: Config, weekends: list[Weekend], provider: PriceProvider
):
    """Return (out_trains, back_trains) of cheap paid Train objects."""
    out_trains = []
    back_trains = []
    origin = cfg.origins[0]  # primary Paris origin for paid lookups
    for city in priority_cities(cfg):
        sched = _windows_for(cfg, city.region)
        for wk in weekends:
            for station in city.stations:
                # OUTBOUND: Paris -> city, Fri evening and Sat morning
                for day, windows in ((wk.friday, sched.friday_out_windows),
                                     (wk.saturday, sched.saturday_out_windows)):
                    for window in windows:
                        out_trains += _safe_search(provider, origin, station, day, window, cfg)
                # RETURN: city -> Paris, Sat and Sun, within return windows
                for day in (wk.saturday, wk.sunday):
                    for window in sched.return_windows:
                        back_trains += _safe_search(provider, station, origin, day, window, cfg)
    return out_trains, back_trains


def _safe_search(provider, origin, destination, day, window, cfg: Config):
    try:
        journeys = provider.search(origin, destination, day, window)
    except Exception as e:  # noqa: BLE001 — never let a paid lookup break the sweep
        print(f"[paid] search failed {origin}->{destination} {day} {window}: {e}", file=sys.stderr)
        return []
    kept = [j for j in journeys if 0 < j.price_eur <= cfg.max_paid_price]
    return [priced_to_train(j) for j in kept]
