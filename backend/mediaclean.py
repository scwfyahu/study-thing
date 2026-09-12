"""Maintenance: transcode video recordings to audio-only mp3.

Runs in a daemon thread at startup + every few minutes. For each
kind=recording stored as a video container (mp4/mov/mkv/avi/webm), extract the
audio track to <name>.mp3 (mono 64kbps — transparent for speech, ~10x smaller),
switch the recording's stored_path to the mp3, and drop that id's Listen proxy
(mp3 is already small + clean). Source video is left on disk untouched.
"""
import logging
import subprocess
import threading
import time
from pathlib import Path

from .config import AUDIO_DIR
from . import db

logger = logging.getLogger("studything.mediaclean")

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
_SCAN_INTERVAL = 120  # seconds between sweeps
_lock = threading.Lock()


def _src_of(rec) -> Path:
    p = Path(rec["stored_path"])
    if not p.is_absolute():
        p = AUDIO_DIR / p
    return p


def convert_one(rec) -> bool:
    """Transcode one recording to mp3; update stored_path. True on success."""
    src = _src_of(rec)
    if not src.exists():
        return False
    if src.suffix.lower() == ".mp3":
        return False  # already audio-only
    dest = src.with_suffix(".mp3")
    if dest.exists() and dest.stat().st_size > 10_000:
        return True  # already converted
    tmp = AUDIO_DIR / f"{rec['id']}.conv_tmp.mp3"
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-i", str(src), "-vn", "-c:a", "libmp3lame", "-b:a", "64k",
             "-ac", "1", str(tmp)],
            capture_output=True, text=True, errors="replace", timeout=7200)
        ok = r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 10_000
        if not ok:
            logger.warning("convert failed %s: %s", rec["id"], (r.stderr or "")[-300:])
            tmp.unlink(missing_ok=True)
            return False
        tmp.replace(dest)
        with db.get_conn() as conn:
            conn.execute("UPDATE recordings SET stored_path=? WHERE id=?",
                         (str(dest), rec["id"]))
            conn.commit()
        # the Listen proxy is now redundant — mp3 is served directly
        for ext in (".m4a", ".mp3"):
            _unlink_quiet(AUDIO_DIR / "proxy" / f"{rec['id']}{ext}")
        # delete proxy dir otherwise
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("convert error %s: %s", rec["id"], e)
        tmp.unlink(missing_ok=True)
        return False


def _unlink_quiet(p: Path) -> None:
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass


def sweep_all() -> int:
    """Convert every video recording once. Returns count converted."""
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, stored_path FROM recordings WHERE kind='recording'"
            " AND stored_path IS NOT NULL").fetchall()
    n = 0
    for rec in rows:
        p = _src_of(rec)
        if not p.exists():
            continue
        if p.suffix.lower() in VIDEO_EXT or p.stat().st_size > 300_000_000:
            with _lock:
                if convert_one(rec):
                    n += 1
    if n:
        logger.warning("mediaclean: converted %d recording(s) to mp3", n)
    return n


def _worker():
    while True:
        try:
            sweep_all()
        except Exception as e:  # noqa: BLE001
            logger.warning("mediaclean sweep failed: %s", e)
        time.sleep(_SCAN_INTERVAL)


def start_thread() -> None:
    threading.Thread(target=_worker, daemon=True).start()
