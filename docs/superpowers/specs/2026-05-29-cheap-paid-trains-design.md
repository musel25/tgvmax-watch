# Cheap paid-train discovery

Date: 2026-05-29
Branch: `feat/cheap-paid-trains`
Status: design approved, awaiting spec review

## Problem

The tool today only surfaces *free* Max Jeune seats: it pulls the SNCF Open Data
`tgvmax` dataset and keeps trains where `od_happy_card == "OUI"`. When a popular
weekend sells out its free quota for a priority city, that city simply vanishes
from the report — even though a paid ticket to the same city may still be cheap
(the user is fine paying up to ~30 EUR if the trip is worth it).

We want to surface those cheap paid options *alongside* the free ones, so a
sold-out-of-free weekend becomes a "cheap paid" option instead of a blank.

## Why this is fundamentally different from past changes

Every prior tuning request lived inside `ranker.py` and stayed entirely within the
open dataset. This one cannot: **the `tgvmax` open dataset has no price field.** Its
only availability signal is `od_happy_card` (OUI/NON). Confirmed by inspecting the
`Train` schema in `api.py` and the full SNCF Open Data catalog (166 datasets):

- `tarifs-tgv-inoui-ouigo` exists but gives only a **static min/max band per
  origin-destination** (e.g. OUIGO Paris->Lyon = 16-99 EUR). It cannot identify
  that a *specific* Saturday train is 45 EUR. Useless for per-train decisions.
- The official SNCF/Navitia API (`api.sncf.com`) exposes schedules and *published*
  fares, not live yield-managed prices.
- Live per-train prices (the 45/51/69 EUR seen when booking) exist **only** in the
  SNCF Connect / OUIGO booking backend. No official API.

SNCF made a deliberate split: **availability is open data, pricing is not.** The
current tool sits entirely on the open side of that line. Getting real prices means
crossing to the booking backend unofficially.

This overrides the standing `CLAUDE.md` rule "Never replace it with
Playwright/scraping unless the user explicitly asks." The user explicitly authorized
the SNCF Connect route for this work on 2026-05-29.

## Decisions (locked with the user, 2026-05-29)

| Decision | Choice |
|---|---|
| Goal | Discover **new** cheap paid trains for priority cities and show them alongside free options — not just label existing free trains. A sold-out-of-free weekend becomes a cheap-paid option; a weekend with a poorly-timed free train can also surface a better-timed cheap-paid one. |
| Price threshold | `<= 30 EUR` (2nd class), global, configurable. |
| Ranking | Price-penalized but **can compete side-by-side** with free trains. |
| When to fetch prices | **Always, for the 8 priority cities, every weekend** — regardless of free availability. Paid and free are ranked together. Throttled to limit DataDome exposure. |
| Carriers | **All** — TGV INOUI, OUIGO, OUIGO Train Classique, Intercites. (OUIGO Grande Vitesse is often cheapest and is *not* in the `tgvmax` dataset at all.) |
| Deployment | Branch only. **Nothing on the VPS** until the user approves the result. |

The 8 priority cities are those with explicit `base_weight` priority in `cities.yaml`
(currently Nice, Montpellier, Marseille, Aix-en-Provence, Annecy, Saint-Tropez, La
Rochelle, plus the standing priority list). The spec scopes paid lookups to these.

## Architecture

### Approach chosen: search-based

For each priority city x weekend x direction, issue **one** journey-search request
to SNCF Connect. A single search returns *all* trains for that route+date with their
cheapest 2nd-class price, mirroring the booking page in the user's screenshot. This:

- catches OUIGO Grande Vitesse (invisible to the `tgvmax` dataset),
- is fewer requests than pricing trains one at a time,
- returns the live price directly.

Rejected alternative — "price the NON set": take trains already in the `tgvmax`
dataset marked `NON` and price each. Misses all non-Max carriers (OUIGO GV), and is
more requests (one per train). Not chosen.

### New module: `pricing.py`

A narrow interface so the fetch mechanism can change without touching the rest:

```python
@dataclass(frozen=True)
class PricedJourney:
    date: date
    train_no: str
    origin: str
    destination: str
    dep: str          # "HH:MM"
    arr: str
    carrier: str      # "TGV INOUI" | "OUIGO" | "OUIGO TRAIN CLASSIQUE" | "INTERCITES"
    price_eur: float  # cheapest 2nd-class fare; 0.0 means a free Max seat was found

class PriceProvider(Protocol):
    def search(self, origin: str, destination: str, day: date,
               window: tuple[str, str]) -> list[PricedJourney]: ...
```

First concrete implementation targets the SNCF Connect BFF JSON endpoint. If that is
blocked (see Risk), a headless-browser implementation behind the same `Protocol` is
the fallback.

