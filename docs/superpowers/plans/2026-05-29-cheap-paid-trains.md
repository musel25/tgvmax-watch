# Cheap Paid-Train Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface cheap (<=30 EUR) paid trains to the user's priority cities alongside free TGVmax options, so a weekend with no free seat (or a poorly-timed one) still produces a ranked, bookable option.

**Architecture:** A new `pricing.py` module fetches live per-train prices from SNCF Connect's internal JSON API (`POST /bff/api/v1/itineraries`) for the priority cities, behind a `PriceProvider` interface. Because DataDome blocks plain server-side requests (confirmed in the Task 1 spike: `httpx` → 403, in-browser `fetch` → 200), the shipped provider drives a **headless Playwright/Chromium session**: launch once, navigate to sncf-connect.com to mint a DataDome session, then issue every search as a cheap in-page `fetch()` via `page.evaluate(...)` (no page reload per search). Priced journeys are converted into the existing `Train` representation (new `price_eur` field) and merged into the same out/back lists the free sweep produces, so routing, pairing, ranking, and reporting flow through unchanged except for a price penalty in scoring and a price tag in the report.

**Tech Stack:** Python 3.12+, `httpx` (existing), `playwright` (added in Task 5 for the browser session — needs `uv run playwright install chromium`), `pytest` (added in Task 2 as a dev dep), `uv` for everything. Parsing is pure and tested offline against the recorded fixture; only the live browser fetch is integration-tested (`@pytest.mark.live`, deselected by default).

**Spike outcome (DECIDED):** Endpoint, payload, response schema, station codes, price-label format, and the YOUNG + Carte Avantage Jeune passenger payload are all captured in `docs/superpowers/notes/sncf-connect-endpoint.md`. Tasks 4-5 below use those concrete facts. Fares are priced as **YOUNG + Carte Avantage Jeune** (`discountCards:[{"code":"YOUNG_PASS",...}]`).

**Branch:** `feat/cheap-paid-trains` (already created). **Nothing is deployed to the VPS in this plan.**

---

## Why Task 1 is a spike, not TDD

Live per-train prices live only in SNCF Connect's DataDome-protected internal API. We do not yet know the current endpoint URL, payload, response schema, or whether a plain server-side request gets past DataDome. Task 1 discovers all of that with a real browser (Playwright MCP), **records a real response to a fixture file**, and documents the contract. Every later task is plain TDD against that recorded fixture, so tests are deterministic and offline. Task 1 ends at a **hard user checkpoint** because its outcome (HTTP-replayable vs browser-required) changes the deployment story.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `docs/superpowers/notes/sncf-connect-endpoint.md` | Captured endpoint contract + DataDome verdict + station code map | Create (Task 1) |
| `tests/fixtures/sncf_connect_search.json` | One real recorded search response, sanitized | Create (Task 1) |
| `tests/conftest.py`, `pyproject.toml` | pytest dev dependency + test discovery | Modify/Create (Task 2) |
| `src/tgvmax_watch/pricing.py` | `PricedJourney`, `PriceProvider`, response parser, `SncfConnectProvider`, station code map | Create (Tasks 3-5) |
| `src/tgvmax_watch/api.py` | Add `price_eur` to `Train` | Modify (Task 6) |
| `src/tgvmax_watch/config.py` | Add `max_paid_price`, `paid_lookup_min_weight` to `Config` | Modify (Task 7) |
| `cities.yaml` | Add the two new config keys | Modify (Task 7) |
| `src/tgvmax_watch/pricing.py` | `priced_to_train()`, `priority_cities()` helpers | Modify (Task 8) |
| `src/tgvmax_watch/ranker.py` | `Pairing.total_price` + price penalty in `_score_pair` | Modify (Task 9) |
| `src/tgvmax_watch/main.py` | Wire paid lookups into `cmd_sweep`, add CLI flags | Modify (Task 10) |
| `src/tgvmax_watch/report.py` | Show price on paid pairings | Modify (Task 11) |

---

## Task 1: Spike — capture the SNCF Connect search endpoint (DISCOVERY, GATED)

