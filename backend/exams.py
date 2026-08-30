"""Detect announced tests/quizzes/exams + their scope from lecture transcripts."""
import json
import re

from . import db
from .config import OLLAMA_MODEL, OLLAMA_URL

DETECT_SCHEMA = {
    "type": "object",
    "properties": {
        "announcements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "date_text": {"type": "string"},
                    "date_iso": {"type": ["string", "null"]},
                    "scope": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title"],
            },
        }
    },
    "required": ["announcements"],
}


def _ollama_json(messages: list[dict]) -> dict:
    import requests

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "format": DETECT_SCHEMA,
        "options": {"temperature": 0.1, "num_ctx": 8192, "num_predict": 2048},
        "keep_alive": "5m",
    }
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=900)
    if r.status_code == 400 and "think" in payload:
        payload.pop("think")
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=900)
    r.raise_for_status()
    content = re.sub(r"<think>.*?</think>", "", r.json()["message"]["content"], flags=re.S)
    return json.loads(content)


def scan_recording(recording_id: int, notebook_id: int, today: str) -> int:
    """Scan one recording's chunks for assessment announcements. Returns count stored."""
    with db.get_conn() as conn:
        chunks = conn.execute(
            "SELECT idx, text FROM chunks WHERE recording_id=? ORDER BY idx", (recording_id,)
        ).fetchall()
    if not chunks:
        return 0

    found = []
    for c in chunks:
        if len(c["text"].split()) < 30:
            continue
        try:
            res = _ollama_json([
                {"role": "system", "content": (
                    "You scan a lecture transcript chunk for assessment announcements: "
                    "quizzes, tests, exams, quarter/summative assessments, practicals, "
                    "major project deadlines. Today's date is " + today + ". "
                    "For each announcement: title (short), date_text (the EXACT phrase as spoken, "
                    "e.g. 'September 9th' / 'next Friday' — never empty if a date is mentioned), "
                    "date_iso (resolve relative dates to YYYY-MM-DD using today's date; null if no date), "
                    "scope (list of topics explicitly announced as covered; empty if not stated). "
                    "Return the schema exactly."
                )},
                {"role": "user", "content": f"Transcript chunk {c['idx']}:\n{c['text'][:6000]}"},
            ])
            for a in res.get("announcements", []):
                title = str(a.get("title", "")).strip()
                if title and len(title) > 2:
                    found.append({
                        "title": title,
                        "date_text": str(a.get("date_text") or "").strip(),
                        "date_iso": (a.get("date_iso") or "").strip() or None,
                        "scope": [str(s).strip() for s in (a.get("scope") or []) if str(s).strip()],
                    })
        except Exception:
            continue  # one chunk failing must not kill the scan

    # dedupe by title (case-insensitive), newest chunk wins
    seen = {}
    for a in found:
        key = a["title"].lower()
        seen.setdefault(key, a)

    with db.get_conn() as conn:
        for a in seen.values():
            conn.execute(
                "INSERT INTO tests(notebook_id, recording_id, title, date_text, date_iso, scope) "
                "VALUES (?,?,?,?,?,?)",
                (notebook_id, recording_id, a["title"], a["date_text"], a["date_iso"],
                 json.dumps(a["scope"], ensure_ascii=False)),
            )
    return len(seen)