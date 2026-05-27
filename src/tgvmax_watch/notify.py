"""Telegram notifications.

Reads TGVMAX_TELEGRAM_TOKEN and TGVMAX_TELEGRAM_CHAT_IDS (comma-separated) from
env. If either is unset the module is a no-op — the sweep still succeeds.
Per-recipient failures are logged and swallowed: the report file on disk is the
source of truth, and one friend's bad chat_id must not block the others.
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


def _chat_ids_from_env() -> list[str]:
    raw = os.environ.get("TGVMAX_TELEGRAM_CHAT_IDS", "")
    return [c.strip() for c in raw.split(",") if c.strip()]


def _send_one(token: str, chat_id: str, report_path: Path, caption: str) -> bool:
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
            print(f"[notify] telegram error for {chat_id}: {r.status_code} {r.text[:200]}", file=sys.stderr)
            return False
        print(f"[notify] sent {report_path.name} to chat {chat_id}", file=sys.stderr)
        return True
    except httpx.HTTPError as exc:
        print(f"[notify] network error for {chat_id}: {exc}", file=sys.stderr)
        return False


def notify_if_configured(
    sections: list[tuple[Weekend, list[Pairing]]],
    report_path: Path,
) -> bool:
    """Send the report to every configured Telegram chat. Returns True if at least one send succeeded."""
    token = os.environ.get("TGVMAX_TELEGRAM_TOKEN")
    chat_ids = _chat_ids_from_env()
    if not token or not chat_ids:
        print("[notify] no Telegram creds in env; skipping", file=sys.stderr)
        return False

    caption = _build_caption(sections)
    sent = sum(_send_one(token, cid, report_path, caption) for cid in chat_ids)
    print(f"[notify] delivered to {sent}/{len(chat_ids)} chats", file=sys.stderr)
    return sent > 0
