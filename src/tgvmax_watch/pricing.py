"""Live paid-fare lookup from SNCF Connect's internal search API.

The TGVmax open dataset has no prices. To surface cheap paid options for the
user's priority cities we query SNCF Connect directly. This module is the only
place that talks to a non-open-data SNCF endpoint; it is kept behind a narrow
PriceProvider interface so the transport (plain HTTP vs headless browser) can
change without touching the rest of the pipeline.
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Protocol
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class PricedJourney:
    date: date
    train_no: str
    origin: str          # canonical dataset station string (e.g. "NICE VILLE")
    destination: str     # canonical dataset station string
    dep: str             # "HH:MM"
    arr: str             # "HH:MM"
    carrier: str         # "TGV INOUI" | "OUIGO" | "OUIGO TRAIN CLASSIQUE" | "INTERCITES"
    price_eur: float     # cheapest 2nd-class fare in EUR; > 0 (free seats are dropped)


class PriceProvider(Protocol):
    def search(
        self,
        origin: str,
        destination: str,
        day: date,
        window: tuple[str, str],
    ) -> list[PricedJourney]:
        """All journeys origin->destination on `day` departing within `window`,
        each with its cheapest 2nd-class fare. `origin`/`destination` are the
        canonical dataset station strings; the provider maps them to SNCF
        Connect codes internally and tags results with the same strings."""
        ...


def _parse_price_label(label: str) -> float:
    """'32,80 €' / '55 €' (non-breaking space, comma decimal) -> float EUR."""
    cleaned = (
        label
        .replace(" ", "")  # non-breaking space
        .replace(" ", "")       # regular space
        .replace("€", "")
        .strip()
        .replace(",", ".")
    )
    return float(cleaned)


def _proposal_price(prop: dict) -> float | None:
    """Cheapest 2nd-class offer for this proposal, or None if no offer (unavailable)."""
    offers = (prop.get("secondComfortClassOffers") or {}).get("offers") or []
    prices = [_parse_price_label(o["priceLabel"]) for o in offers if o.get("priceLabel")]
    return min(prices) if prices else None


def _carrier(prop: dict) -> str:
    """'Direct OUIGO' -> 'OUIGO', 'Direct TGV INOUI' -> 'TGV INOUI'."""
    desc = (prop.get("transporterDescription") or "").strip()
    return re.sub(r"^Direct\s+", "", desc).strip() or "TGV INOUI"


def parse_journeys(
    payload: dict, origin: str, destination: str, day: date
) -> list[PricedJourney]:
    """Parse a raw SNCF Connect /itineraries response into PricedJourneys.

    Journeys with no purchasable offer (sold out / past) are dropped. `origin`/
    `destination` are the canonical dataset station strings we searched for; we tag
    every result with them (the response uses SNCF Connect's own station names,
    which would not match the routing layer's station map).
    """
    proposals = (
        (payload.get("longDistance") or {}).get("proposals") or {}
    ).get("proposals") or []
    out: list[PricedJourney] = []
    for prop in proposals:
        price = _proposal_price(prop)
        if price is None:
            continue  # unavailable train
        travel_id = prop.get("travelId", "")
        train_no = travel_id.split("_", 1)[1] if "_" in travel_id else ""
        out.append(
            PricedJourney(
                date=day,
                train_no=train_no,
                origin=origin,
                destination=destination,
                dep=(prop.get("departure") or {}).get("timeLabel", ""),
                arr=(prop.get("arrival") or {}).get("timeLabel", ""),
                carrier=_carrier(prop),
                price_eur=price,
            )
        )
    return out


PARIS_TZ = ZoneInfo("Europe/Paris")
SEARCH_PATH = "/bff/api/v1/itineraries"
HOME_URL = "https://www.sncf-connect.com/"

# Headers shipped by the SNCF Connect frontend. x-bff-key is static; may rotate with
# the app version — re-capture (see docs/superpowers/notes/sncf-connect-endpoint.md)
# if searches start returning 400/401.
BFF_HEADERS = {
    "content-type": "application/json",
    "accept": "application/json, text/plain, */*",
    "x-bff-key": "ah1MPO-izehIHD-QZZ9y88n-kku876",
    "x-client-app-id": "front-web",
    "x-api-env": "production",
    "x-market-locale": "fr_FR",
    "x-client-channel": "web",
    "x-device-class": "desktop",
}

# YOUNG + Carte Avantage Jeune (decided 2026-05-29).
PASSENGER = {
    "discountCards": [{"code": "YOUNG_PASS", "label": "Carte Avantage Jeune", "selected": True}],
    "typology": "YOUNG",
    "displayName": "4 - 29 ans",
    "age": 25,
    "withoutSeatAssignment": False,
    "hasDisability": False,
    "hasWheelchair": False,
}

# dataset station string -> SNCF Connect place (id + RESARAIL code), captured in Task 1.
STATION_PLACES: dict[str, dict] = {
    "PARIS (intramuros)":        {"id": "CITY_FR_6455259",      "resa": "FRPAR", "label": "Paris",                     "city": "Paris"},
    "MASSY TGV":                 {"id": "RESARAIL_STA_8739370", "resa": "FRDJU", "label": "Massy TGV",                 "city": "Massy"},
    "NICE VILLE":                {"id": "RESARAIL_STA_8775605", "resa": "FRNIC", "label": "Nice",                      "city": "Nice"},
    "MONTPELLIER SAINT ROCH":    {"id": "RESARAIL_STA_8777300", "resa": "FRMPL", "label": "Montpellier Saint-Roch",    "city": "Montpellier"},
    "MONTPELLIER SUD DE FRANCE": {"id": "RESARAIL_STA_8768888", "resa": "FRSUF", "label": "Montpellier Sud-de-France", "city": "Montpellier"},
    "MARSEILLE ST CHARLES":      {"id": "RESARAIL_STA_8775100", "resa": "FRMSC", "label": "Marseille Saint-Charles",   "city": "Marseille"},
    "AIX EN PROVENCE TGV":       {"id": "RESARAIL_STA_8731901", "resa": "FRAIE", "label": "Aix-en-Provence TGV",       "city": "Aix-en-Provence"},
    "ANNECY":                    {"id": "RESARAIL_STA_8774600", "resa": "FRNCY", "label": "Annecy",                    "city": "Annecy"},
    "ST RAPHAEL VALESCURE":      {"id": "RESARAIL_STA_8775752", "resa": "FRXSK", "label": "Saint-Raphaël – Valescure", "city": "Saint-Raphaël"},
    "LES ARCS DRAGUIGNAN":       {"id": "RESARAIL_STA_8775544", "resa": "FRXRS", "label": "Les Arcs – Draguignan",     "city": "Les Arcs"},
    "LA ROCHELLE VILLE":         {"id": "RESARAIL_STA_8748500", "resa": "FRLRH", "label": "La Rochelle Ville",         "city": "La Rochelle"},
    "LYON (intramuros)":         {"id": "CITY_FR_6454573",      "resa": "FRLYS", "label": "Lyon",                      "city": "Lyon"},
}


def _utc_z(day: date, hhmm: str) -> str:
    """Paris-local day+HH:MM -> UTC '...T..Z' string the BFF expects."""
    h, m = (int(x) for x in hhmm.split(":"))
    local = datetime(day.year, day.month, day.day, h, m, tzinfo=PARIS_TZ)
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _place(station: str) -> dict:
    p = STATION_PLACES[station]   # KeyError if unmapped
    return {
        "label": p["label"],
        "id": p["id"],
        "codes": [{"type": "RESARAIL", "value": p["resa"]}, {"type": "RESARAIL", "value": p["resa"]}],
        "geolocation": False,
        "resarailCode": p["resa"],
        "city": p["city"],
    }


def _build_body(origin: str, destination: str, day: date, window: tuple[str, str]) -> dict:
    """Exact /itineraries request body (depart at window start, YOUNG + Carte Jeune)."""
    return {
        "schedule": {"outward": {"date": _utc_z(day, window[0]), "arrivalAt": False}},
        "mainJourney": {"origin": _place(origin), "destination": _place(destination)},
        "passengers": [{"id": "00000000-0000-4000-8000-000000000001", **PASSENGER}],
        "pets": [],
        "itineraryId": "00000000-0000-4000-8000-0000000000ff",
        "forceDisplayResults": True,
        "trainExpected": True,
        "wishBike": False,
        "strictMode": False,
        "directJourney": False,
        "transporterLabels": [],
        "metadataY": {},
        "userNavigation": ["IS_NOT_BUSINESS"],
    }


def _in_window(hhmm: str, window: tuple[str, str]) -> bool:
    return bool(hhmm) and window[0] <= hhmm <= window[1]


# JS run inside the page: POST the body via in-page fetch (carries the DataDome
# cookie + browser TLS automatically) and return the parsed JSON.
_FETCH_JS = """
async ({path, headers, body}) => {
  const r = await fetch(path, {method:'POST', headers, body: JSON.stringify(body)});
  return {status: r.status, json: await r.json()};
}
"""


class SncfConnectProvider:
    """PriceProvider backed by SNCF Connect via a Playwright browser session.

    SNCF Connect is protected by DataDome. A plain server-side request (httpx) is
    blocked outright (403), and so is *headless* Chromium: DataDome's JS challenge
    never resolves and even the homepage stays on the 403 interstitial. A **headed**
    Chromium session (needs a display — DISPLAY locally, Xvfb on a server) lets the
    challenge resolve; once the real homepage has loaded, in-page `fetch()` calls to
    the BFF succeed. So we launch headed once, wait for the challenge to clear, then
    issue every search as an in-page fetch. Use as a context manager (or call
    close()) so the browser is released.
    """

    def __init__(self, delay_range: tuple[float, float] = (1.5, 4.0), headless: bool = False) -> None:
        # headless defaults to False: DataDome blocks headless Chromium. Keep False
        # unless you have a working stealth setup; on a server run under Xvfb.
        self._delay_range = delay_range
        self._headless = headless
        self._pw = None
        self._browser = None
        self._page = None

    def __enter__(self) -> "SncfConnectProvider":
        self._start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _start(self) -> None:
        if self._page is not None:
            return
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self._headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._page = self._browser.new_page(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
        )
        self._page.goto(HOME_URL, wait_until="domcontentloaded")
        self._wait_for_datadome()

    def _wait_for_datadome(self, timeout_s: int = 25) -> None:
        """Block until the DataDome challenge resolves to the real homepage.

        DataDome serves a 403 interstitial first (title 'sncf-connect.com'); when
        the challenge passes, the page becomes the real homepage (title contains
        'Réservez'). Poll for that instead of a fixed sleep.
        """
        for _ in range(timeout_s):
            self._page.wait_for_timeout(1000)
            if "Réservez" in (self._page.title() or ""):
                return
        raise RuntimeError("SNCF Connect DataDome challenge did not resolve (still blocked)")

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._pw is not None:
            self._pw.stop()
        self._pw = self._browser = self._page = None

    def search(self, origin: str, destination: str, day: date, window: tuple[str, str]) -> list[PricedJourney]:
        self._start()
        body = _build_body(origin, destination, day, window)  # KeyError on unmapped station
        lo, hi = self._delay_range
        if hi > 0:
            time.sleep(random.uniform(lo, hi))  # throttle to limit DataDome escalation
        res = self._page.evaluate(_FETCH_JS, {"path": SEARCH_PATH, "headers": BFF_HEADERS, "body": body})
        if res.get("status") != 200:
            raise RuntimeError(f"SNCF Connect search {origin}->{destination} {day}: HTTP {res.get('status')}")
        journeys = parse_journeys(res["json"], origin=origin, destination=destination, day=day)
        return [j for j in journeys if _in_window(j.dep, window)]


from .api import Train  # noqa: E402  (placed here to avoid import cycles)
from .config import City, Config  # noqa: E402


def priority_cities(cfg: Config) -> list[City]:
    """Cities eligible for paid-price lookup: base_weight at/above the threshold."""
    return [c for c in cfg.cities if c.base_weight >= cfg.paid_lookup_min_weight]


def priced_to_train(j: PricedJourney) -> Train:
    """Convert a PricedJourney into the Train representation the pipeline consumes.

    Carrier is stored in `axe` (already a free-form grouping field) so the report
    can show it; `entity` is left blank. The price rides along in `price_eur`.
    """
    return Train(
        date=j.date,
        train_no=j.train_no,
        origin=j.origin,
        destination=j.destination,
        dep=j.dep,
        arr=j.arr,
        entity="",
        axe=j.carrier,
        price_eur=j.price_eur,
    )
