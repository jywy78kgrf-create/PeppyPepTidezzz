#!/usr/bin/env bash
# Launch the ATLAS options desk API.
#
#   ./run_api.sh            # dev server on :8000 with reload
#   PORT=9000 ./run_api.sh  # custom port
#
# Run from optionsdesk/backend so the `optdesk` package is importable.
set -euo pipefail

cd "$(dirname "$0")"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

# Ensure sample data exists for offline dev.
if ! ls ../data/chains/*.parquet >/dev/null 2>&1; then
  echo "No chain data found; generating sample store..."
  python -m optdesk.data.make_sample
fi

exec uvicorn optdesk.api.main:app --host "$HOST" --port "$PORT" --reload
