"""Auto-split: cut a long cross-class recording into per-class recordings.

Pipeline:
  propose(rec_id)  -> LLM reads the timestamped transcript + notebook list,
                      returns segment proposals [{start_sec, end_sec, title,
                      notebook_id}]. Read-only; the UI shows them for editing.
  apply(rec_id, segments) -> ffmpeg stream-copies each segment to a new file,
                      inserts one recording per segment (status 'unclassified',
                      each pre-classified via the escrow suggester), then removes
                      the original. Filing stays a human decision per segment.
"""
import json
import logging
import re
import subprocess

from pathlib import Path

from . import db
from .config import AUDIO_DIR

logger = logging.getLogger(__name__)

_MIN_DURATION = 15 * 60  # don't offer splitting under 15 minutes

PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_min": {"type": "number"},
                    "end_min": {"type": "number"},
                    "title": {"type": "string"},
                    "notebook_id": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["start_min", "end_min", "title", "notebook_id"],
            },
        }
    },
    "required": ["segments"],
}

_SYSTEM = """You analyze a timestamped transcript of one long school-day
recording that may span several different classes back to back.

Task: find the class boundaries and return contiguous segments, one per class
session, covering the ENTIRE recording from 0 to {duration_min} minutes.

Rules:
- Segments must be contiguous and non-overlapping: each starts where the
  previous ended; the first starts at 0; the last ends at {duration_min}.
- Use the timestamps in the transcript to place boundaries precisely (the
  moment the topic/teacher/class clearly changes).
- For each segment pick the notebook_id it belongs to from the CANDIDATE
  CLASSES list (match by subject matter). If none matches, use 0.
- title: short human label of that segment's class/topic.
- Return ONLY the schema. If the whole recording is clearly one single class,
  return one segment covering it all."""


def _loads_robust(content: str) -> dict:
    c = re.sub(r"```(?:json)?", "", content or "", flags=re.I).strip()
    try:
        return json.loads(c)
    except Exception:
        s, e = c.find("{"), c.rfind("}")
        if s < 0 or e < 0:
            raise
        return json.loads(c[s : e + 1])


def eligible(rec) -> bool:
    return (rec["kind"] == "recording" and rec["status"] in ("done", "unclassified")
            and (rec["duration_sec"] or 0) >= _MIN_DURATION)


def _transcript_sample(rec_id: int, max_chars: int = 24000) -> tuple[str, float]:
    """Timestamped transcript [MM:SS] lines + total duration."""
    with db.get_conn() as conn:
        rec = conn.execute("SELECT duration_sec FROM recordings WHERE id=?",
                           (rec_id,)).fetchone()
        rows = conn.execute(
            "SELECT start_sec, text FROM chunks WHERE recording_id=? ORDER BY idx",
            (rec_id,)).fetchall()
    duration = (rec["duration_sec"] if rec else 0) or 0
    lines, size, cut_every = [], 0, max(1, len(rows) // 160 or 1)
    for i, r in enumerate(rows):
        if i % cut_every:  # sample every Nth chunk to stay in budget
            continue
        m, s = divmod(int(r["start_sec"]), 60)
        line = f"[{m:02d}:{s:02d}] {r['text']}"
        if size + len(line) > max_chars:
            break
        lines.append(line)
        size += len(line)
    return "\n".join(lines), duration / 60.0


def propose(rec_id: int) -> dict:
    """LLM boundary proposal. Raises on LLM failure — caller keeps UI calm."""
    from . import classify as _classify
    from . import llm

    sample, duration_min = _transcript_sample(rec_id)
    if not sample.strip():
        raise RuntimeError("recording has no transcript yet")
    with db.get_conn() as conn:
        nbs = conn.execute(
            "SELECT n.id, n.name, COALESCE(n.topics,'') AS topics FROM notebooks n"
            " ORDER BY n.name").fetchall()
    cand = "\n".join(f'- id {n["id"]}: {n["name"]}'
                     + (f" (topics: {n['topics'][:200]})" if n["topics"] else "")
                     for n in nbs)
    user = (f"CANDIDATE CLASSES:\n{cand}\n\n"
            f"TOTAL RECORDING LENGTH: {duration_min:.1f} minutes.\n\n"
            f"TIMESTAMPED TRANSCRIPT (sampled):\n{sample}")
    # NB: guided JSON makes the free model return empty segments intermittently;
    # a plain JSON request + robust parse is reliable. Retry a few times.
    segs = []
    last_err = None
    for attempt in range(3):
        try:
            content = llm.chat(
                [{"role": "system", "content": _SYSTEM.format(duration_min=f"{duration_min:.1f}")},
                 {"role": "user", "content": user}],
                num_ctx=32768, num_predict=4096, temperature=0.1,
            )
            segs = _loads_robust(content).get("segments") or []
            if segs:
                break
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning("split propose attempt %d failed: %s", attempt + 1, e)
    if not segs and last_err:
        raise last_err
    # validate + normalize: monotonic, inside [0, duration], known notebook ids
    out, cursor = [], 0.0
    prev_end = 0.0
    valid_ids = {n["id"] for n in nbs}
    for s in segs:
        try:
            start = max(0.0, min(duration_min, float(s.get("start_min", s.get("start", 0)))))
            end = max(0.0, min(duration_min, float(s.get("end_min", s.get("end", 0)))))
        except (TypeError, ValueError):
            continue
        if end - start < 1.0:
            continue
        if start < prev_end - 0.5:  # overlap -> clamp
            start = prev_end
            if end - start < 1.0:
                continue
        prev_end = end
        try:
            nb_id = int(s.get("notebook_id", 0))
        except (TypeError, ValueError):
            nb_id = 0
        if nb_id != 0 and nb_id not in valid_ids:
            nb_id = 0
        nb_name = next((n["name"] for n in nbs if n["id"] == nb_id), None)
        out.append({
            "start_min": round(start, 2), "end_min": round(end, 2),
            "title": str(s.get("title") or "").strip()[:120],
            "notebook_id": nb_id if nb_id else None,
            "notebook_name": nb_name,
            "reason": str(s.get("reason") or "").strip()[:300],
        })
    return {"segments": out, "duration_min": round(duration_min, 2)}


def _ffmpeg_cut(src: Path, start_s: float, end_s: float, dest: Path) -> float:
    """Stream-copy a segment (fast, no re-encode). Returns cut duration."""
    dur = max(0.5, end_s - start_s)
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-ss", f"{start_s:.2f}", "-i", str(src), "-t", f"{dur:.2f}",
         "-c", "copy", str(dest)],
        check=True, timeout=600)
    return dur


