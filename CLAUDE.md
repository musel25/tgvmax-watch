# CLAUDE.md

Context for future Claude sessions working on this repo. Read this first.

## What this project is

A nightly cron job that pulls SNCF's TGVmax open dataset and produces a ranked Markdown report of weekend round-trip options from Paris. Runs on the user's VPS (`ubuntu@145.241.168.188`). Read end-to-end in `README.md`.

**Purpose**: the user has a Max Jeune subscription (€79/month, ages 16-27, unlimited TGV/Intercités inside a hard quota). Seats unlock J-30, sell out fast on popular weekends. This tool surfaces availability + ranks it so the user can pick from a short list instead of scanning thousands of trains.

## The single most important fact

**The data source is the SNCF Open Data tgvmax dataset, not SNCF Connect.** Endpoint:

```
https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets/tgvmax/records
```

This is the authoritative source — exactly the same quota the user would see if they booked on SNCF Connect — and it has no auth, no rate limits worth worrying about, and a clean OpenDataSoft v2.1 query API. **Never replace it with Playwright/scraping unless the user explicitly asks.** That was discussed in the initial design conversation and ruled out.

Schema (relevant fields):

```
date              YYYY-MM-DD       trip date
train_no          string           SNCF train number
origine           string           e.g. "PARIS (intramuros)", "MASSY TGV"
destination       string           e.g. "LYON (intramuros)", "RENNES"
heure_depart      "HH:MM"
heure_arrivee     "HH:MM"
od_happy_card     "OUI" | "NON"    OUI = Max Jeune seat available right now
entity            string           internal SNCF service grouping
axe               string           "SUD EST", "ATLANTIQUE", "OUIGO_TC", …
```

The dataset window is rolling: always today → today+30. Each midnight Paris time, a new day is appended at the far edge. That's J-30 unlocking.

Query language is OpenDataSoft v2.1's ODSQL — use `where=`, `order_by=`, `limit=` (max 100), `offset=`. Dates compare with `date>=date'YYYY-MM-DD'`. Strings need `"…"`. `in (…)` works.

## Architecture

Six modules under `src/tgvmax_watch/`:

| Module | Role | Touch when… |
|---|---|---|
| `api.py` | HTTP client. Paginated fetch with retries. Returns `Train` dataclasses. | Schema changes, adding new query filters, error handling. |
| `config.py` | Loads `cities.yaml` into typed dataclasses (`City`, `Scheduling`, `Config`). | Adding new fields to cities or scheduling rules. |
| `routing.py` | Groups raw trains into weekends, pairs outbound + return per city. | Changing what counts as a "weekend" or how pairs are built. |
| `ranker.py` | Scoring formula. Returns top N `Pairing`s per weekend. | **Tuning rankings** (most common edit). |
| `report.py` | Markdown render + file write + `latest.md` symlink. | Output format changes. |
| `main.py` | argparse CLI: `sweep`, `status`. | Adding new CLI commands. |

`cities.yaml` is the only user-facing config and lives at repo root.

## Scoring formula (where to make 90% of changes)

In `ranker.py::_score_pair`. Starting from `city.base_weight`, the score adds/subtracts:

- **Time-window fit** (±25 each for out & back). Windows are region-specific in `cities.yaml`.
- **Total ride length penalty** (1 pt per ride-hour).
- **Nights on site** (huge driver): 0 nights = -40, 1 = +10, 2+ = +30. This is what keeps Sat-only returns from beating Sun returns.
- **Later return bonus** (within nights group).
- **Last-mile penalty** (`needs_extra_leg` → -8).
- **Visited penalty** (-60). Drops cities the user has done to the bottom.
- **South-region sleep bonuses**: +8 for Fri-evening out, +8 for Sun-late-evening return — matches the user's "I can sleep on the train" pattern for far destinations.

If the user complains "I want X weighted higher / Y lower", this is where to edit.

## User context (durable)

- Lives in Paris. Has Max Jeune. Every weekend free, generally wants:
  - **South (5h+ rides)**: Fri evening out OR Sat early; Sun morning or late evening back (sleep on train).
  - **Medium (Lyon, Strasbourg, Rennes, Nantes)**: Sat morning out, Sun afternoon/evening back.
  - **Close**: anytime, just not arriving home after ~01:00.
- Has visited **Grenoble** (marked `visited: true`). Should not show in top picks unless nothing else works.
- **Explicit priority list** (as of 2026-05-19, encoded in `cities.yaml` base_weights):
  1. Nice  2. Montpellier  3. Marseille  4. Aix-en-Provence  5. Annecy  6. Saint-Tropez  7. (Annecy again)  8. La Rochelle.
  Everything else is secondary. Treat these as a hard preference, not a hint.
