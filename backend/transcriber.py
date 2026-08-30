"""ASR via mlx-whisper. Imported lazily so the server can start without it."""

from .config import WHISPER_LANGUAGE, WHISPER_MODEL


def transcribe(path, model: str = WHISPER_MODEL, language: str = WHISPER_LANGUAGE) -> dict:
    try:
        import mlx_whisper
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "mlx-whisper is not installed in this venv. Run ./setup.sh "
            "(it creates .venv with python3.11 and installs requirements.txt)."
        ) from e

    kwargs = {"path_or_hf_repo": model}
    if language and language.lower() != "auto":
        kwargs["language"] = language
    return mlx_whisper.transcribe(str(path), **kwargs)