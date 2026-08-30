"""Configuration — all overridable via environment variables."""
import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ASR backend: MLX on Apple Silicon, faster-whisper elsewhere (Windows/Linux/Intel Mac)
ASR_BACKEND = os.environ.get("STUDY_ASR_BACKEND") or (
    "mlx" if sys.platform == "darwin" and platform.machine() == "arm64" else "faster-whisper"
)
_ASR_DEFAULT_MODEL = {
    "mlx": "mlx-community/whisper-large-v3-turbo",
    "faster-whisper": "large-v3-turbo",
}

DATA_DIR = Path(os.environ.get("STUDY_DATA_DIR", ROOT / "data"))
AUDIO_DIR = DATA_DIR / "audio"
DB_PATH = DATA_DIR / "studything.db"

# Optional RNNoise model (.rnnn). If present, used instead of ffmpeg's afftdn.
# Get one: https://github.com/GregorR/rnnoise-models
RNNOISE_MODEL = Path(os.environ.get("STUDY_RNNOISE", DATA_DIR / "rnnoise.rnn"))

# ASR model per backend (env override wins; mlx-community names are auto-swapped off-MLX)
WHISPER_MODEL = os.environ.get("STUDY_WHISPER_MODEL", _ASR_DEFAULT_MODEL[ASR_BACKEND])
WHISPER_LANGUAGE = os.environ.get("STUDY_WHISPER_LANGUAGE", "en")  # "auto" to detect

# Flashcard LLM (local via Ollama)
OLLAMA_URL = os.environ.get("STUDY_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("STUDY_OLLAMA_MODEL", "qwen3:8b")

# Pipeline tuning
CHUNK_SECONDS = int(os.environ.get("STUDY_CHUNK_SECONDS", "600"))
MAX_CARDS_PER_CHUNK = int(os.environ.get("STUDY_MAX_CARDS", "10"))

for _d in (DATA_DIR, AUDIO_DIR):
    _d.mkdir(parents=True, exist_ok=True)