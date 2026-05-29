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
from .pricing import SearchResult, priced_to_train, priority_cities
from .routing import Weekend


def _windows_for(cfg: Config, region: str):
    sched = cfg.scheduling.get(region) or next(iter(cfg.scheduling.values()))
    return sched


def gather_paid_trains(cfg, weekends, provider):
    """Return (out_trains, back_trains) of cheap paid Train objects.

    Uses each search's bestPrices day-calendar to skip detailed searches for days
    whose cheapest fare already exceeds max_paid_price.
    """
    out_trains, back_trains = [], []
    origin = cfg.origins[0]
    for city in priority_cities(cfg):
        sched = _windows_for(cfg, city.region)
        for wk in weekends:
            for station in city.stations:
                out_trains += _gather_direction(
                    provider, cfg, origin, station,
                    [(wk.friday, sched.friday_out_windows), (wk.saturday, sched.saturday_out_windows)],
                )
                back_trains += _gather_direction(
                    provider, cfg, station, origin,
                    [(wk.saturday, sched.return_windows), (wk.sunday, sched.return_windows)],
                )
    return out_trains, back_trains


def _gather_direction(provider, cfg, frm, to, day_windows):
    """Search each (day, window), skipping days the calendar says are too pricey."""
    known: dict = {}          # {date: cheapest EUR}, learned from responses
    trains = []
    for day, windows in day_windows:
        if day in known and known[day] > cfg.max_paid_price:
            continue          # whole day already known too expensive — skip its windows
        for window in windows:
            res = _safe_search(provider, frm, to, day, window)
            if res is not None:
                known.update(res.cheapest_by_day)
                trains += [priced_to_train(j) for j in res.journeys
                           if 0 < j.price_eur <= cfg.max_paid_price]
            if known.get(day, 0.0) > cfg.max_paid_price:
                break         # this day is too pricey — skip remaining windows
    return trains


def _safe_search(provider, frm, to, day, window):
    try:
        return provider.search(frm, to, day, window)
    except Exception as e:  # noqa: BLE001 — never let a paid lookup break the sweep
        print(f"[paid] search failed {frm}->{to} {day} {window}: {e}", file=sys.stderr)
        return None
