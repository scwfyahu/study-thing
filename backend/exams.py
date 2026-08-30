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


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


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
                    "For each announcement: title (short, SPECIFIC — e.g. 'Quiz Two', 'Quarter Exam', "
                    "'Unit 3 Test'), date_text (the EXACT phrase as spoken, "
                    "e.g. 'September 9th' / 'next Friday' — never empty if a date is mentioned; "
                    "if no concrete date, use the announced timeframe phrase like 'exam week'), "
                    "date_iso (ISO 8601 YYYY-MM-DD. Convert concrete calendar dates — 'September 9th' "
                    "→ 2026-09-09, 'next Friday' → resolve using today's date — ONLY when a specific "
                    "day is stated. For vague timeframes like 'exam week', 'the week after', "
                    "'a week before', 'sometime next month' → date_iso MUST be null and keep the "
                    "vague phrase in date_text. Never guess a specific day from vagueness.), "
                    "scope (list of topics explicitly announced as covered; empty if not stated). "
                    "IMPORTANT: do NOT report schedule logistics — coordination talk like 'the schedule "
                    "will be posted', who announces dates, exam-week planning, or generic mentions of "
                    "'a test' without a named assessment. Only report concrete named assessments. "
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

    # dedupe by title (case-insensitive); a concrete date beats a vague one
    seen = {}
    VAGUE = {"test schedule", "exam schedule", "schedule", "test details", "quiz schedule", "the test"}
    for a in found:
        if _norm(a["title"]) in VAGUE:
            continue
        key = a["title"].lower()
        cur = seen.get(key)
        if cur is None or (a["date_iso"] and not cur["date_iso"]):
            seen[key] = a

    with db.get_conn() as conn:
        for a in seen.values():
            if not a["date_iso"]:
                # No concrete date -> keep out of the schedule (low confidence).
                # A later recording with a concrete date will create/upgrade the row.
                continue
            row = conn.execute(
                "SELECT id, date_iso FROM tests WHERE notebook_id=? AND title=? COLLATE NOCASE",
                (notebook_id, a["title"]),
            ).fetchone()
            if row:
                if row["date_iso"] is None:
                    # upgrade: a recording finally confirmed the date
                    conn.execute(
                        "UPDATE tests SET date_text=?, date_iso=?, scope=?, recording_id=? WHERE id=?",
                        (a["date_text"], a["date_iso"], json.dumps(a["scope"], ensure_ascii=False),
                         recording_id, row["id"]),
                    )
                test_id = row["id"]
            else:
                cur = conn.execute(
                    "INSERT INTO tests(notebook_id, recording_id, title, date_text, date_iso, scope) "
                    "VALUES (?,?,?,?,?,?)",
                    (notebook_id, recording_id, a["title"], a["date_text"], a["date_iso"],
                     json.dumps(a["scope"], ensure_ascii=False)),
                )
                test_id = cur.lastrowid
            # auto-create a draft deck for this quiz (scope guessed later at confirm-time)
            has_deck = conn.execute(
                "SELECT 1 FROM decks WHERE quiz_id=?", (test_id,)
            ).fetchone()
            if not has_deck:
                conn.execute(
                    "INSERT INTO decks(notebook_id, quiz_id, title, scope, status) VALUES (?,?,?,'[]','draft')",
                    (notebook_id, test_id, a["title"]),
                )
    return len(seen)