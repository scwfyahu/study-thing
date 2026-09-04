"""Processing pipeline: denoise -> chunk -> transcribe -> extract flashcards -> dedupe/store.

Runs sequentially (one recording at a time) so an M-series Air with 16GB
unified memory never holds the ASR model and the LLM at the same time.
"""
import json
import re
import shutil
import subprocess
import threading

from . import db
from .config import (
    AUDIO_DIR,
    LLM_NUM_CTX,
    OLLAMA_MODEL,
    OLLAMA_URL,
    RNNOISE_MODEL,
)

_pipeline_lock = threading.Lock()

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "answer": {"type": "string"},
                    "topic": {"type": "string"},
                },
                "required": ["question", "answer"],
            },
        }
    },
    "required": ["cards"],
}

SYSTEM_PROMPT = """You turn lecture transcripts into study flashcards.
Rules:
- Extract only information stated in the transcript. Never invent facts.
- Skip greetings, announcements, homework/logistics talk, and garbled noise.
- Write self-contained questions a student could see on an exam. Answers are concise (1-3 sentences).
- Each card covers one distinct concept or fact; no near-duplicate cards.
- When the user provides syllabus topics: create cards ONLY about those topics, and tag each card with the single most relevant topic using the EXACT topic text from the list. If none matches, omit the topic field.
- If the chunk contains no meaningful lecture content, return {"cards": []}."""


def _set(recording_id: int, **fields) -> None:
    cols = ", ".join(f"{k}=?" for k in fields)
    with db.get_conn() as conn:
        conn.execute(f"UPDATE recordings SET {cols} WHERE id=?", (*fields.values(), recording_id))


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {p.stderr[-500:]}")
    return p


def prepare_audio(src: str, work_dir) -> tuple:
    """Loudness-normalize + denoise + convert to 16kHz mono WAV. Returns (wav_path, duration)."""
    filters = ["highpass=f=80"]
    if RNNOISE_MODEL.exists():
        filters.append(f"arnndn=m={RNNOISE_MODEL}")
    else:
        # FFT denoiser: built into ffmpeg, no model file needed. Decent on babble hiss.
        filters.append("afftdn=nr=12:nf=-25")
    filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")

    wav = work_dir / "source_16k.wav"
    _run([
        "ffmpeg", "-y", "-hide_banner", "-i", src,
        "-vn", "-af", ",".join(filters),
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        str(wav),
    ])
    p = _run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(wav),
    ])
    return wav, float(p.stdout.strip() or 0)


def split_chunks(wav, work_dir) -> list:
    _run([
        "ffmpeg", "-y", "-hide_banner", "-i", str(wav),
        "-f", "segment", "-segment_time", str(CHUNK_SECONDS),
        "-reset_timestamps", "1", "-c", "copy",
        str(work_dir / "chunk_%04d.wav"),
    ])
    return sorted(work_dir.glob("chunk_*.wav"))


def _transcribe_chunk(path) -> tuple[str, list]:
    from .transcriber import transcribe  # lazy: mlx import is slow + may be absent

    result = transcribe(path)
    return (result.get("text") or "").strip(), result.get("segments") or []


def _ollama_chat(payload: dict) -> dict:
    from . import llm
    content = llm.chat(
        payload["messages"],
        schema=payload.get("format"),
        num_ctx=(payload.get("options") or {}).get("num_ctx", 65536),
        num_predict=(payload.get("options") or {}).get("num_predict", 8192),
        temperature=(payload.get("options") or {}).get("temperature", 0.2),
        timeout=1800)
    return {"message": {"content": content}}


def _parse_cards_json(content: str) -> list:
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end < 0:
            return []
        data = json.loads(content[start : end + 1])
    cards = data.get("cards") if isinstance(data, dict) else data
    return cards if isinstance(cards, list) else []


