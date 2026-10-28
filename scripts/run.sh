#!/usr/bin/env bash
# Start the dashboard + API + webhook on localhost (simulator mode unless WA_LIVE=1). Usage: scripts/run.sh [port]
cd "$(dirname "$0")/.." && export PORT="${1:-${PORT:-5090}}"
[ -f data/krio_crm.sqlite3 ] || .venv/bin/python -m seed.seed
exec .venv/bin/python -m krio_crm.server
