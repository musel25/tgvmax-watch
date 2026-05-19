"""Telegram notifications.

Reads TGVMAX_TELEGRAM_TOKEN and TGVMAX_TELEGRAM_CHAT_ID from env. If either is
unset the module is a no-op — the sweep still succeeds. Network/API failures
are logged and swallowed for the same reason: the report file on disk is the
source of truth.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

from .ranker import Pairing
from .routing import Weekend

_API = "https://api.telegram.org"
_MAX_CAPTION = 1024  # Telegram document caption limit


def _build_caption(sections: list[tuple[Weekend, list[Pairing]]]) -> str:
    weekends_with_picks = [(wk, top) for wk, top in sections if top]
    total_weekends = len(sections)
    covered = len(weekends_with_picks)

    lines = [f"TGVmax sweep — {covered}/{total_weekends} weekends with picks"]
    for wk, top in weekends_with_picks[:6]:
        label = wk.friday.strftime("%a %d %b")
        top_cities = []
        seen: set[str] = set()
        for p in top:
            if p.city.name not in seen:
                seen.add(p.city.name)
                top_cities.append(p.city.name)
            if len(top_cities) >= 3:
                break
        lines.append(f"• {label}: {', '.join(top_cities)}")

    text = "\n".join(lines)
    if len(text) > _MAX_CAPTION:
        text = text[: _MAX_CAPTION - 20] + "\n… (see attached)"
    return text


def notify_if_configured(
    sections: list[tuple[Weekend, list[Pairing]]],
    report_path: Path,
) -> bool:
    """Send the report to Telegram if creds are present. Returns True on send."""
    token = os.environ.get("TGVMAX_TELEGRAM_TOKEN")
    chat_id = os.environ.get("TGVMAX_TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[notify] no Telegram creds in env; skipping", file=sys.stderr)
        return False

    caption = _build_caption(sections)
    url = f"{_API}/bot{token}/sendDocument"
    try:
        with report_path.open("rb") as fh:
            r = httpx.post(
                url,
                data={"chat_id": chat_id, "caption": caption},
                files={"document": (report_path.name, fh, "text/markdown")},
                timeout=20.0,
            )
        if r.status_code != 200 or not r.json().get("ok"):
            print(f"[notify] telegram error {r.status_code}: {r.text[:200]}", file=sys.stderr)
            return False
        print(f"[notify] sent {report_path.name} to chat {chat_id}", file=sys.stderr)
        return True
    except httpx.HTTPError as exc:
        print(f"[notify] network error: {exc}", file=sys.stderr)
        return False
