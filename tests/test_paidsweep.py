from datetime import date

from tgvmax_watch.config import City, Config, Scheduling
from tgvmax_watch.paidsweep import gather_paid_trains
from tgvmax_watch.pricing import PricedJourney, SearchResult
from tgvmax_watch.routing import Weekend


def _cfg():
    sched = Scheduling(
        friday_out_windows=(("18:00", "23:00"),),
        saturday_out_windows=(("06:00", "12:00"),),
        return_windows=(("06:00", "23:30"),),
    )
    return Config(
        origins=("PARIS (intramuros)",),
        cities=(City("Nice", "south", ("NICE VILLE",), base_weight=100),
                City("Lyon", "east", ("LYON (intramuros)",), base_weight=58)),
        scheduling={"south": sched, "east": sched},
        max_paid_price=30.0,
        paid_lookup_min_weight=80,
    )


WK = Weekend(date(2026, 5, 29), date(2026, 5, 30), date(2026, 5, 31))


class FakeProvider:
    """Returns one cheap, one too-expensive, one free journey; cheap calendar."""
    def __init__(self, calendar=None):
        self.calls = []
        self.calendar = calendar or {}

    def search(self, origin, destination, day, window):
        self.calls.append((origin, destination, day, window))
        journeys = [
            PricedJourney(day, "1", origin, destination, window[0], "23:00", "OUIGO", 22.0),
            PricedJourney(day, "2", origin, destination, window[0], "23:30", "TGV INOUI", 80.0),
            PricedJourney(day, "3", origin, destination, window[0], "22:00", "TGV INOUI", 0.0),
        ]
        # default: mark every day cheap so nothing is gated out
        cal = self.calendar or {day: 10.0}
        return SearchResult(journeys=journeys, cheapest_by_day=cal)


def test_gather_only_priority_cities():
    prov = FakeProvider()
    gather_paid_trains(_cfg(), [WK], prov)
    assert all("LYON" not in d for _, d, _, _ in prov.calls)
    assert prov.calls and all(("NICE" in o or "NICE" in d) for o, d, _, _ in prov.calls)


def test_gather_filters_price_threshold_and_free():
    prov = FakeProvider()
    out_trains, back_trains = gather_paid_trains(_cfg(), [WK], prov)
    all_trains = out_trains + back_trains
    assert all_trains
    for t in all_trains:
        assert t.price_eur is not None and 0 < t.price_eur <= 30.0


def test_gather_swallows_provider_errors():
    class Boom:
        def search(self, *a, **k):
            raise RuntimeError("datadome challenge")
    out_trains, back_trains = gather_paid_trains(_cfg(), [WK], Boom())
    assert out_trains == [] and back_trains == []


def test_gather_skips_days_when_calendar_too_expensive():
    # Calendar says EVERY day costs 99 EUR -> after the first search per direction,
    # subsequent days for that direction are skipped.
    prov = FakeProvider(calendar={date(2026, 5, 29): 99.0, date(2026, 5, 30): 99.0,
                                  date(2026, 5, 31): 99.0})
    gather_paid_trains(_cfg(), [WK], prov)
    # Nice has 1 station. Outbound day_windows = [Fri(1 win), Sat(1 win)]; the Fri
    # search returns the expensive calendar, so Sat is skipped -> 1 outbound call.
    # Return day_windows = [Sat(1 win), Sun(1 win)]; Sat search -> Sun skipped -> 1 call.
    # Total 2 calls (vs 4 without gating).
    assert len(prov.calls) == 2
