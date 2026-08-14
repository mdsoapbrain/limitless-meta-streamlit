#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: ./scripts/update_data.sh END_DATE [START_DATE]" >&2
  exit 2
fi

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
END_DATE="$1"
START_DATE="${2:-2026-07-01}"
TODAY="$(date +%F)"

if [[ ! "$END_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || \
   [[ ! "$START_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "Dates must use YYYY-MM-DD format." >&2
  exit 2
fi

if [[ "$END_DATE" > "$TODAY" ]]; then
  echo "END_DATE $END_DATE is in the future. Use $TODAY or an earlier date." >&2
  exit 2
fi

if [[ -n "${LIMITLESS_PYTHON:-}" ]]; then
  PYTHON_BIN="$LIMITLESS_PYTHON"
elif [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
elif [[ -x "$PROJECT_DIR/../.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_DIR/../.venv/bin/python"
else
  echo "No project Python environment found." >&2
  echo "Create one with: python3 -m venv .venv" >&2
  echo "Then install dependencies with: .venv/bin/python -m pip install -r requirements-dev.txt" >&2
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python is not executable: $PYTHON_BIN" >&2
  exit 1
fi

cd "$PROJECT_DIR"

"$PYTHON_BIN" -m limitless_meta fetch \
  --start "$START_DATE" \
  --end "$END_DATE" \
  --min-players 60

"$PYTHON_BIN" -m limitless_meta analyze \
  --start "$START_DATE" \
  --end "$END_DATE" \
  --min-players 60 \
  --match-scope all

"$PYTHON_BIN" scripts/verify_deploy.py

echo
echo "Snapshot updated for $START_DATE through $END_DATE."
echo "Review the dashboard, then commit and push data/meta.duckdb."
