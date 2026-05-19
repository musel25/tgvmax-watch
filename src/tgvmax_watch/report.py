"""Render the ranked sweep into a Markdown report."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from .ranker import Pairing
from .routing import Weekend, duration_min

WEEKDAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _fmt_date(d: date) -> str:
    return f"{WEEKDAY[d.weekday()]} {d.isoformat()}"


def _fmt_train(t) -> str:
    return f"{t.origin} → {t.destination}, {t.dep} → {t.arr} ({duration_min(t)//60}h{duration_min(t)%60:02d})"


def render(weekends: list[tuple[Weekend, list[Pairing]]], generated_at: datetime) -> str:
    parts: list[str] = []
    parts.append(f"# TGVmax weekend sweep — {generated_at.isoformat(timespec='minutes')}\n")
    parts.append(f"_Source: SNCF Open Data (od_happy_card=OUI). Confirm each trip on SNCF Connect at J-2 by 17:00._\n")

    any_options = False
    for wk, top in weekends:
        parts.append(f"## Weekend {wk.friday.isoformat()} → {wk.sunday.isoformat()}\n")
        if not top:
            parts.append("_No TGVmax options found for any city in scope._\n")
            continue
        any_options = True
        for i, p in enumerate(top, 1):
            star = "⭐" if i <= 3 else " "
            extra = f"  _last leg_: {p.city.extra_leg}\n" if p.city.needs_extra_leg else ""
            parts.append(
                f"{i}. {star} **{p.city.name}** — score {p.score:.0f}\n"
                f"   - OUT {_fmt_date(p.out.train.date)}  {_fmt_train(p.out.train)}\n"
                f"   - BACK {_fmt_date(p.back.train.date)}  {_fmt_train(p.back.train)}\n"
                f"{extra}"
            )
        parts.append("")
    if not any_options:
        parts.append("\n> Either the dataset hasn't unlocked these dates yet, or peak-period quota is zero.\n")
    return "\n".join(parts)


def write_report(text: str, reports_dir: Path, run_at: datetime) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    p = reports_dir / f"{run_at.strftime('%Y-%m-%dT%H%M')}.md"
    p.write_text(text)
    latest = reports_dir / "latest.md"
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    latest.symlink_to(p.name)
    return p