def extract_cards(text: str, notebook_name: str, topics: str | None = None) -> list:
    focus = ""
    if topics and topics.strip():
        focus = (
            "The course covers ONLY these syllabus topics:\n"
            f"{topics.strip()}\n"
            "Create flashcards ONLY about these topics. Skip personal anecdotes, classroom "
            "logistics, and any content that does not map to a listed topic. "
            "Tag each card with the exact topic text it belongs to.\n\n"
        )
    user_msg = (
        f"Class: {notebook_name}\n"
        f"{focus}"
        f"Full lecture transcript (do not truncate; cover everything important):\n\n"
        f"{text}"
    )
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "stream": False,
        "think": False,
        "format": EXTRACT_SCHEMA,
        "options": {"temperature": 0.2, "num_ctx": LLM_NUM_CTX, "num_predict": 8192},
        "keep_alive": "5m",
    }
    try:
        content = _ollama_chat(payload)["message"]["content"]
    except Exception:
        # Older Ollama without structured output: retry with plain chat, parse manually
        payload.pop("format", None)
        payload.pop("think", None)
        content = _ollama_chat(payload)["message"]["content"]
    return _parse_cards_json(content)


def _norm_key(s: str) -> str:
    s = re.sub(r"[^a-z0-9 ]+", "", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def clean_cards(raw_cards: list, seen: set, cap: int = 100000) -> list:
    """Returns list of (question, answer, topic_or_None)."""
    out = []
    for c in raw_cards:
        if not isinstance(c, dict):
            continue
        q = str(c.get("question", "")).strip()
        a = str(c.get("answer", "")).strip()
        if len(q) < 8 or len(a) < 2 or q.lower() == a.lower():
            continue
        key = _norm_key(q)
        if not key or key in seen:
            continue
        seen.add(key)
        topic = str(c.get("topic") or "").strip() or None
        out.append((q, a, topic))
        if len(out) >= cap:
            break
    return out


def _unload_ollama() -> None:
    try:
        import requests

        requests.post(f"{OLLAMA_URL}/api/generate", json={"model": OLLAMA_MODEL, "keep_alive": 0}, timeout=30)
    except Exception:
        pass


def _meaningful(text: str, min_words: int = 20) -> bool:
    return sum(1 for w in text.split() if len(w) >= 3) >= min_words


def split_text(text: str, size: int = 6000) -> list[str]:
    """Split long text into word-boundary blocks the LLM can chew per call."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    out, cur = [], ""
    for word in text.split():
        if len(cur) + len(word) + 1 > size and cur:
            out.append(cur.strip())
            cur = word
        else:
            cur = (cur + " " + word).strip()
    if cur:
        out.append(cur.strip())
    return out


def _store_chunk(recording_id: int, text: str, start_sec: float = 0.0) -> None:
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO chunks(recording_id, idx, start_sec, text) VALUES (?,?,?,?)",
            (recording_id, 0, start_sec, text),
        )


def store_transcript(recording_id: int, segments: list) -> str:
    """Persist timestamped segments as chunks. Returns the joined transcript text."""
    with db.get_conn() as conn:
        conn.execute("DELETE FROM chunks WHERE recording_id=?", (recording_id,))
        for i, seg in enumerate(segments):
            t = (seg.get("text") or "").strip()
            if not t:
                continue
            conn.execute(
                "INSERT INTO chunks(recording_id, idx, start_sec, text) VALUES (?,?,?,?)",
                (recording_id, i, float(seg.get("start") or 0), t),
            )
    return "\n\n".join((s.get("text") or "").strip() for s in segments if (s.get("text") or "").strip())


def _scan_tests(recording_id: int, notebook_id: int) -> None:
    """Scan a transcript for test announcements (only once the rec is assigned)."""
    import datetime as _dt
    from . import exams as _exams

    try:
        _exams.scan_recording(recording_id, notebook_id, _dt.date.today().isoformat())
    except Exception:
        pass  # one failing scan never kills the pipeline


def finish_assignment(recording_id: int, notebook_id: int) -> None:
    """Run once a human assigns an inbox (escrowed) recording to a notebook.
    Scans for test announcements; NEVER generates flashcards (that is per-test scope)."""
    _set(recording_id, status="done", progress=1.0,
         note="Assigned — scanning transcript for test announcements…")
    _scan_tests(recording_id, notebook_id)
    _set(recording_id, status="done", progress=1.0,
         note="Assigned & transcribed — flashcards generate from a test's scope.")


def _classify_and_escrow(recording_id: int, text: str) -> None:
    """Inbox path: classify the transcript, then hold it as 'unclassified'.
    NEVER files the recording — filing is a human decision in the inbox."""
    suggestion = None
    _set(recording_id, status="classifying", progress=0.95,
         note="Transcribed — classifying…", error=None)
    try:
        from . import classify as _classify

        sug = _classify.classify(text)
        suggestion = json.dumps(sug, ensure_ascii=False) if sug else None
    except Exception:
        suggestion = None
    note = "Transcribed — assign it to a notebook from the Suggest tab."
    _set(recording_id, status="unclassified", progress=1.0, note=note,
         suggestion=suggestion, error=None)


def _process_notes(recording_id: int, rec) -> None:
    """OCR handwritten-note images/PDFs into a transcript chunk."""
    from .notes import ocr_file

    _set(recording_id, status="reading", progress=0.05, error=None)
    text = ocr_file(rec["stored_path"])
    _store_chunk(recording_id, text)
    if not _meaningful(text, min_words=10):
        _set(recording_id, status="done", progress=1.0,
             note="No readable text found in the notes — blurry or not handwriting?")
        return
    if rec["notebook_id"] is None:
        _classify_and_escrow(recording_id, text)
    else:
        _set(recording_id, status="done", progress=1.0,
             note="Notes read — flashcards generate from a test's scope.")


def process_recording(recording_id: int) -> None:
    """Full pipeline for one recording. Serialized by _pipeline_lock.

    Assigned recording (notebook set, e.g. re-process):
      denoise -> transcribe -> store -> scan tests -> done.
    Inbox recording (notebook NULL):
      denoise -> transcribe -> store -> classify -> 'unclassified' (escrow).
    LLM (classify) runs ONLY for inbox recordings, after transcription — never
    during upload. Flashcard decks are generated separately, per test scope.
    """
    with _pipeline_lock:
        with db.get_conn() as conn:
            rec = conn.execute(
                "SELECT r.*, n.name AS notebook_name FROM recordings r "
                "LEFT JOIN notebooks n ON n.id = r.notebook_id WHERE r.id=?",
                (recording_id,),
            ).fetchone()
        if rec is None:
            return
        work_dir = AUDIO_DIR / f"work_{recording_id}"
        try:
            if rec["kind"] == "notes":
                _process_notes(recording_id, rec)
                return
            work_dir.mkdir(parents=True, exist_ok=True)
            _set(recording_id, status="denoising", progress=0.02, error=None)
            wav, duration = prepare_audio(rec["stored_path"], work_dir)
            _set(recording_id, duration_sec=duration, status="transcribing",
                 progress=0.1)
            text, segments = _transcribe_chunk(wav)  # whole recording, one pass
            _set(recording_id, duration_sec=duration, progress=0.15)
            text = store_transcript(recording_id, segments)  # timestamped segments

            if not _meaningful(text):
                _set(recording_id, status="done", progress=1.0,
                     note="No clear speech found — the recording may be too noisy or empty.")
                return

            if rec["notebook_id"] is None:
                # inbox -> classify + escrow, wait for human assignment
                _classify_and_escrow(recording_id, text)
            else:
                _scan_tests(recording_id, rec["notebook_id"])
                _set(recording_id, status="done", progress=1.0,
                     note="Transcribed — flashcards generate from a test's scope.")
        except Exception as e:  # noqa: BLE001 — surface any failure on the recording row
            _set(recording_id, status="error", error=str(e)[:800])
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
            _unload_ollama()