**This task uses the Playwright MCP browser tools and produces artifacts, not running software. It is NOT TDD. End at the user checkpoint.**

**Files:**
- Create: `docs/superpowers/notes/sncf-connect-endpoint.md`
- Create: `tests/fixtures/sncf_connect_search.json`

- [ ] **Step 1: Open SNCF Connect and run a real search**

Use the Playwright MCP tools:
1. `browser_navigate` to `https://www.sncf-connect.com/`
2. Accept cookies if prompted (`browser_snapshot` then `browser_click` the accept button).
3. Search a known cheap route with a near date inside J-30, e.g. Paris -> Lyon, next Saturday, "à partir de 18:00", 1 passenger, 2nd class. Use `browser_type` / `browser_click` / `browser_snapshot` to drive the form, matching the screenshot the user provided.
4. Land on the results page (the journey list with prices).

- [ ] **Step 2: Capture the underlying network request(s)**

Use `browser_network_requests` to list all requests made during the search. Identify the XHR/fetch call(s) that return the journey list with prices (look for JSON responses containing price values and departure/arrival times). For the matching request, record from `browser_network_request`:
- full URL (host + path + query),
- HTTP method,
- request headers (note any DataDome cookie, `x-` headers, `user-agent`, content-type),
- request body (the search payload),
- response body (the JSON journey list).

- [ ] **Step 3: Save a sanitized response fixture**

Write the JSON response body to `tests/fixtures/sncf_connect_search.json` verbatim (pretty-printed). Remove any session tokens / personal identifiers from the saved copy but keep the full journey/price structure intact. This file is the golden input for all parser tests.

- [ ] **Step 4: Test DataDome replayability with plain HTTP**

Try to reproduce the captured request from plain `httpx` (replay the exact method, URL, headers, and body) via a one-off `uv run python` snippet. Record the result:
- HTTP 200 with the same JSON shape -> **HTTP-REPLAYABLE**.
- 403 / challenge / DataDome HTML -> **BROWSER-REQUIRED**.
Try with and without the captured DataDome cookie to learn what's actually required.

- [ ] **Step 5: Build the station code map for priority stations**

Determine how the search payload references stations (place id / UIC / resarail code). Using the same site (autocomplete request or the search payload), resolve the SNCF Connect identifier for each station string the priority cities use, plus origins:
`PARIS (intramuros)`, `MASSY TGV`, `NICE VILLE`, `MONTPELLIER SAINT ROCH`, `MONTPELLIER SUD DE FRANCE`, `MARSEILLE ST CHARLES`, `AIX EN PROVENCE TGV`, `ANNECY`, `ST RAPHAEL VALESCURE`, `LES ARCS DRAGUIGNAN`, `LA ROCHELLE VILLE`.

- [ ] **Step 6: Write the endpoint contract note**

Create `docs/superpowers/notes/sncf-connect-endpoint.md` documenting, concretely:
- endpoint URL + method,
- required headers (and which are mandatory vs optional),
- request payload template with the fields that vary (origin code, destination code, date, time, class, passenger),
- response JSON paths to: each journey, its departure datetime, arrival datetime, cheapest 2nd-class price, carrier label, train number (if present),
- the DataDome verdict from Step 4 (HTTP-REPLAYABLE or BROWSER-REQUIRED),
- the station code map from Step 5 as a Python dict literal.

- [ ] **Step 7: Commit the artifacts**

```bash
git add docs/superpowers/notes/sncf-connect-endpoint.md tests/fixtures/sncf_connect_search.json
git commit -m "chore: spike SNCF Connect search endpoint contract + fixture"
```

- [ ] **Step 8: STOP — user checkpoint**

Report to the user: the endpoint contract, the DataDome verdict, and the resulting deployment implication:
- **HTTP-REPLAYABLE** -> proceed; shipped provider is plain `httpx`, VPS cron unaffected.
- **BROWSER-REQUIRED** -> flag that the shipped provider needs a headless browser (Chromium on the VPS, slower cron). Do **not** build the browser provider until the user approves that tradeoff.
Wait for the user before continuing to Task 2.

