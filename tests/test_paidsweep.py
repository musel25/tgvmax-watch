from datetime import date

from tgvmax_watch.config import City, Config, Scheduling
from tgvmax_watch.paidsweep import gather_paid_trains
from tgvmax_watch.pricing import PricedJourney
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


class FakeProvider:
    def __init__(self):
        self.calls = []

    def search(self, origin, destination, day, window):
        self.calls.append((origin, destination, day, window))
        # one cheap, one too-expensive, one free
        return [
            PricedJourney(day, "1", origin, destination, window[0], "23:00", "OUIGO", 22.0),
            PricedJourney(day, "2", origin, destination, window[0], "23:30", "TGV INOUI", 80.0),
            PricedJourney(day, "3", origin, destination, window[0], "22:00", "TGV INOUI", 0.0),
        ]


def test_gather_only_priority_cities():
    cfg = _cfg()
    prov = FakeProvider()
    wk = Weekend(date(2026, 5, 29), date(2026, 5, 30), date(2026, 5, 31))
    out_trains, back_trains = gather_paid_trains(cfg, [wk], prov)
    # Nice is the only priority city -> Lyon never queried
    assert all("LYON" not in d for _, d, _, _ in prov.calls)
    assert all("NICE" in d or "NICE" in o for o, d, _, _ in prov.calls)


def test_gather_filters_price_threshold_and_free():
    cfg = _cfg()
    prov = FakeProvider()
    wk = Weekend(date(2026, 5, 29), date(2026, 5, 30), date(2026, 5, 31))
    out_trains, back_trains = gather_paid_trains(cfg, [wk], prov)
    all_trains = out_trains + back_trains
    assert all_trains, "should keep the cheap paid train"
    for t in all_trains:
        assert t.price_eur is not None and 0 < t.price_eur <= 30.0


def test_gather_swallows_provider_errors():
    cfg = _cfg()

    class Boom:
        def search(self, *a, **k):
            raise RuntimeError("datadome challenge")

    wk = Weekend(date(2026, 5, 29), date(2026, 5, 30), date(2026, 5, 31))
    out_trains, back_trains = gather_paid_trains(cfg, [wk], Boom())
    assert out_trains == [] and back_trains == []  # never raises
