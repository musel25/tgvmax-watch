"""Render the ranked sweep into a Markdown report.

Two render modes:
- compact (default): one-line-per-option, message-style, dense
- verbose (--verbose flag): the original full-detail layout
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import City
from .ranker import Pairing
from .routing import Weekend, duration_min

# Pulls the "~€N" or "~€N.NN" amount out of an extra_leg description.
_EXTRA_COST_RE = re.compile(r"~€\d+(?:\.\d+)?")


def _extra_cost(city: City) -> str:
    """Return '+~€N' for a city that needs a last-mile leg, '' otherwise.

    TGVmax itself is free for the user (covered by Max Jeune), so only the
    extra-leg (TER / bus / ferry) cost is shown. Falls back to the full
    extra_leg string if no €-amount could be parsed.
    """
    if not city.needs_extra_leg:
        return ""
    m = _EXTRA_COST_RE.search(city.extra_leg)
    if m:
        return f"+{m.group(0)}"
    return f"+{city.extra_leg}" if city.extra_leg else "+last-mile"


def _price_tag(p: Pairing) -> str:
    """' · 30€' for a paid pairing, '' for a free one."""
    if p.total_price is None:
        return ""
    return f" · {p.total_price:.0f}€"

# --- station name prettifier -------------------------------------------------
# SNCF station names in the dataset are ALL CAPS and sometimes have trailing
# dots or "(intramuros)" tags. Map the common ones; fall back to title-casing.
STATION_PRETTY = {
    "PARIS (intramuros)": "Paris",
    "LYON (intramuros)": "Lyon Part-Dieu",
    "LYON ST EXUPERY TGV.": "Lyon St-Exupéry",
    "LILLE (intramuros)": "Lille",
    "MASSY TGV": "Massy TGV",
    "MARSEILLE ST CHARLES": "Marseille St-Charles",
    "MONTPELLIER SAINT ROCH": "Montpellier Saint-Roch",
    "MONTPELLIER SUD DE FRANCE": "Montpellier Sud-de-France",
    "AIX EN PROVENCE TGV": "Aix-en-Provence TGV",
    "NICE VILLE": "Nice Ville",
    "BORDEAUX ST JEAN": "Bordeaux St-Jean",
    "LA ROCHELLE VILLE": "La Rochelle",
    "TOULOUSE MATABIAU": "Toulouse Matabiau",
    "ST RAPHAEL VALESCURE": "St-Raphaël Valescure",
    "LES ARCS DRAGUIGNAN": "Les Arcs-Draguignan",
    "AVIGNON CENTRE": "Avignon Centre",
    "AVIGNON TGV": "Avignon TGV",
    "TOULON": "Toulon",
    "HYERES": "Hyères",
    "STRASBOURG": "Strasbourg",
    "COLMAR": "Colmar",
    "ANNECY": "Annecy",
    "GRENOBLE": "Grenoble",
    "RENNES": "Rennes",
    "NANTES": "Nantes",
    "QUIMPER": "Quimper",
    "SAINT MALO": "Saint-Malo",
    "CARCASSONNE": "Carcassonne",
    "ARLES": "Arles",
    "MENTON": "Menton",
}

WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTH_SHORT = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

PRIORITY_BASE_WEIGHT = 80  # cities at/above this get a leading star


def _pretty(station: str) -> str:
    if station in STATION_PRETTY:
        return STATION_PRETTY[station]
    # fallback: title-case, strip trailing dots, collapse whitespace
    return " ".join(w.capitalize() for w in station.rstrip(".").split())


def _short_date(d: date) -> str:
    return f"{MONTH_SHORT[d.month]} {d.day}"


def _weekend_header_dates(wk: Weekend) -> str:
    """Friendly weekend label, handles cross-month weekends (e.g. Jul 31 → Aug 2)."""
    if wk.friday.month == wk.sunday.month:
        return f"{_short_date(wk.friday)}-{wk.sunday.day}"
    return f"{_short_date(wk.friday)} – {_short_date(wk.sunday)}"


def _unlock_msg(unlock_day: date, today: date) -> str:
    days = (unlock_day - today).days
    if days <= 0:
        return "_unlocked_"
    if days == 1:
        return "_unlocks tonight 00:05_"
    if days == 2:
        return "_unlocks tomorrow night 00:05_"
    return f"_unlocks {_short_date(unlock_day)} 00:05 ({days}d)_"


def _wd(d: date) -> str:
    return WEEKDAY_SHORT[d.weekday()]


def _nights(p: Pairing) -> int:
    return (p.back.train.date - p.out.train.date).days


def _on_site_label(p: Pairing) -> str:
    """How long the user spends on site: '12h' or '1d12h'. Mirrors ranker._on_site_minutes."""
    out_arr_h, out_arr_m = (int(x) for x in p.out.train.arr.split(":"))
    back_dep_h, back_dep_m = (int(x) for x in p.back.train.dep.split(":"))
    day_diff = (p.back.train.date - p.out.train.date).days
    total_min = day_diff * 24 * 60 + (back_dep_h * 60 + back_dep_m) - (out_arr_h * 60 + out_arr_m)
    if total_min < 0:
        total_min = 0
    h, m = divmod(total_min, 60)
    if h < 24:
        return f"{h}h" if m == 0 else f"{h}h{m:02d}"
    d, rem_h = divmod(h, 24)
    return f"{d}d" if rem_h == 0 else f"{d}d{rem_h}h"


def _city_label(c: City) -> str:
    star = "★ " if c.base_weight >= PRIORITY_BASE_WEIGHT and not c.visited else "  "
    name = c.name
    if c.visited:
        name = f"{name} (visited)"
    return f"{star}{name}"


def _ride_hm(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h}h{m:02d}" if m else f"{h}h"


# --- compact (default) -------------------------------------------------------

def _compact_line(idx: int, p: Pairing, max_city_width: int) -> str:
    out_t, back_t = p.out.train, p.back.train
    on_site = _on_site_label(p)
    origin_paris = _pretty(out_t.origin) != "Paris"
    via = f" · from {_pretty(out_t.origin)}" if origin_paris else ""
    via_back = ""
    if _pretty(back_t.destination) != "Paris":
        via_back = f" · back to {_pretty(back_t.destination)}"
    total_ride = duration_min(out_t) + duration_min(back_t)
    cost = _extra_cost(p.city)
    extra = f" · {cost}" if cost else ""
    price = _price_tag(p)
    return (
        f"{idx:>2}  {_city_label(p.city):<{max_city_width}}  "
        f"{_wd(out_t.date)} {out_t.dep} → {_wd(back_t.date)} {back_t.dep}   "
        f"{on_site} on · {_ride_hm(total_ride)} ride{price}{extra}{via}{via_back}"
    )


def _render_weekend_compact(
    wk: Weekend, top: list[Pairing], today: date, city_col: int
) -> list[str]:
    header = f"🗓 {_weekend_header_dates(wk)}"
    out: list[str] = []
    if not top:
        unlock = wk.friday - timedelta(days=30)
        if unlock > today:
            out.append(f"{header} — {_unlock_msg(unlock, today)}")
        else:
            out.append(f"{header} — _no TGVmax options found_")
        return out
    out.append(header)
    for i, p in enumerate(top, 1):
        out.append(_compact_line(i, p, city_col))
    return out


def render_compact(
    weekends: list[tuple[Weekend, list[Pairing]]],
    generated_at: datetime,
    today: date,
) -> str:
    # global column width so blocks line up across weekends
    all_pairings = [p for _, top in weekends for p in top]
    if all_pairings:
        city_col = min(max(len(_city_label(p.city)) for p in all_pairings), 22)
    else:
        city_col = 12

    lines: list[str] = []
    lines.append(f"# TGVmax sweep · {generated_at.strftime('%d %b %H:%M')}")
    lines.append("")
    lines.append("_★ = priority · `Nh on` = hours on site · `Nh ride` = total train time · TGVmax free w/ Max Jeune, only last-mile cost shown_")
    lines.append("")
    lines.append("```")
    for wk, top in weekends:
        lines.extend(_render_weekend_compact(wk, top, today, city_col))
        lines.append("")
    lines.append("```")
    return "\n".join(lines)


# --- verbose (--verbose flag) ------------------------------------------------

def _fmt_train_verbose(t) -> str:
    return (
        f"{_pretty(t.origin)} → {_pretty(t.destination)}, "
        f"{t.dep} → {t.arr} ({_ride_hm(duration_min(t))})"
    )


def render_verbose(
    weekends: list[tuple[Weekend, list[Pairing]]],
    generated_at: datetime,
    today: date,
) -> str:
    parts: list[str] = []
    parts.append(f"# TGVmax weekend sweep — {generated_at.isoformat(timespec='minutes')}\n")
    parts.append(
        "_Source: SNCF Open Data (od_happy_card=OUI). Confirm each trip on SNCF Connect at J-2 by 17:00._\n"
    )
    for wk, top in weekends:
        parts.append(f"## Weekend {wk.friday.isoformat()} → {wk.sunday.isoformat()}\n")
        if not top:
            unlock = wk.friday - timedelta(days=30)
            if unlock > today:
                parts.append(f"_J-30 unlocks {unlock.isoformat()} 00:05 Paris time._\n")
            else:
                parts.append("_No TGVmax options found for any city in scope._\n")
            continue
        for i, p in enumerate(top, 1):
            star = "⭐" if i <= 3 else " "
            extra = f"  _last leg_: {p.city.extra_leg}\n" if p.city.needs_extra_leg else ""
            price = f" · {p.total_price:.0f}€ paid" if p.total_price is not None else " · TGVmax (free)"
            parts.append(
                f"{i}. {star} **{p.city.name}** — score {p.score:.0f}{price}\n"
                f"   - OUT {_wd(p.out.train.date)} {p.out.train.date.isoformat()}  {_fmt_train_verbose(p.out.train)}\n"
                f"   - BACK {_wd(p.back.train.date)} {p.back.train.date.isoformat()}  {_fmt_train_verbose(p.back.train)}\n"
                f"{extra}"
            )
        parts.append("")
    return "\n".join(parts)


# --- entry points ------------------------------------------------------------

def render(
    weekends: list[tuple[Weekend, list[Pairing]]],
    generated_at: datetime,
    verbose: bool = False,
    today: date | None = None,
) -> str:
    today = today or generated_at.date()
    return (render_verbose if verbose else render_compact)(weekends, generated_at, today)


def write_report(text: str, reports_dir: Path, run_at: datetime) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    p = reports_dir / f"{run_at.strftime('%Y-%m-%dT%H%M')}.md"
    p.write_text(text)
    latest = reports_dir / "latest.md"
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    latest.symlink_to(p.name)
    return p