### Data flow (parallel path, additive)

```
existing free sweep (api.fetch_oui)  ----------------+
                                                     |
for each priority city:                              |
  for each weekend in window:                        |
    for each direction (out / back):                 v
      pricing.search(...) -> PricedJourney[]    merge -> routing -> ranker -> report
        keep 0 < price <= max_paid_price
```

1. Run the existing free sweep unchanged.
2. For each priority city, each weekend in the rolling window, query paid prices for
   the outbound leg (within `friday_out_windows` / `saturday_out_windows`) and the
   return leg.
3. Keep journeys with `0 < price_eur <= max_paid_price`. Drop any that come back at
   `0` (already free — the free sweep owns those).
4. Convert kept journeys into the same train representation routing/ranking consume,
   carrying their price.
5. Pair cheap outbound + cheap return per city per weekend (reuse existing routing
   pairing logic).
6. Merge free + paid pairings and rank them together.

### Data model change

Add an optional price to the existing pairing/train representation:

- `Train` (or a thin paid variant) gains `price_eur: float | None` — `None` for
  open-dataset free trains, a float for priced ones.
- `Pairing` gains `total_price: float | None` (sum of the two legs; `None` if both
  legs are free).

Routing and the report treat `None` as "free" and otherwise show the price. Keeping
one model avoids a parallel pairing type.

### Ranking (`ranker.py::_score_pair`)

Paid pairings go through the **same** hard outbound-window filter, `_is_valid_pair`
floor, and on-site-hours scoring as free ones. Then:

- Add a **price penalty**: `score -= total_price / 2` (tunable; 30 EUR -> -15).
  Free pairings have `total_price is None` -> penalty 0.

Effect: a free train keeps its edge over an equivalent paid one, but a cheap,
well-timed paid train can outrank a free train with worse timing or shorter on-site
hours. This is the user's "price-penalized, can compete" choice.

The divisor is a starting point; tune after seeing real output (same before/after
diff discipline as any ranker change).

### Config (`cities.yaml`)

Add to the scheduling block:

```yaml
scheduling:
  max_paid_price: 30        # EUR, 2nd class; paid trains above this are dropped
```

Per-city override (`max_paid_price` on a city) is a possible later extension; not in
this iteration (YAGNI).

### Report (`report.py`)

Paid pairings appear inline in the same ranked list, tagged with their total price
(e.g. `28 EUR`); free pairings render as they do today (no price tag, or `0 EUR`).
Free remains visually distinguishable. Exact layout decided during implementation to
match the existing compact message style.

## Risk: DataDome / endpoint feasibility

The documented `oui.sncf/proposition/...` endpoint is **deprecated** (oui.sncf became
sncf-connect.com in 2022). The current site uses an internal BFF JSON API protected
by DataDome bot-detection. Whether a plain server-side HTTP request gets through is
unknown and is the single biggest risk.

**Implementation step 1 is a throwaway spike**: hit the current endpoint for one
route/date and confirm we can read prices. Two outcomes:

- **Works from plain HTTP** -> build the lightweight `httpx`-based `PriceProvider`.
  Best fit for the eventual VPS cron (synchronous, no browser).
- **Blocked by DataDome** -> fall back to a headless-browser `PriceProvider`
  (Playwright) to mint a valid token or read the rendered page. Heavier; its VPS
  implications (Chromium install, runtime, cron timing) get flagged to the user
  before anything is built on it.

The `PriceProvider` Protocol means the rest of the system is identical either way.

### Request volume / throttling

"Always, priority cities" is roughly: 8 cities x ~4-5 weekends x 2 directions x ~1-2
candidate days ~= 100-160 searches per sweep. Mitigations:

- Sequential requests with a small randomized delay between them.
- Cache within a sweep (don't re-search the same OD+date).
- Bail out early / back off if DataDome starts returning challenges, and log it
  rather than failing the whole sweep (mirror the notify "swallow and log" pattern).
- The free sweep must never be blocked by paid-lookup failures.

## Out of scope

- Auto-booking (user opposed).
- 1st-class pricing.
- Per-city price thresholds (later, if wanted).
- Non-priority cities.
- Any VPS/cron change — branch only this iteration.

## Implementation order (for the plan)

1. Spike: confirm SNCF Connect price retrieval is feasible (HTTP, else browser).
2. `pricing.py`: `PricedJourney`, `PriceProvider`, first concrete provider.
3. Data-model additions (`price_eur`, `total_price`).
4. Wire paid lookups into the sweep for priority cities (throttled, fault-tolerant).
5. Routing pairing for paid legs.
6. Ranking price penalty.
7. Report rendering of paid options.
8. Config `max_paid_price`.
9. Local end-to-end run + ranker before/after diff. No VPS deploy.
