from datetime import date

import pytest

from tgvmax_watch.pricing import PricedJourney, parse_journeys, _parse_price_label


@pytest.mark.parametrize("label,expected", [
    ("55 €", 55.0),
    ("32,80 €", 32.80),
    ("16 €", 16.0),
    ("74 €", 74.0),
])
def test_parse_price_label_handles_nbsp_and_comma(label, expected):
    assert _parse_price_label(label) == expected


def test_parse_returns_priced_journeys(sncf_search_response):
    journeys = parse_journeys(
        sncf_search_response,
        origin="PARIS (intramuros)",
        destination="LYON (intramuros)",
        day=date(2026, 5, 29),
    )
    # 5 proposals in the fixture, one has empty offers -> skipped -> 4 priced
    assert len(journeys) == 4
    assert all(isinstance(j, PricedJourney) for j in journeys)
    for j in journeys:
        assert j.origin == "PARIS (intramuros)"
        assert j.destination == "LYON (intramuros)"
        assert j.date == date(2026, 5, 29)
        assert j.price_eur > 0.0
        assert len(j.dep) == 5 and j.dep[2] == ":"
        assert len(j.arr) == 5 and j.arr[2] == ":"
        assert j.carrier in {"OUIGO", "TGV INOUI", "OUIGO TRAIN CLASSIQUE", "INTERCITES"}


def test_parse_takes_cheapest_offer_and_train_no(sncf_search_response):
    journeys = parse_journeys(
        sncf_search_response, "PARIS (intramuros)", "LYON (intramuros)", date(2026, 5, 29))
    ouigo_2056 = next(j for j in journeys if j.dep == "20:56")
    assert ouigo_2056.carrier == "OUIGO"
    assert ouigo_2056.train_no == "7815"
    assert ouigo_2056.price_eur == 65.0   # min of ["74 €", "65 €"]
