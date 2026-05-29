from datetime import date

from tgvmax_watch.api import Train
from tgvmax_watch.config import City, Config, Scheduling
from tgvmax_watch.ranker import _score_pair, total_price
from tgvmax_watch.routing import Journey


def _cfg():
    return Config(
        origins=("PARIS (intramuros)",),
        cities=(City("Lyon", "east", ("LYON (intramuros)",), base_weight=58),),
        scheduling={"east": Scheduling(
            friday_out_windows=(("18:00", "23:00"),),
            saturday_out_windows=(("06:00", "12:00"),),
            return_windows=(("14:00", "22:00"),),
        )},
    )


def _pair(out_price, back_price):
    city = City("Lyon", "east", ("LYON (intramuros)",), base_weight=58)
    out_t = Train(date(2026, 5, 30), "1", "PARIS (intramuros)", "LYON (intramuros)",
                  "08:00", "10:00", "", "", price_eur=out_price)   # Saturday morning
    back_t = Train(date(2026, 5, 31), "2", "LYON (intramuros)", "PARIS (intramuros)",
                   "18:00", "20:00", "", "", price_eur=back_price)  # Sunday evening
    o = Journey(city, out_t, "out")
    b = Journey(city, back_t, "back")
    return city, o, b


def test_total_price_none_when_both_free():
    _, o, b = _pair(None, None)
    assert total_price(o, b) is None


def test_total_price_sums_paid_legs():
    _, o, b = _pair(20.0, 10.0)
    assert total_price(o, b) == 30.0


def test_total_price_counts_one_paid_leg():
    _, o, b = _pair(None, 25.0)
    assert total_price(o, b) == 25.0


def test_paid_pair_scores_lower_than_free_equivalent():
    cfg = _cfg()
    _, fo, fb = _pair(None, None)
    _, po, pb = _pair(20.0, 10.0)
    free_score = _score_pair(cfg, fo.city, fo, fb)
    paid_score = _score_pair(cfg, po.city, po, pb)
    assert free_score is not None and paid_score is not None
    assert paid_score == free_score - 30.0 / 2  # penalty = total_price / 2