---

## Task 2: Test scaffolding

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Add pytest as a dev dependency**

```bash
uv add --dev pytest
```

- [ ] **Step 2: Create test discovery config**

Append to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
markers = [
    "live: hits the real SNCF Connect endpoint; deselected by default",
]
addopts = "-m 'not live'"
```

- [ ] **Step 3: Create a fixture loader in conftest**

Create `tests/conftest.py`:

```python
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sncf_search_response() -> dict:
    return json.loads((FIXTURES / "sncf_connect_search.json").read_text())
```

- [ ] **Step 4: Write a smoke test**

Create `tests/test_smoke.py`:

```python
def test_fixture_loads(sncf_search_response):
    assert isinstance(sncf_search_response, dict)
    assert sncf_search_response  # non-empty
```

- [ ] **Step 5: Run it**

Run: `uv run pytest tests/test_smoke.py -v`
Expected: PASS (1 passed).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock tests/conftest.py tests/test_smoke.py
git commit -m "test: add pytest scaffolding and SNCF Connect fixture loader"
```

---

## Task 3: `PricedJourney` and `PriceProvider`

**Files:**
- Create: `src/tgvmax_watch/pricing.py`
- Create: `tests/test_pricing_types.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pricing_types.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pricing_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tgvmax_watch.pricing'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/tgvmax_watch/pricing.py`:

```python
"""Live paid-fare lookup from SNCF Connect's internal search API.

The TGVmax open dataset has no prices. To surface cheap paid options for the
user's priority cities we query SNCF Connect directly. This module is the only
place that talks to a non-open-data SNCF endpoint; it is kept behind a narrow
PriceProvider interface so the transport (plain HTTP vs headless browser) can
change without touching the rest of the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pricing_types.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tgvmax_watch/pricing.py tests/test_pricing_types.py
git commit -m "feat: add PricedJourney and PriceProvider interface"
```

---

## Task 4: Response parser

**The structure is now KNOWN (Task 1 spike) — the code below matches the recorded fixture exactly.** Journeys live at `longDistance.proposals.proposals[]`. Per proposal: `travelId` = `"<ISO-local-datetime>_<trainNo>"` (e.g. `"2026-05-29T19:26_7805"`), `departure.timeLabel`/`arrival.timeLabel` = `"HH:MM"`, `transporterDescription` = `"Direct OUIGO"` / `"Direct TGV INOUI"` (strip leading `"Direct "`), price = **min** over `secondComfortClassOffers.offers[].priceLabel`. **Empty `offers` ⇒ train unavailable ⇒ skip.** Price labels are localized: non-breaking space (U+00A0) + comma decimal, e.g. `"32,80 €"`, `"55 €"`.

**Files:**
- Modify: `src/tgvmax_watch/pricing.py`
- Create: `tests/test_pricing_parser.py`

- [ ] **Step 1: Write the failing test against the recorded fixture**

Create `tests/test_pricing_parser.py`. The recorded fixture is the YOUNG Paris→Lyon response: 5 proposals, one OUIGO 19:26 with **no offers** (must be skipped), the rest priced (TGV INOUI 19:27 → 55€, etc.). So a correct parser yields **4** journeys, all with `price_eur > 0`.

```python
from datetime import date

import pytest

from tgvmax_watch.pricing import PricedJourney, parse_journeys, _parse_price_label


@pytest.mark.parametrize("label,expected", [
    ("55 €", 55.0),
    ("32,80 €", 32.80),
    ("16 €", 16.0),
    ("74 €", 74.0),
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
        assert j.price_eur > 0.0                      # unavailable trains dropped
        assert len(j.dep) == 5 and j.dep[2] == ":"    # HH:MM
        assert len(j.arr) == 5 and j.arr[2] == ":"
        assert j.carrier in {"OUIGO", "TGV INOUI", "OUIGO TRAIN CLASSIQUE", "INTERCITES"}


def test_parse_takes_cheapest_offer_and_train_no(sncf_search_response):
    journeys = parse_journeys(
        sncf_search_response, "PARIS (intramuros)", "LYON (intramuros)", date(2026, 5, 29))
    ouigo_2056 = next(j for j in journeys if j.dep == "20:56")
    assert ouigo_2056.carrier == "OUIGO"
    assert ouigo_2056.train_no == "7815"
    assert ouigo_2056.price_eur == 65.0   # min of ["74 €", "65 €"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pricing_parser.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_journeys'`.

