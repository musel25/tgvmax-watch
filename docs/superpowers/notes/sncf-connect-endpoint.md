# SNCF Connect endpoint contract (Task 1 spike)

Captured live 2026-05-29 by driving sncf-connect.com with a real browser.

## DataDome verdict: HEADED BROWSER REQUIRED

- Plain `httpx` POST → **403** with `x-datadome: protected` and a
  `geo.captcha-delivery.com` captcha URL. Server-side replay is blocked.
- **Headless Chromium is ALSO blocked** (verified): even the homepage GET returns
  403 and stays on the bare interstitial (title `sncf-connect.com`). Clearing
  `navigator.webdriver` via `--disable-blink-features=AutomationControlled` is not
  enough on its own.
- **Headed Chromium works** (verified): DataDome's JS challenge resolves, the real
  homepage loads (title contains `Réservez`), and subsequent in-page `fetch()` calls
  to the BFF return **200**.

**Shipped design (implemented in `pricing.py::SncfConnectProvider`):** launch
**headed** Chromium once (`headless=False`, arg
`--disable-blink-features=AutomationControlled`), `goto` the homepage, **poll until
the challenge resolves** (title contains `Réservez`, ~3 s; not a fixed sleep), then
fire all searches as cheap in-page `fetch()` via `page.evaluate(...)` — no page
reload per search; one session covers many searches.

**VPS implication (deferred — not deployed yet):** headed Chromium needs a display.
Locally `DISPLAY` exists. On the headless VPS the cron must run under a virtual
framebuffer (`xvfb-run -a tgvmax-watch sweep ...`, install `xvfb` + the Playwright
Chromium deps). This is heavier than the current pure-`httpx` cron and is the
concrete cost of the no-scraping-rule override. Flag to the user before deploying.

## Search endpoint

`POST https://www.sncf-connect.com/bff/api/v1/itineraries`

### Required headers (minimal working set, confirmed)

```
content-type: application/json
accept: application/json, text/plain, */*
x-bff-key: ah1MPO-izehIHD-QZZ9y88n-kku876   # static frontend key; may rotate with x-app-version (was 48d2c6fc70)
x-client-app-id: front-web
x-api-env: production
x-market-locale: fr_FR
x-client-channel: web
x-device-class: desktop
```

The `datadome` cookie is supplied automatically by the browser session — do NOT
send it manually.

### Request body (exact shape matters — a trimmed body returns 400)

```json
{
  "schedule": {"outward": {"date": "2026-05-29T16:00:00.000Z", "arrivalAt": false}},
  "mainJourney": {
    "origin":      {"label":"Paris","id":"CITY_FR_6455259","codes":[{"type":"RESARAIL","value":"FRPAR"},{"type":"RESARAIL","value":"FRPAR"}],"geolocation":false,"resarailCode":"FRPAR","city":"Paris"},
    "destination": {"label":"Lyon","id":"CITY_FR_6454573","codes":[{"type":"RESARAIL","value":"FRLYS"},{"type":"RESARAIL","value":"FRLYS"}],"geolocation":false,"resarailCode":"FRLYS","city":"Lyon"}
  },
  "passengers": [{"id":"<uuid>","discountCards":[{"code":"YOUNG_PASS","label":"Carte Avantage Jeune","selected":true}],"typology":"YOUNG","displayName":"4 - 29 ans","age":25,"withoutSeatAssignment":false,"hasDisability":false,"hasWheelchair":false}],
  "pets": [],
  "itineraryId": "<uuid>",
  "forceDisplayResults": true,
  "trainExpected": true,
  "wishBike": false,
  "strictMode": false,
  "directJourney": false,
  "transporterLabels": [],
  "metadataY": {},
  "userNavigation": ["IS_NOT_BUSINESS"]
}
```

Notes:
- `schedule.outward.date` is **UTC** with `Z`. Paris local must be converted
  (CEST = UTC+2 in summer, CET = UTC+1 in winter). `arrivalAt:false` = "depart at".
- `codes` array having two identical RESARAIL entries mirrors the live frontend;
  keep it (a single-entry body still returned 400 in testing — keep the captured
  shape).
- `itineraryId` / passenger `id` are client-generated UUIDs.
- **Passenger profile (DECIDED 2026-05-29): YOUNG + Carte Avantage Jeune.**
  `typology:"YOUNG"`, `displayName:"4 - 29 ans"`, integer `age` (we send e.g. 25),
  and `discountCards:[{"code":"YOUNG_PASS","label":"Carte Avantage Jeune","selected":true}]`.
  This gives the capped youth fares (Carte Avantage Jeune caps weekend long-distance
  2nd class — e.g. Paris→Lyon came back at 32,80 € vs 79 € for ADULT).
  - Caveat: this assumes the user holds a Carte Avantage Jeune (a separate ~49 €/yr
    card, distinct from the Max Jeune subscription). The card is configurable; the
    other selectable card in the UI is `MAX JEUNE` if we ever want that instead.

### Price label parsing (IMPORTANT)