- Doesn't want auto-booking. Reads the report and books manually on SNCF Connect.
- **Telegram notifications are wired** (as of 2026-05-19). Bot `@gusviado_bot` posts to chat `7135043161` after every sweep, attaching the report as a Markdown document with a short caption. Secrets live at `~/.config/tgvmax-watch/secrets.env` (chmod 600, sourced by `scripts/cron.sh`). Failure to notify never fails the sweep.
- VPS: `ssh -i ~/.ssh/ssh-key-2026-04-05.key ubuntu@145.241.168.188`. Cron is `5 0 * * *`. **System TZ is set to `Europe/Paris` via `timedatectl`** — this is what makes the schedule correct. The `TZ=Europe/Paris` line in the crontab is decorative (Vixie cron does NOT honor per-crontab TZ for scheduling; it only sets the env passed to the script). Verified live 2026-05-19.
- Project lives at `/home/ubuntu/tgvmax-watch` on the VPS, `~/Github/tgvmax-watch` on the laptop.

## Conventions

- **`uv` everywhere.** Never `pip`, never `python -m venv`. Add deps with `uv add`. Run with `uv run`.
- Python 3.12+. Type hints on all public functions. Dataclasses (`frozen=True`) for data.
- No emojis in code or commits unless explicitly asked. Comments only when the *why* is non-obvious — code is mostly self-explanatory.
- Conventional Commits: `feat:`, `fix:`, `refactor:`, `chore:`, `docs:`.
- Branches: short-lived `feat/<name>` / `fix/<name>`. Merge to `main`, delete branch immediately (local + remote). No PRs needed — this is a personal project.

## How to test changes locally

```bash
cd ~/Github/tgvmax-watch
uv run tgvmax-watch status         # confirms API is reachable + shows dataset range
uv run tgvmax-watch sweep --stdout # full sweep, prints report
```

The sweep is idempotent and cheap (~2-3s). Run it freely.

For ranker edits specifically, run the sweep before and after, diff the top-N per weekend, and sanity-check that the new ordering matches the user's stated preference.

## Gotchas

- **OpenDataSoft date literals require `date'YYYY-MM-DD'`** (single-quoted), not a plain string. Schema-typed comparisons fail otherwise — there's a real example in the dev history.
- **Some station names have trailing periods or weird casing**: e.g. `"LYON ST EXUPERY TGV."` (note the trailing dot), `"PARIS (intramuros)"`, `"LYON (intramuros)"`. Always copy exact strings from the dataset rather than guessing. Use a `group_by=destination` query to enumerate.
- **The dataset pagination caps at 100 rows per request.** `api.fetch_oui` handles this, but if you add new queries, paginate.
- **Saturday returns aren't bugs.** When the J-30 hasn't unlocked Sunday yet for a far-out weekend, the report falls back to showing Sat-only returns. The score correctly down-weights them (1 night vs 2). Don't "fix" this by filtering them out — they're informational.
- **Friday and Sunday peak periods**: Max Jeune contractually excludes Fri afternoon/eve and Sun afternoon/eve. SNCF still publishes a few quota seats on these slots — that's why they show up. The user wants them shown.
- **Origins include `MASSY TGV`** as well as `PARIS (intramuros)`. Massy is RER B from Paris (~30min). Don't drop it — it's a valid alternative and often the only origin for Atlantique-axis trains (Nantes, Bordeaux).
- **Cron timezone trap.** On Debian/Ubuntu Vixie cron, `TZ=…` and `CRON_TZ=…` in a crontab do **not** change scheduling — they only set env for the executed command. The schedule is interpreted in the **system** timezone. This VPS has the system TZ set to `Europe/Paris` (`timedatectl`); don't change that or all cron times will silently drift. Confirmed via `man 5 crontab` LIMITATIONS section.

## When the user says…

- **"Tune the ranking"** → `ranker.py::_score_pair`. Make sure to also explain *why* you changed weights.
- **"Add a city"** → `cities.yaml` entry. Verify the station name exists in the dataset with a quick API query first.
- **"I visited X"** → flip `visited: true` in `cities.yaml`. Don't delete the entry (they may want to re-enable later).
- **"Why is X not showing up?"** → likely either no `OUI` quota for that weekend yet (J-30 not fired), or station name mismatch. Query the API directly to confirm.
- **"Notifications"** → wired via `notify.py` → Telegram (`@gusviado_bot`). Triggered automatically at the end of `cmd_sweep` when `TGVMAX_TELEGRAM_TOKEN` + `TGVMAX_TELEGRAM_CHAT_ID` are in env. Pass `--no-notify` to suppress. Secrets file: `~/.config/tgvmax-watch/secrets.env`.
- **"Auto-booking"** → user is opposed for now. Would require Playwright + a logged-in SNCF Connect session. Don't build until explicitly asked.

## Don't

- Don't introduce Playwright, Selenium, or any browser automation.
- Don't add a database. `cities.yaml` + report files are enough; trip history can live in YAML flags.
- Don't add a web UI. The user reads `latest.md` over SSH and is happy.
- Don't add async/background workers. Cron + a synchronous script is the right shape.
- Don't widen scope to non-TGVmax trips (Eurostar, Renfe, ÖBB, etc.) without asking.
