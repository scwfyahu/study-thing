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
    CHUNK_SECONDS,
    MAX_CARDS_PER_CHUNK,
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


def _transcribe_chunk(path) -> str:
    from .transcriber import transcribe  # lazy: mlx import is slow + may be absent

    result = transcribe(path)
    return (result.get("text") or "").strip()


def _ollama_chat(payload: dict) -> dict:
    import requests

    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=1800)
    if r.status_code == 400 and "think" in payload:
        payload.pop("think")
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=1800)
    r.raise_for_status()
    return r.json()


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


def extract_cards(text: str, notebook_name: str, chunk_idx: int, total: int, topics: str | None = None) -> list:
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
        f"This is part {chunk_idx + 1} of {total} of one lecture recording.\n\n"
        f"Transcript chunk:\n{text}"
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
        "options": {"temperature": 0.2, "num_ctx": 8192, "num_predict": 4096},
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


def clean_cards(raw_cards: list, seen: set, cap: int = MAX_CARDS_PER_CHUNK) -> list:
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


def _extract_cards_from_texts(recording_id: int, rec, texts: list[tuple[int, str]]) -> None:
    """Shared card-extraction stage: chunk texts -> LLM cards -> dedupe/store."""
    seen: set = set()
    total_cards = 0
    n = len(texts)
    for k, (i, text) in enumerate(texts):
        _set(recording_id, status="extracting", progress=0.60 + 0.38 * (k / max(n, 1)))
        raw = extract_cards(text, rec["notebook_name"], i, n, rec["topics"])
        for q, a, topic in clean_cards(raw, seen):
            with db.get_conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO cards(recording_id, question, answer, topic, position) VALUES (?,?,?,?,?)",
                    (recording_id, q, a, topic, total_cards),
                )
            total_cards += 1

    if total_cards == 0 and rec["topics"] and (rec["topics"] or "").strip():
        _set(recording_id, status="done", progress=1.0,
             note=("0 flashcards — the content didn't match this notebook's Focus "
                   "topics. Move to the right class (dropdown) or edit Focus, then Re-process."))
    else:
        _set(recording_id, status="done", progress=1.0, note=f"{total_cards} flashcards")


def _process_notes(recording_id: int, rec) -> None:
    """OCR handwritten-note images/PDFs, then extract cards from the text."""
    from .notes import ocr_file

    _set(recording_id, status="reading", progress=0.05, error=None)
    text = ocr_file(rec["stored_path"])
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO chunks(recording_id, idx, start_sec, text) VALUES (?,?,?,?)",
            (recording_id, 0, 0, text),
        )
    if not _meaningful(text, min_words=10):
        _set(recording_id, status="done", progress=1.0,
             note="No readable text found in the notes — blurry or not handwriting?")
        return
    _extract_cards_from_texts(recording_id, rec, [(0, text)])


def process_recording(recording_id: int) -> None:
    """Full pipeline for one recording. Serialized by _pipeline_lock."""
    with _pipeline_lock:
        with db.get_conn() as conn:
            rec = conn.execute(
                "SELECT r.*, n.name AS notebook_name, n.topics AS topics FROM recordings r "
                "JOIN notebooks n ON n.id = r.notebook_id WHERE r.id=?",
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
            _set(recording_id, duration_sec=duration, status="splitting", progress=0.04)
            chunk_files = split_chunks(wav, work_dir)
            n = len(chunk_files)

            texts = []
            for i, cf in enumerate(chunk_files):
                _set(recording_id, status="transcribing", progress=0.05 + 0.50 * (i / max(n, 1)))
                text = _transcribe_chunk(cf)
                with db.get_conn() as conn:
                    conn.execute(
                        "INSERT INTO chunks(recording_id, idx, start_sec, text) VALUES (?,?,?,?)",
                        (recording_id, i, i * CHUNK_SECONDS, text),
                    )
                texts.append((i, text))

            # tests are extracted right after transcription — don't wait for card generation
            try:
                import datetime as _dt
                from . import exams as _exams

                _exams.scan_recording(recording_id, rec["notebook_id"], _dt.date.today().isoformat())
            except Exception:
                pass

            meaningful = [(i, t) for i, t in texts if _meaningful(t)]
            if not meaningful:
                _set(recording_id, status="done", progress=1.0,
                     note="No clear speech found — the recording may be too noisy or empty.")
                return

            seen: set = set()
            total_cards = 0
            for k, (i, text) in enumerate(meaningful):
                _set(recording_id, status="extracting", progress=0.60 + 0.38 * (k / max(len(meaningful), 1)))
                raw = extract_cards(text, rec["notebook_name"], i, n, rec["topics"])
                for q, a, topic in clean_cards(raw, seen):
                    with db.get_conn() as conn:
                        conn.execute(
                            "INSERT OR IGNORE INTO cards(recording_id, question, answer, topic, position) VALUES (?,?,?,?,?)",
                            (recording_id, q, a, topic, total_cards),
                        )
                    total_cards += 1

            if total_cards == 0 and rec["topics"] and (rec["topics"] or "").strip():
                _set(recording_id, status="done", progress=1.0,
                     note=("0 flashcards — the audio content didn't match this notebook's Focus "
                           "topics. Move the recording to the right class (dropdown) or edit "
                           "Focus, then Re-process."))
            else:
                _set(recording_id, status="done", progress=1.0, note=f"{total_cards} flashcards")
        except Exception as e:  # noqa: BLE001 — surface any failure on the recording row
            _set(recording_id, status="error", error=str(e)[:800])
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
            _unload_ollama()