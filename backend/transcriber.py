"""ASR backends.

- MLX (Apple Silicon, default on M-series Macs): mlx-whisper, GPU, ~15x realtime.
- faster-whisper (Windows / Linux / Intel): CTranslate2, CPU int8 or CUDA when available.

Selected by config.ASR_BACKEND (auto by platform, override with STUDY_ASR_BACKEND).
"""
import platform
import sys

from .config import WHISPER_LANGUAGE, WHISPER_MODEL

_fw_model_cache = {}


def transcribe(path, model: str = WHISPER_MODEL, language: str = WHISPER_LANGUAGE) -> dict:
    from .config import ASR_BACKEND

    # Guard: mlx-community model names only exist on the MLX backend
    if ASR_BACKEND != "mlx" and "mlx-community" in model:
        model = "large-v3-turbo"
    if ASR_BACKEND == "mlx":
        return _mlx(path, model, language)
    return _faster_whisper(path, model, language)


def _mlx(path, model, language) -> dict:
    try:
        import mlx_whisper
    except ImportError as e:
        raise RuntimeError(
            "mlx-whisper is not installed (macOS Apple Silicon only). "
            "On Windows use faster-whisper: run setup.ps1. "
            "Force MLX on macOS with STUDY_ASR_BACKEND=mlx after ./setup.sh."
        ) from e
    kwargs = {"path_or_hf_repo": model}
    if language and language.lower() != "auto":
        kwargs["language"] = language
    return mlx_whisper.transcribe(str(path), **kwargs)


def _faster_whisper(path, model, language) -> dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper is not installed. Run setup.ps1 (Windows) or setup.sh, "
            "or: pip install faster-whisper"
        ) from e
    if model not in _fw_model_cache:
        _fw_model_cache.clear()  # one model at a time — 16GB machines
        _fw_model_cache[model] = WhisperModel(model, device="auto", compute_type="auto")
    m = _fw_model_cache[model]
    kwargs = {"vad_filter": True}
    if language and language.lower() != "auto":
        kwargs["language"] = language
    segments, _info = m.transcribe(str(path), **kwargs)
    text = " ".join(s.text.strip() for s in segments).strip()
    return {"text": text, "segments": []}