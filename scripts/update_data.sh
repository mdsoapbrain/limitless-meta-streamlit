#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: ./scripts/update_data.sh END_DATE [START_DATE]" >&2
  exit 2
fi

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
END_DATE="$1"
START_DATE="${2:-2026-07-01}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing $PYTHON_BIN. Create the project virtual environment first." >&2
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
