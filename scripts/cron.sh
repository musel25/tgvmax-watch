#!/usr/bin/env bash
# Invoked by cron on the VPS. Runs a sweep, logs to reports/cron.log.
set -euo pipefail
cd "$(dirname "$0")/.."
export TZ="${TZ:-Europe/Paris}"
# uv lives in ~/.local/bin on Ubuntu after the official installer
PATH="$HOME/.local/bin:$PATH"
uv run tgvmax-watch sweep "$@" >> reports/cron.log 2>&1
