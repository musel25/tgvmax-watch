from datetime import date

import pytest

from tgvmax_watch.pricing import SncfConnectProvider, STATION_PLACES, _build_body, _utc_z


def test_utc_z_converts_paris_local_to_utc():
    # 18:00 Paris in summer (CEST, UTC+2) -> 16:00 UTC, matches captured payload
    assert _utc_z(date(2026, 5, 30), "18:00") == "2026-05-30T16:00:00.000Z"


def test_build_body_sets_codes_date_and_young_passenger():
    body = _build_body("PARIS (intramuros)", "LYON (intramuros)", date(2026, 5, 30), ("06:00", "12:00"))
    assert body["mainJourney"]["origin"]["resarailCode"] == "FRPAR"
    assert body["mainJourney"]["origin"]["id"] == "CITY_FR_6455259"
    assert body["mainJourney"]["destination"]["resarailCode"] == "FRLYS"
    assert body["schedule"]["outward"]["date"] == "2026-05-30T04:00:00.000Z"  # 06:00 CEST
    p = body["passengers"][0]
    assert p["typology"] == "YOUNG"
    assert p["discountCards"][0]["code"] == "YOUNG_PASS"


def test_build_body_unknown_station_raises_keyerror():
    with pytest.raises(KeyError):
        _build_body("NOWHERE", "LYON (intramuros)", date(2026, 5, 30), ("06:00", "12:00"))


def test_station_map_covers_priority_stations():
    for s in ["PARIS (intramuros)", "NICE VILLE", "MARSEILLE ST CHARLES",
              "AIX EN PROVENCE TGV", "ANNECY", "ST RAPHAEL VALESCURE",
              "LES ARCS DRAGUIGNAN", "LA ROCHELLE VILLE",
              "MONTPELLIER SAINT ROCH", "MONTPELLIER SUD DE FRANCE"]:
        assert s in STATION_PLACES


@pytest.mark.live
def test_live_search_returns_real_prices():
    from datetime import timedelta
    day = date.today() + timedelta(days=7)
    with SncfConnectProvider() as provider:
        result = provider.search("PARIS (intramuros)", "LYON (intramuros)", day, ("06:00", "23:59"))
    assert result.journeys
    assert any(j.price_eur > 0 for j in result.journeys)
    assert result.cheapest_by_day  # calendar present