`priceLabel` and `bestPrices[].priceLabel` are localized French strings using a
**non-breaking space (U+00A0)** before `€` and a **comma decimal separator**:
`"55 €"`, `"32,80 €"`, `"16 €"`. Parse by: strip non-digit/comma, replace `,` with
`.`, `float(...)`. Do NOT assume a regular space or a dot decimal.

### Pagination / coverage caveat

One call returns only ~3 proposals clustered around the requested departure time
(`longDistance.proposals.pagination.next` is a cursor for more). To cover a whole
window (e.g. Saturday 06:00-12:00) we must either page via `next` or issue a few
calls at stepped start times. `bestPrices` (below) gives the cheapest price per day
across all trains and can pre-filter which days are even worth paging.

## Response structure

Root: `longDistance.proposals`

- `longDistance.proposals.proposals[]` — one entry per train:
  - `travelId`: `"2026-05-29T19:26_7805"` → **local departure datetime + train number** (split on `_`).
  - `departure.timeLabel` `"19:26"`, `departure.originStationLabel`.
  - `arrival.timeLabel` `"21:26"`, `arrival.destinationStationLabel`.
  - `transporterDescription`: `"Direct OUIGO"` / `"Direct TGV INOUI"` → carrier (strip leading `Direct `).
  - `secondComfortClassOffers.offers[]`: each has `priceLabel` (`"74 €"`), `comfortClass`, `type`.
    - **Per-train price = min over offers' `priceLabel`** (parse `"74 €"` → `74.0`).
    - **Empty `offers` = train unavailable / sold out → skip it.**
- `longDistance.proposals.bestPrices[]` — per-day cheapest calendar:
  `{label:"Sam 30", priceLabel:"45 €", bestPriceDateTime:"2026-05-30T19:26:00", departureDay:bool}`.

Recorded sample (real, Paris→Lyon, YOUNG + Carte Avantage Jeune): TGV INOUI 19:27 →
`55 €`, TGV INOUI 19:59 → `56 €`, OUIGO 20:56 → min `65 €`, TGV INOUI 21:00 → `55 €`;
OUIGO 19:26 → no offers (past/unavailable). bestPrices day calendar capped at
`32,80 €` for the near weekend.

Full recorded response saved at `tests/fixtures/sncf_connect_search.json` (golden
parser input) — this is the **YOUNG + Carte Avantage Jeune** response, matching the
shipping config.

## Autocomplete endpoint (station-code resolution)

`POST https://www.sncf-connect.com/bff/api/v1/autocomplete`
Body: `{"searchTerm":"Nice","keepStationsOnly":false,"returnsSuggestions":false}`
Response: `places.transportPlaces[]`, each with `id`, `label`, `type.placeType`
(`CITY`|`STATION`), `codes[]` (RESARAIL / UIC7 / UIC8 / NAVITIA_ID).
Same headers as the search endpoint; same browser-session requirement.

## Station code map (dataset station string → SNCF Connect place)

Resolved live. For the itineraries body, use the place's `id` + `resarailCode`.
Origins use Paris CITY; destinations use the STATION matching the dataset string
(city-level shown for reference).

| Dataset station | placeType | id | RESARAIL |
|---|---|---|---|
| `PARIS (intramuros)` | CITY | `CITY_FR_6455259` | `FRPAR` |
| `MASSY TGV` | STATION | `RESARAIL_STA_8739370` | `FRDJU` |
| `NICE VILLE` | STATION | `RESARAIL_STA_8775605` | `FRNIC` (city `FRNCE`) |
| `MONTPELLIER SAINT ROCH` | STATION | `RESARAIL_STA_8777300` | `FRMPL` |
| `MONTPELLIER SUD DE FRANCE` | STATION | `RESARAIL_STA_8768888` | `FRSUF` |
| `MARSEILLE ST CHARLES` | STATION | `RESARAIL_STA_8775100` | `FRMSC` (city `FRMRS`) |
| `AIX EN PROVENCE TGV` | STATION | `RESARAIL_STA_8731901` | `FRAIE` |
| `ANNECY` | STATION | `RESARAIL_STA_8774600` | `FRNCY` |
| `ST RAPHAEL VALESCURE` | STATION | `RESARAIL_STA_8775752` | `FRXSK` |
| `LES ARCS DRAGUIGNAN` | STATION | `RESARAIL_STA_8775544` | `FRXRS` |
| `LA ROCHELLE VILLE` | STATION | `RESARAIL_STA_8748500` | `FRLRH` |
| `LYON (intramuros)` (ref) | CITY | `CITY_FR_6454573` | `FRLYS` |

## Risks / things that can break

- `x-bff-key` and `x-app-version` may rotate; if searches start 400/401-ing, re-capture.
- DataDome session/cookie expires — the browser session must be refreshed periodically.
- Body schema can change (a trimmed body already 400s). Keep the captured shape.
- DataDome may escalate to a visible captcha if traffic looks botty → throttle, reuse one session, randomize timing.