- [ ] **Step 3: Implement the parser**

Add to `src/tgvmax_watch/pricing.py`:

```python
import re


def _parse_price_label(label: str) -> float:
    """'32,80 €' / '55 €' (non-breaking space, comma decimal) -> float EUR."""
    cleaned = label.replace(" ", " ").replace("€", "").strip().replace(",", ".")
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
) -> list["PricedJourney"]:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pricing_parser.py -v`
Expected: PASS (7 passed: 4 parametrized + 3 behavior).

- [ ] **Step 5: Commit**

```bash
git add src/tgvmax_watch/pricing.py tests/test_pricing_parser.py
git commit -m "feat: parse SNCF Connect search responses into PricedJourney"
```

---

## Task 5: `SncfConnectProvider.search()` (Playwright browser session)

**Task 1 verdict: BROWSER-REQUIRED** (httpx → 403 DataDome; in-page `fetch` → 200). The provider drives a headless Playwright/Chromium session: launch once, navigate to sncf-connect.com to establish a DataDome session, then issue each search as an in-page `fetch()`. All endpoint/header/payload/station-code values below are the concrete captured values from `docs/superpowers/notes/sncf-connect-endpoint.md`. Use the provider as a context manager so the browser is opened once and reused across the whole sweep (Task 10), not per search.

**Files:**
- Modify: `src/tgvmax_watch/pricing.py`
- Create: `tests/test_pricing_provider.py`

- [ ] **Step 1: Add the playwright dependency**

```bash
uv add playwright
uv run playwright install chromium
```

- [ ] **Step 2: Write the failing unit tests (pure body-builder, offline)**

The browser call itself is only testable live (Step 5). The pure, deterministic seam is `_build_body` + the station map; test those offline. Create `tests/test_pricing_provider.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_pricing_provider.py -v`
Expected: FAIL with `ImportError: cannot import name '_build_body'`.

- [ ] **Step 4: Implement the provider (Playwright browser session)**

Add to `src/tgvmax_watch/pricing.py`. All constants are the captured Task 1 values.

```python
import random
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

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
    """PriceProvider backed by SNCF Connect via a headless Playwright session.

    DataDome blocks plain server-side requests, so we launch Chromium once,
    establish a session on the homepage, then issue each search as an in-page
    fetch. Use as a context manager (or call close()) so the browser is released.
    """

    def __init__(self, delay_range: tuple[float, float] = (1.5, 4.0), headless: bool = True) -> None:
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
        self._browser = self._pw.chromium.launch(headless=self._headless)
        self._page = self._browser.new_page(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
        )
        self._page.goto(HOME_URL, wait_until="domcontentloaded")
        self._page.wait_for_timeout(2500)  # let DataDome set its cookie

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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_pricing_provider.py -v`
Expected: PASS (4 passed). These cover the pure logic; the browser path is exercised live in Step 6.

- [ ] **Step 6: Add a live integration test (deselected by default)**

Append to `tests/test_pricing_provider.py`:

```python
@pytest.mark.live
def test_live_search_returns_real_prices():
    from datetime import timedelta
    day = date.today() + timedelta(days=7)
    with SncfConnectProvider() as provider:
        journeys = provider.search("PARIS (intramuros)", "LYON (intramuros)", day, ("06:00", "23:59"))
    assert journeys
    assert any(j.price_eur > 0 for j in journeys)
```

Run (manual, opt-in): `uv run pytest tests/test_pricing_provider.py -m live -v`
Expected: PASS — this is the real DataDome-passing confirmation. Not in the default suite.

