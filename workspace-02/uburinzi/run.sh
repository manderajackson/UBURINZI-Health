#!/usr/bin/env bash
# Start Uburinzi Health (creates the DB and seeds a demo cohort on first run).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then cp .env.example .env; fi
python3 -m app.cli init-db
python3 -m app.cli seed

echo ""
echo "  Uburinzi Health is starting on http://localhost:8000"
echo "  Sign in: manderajackson99@gmail.com / uburinzi2026"
echo ""
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
