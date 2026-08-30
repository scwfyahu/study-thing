#!/usr/bin/env bash
# Dev mode: backend on :8765 + Vite dev server on :5173 (open http://localhost:5173)
set -euo pipefail
cd "$(dirname "$0")"

[ -d .venv ] || { echo "Run ./setup.sh first."; exit 1; }

./.venv/bin/uvicorn backend.main:app --port 8765 --reload &
BACK=$!
( cd frontend && npm run dev ) &
FRONT=$!
trap 'kill $BACK $FRONT 2>/dev/null' EXIT
echo ""
echo "  StudyThing dev →  http://localhost:5173"
echo ""
wait