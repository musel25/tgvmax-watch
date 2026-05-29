from datetime import date

from tgvmax_watch.api import Train


def test_train_defaults_to_free():
    t = Train(date(2026, 5, 30), "1", "A", "B", "08:00", "10:00", "", "")
    assert t.price_eur is None


def test_train_can_carry_price():
    t = Train(date(2026, 5, 30), "1", "A", "B", "08:00", "10:00", "", "", price_eur=19.0)
    assert t.price_eur == 19.0


def test_from_record_leaves_price_none():
    t = Train.from_record({
        "date": "2026-05-30", "train_no": "1", "origine": "A", "destination": "B",
        "heure_depart": "08:00", "heure_arrivee": "10:00",
    })
    assert t.price_eur is None
