from datetime import date

from tgvmax_watch.config import City, Config
from tgvmax_watch.pricing import PricedJourney, priced_to_train, priority_cities


def _cfg():
    return Config(
        origins=("PARIS (intramuros)",),
        cities=(
            City("Nice", "south", ("NICE VILLE",), base_weight=100),
            City("Lyon", "east", ("LYON (intramuros)",), base_weight=58),
        ),
        scheduling={},
        max_paid_price=30.0,
        paid_lookup_min_weight=80,
    )


def test_priority_cities_filters_by_weight():
    names = [c.name for c in priority_cities(_cfg())]
    assert names == ["Nice"]


def test_priced_to_train_preserves_price_and_stations():
    j = PricedJourney(date(2026, 5, 30), "6607", "PARIS (intramuros)", "NICE VILLE",
                       "19:00", "23:30", "OUIGO", 22.5)
    t = priced_to_train(j)
    assert t.origin == "PARIS (intramuros)"
    assert t.destination == "NICE VILLE"
    assert t.dep == "19:00" and t.arr == "23:30"
    assert t.price_eur == 22.5
    assert t.axe == "OUIGO"   # carrier stored in axe for display
