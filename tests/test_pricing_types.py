from datetime import date

from tgvmax_watch.pricing import PricedJourney


def test_priced_journey_holds_fields():
    j = PricedJourney(
        date=date(2026, 5, 30),
        train_no="6607",
        origin="PARIS (intramuros)",
        destination="LYON (intramuros)",
        dep="19:00",
        arr="20:56",
        carrier="OUIGO",
        price_eur=19.0,
    )
    assert j.price_eur == 19.0
    assert j.carrier == "OUIGO"
