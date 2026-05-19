# tgvmax-watch

Nightly TGVmax (Max Jeune) availability sweep for Paris weekend trips, ranked.

Reads SNCF's public **TGVmax open dataset** (no login, no browser) and produces a
Markdown report grouping the best Friday/Saturday → Sunday round-trip pairings for a
fixed list of destination cities. Built to run on a small VPS via cron.

## What it does

1. Pull every train in the dataset where a Max Jeune seat (`od_happy_card = OUI`) is
   available, in both directions, within the next ~30 days (the dataset's natural cap).
2. Pair outbound (Fri/Sat) and return (Sat/Sun) trains per city.
3. Score each pairing on:
   - region-aware time-of-day windows (south = long ride, Friday-evening-friendly; close = anytime)
   - total travel time
   - "time on site" (early out + late back wins)
   - whether the destination needs a TER/bus leg
   - base interest weight per city (hand-tuned in `cities.yaml`)
   - **visited** flag → heavy down-weighting
4. Write `reports/YYYY-MM-DDTHHMM.md` + a `latest.md` symlink.

It **does not book**. You still pick from the list and reserve on SNCF Connect.

## Setup

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/<you>/tgvmax-watch.git
cd tgvmax-watch
uv sync
uv run tgvmax-watch status               # sanity: shows dataset date range
uv run tgvmax-watch sweep --stdout       # one-off sweep, also writes reports/
```

## Cron (Europe/Paris)

```cron
TZ=Europe/Paris
5 0 * * * /home/ubuntu/tgvmax-watch/scripts/cron.sh
```

Runs daily at 00:05 Paris time, which catches every J-30 unlock automatically
(since each midnight makes a new day appear at the far edge of the dataset).

Read the latest report:

```bash
cat ~/tgvmax-watch/reports/latest.md
```

## Tuning

Everything is in `cities.yaml`:

- `base_weight` — your interest in this city
- `visited: true` — push it down hard
- `needs_extra_leg` / `extra_leg` — describe the cheap last-mile
- `scheduling.<region>.out_windows` / `return_windows` — preferred departure times
