# tgvmax-watch

A nightly TGVmax (Max Jeune) availability sweep for Paris weekend trips.

Pulls SNCF's public **TGVmax open dataset**, ranks Friday/Saturday → Saturday/Sunday round-trips across a configured list of destination cities, and writes a Markdown report you read over SSH. No login, no scraping, no booking — just signal.

## Why this exists

Max Jeune (the €79/month subscription formerly branded "TGV Max") gives you unlimited free seats on TGV/Intercités — but only inside a hard quota that opens 30 days before each train. Popular weekends sell out within minutes. The strategy is:

1. Know which cities have seats available right now, on which trains, for which weekends.
2. Rank them so you don't have to scan 1,000+ trains every morning.
3. Re-check daily because SNCF keeps adding quota throughout the J-30 window and trickles more in the final 48h.

This tool does exactly that.

## How it works

```
                                    ┌──────────────┐
SNCF Open Data (tgvmax dataset)  →  │  api.py      │  pulls every Paris↔city train
(no auth, refreshed nightly)        │              │  with od_happy_card = "OUI"
                                    └──────┬───────┘
                                           ▼
                                    ┌──────────────┐
                                    │  routing.py  │  groups by weekend, pairs out+back
                                    └──────┬───────┘
                                           ▼
                                    ┌──────────────┐
                                    │  ranker.py   │  scores: nights on site, time-of-day fit,
                                    │              │  ride length, visited cities, last-mile legs
                                    └──────┬───────┘
                                           ▼
                                    ┌──────────────┐
                                    │  report.py   │  writes reports/YYYY-MM-DDTHHMM.md
                                    │              │  + reports/latest.md symlink
                                    └──────────────┘
```

The dataset always covers exactly today → today+30. Every midnight a fresh day appears at the far edge — that's the J-30 unlock. A daily 00:05 cron is enough to never miss one.

## Setup (VPS)

```bash
ssh ubuntu@<vps>
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/musel25/tgvmax-watch.git
cd tgvmax-watch
uv sync
uv run tgvmax-watch status         # sanity: prints dataset date range
uv run tgvmax-watch sweep          # one-off sweep → reports/latest.md
```

Cron (Europe/Paris):

```cron
TZ=Europe/Paris
5 0 * * * /home/ubuntu/tgvmax-watch/scripts/cron.sh
```

## Usage

```bash
# from your laptop:
ssh ubuntu@<vps> 'cat ~/tgvmax-watch/reports/latest.md'
```

Manual one-off (any host with uv):

```bash
uv run tgvmax-watch sweep --stdout            # print to terminal too
uv run tgvmax-watch sweep --top-n 20          # more options per weekend
uv run tgvmax-watch sweep --horizon-days 60   # narrower weekend window
```

## Configuration: `cities.yaml`

Everything tunable lives in one file. No code change needed for normal use.

```yaml
cities:
  - name: Annecy
    region: alps              # selects scheduling rules below
    stations: ["ANNECY"]      # exact SNCF station names in the dataset
    base_weight: 90           # 0–100 interest score
    visited: false            # true → ~-60 to score, drops to bottom

  - name: Cassis
    region: south
    stations: ["MARSEILLE ST CHARLES"]
    needs_extra_leg: true
    extra_leg: "Marseille→Cassis TER 20min, ~€7"
    base_weight: 80

scheduling:
  south:                      # long rides — Fri evening out, Sun late return OK
    out_windows:    [["17:00","21:00"], ["06:00","10:00"]]
    return_windows: [["06:00","11:00"], ["18:00","23:30"]]
  east:                       # 2-3h rides
    out_windows:    [["06:00","11:00"], ["16:00","20:00"]]
    return_windows: [["14:00","22:00"]]
  # …west, alps, close
```

After editing, next cron run uses the new config — no restart needed.

### "I just visited Annecy"

```yaml
- name: Annecy
  visited: true        # ← that's it
```

Or for permanent removal, delete the entry entirely.

## Reports

```
reports/
├── latest.md                  # symlink — what you read
├── 2026-05-19T0905.md         # one per sweep, kept indefinitely
├── 2026-05-20T0005.md
└── cron.log                   # stderr from every cron run; check if reports stop updating
```

Each report is grouped by weekend, top 12 pairings per weekend. Top 3 marked with ⭐. Format:

```
1. ⭐ **Lyon** — score 158
   - OUT Fri 2026-05-22  PARIS (intramuros) → LYON (intramuros), 07:00 → 08:56 (1h56)
   - BACK Sun 2026-05-24  LYON ST EXUPERY TGV. → PARIS (intramuros), 17:54 → 19:46 (1h52)
```

For cities with `needs_extra_leg`, the report appends the last-mile hint (TER price/time).

## What this is not

- **Not a booker.** Still go to SNCF Connect to reserve. Confirm at J-2 by 17:00 or seats auto-release.
- **Not real-time.** The dataset is SNCF's nightly snapshot. Seats added mid-day show up tomorrow.
- **Not a TER planner.** Last-mile legs (Marseille→Cassis, Rennes→Saint-Malo, etc.) are shown as hints. Buy those tickets separately.

## Project layout

```
tgvmax-watch/
├── pyproject.toml            # uv-managed Python project (3.12+)
├── cities.yaml               # destinations + scheduling — the only "config"
├── src/tgvmax_watch/
│   ├── api.py                # SNCF Open Data HTTP client
│   ├── config.py             # cities.yaml loader → typed dataclasses
│   ├── routing.py            # weekend pairing logic
│   ├── ranker.py             # scoring formula (tune here)
│   ├── report.py             # Markdown rendering
│   └── main.py               # argparse CLI: sweep / status
├── scripts/cron.sh           # invoked by cron, pins PATH + TZ
└── reports/                  # generated, gitignored except .gitkeep
```

## License

Personal project. SNCF Open Data is licensed under the Licence Ouverte v2.0.
