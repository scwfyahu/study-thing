#!/usr/bin/env bash
# One-command setup for StudyThing (local-only flashcards from lecture recordings).
set -euo pipefail
cd "$(dirname "$0")"

echo "==> 1/5 Python venv (mlx-whisper needs <=3.13; python3.11 preferred)"
PY=""
for c in python3.11 python3.12 python3.13; do
  command -v "$c" >/dev/null 2>&1 && PY="$c" && break
done
PY="${PY:-python3}"
echo "    using $($PY --version 2>&1)"
[ -d .venv ] || "$PY" -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt

echo "==> 2/5 brew deps (ffmpeg, ollama, node)"
command -v ffmpeg >/dev/null || brew install ffmpeg
command -v ollama >/dev/null || brew install ollama
command -v node   >/dev/null || brew install node

echo "==> 3/5 ollama daemon"
ollama list >/dev/null 2>&1 || { brew services start ollama >/dev/null 2>&1 || ollama serve >/dev/null 2>&1 & sleep 3; }

echo "==> 4/5 pulling ${STUDY_OLLAMA_MODEL:-qwen3:8b} (~5 GB, one time)"
ollama list | awk '{print $1}' | grep -qx "${STUDY_OLLAMA_MODEL:-qwen3:8b}" || ollama pull "${STUDY_OLLAMA_MODEL:-qwen3:8b}"

echo "==> 5/5 frontend deps"
( cd frontend && npm install --silent )

cat <<'EOF'

Setup complete. Start the app:
  ./run-dev.sh          # dev mode (backend :8765 + Vite :5173)

Or production mode (single server on :8765):
  ( cd frontend && npm run build )
  ./.venv/bin/uvicorn backend.main:app --port 8765

The first transcription downloads the Whisper model (~1.6 GB, one time).
EOF