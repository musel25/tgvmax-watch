#!/usr/bin/env bash
# Invoked by cron on the VPS. Runs a sweep, logs to reports/cron.log.
set -euo pipefail
cd "$(dirname "$0")/.."
export TZ="${TZ:-Europe/Paris}"
# uv lives in ~/.local/bin on Ubuntu after the official installer
PATH="$HOME/.local/bin:$PATH"
# Optional secrets (Telegram). Sourced if present; absence is fine.
if [ -f "$HOME/.config/tgvmax-watch/secrets.env" ]; then
  # shellcheck source=/dev/null
  . "$HOME/.config/tgvmax-watch/secrets.env"
fi
uv run tgvmax-watch sweep "$@" >> reports/cron.log 2>&1