- [ ] **Step 7: Commit**

```bash
git add src/tgvmax_watch/pricing.py tests/test_pricing_provider.py pyproject.toml uv.lock
git commit -m "feat: SncfConnectProvider via Playwright browser session"
```

---

## Task 6: Add `price_eur` to `Train`

**Files:**
- Modify: `src/tgvmax_watch/api.py:20-42`
- Create: `tests/test_train_price.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_train_price.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_train_price.py -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'price_eur'`.

- [ ] **Step 3: Add the field**

In `src/tgvmax_watch/api.py`, add the field at the end of the `Train` dataclass (after `axe: str`):

```python
    axe: str
    price_eur: float | None = None  # None = free Max Jeune seat; float = paid fare (EUR)
```

`from_record` is unchanged — it never sets `price_eur`, so it defaults to `None`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_train_price.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/tgvmax_watch/api.py tests/test_train_price.py
git commit -m "feat: add optional price_eur to Train"
```

---

## Task 7: Config — `max_paid_price` and `paid_lookup_min_weight`

**Files:**
- Modify: `src/tgvmax_watch/config.py:29-59`
- Modify: `cities.yaml:11-13` (top-level, near `origins`)
- Create: `tests/test_config_paid.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_paid.py`:

```python
from tgvmax_watch import config as cfgmod


def test_paid_config_defaults_and_load(tmp_path):
    yaml_text = (
        "origins:\n  paris:\n    - \"PARIS (intramuros)\"\n"
        "max_paid_price: 30\n"
        "paid_lookup_min_weight: 80\n"
        "cities:\n"
        "  - name: Nice\n    region: south\n    stations: [\"NICE VILLE\"]\n    base_weight: 100\n"
        "scheduling:\n"
        "  south:\n    friday_out_windows: [[\"18:00\",\"23:00\"]]\n"
        "    saturday_out_windows: [[\"06:00\",\"12:00\"]]\n"
        "    return_windows: [[\"06:00\",\"11:00\"]]\n"
    )
    p = tmp_path / "c.yaml"
    p.write_text(yaml_text)
    cfg = cfgmod.load(p)
    assert cfg.max_paid_price == 30.0
    assert cfg.paid_lookup_min_weight == 80
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config_paid.py -v`
Expected: FAIL with `AttributeError: 'Config' object has no attribute 'max_paid_price'`.

- [ ] **Step 3: Add the fields to `Config` and `load`**

In `src/tgvmax_watch/config.py`, extend the `Config` dataclass:

```python
@dataclass(frozen=True)
class Config:
    origins: tuple[str, ...]
    cities: tuple[City, ...]
    scheduling: dict[str, Scheduling] = field(default_factory=dict)
    max_paid_price: float = 30.0
    paid_lookup_min_weight: int = 80
