"""CLI: `tgvmax-watch sweep` — pulls the current SNCF dataset, ranks, writes a Markdown report."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from . import api, config as cfgmod, notify, paidsweep, pricing, ranker, report, routing


def cmd_sweep(args: argparse.Namespace) -> int:
    cfg = cfgmod.load(args.config)
    today = date.today()
    end = today + timedelta(days=args.horizon_days)
    weekends = routing.weekends_in_range(today, end)

    dest_stations = cfgmod.all_destination_stations(cfg)
    origins = list(cfg.origins)

    print(f"[sweep] horizon: {today} → {end}; weekends: {len(weekends)}", file=sys.stderr)
    print(f"[sweep] origins: {len(origins)}; destination stations: {len(dest_stations)}", file=sys.stderr)

    out_trains = api.fetch_oui(origins, dest_stations, today, end)
    print(f"[sweep] outbound OUI trains: {len(out_trains)}", file=sys.stderr)
    back_trains = api.fetch_oui(dest_stations, origins, today, end)
    print(f"[sweep] return   OUI trains: {len(back_trains)}", file=sys.stderr)

    if not args.no_paid:
        if args.max_paid_price is not None:
            cfg = cfgmod.replace_max_paid_price(cfg, args.max_paid_price)
        # Paid lookups hit SNCF Connect via a headed browser (slow, rate-sensitive),
        # so bound them to a near horizon regardless of the free-sweep horizon.
        paid_weekends = [wk for wk in weekends if (wk.friday - today).days <= cfg.paid_horizon_days]
        print(f"[sweep] paid lookup weekends (<= {cfg.paid_horizon_days}d): {len(paid_weekends)}", file=sys.stderr)
        try:
            with pricing.SncfConnectProvider() as provider:   # launches Chromium once
                paid_out, paid_back = paidsweep.gather_paid_trains(cfg, paid_weekends, provider)
            print(f"[sweep] paid outbound trains <= {cfg.max_paid_price}EUR: {len(paid_out)}", file=sys.stderr)
            print(f"[sweep] paid return   trains <= {cfg.max_paid_price}EUR: {len(paid_back)}", file=sys.stderr)
            out_trains += paid_out
            back_trains += paid_back
        except Exception as e:  # noqa: BLE001 — browser/DataDome failure must not kill the sweep
            print(f"[sweep] paid lookup unavailable, continuing free-only: {e}", file=sys.stderr)

    sections: list[tuple[routing.Weekend, list[ranker.Pairing]]] = []
    for wk in weekends:
        grouped = routing.journeys_for_weekend(cfg, wk, out_trains, back_trains)
        top = ranker.rank_weekend(cfg, wk, grouped, top_n_total=args.top_n)
        sections.append((wk, top))

    now = datetime.now()
    text = report.render(sections, now, verbose=args.verbose)
    out_path = report.write_report(text, Path(args.reports), now)
    print(f"[sweep] wrote {out_path}", file=sys.stderr)
    if not args.no_notify:
        notify.notify_if_configured(sections, out_path)
    if args.stdout:
        print(text)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    lo, hi = api.dataset_date_range()
    print(f"dataset covers {lo} → {hi}  ({(hi - lo).days + 1} days)")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tgvmax-watch")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sweep", help="Pull TGVmax data and write a ranked weekend report.")
    s.add_argument("--config", default="cities.yaml")
    s.add_argument("--reports", default="reports")
    s.add_argument("--horizon-days", type=int, default=90,
                   help="Look up to N days ahead (dataset itself caps at J-30).")
    s.add_argument("--top-n", type=int, default=15, help="Top pairings per weekend.")
    s.add_argument("--verbose", action="store_true",
                   help="Use the original full-detail layout instead of the compact one.")
    s.add_argument("--stdout", action="store_true", help="Also print the report to stdout.")
    s.add_argument("--no-notify", action="store_true",
                   help="Skip Telegram notification even if creds are set.")
    s.add_argument("--no-paid", action="store_true",
                   help="Skip SNCF Connect paid-price lookups (free TGVmax only).")
    s.add_argument("--max-paid-price", type=float, default=None,
                   help="Override cities.yaml max_paid_price (EUR).")
    s.set_defaults(func=cmd_sweep)

    st = sub.add_parser("status", help="Show the dataset's current date coverage.")
    st.set_defaults(func=cmd_status)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