def apply(rec_id: int, segments: list[dict]) -> dict:
    """Cut + create one recording per segment, each escrowed for approval.

    Transcript chunks are sliced from the original by time range (no
    re-transcription), so escrow classification works immediately.
    """
    if not segments:
        raise RuntimeError("no segments to apply")
    with db.get_conn() as conn:
        rec = conn.execute("SELECT * FROM recordings WHERE id=?", (rec_id,)).fetchone()
        chunks = conn.execute(
            "SELECT start_sec, text FROM chunks WHERE recording_id=? ORDER BY idx",
            (rec_id,)).fetchall()
    if rec is None:
        raise RuntimeError("recording not found")
    src = Path(rec["stored_path"])
    if not src.is_absolute():
        # legacy relative rows were stored as "data/audio/<file>" under ROOT
        name = src.name
        cand = AUDIO_DIR / name
        src = cand if cand.exists() else src
    if not src.exists():
        raise RuntimeError(f"source file missing: {src}")
    safe_base = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(rec["original_name"]).stem)[:60]
    created = []
    for i, seg in enumerate(segments, 1):
        try:
            start = float(seg["start_min"]) * 60.0
            end = float(seg["end_min"]) * 60.0
        except (KeyError, TypeError, ValueError) as e:
            raise RuntimeError(f"segment {i}: bad start/end") from e
        if end - start < 30:
            raise RuntimeError(f"segment {i}: under 30 seconds")
        ext = src.suffix.lower() or ".m4a"
        dest = AUDIO_DIR / f"{safe_base}_part{i:02d}{ext}"
        if dest.exists():
            dest.unlink()
        _ffmpeg_cut(src, start, end, dest)
        with db.get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO recordings(notebook_id, original_name, stored_path,"
                " kind, status, progress, note, duration_sec, recorded_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (None, f"{Path(rec['original_name']).stem} (part {i})",
                 str(dest), "recording", "unclassified", 1.0,
                 "Auto-split — review the suggestion, then assign.",
                 round(end - start, 1), rec["recorded_at"]),
            )
            new_id = cur.lastrowid
            for c in chunks:
                if start - 1 <= c["start_sec"] < end:
                    conn.execute(
                        "INSERT INTO chunks(recording_id, idx, start_sec, text)"
                        " VALUES (?,?,?,?)",
                        (new_id, int(c["start_sec"] - start),
                         max(0.0, c["start_sec"] - start), c["text"]),
                    )
            conn.commit()
        created.append(new_id)
    # classify each segment from its own transcript slice (escrow suggestion)
    # NOTE: pass notebooks=None — classify builds its own well-formed profiles
    from . import classify as _classify
    for new_id in created:
        try:
            with db.get_conn() as conn:
                text = " ".join(r["text"] for r in conn.execute(
                    "SELECT text FROM chunks WHERE recording_id=? ORDER BY idx",
                    (new_id,)).fetchall())
            sug = _classify.classify(text) if text.strip() else None
            if sug:
                with db.get_conn() as conn:
                    conn.execute("UPDATE recordings SET suggestion=? WHERE id=?",
                                 (json.dumps(sug, ensure_ascii=False), new_id))
                    conn.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("segment classify failed (id %s): %s", new_id, e)
    # segments exist -> retire the original
    try:
        src.unlink()
    except OSError as e:
        logger.warning("could not remove original %s: %s", src, e)
    with db.get_conn() as conn:
        conn.execute("DELETE FROM chunks WHERE recording_id=?", (rec_id,))
        conn.execute("DELETE FROM recordings WHERE id=?", (rec_id,))
        conn.commit()
    return {"created": created,
            "note": "Segments are in the Suggest inbox — assign each one."}