```

In `load()`, change the final return to read the optional top-level keys:

```python
    return Config(
        origins=origins,
        cities=cities,
        scheduling=scheduling,
        max_paid_price=float(raw.get("max_paid_price", 30.0)),
        paid_lookup_min_weight=int(raw.get("paid_lookup_min_weight", 80)),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config_paid.py -v`
Expected: PASS.

- [ ] **Step 5: Add the keys to the real `cities.yaml`**

In `cities.yaml`, immediately after the `origins:` block (before the priority-tier comment), add:

```yaml
# Paid-train discovery (SNCF Connect). Only priority cities (base_weight >= the
# threshold) get live price lookups; paid trains above max_paid_price are dropped.
max_paid_price: 30
paid_lookup_min_weight: 80
```

- [ ] **Step 6: Confirm the real config still loads**

Run: `uv run python -c "from tgvmax_watch import config; c=config.load('cities.yaml'); print(c.max_paid_price, c.paid_lookup_min_weight)"`
Expected: `30.0 80`

- [ ] **Step 7: Commit**

```bash
git add src/tgvmax_watch/config.py cities.yaml tests/test_config_paid.py
git commit -m "feat: add max_paid_price and paid_lookup_min_weight config"
```

---

## Task 8: Conversion helpers — `priced_to_train()` and `priority_cities()`

**Files:**
- Modify: `src/tgvmax_watch/pricing.py`
- Create: `tests/test_pricing_convert.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pricing_convert.py`:

```python
from datetime import date

from tgvmax_watch.config import City, Config, Scheduling
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pricing_convert.py -v`
Expected: FAIL with `ImportError: cannot import name 'priced_to_train'`.

- [ ] **Step 3: Implement the helpers**

Add to `src/tgvmax_watch/pricing.py`:

```python
from .api import Train
from .config import City, Config


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pricing_convert.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/tgvmax_watch/pricing.py tests/test_pricing_convert.py
git commit -m "feat: PricedJourney->Train conversion and priority-city selection"
```

---

## Task 9: Ranking — `total_price` and price penalty

**Files:**
- Modify: `src/tgvmax_watch/ranker.py:11-17` (Pairing) and `:19-78` (`_score_pair`) and `:115-127` (construction)
- Create: `tests/test_ranker_price.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ranker_price.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ranker_price.py -v`
Expected: FAIL with `ImportError: cannot import name 'total_price'`.

- [ ] **Step 3: Add `total_price` and the penalty**

In `src/tgvmax_watch/ranker.py`, add a `total_price` field to `Pairing`:

```python
@dataclass(frozen=True)
class Pairing:
    city: City
    out: Journey
    back: Journey
    score: float
    total_price: float | None = None
```

Add a module-level helper (near `_to_min`):

```python
def total_price(out: Journey, back: Journey) -> float | None:
    """Sum of paid legs in EUR; None if both legs are free Max Jeune seats."""
    prices = [j.train.price_eur for j in (out, back) if j.train.price_eur is not None]
    return sum(prices) if prices else None
```

In `_score_pair`, just before `return s`, apply the penalty:

```python
    # paid trains compete with free ones but pay a price penalty (free legs add 0)
    tp = total_price(out, back)
    if tp is not None:
        s -= tp / 2

    return s
```

In `rank_weekend`, set `total_price` when building each `Pairing`:

```python
                scored.append(Pairing(city, o, b, score, total_price(o, b)))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ranker_price.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/tgvmax_watch/ranker.py tests/test_ranker_price.py
git commit -m "feat: rank paid pairings with a price penalty"
```

---

## Task 10: Wire paid lookups into the sweep

**Files:**
- Modify: `src/tgvmax_watch/main.py:13-44` (`cmd_sweep`) and `:57-68` (argparse)
- Create: `src/tgvmax_watch/paidsweep.py` (the fault-tolerant gather loop, kept out of main for testability)
- Create: `tests/test_paidsweep.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_paidsweep.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_paidsweep.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tgvmax_watch.paidsweep'`.

- [ ] **Step 3: Implement the gather loop**

Create `src/tgvmax_watch/paidsweep.py`:

```python
"""Fault-tolerant paid-fare gathering for priority cities.

Queries the PriceProvider for each priority city x weekend x direction, keeps
only journeys priced 0 < price <= max_paid_price, and returns them already
converted into Train objects ready to merge into the free sweep's lists. Any
provider failure for one (city, day, direction) is logged and skipped — the
sweep must never fail because of paid lookups.
"""

from __future__ import annotations

import sys

from .config import Config
from .pricing import PriceProvider, priced_to_train, priority_cities
from .routing import Weekend


def _windows_for(cfg: Config, region: str):
    sched = cfg.scheduling.get(region) or next(iter(cfg.scheduling.values()))
    return sched


def gather_paid_trains(
    cfg: Config, weekends: list[Weekend], provider: PriceProvider
):
    """Return (out_trains, back_trains) of cheap paid Train objects."""
    out_trains = []
    back_trains = []
    origin = cfg.origins[0]  # primary Paris origin for paid lookups
    for city in priority_cities(cfg):
        sched = _windows_for(cfg, city.region)
        for wk in weekends:
            for station in city.stations:
                # OUTBOUND: Paris -> city, Fri evening and Sat morning
                for day, windows in ((wk.friday, sched.friday_out_windows),
                                     (wk.saturday, sched.saturday_out_windows)):
                    for window in windows:
                        out_trains += _safe_search(provider, origin, station, day, window, cfg)
                # RETURN: city -> Paris, Sat and Sun, within return windows
                for day in (wk.saturday, wk.sunday):
                    for window in sched.return_windows:
                        back_trains += _safe_search(provider, station, origin, day, window, cfg)
    return out_trains, back_trains


def _safe_search(provider, origin, destination, day, window, cfg: Config):
    try:
        journeys = provider.search(origin, destination, day, window)
    except Exception as e:  # noqa: BLE001 — never let a paid lookup break the sweep
        print(f"[paid] search failed {origin}->{destination} {day} {window}: {e}", file=sys.stderr)
        return []
    kept = [j for j in journeys if 0 < j.price_eur <= cfg.max_paid_price]
    return [priced_to_train(j) for j in kept]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_paidsweep.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Wire into `cmd_sweep` and add CLI flags**

In `src/tgvmax_watch/main.py`, add imports at the top:

```python
from . import api, config as cfgmod, notify, paidsweep, pricing, ranker, report, routing
```

In `cmd_sweep`, after the two `api.fetch_oui` calls and their prints (after line 28), before the per-weekend loop, add:

```python
    if not args.no_paid:
        if args.max_paid_price is not None:
            cfg = cfgmod.replace_max_paid_price(cfg, args.max_paid_price)
        try:
            with pricing.SncfConnectProvider() as provider:   # launches Chromium once
                paid_out, paid_back = paidsweep.gather_paid_trains(cfg, weekends, provider)
            print(f"[sweep] paid outbound trains <= {cfg.max_paid_price}EUR: {len(paid_out)}", file=sys.stderr)
            print(f"[sweep] paid return   trains <= {cfg.max_paid_price}EUR: {len(paid_back)}", file=sys.stderr)
            out_trains += paid_out
            back_trains += paid_back
        except Exception as e:  # noqa: BLE001 — browser/DataDome failure must not kill the sweep
            print(f"[sweep] paid lookup unavailable, continuing free-only: {e}", file=sys.stderr)
```

The outer `try` covers browser launch / DataDome failures; `gather_paid_trains` already swallows per-search errors internally (Task 10 gather loop). Either way the free sweep is never blocked.

Add the argparse flags to the `sweep` parser (after `--no-notify`):

```python
    s.add_argument("--no-paid", action="store_true",
                   help="Skip SNCF Connect paid-price lookups (free TGVmax only).")
    s.add_argument("--max-paid-price", type=float, default=None,
                   help="Override cities.yaml max_paid_price (EUR).")
```

- [ ] **Step 6: Add the config override helper**

In `src/tgvmax_watch/config.py`, add at module level:

```python
import dataclasses


def replace_max_paid_price(cfg: Config, value: float) -> Config:
    return dataclasses.replace(cfg, max_paid_price=value)
```

- [ ] **Step 7: Verify the sweep runs with paid lookups disabled (offline-safe)**

Run: `uv run tgvmax-watch sweep --no-paid --stdout --horizon-days 30 >/dev/null`
Expected: exits 0, behaves exactly as today (paid path skipped).

- [ ] **Step 8: Commit**

```bash
git add src/tgvmax_watch/paidsweep.py src/tgvmax_watch/main.py src/tgvmax_watch/config.py tests/test_paidsweep.py
git commit -m "feat: gather cheap paid trains for priority cities in the sweep"
```

---

## Task 11: Report — show price on paid pairings

**Files:**
- Modify: `src/tgvmax_watch/report.py:146-161` (`_compact_line`) and `:209-245` (verbose)
- Create: `tests/test_report_price.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_price.py`:

```python
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
    # the free line should not carry a paid-price marker
    assert "€" not in text.split("```")[1].splitlines()[2]  # the option line
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_report_price.py -v`
Expected: FAIL (price not rendered yet).

- [ ] **Step 3: Render the price in the compact line**

In `src/tgvmax_watch/report.py`, add a helper near `_extra_cost`:

```python
def _price_tag(p: Pairing) -> str:
    """' · 30€' for a paid pairing, '' for a free one."""
    if p.total_price is None:
        return ""
    return f" · {p.total_price:.0f}€"
```

In `_compact_line`, include it in the returned string (append `{_price_tag(p)}` right after the `extra` segment):

```python
    price = _price_tag(p)
    return (
        f"{idx:>2}  {_city_label(p.city):<{max_city_width}}  "
        f"{_wd(out_t.date)} {out_t.dep} → {_wd(back_t.date)} {back_t.dep}   "
        f"{on_site} on · {_ride_hm(total_ride)} ride{price}{extra}{via}{via_back}"
    )
```

In `render_verbose`, add the price to the per-option block. Change the score line to include it:

```python
            price = f" · {p.total_price:.0f}€ paid" if p.total_price is not None else " · TGVmax (free)"
            parts.append(
                f"{i}. {star} **{p.city.name}** — score {p.score:.0f}{price}\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_report_price.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/tgvmax_watch/report.py tests/test_report_price.py
git commit -m "feat: show paid-train prices in compact and verbose reports"
```

---

## Task 12: End-to-end local verification (no VPS)

**Files:** none modified — verification + tuning only.

- [ ] **Step 1: Capture the current free-only output as a baseline**

Run: `uv run tgvmax-watch sweep --no-paid --stdout --horizon-days 30 > /tmp/free_only.md`
Expected: exits 0.

- [ ] **Step 2: Run the full sweep with paid lookups (live)**

Run: `uv run tgvmax-watch sweep --stdout --horizon-days 30 --no-notify > /tmp/with_paid.md`
Expected: exits 0. If DataDome blocks live requests, the `[paid] search failed` lines appear and the report still renders (free-only) — confirming fault tolerance. If so, STOP and report to the user (this is the BROWSER-REQUIRED branch surfacing in practice).

- [ ] **Step 3: Diff and sanity-check**

Run: `diff /tmp/free_only.md /tmp/with_paid.md`
Confirm: paid options appear only for priority cities, all carry a `NN€` tag, none exceed `max_paid_price`, and free options still rank above equivalent paid ones. Eyeball that the price penalty (`/2`) produces sensible ordering; note any tuning the user might want (the divisor is the knob).

- [ ] **Step 4: Final suite + summary**

Run: `uv run pytest -v`
Expected: all non-live tests PASS.

Report to the user: what the live run produced, whether DataDome cooperated, and the suggested price-penalty tuning. **Do not touch the VPS.** Branch `feat/cheap-paid-trains` stays unmerged until the user decides.

---

## Self-review notes

- **Spec coverage:** search-based architecture (Tasks 1,5), `pricing.py`+`PriceProvider` (Task 3), all-carriers (parser keeps any carrier, Task 4), `<=30` threshold (Tasks 7,10), price penalty/can-compete (Task 9), always-priority-cities trigger (Tasks 8,10), data-model `price_eur`/`total_price` (Tasks 6,9), report tag (Task 11), throttling+fault-tolerance (Tasks 5,10), spike-first+DataDome verdict+VPS-untouched (Tasks 1,12). All covered.
- **Reverse-engineering caveat:** Tasks 4 and 5 contain concrete code against the documented contract shape, with an explicit instruction to reconcile JSON paths / URL / headers / station codes against the Task 1 fixture and note. This is inherent to reverse-engineering a closed API and is gated by the Task 1 user checkpoint.
- **Type consistency:** `PricedJourney` fields (Task 3) are reused verbatim in Tasks 4,5,8,10. `Train.price_eur` (Task 6) is read in Tasks 8,9. `Pairing.total_price` (Task 9) is read in Task 11. `priority_cities`/`priced_to_train` (Task 8) used in Task 10. `replace_max_paid_price` (Task 10 Step 6) used in Task 10 Step 5.
```
