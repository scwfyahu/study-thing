"""Configuration — all overridable via environment variables."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.environ.get("STUDY_DATA_DIR", ROOT / "data"))
AUDIO_DIR = DATA_DIR / "audio"
DB_PATH = DATA_DIR / "studything.db"

# Optional RNNoise model (.rnnn). If present, used instead of ffmpeg's afftdn.
# Get one: https://github.com/GregorR/rnnoise-models
RNNOISE_MODEL = Path(os.environ.get("STUDY_RNNOISE", DATA_DIR / "rnnoise.rnn"))

# ASR (Apple Silicon / MLX)
WHISPER_MODEL = os.environ.get("STUDY_WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")
WHISPER_LANGUAGE = os.environ.get("STUDY_WHISPER_LANGUAGE", "en")  # "auto" to detect

# Flashcard LLM (local via Ollama)
OLLAMA_URL = os.environ.get("STUDY_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("STUDY_OLLAMA_MODEL", "qwen3:8b")

# Pipeline tuning
CHUNK_SECONDS = int(os.environ.get("STUDY_CHUNK_SECONDS", "600"))
MAX_CARDS_PER_CHUNK = int(os.environ.get("STUDY_MAX_CARDS", "10"))

for _d in (DATA_DIR, AUDIO_DIR):
    _d.mkdir(parents=True, exist_ok=True)