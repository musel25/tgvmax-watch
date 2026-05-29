from datetime import date, datetime

from tgvmax_watch.api import Train
from tgvmax_watch.config import City
from tgvmax_watch.ranker import Pairing
from tgvmax_watch.report import render_compact
from tgvmax_watch.routing import Journey, Weekend


def _pairing(total_price):
    city = City("Lyon", "east", ("LYON (intramuros)",), base_weight=58)
    out_t = Train(date(2026, 5, 30), "1", "PARIS (intramuros)", "LYON (intramuros)",
                  "08:00", "10:00", "", "", price_eur=(None if total_price is None else 20.0))
    back_t = Train(date(2026, 5, 31), "2", "LYON (intramuros)", "PARIS (intramuros)",
                   "18:00", "20:00", "", "", price_eur=(None if total_price is None else 10.0))
    return Pairing(city, Journey(city, out_t, "out"), Journey(city, back_t, "back"),
                   score=100.0, total_price=total_price)


def test_paid_pairing_shows_price():
    wk = Weekend(date(2026, 5, 29), date(2026, 5, 30), date(2026, 5, 31))
    text = render_compact([(wk, [_pairing(30.0)])], datetime(2026, 5, 29, 9, 0), date(2026, 5, 29))
    assert "30" in text and "€" in text


def test_free_pairing_has_no_price_tag():
    wk = Weekend(date(2026, 5, 29), date(2026, 5, 30), date(2026, 5, 31))
    text = render_compact([(wk, [_pairing(None)])], datetime(2026, 5, 29, 9, 0), date(2026, 5, 29))
    # the free option line should not carry a paid-price marker
    assert "€" not in text.split("```")[1].splitlines()[2]  # the option line
