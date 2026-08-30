"""Deck lifecycle: scope guessing + on-demand flashcard generation per quiz deck."""
import json
import re

from . import db
from .config import OLLAMA_MODEL, OLLAMA_URL

SCOPE_SCHEMA = {
    "type": "object",
    "properties": {"scope": {"type": "array", "items": {"type": "string"}}},
    "required": ["scope"],
}


def _ollama(messages: list[dict], schema=None, timeout=600) -> str:
    import requests

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.2, "num_ctx": 16384, "num_predict": 4096},
        "keep_alive": "5m",
    }
    if schema:
        payload["format"] = schema
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
    if r.status_code == 400 and "think" in payload:
        payload.pop("think")
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
    r.raise_for_status()
    return re.sub(r"<think>.*?</think>", "", r.json()["message"]["content"], flags=re.S).strip()


def guess_scope(notebook_name: str, syllabus_topics: list[str], announcement: str) -> list[str]:
    """Auto-guess a quiz's scope: most relevant syllabus topics for the announced assessment."""
    try:
        raw = _ollama([
            {"role": "system", "content": (
                "You estimate the study scope for an upcoming assessment. Given the course's "
                "syllabus topics and what the teacher announced, return the syllabus topics the "
                "assessment most likely covers (usually 2-5). Use EXACT syllabus topic text. "
                "If a topic isn't in the syllabus, phrase it as a short scope line. "
                "Return the schema exactly."
            )},
            {"role": "user", "content": (
                f"Course: {notebook_name}\n"
                f"Syllabus topics:\n" + "\n".join(f"- {t}" for t in syllabus_topics) +
                f"\n\nTeacher's announcement:\n{announcement}"
            )},
        ], SCOPE_SCHEMA, timeout=300)
        data = json.loads(raw)
        return [str(t).strip() for t in data.get("scope", []) if str(t).strip()]
    except Exception:
        return []


def generate_deck_cards(deck_id: int) -> int:
    """Extract flashcards for a deck from all transcribed chunks in its notebook."""
    from . import pipeline

    with db.get_conn() as conn:
        deck = conn.execute("SELECT * FROM decks WHERE id=?", (deck_id,)).fetchone()
        if deck is None:
            return 0
        nb = conn.execute(
            "SELECT name, topics FROM notebooks WHERE id=?", (deck["notebook_id"],)
        ).fetchone()
        scope = json.loads(deck["scope"] or "[]")
        chunks = conn.execute(
            """SELECT r.id AS recording_id, c.id AS chunk_id, c.text
               FROM chunks c JOIN recordings r ON r.id = c.recording_id
               WHERE r.notebook_id=? ORDER BY r.id, c.idx""",
            (deck["notebook_id"],),
        ).fetchall()

    with db.get_conn() as conn:
        conn.execute("UPDATE decks SET status='generating', error=NULL WHERE id=?", (deck_id,))
    conn = db.get_conn()
    conn.execute("DELETE FROM cards WHERE deck_id=?", (deck_id,))
    conn.commit()
    conn.close()

    seen: set = set()
    total = 0
    n = max(len(chunks), 1)
    for k, ch in enumerate(chunks):
        try:
            raw = pipeline.extract_cards(ch["text"], nb["name"], k, n, "\n".join(scope) if scope else None)
            for q, a, topic in pipeline.clean_cards(raw, seen):
                with db.get_conn() as conn:
                    conn.execute(
                        "INSERT INTO cards(recording_id, deck_id, question, answer, topic, position) "
                        "VALUES (?,?,?,?,?,?)",
                        (ch["recording_id"], deck_id, q, a, topic, total),
                    )
                total += 1
        except Exception:
            continue
    with db.get_conn() as conn:
        conn.execute("UPDATE decks SET status='ready', error=NULL WHERE id=?", (deck_id,))
    return total