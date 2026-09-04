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
    if ASR_BACKEND == "whisper.cpp":
        return _whisper_cpp(path, model, language)
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
    res = mlx_whisper.transcribe(str(path), **kwargs)
    segs = [
        {"start": float(s.get("start", 0)), "end": float(s.get("end", 0)),
         "text": (s.get("text") or "").strip()}
        for s in (res.get("segments") or []) if isinstance(s, dict)
    ]
    return {"text": (res.get("text") or "").strip(), "segments": segs}


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
    segs = []
    for s in segments:
        t = (s.text or "").strip()
        if t:
            segs.append({"start": float(s.start), "end": float(s.end), "text": t})
    text = " ".join(x["text"] for x in segs).strip()
    return {"text": text, "segments": segs}

def _whisper_cpp(path, model, language) -> dict:
    """Local whisper.cpp (Vulkan) — the AMD/Intel GPU path on Windows."""
    import shutil
    import subprocess
    from pathlib import Path

    from .config import WHISPERCPP_BIN, WHISPERCPP_MODEL

    bin_path = WHISPERCPP_BIN or shutil.which("whisper-cli")
    if not bin_path:
        default_dir = Path(__file__).resolve().parent.parent / "data" / "whispercpp"
        cand = sorted(default_dir.glob("**/whisper-cli.exe")) if (default_dir := default_dir).exists() else []
        bin_path = cand[0] if cand else None
    if not bin_path:
        raise RuntimeError(
            "whisper.cpp backend selected but whisper-cli not found. "
            "Run setup.ps1 (downloads the Vulkan build) or set STUDY_WHISPERCPP_BIN."
        )
    model_path = Path(WHISPERCPP_MODEL)
    if not model_path.exists():
        raise RuntimeError(
            f"whisper.cpp model not found at {model_path}. "
            "Run setup.ps1 (downloads ggml-large-v3-turbo-q5_1) or set STUDY_WHISPERCPP_MODEL."
        )
    cmd = [str(bin_path), "-m", str(model_path), "-f", str(path), "-nt", "-np"]
    if language and language.lower() != "auto":
        cmd += ["-l", language]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=14400)
    if p.returncode != 0:
        raise RuntimeError(f"whisper-cli failed: {p.stderr[-500:]}")
    text = " ".join(p.stdout.split()).strip()
    # whisper.cpp text mode has no per-segment timestamps; store as one segment
    return {"text": text, "segments": [{"start": 0, "end": 0, "text": text}] if text else []}