"""Per-topic study reviewer generation (Philippine-English 'reviewer' = study guide)."""
import re

from . import db
from .config import OLLAMA_MODEL, OLLAMA_URL

REVIEWER_PROMPT = """You write a study reviewer (study guide) for ONE topic of a course, using ONLY the provided flashcards from the student's own lecture notes.

Rules:
- Use ONLY facts present in the cards. Never invent or add outside content.
- Structure (markdown):
  # <Topic>
  ## Key Concepts — bulleted definitions, one line each
  ## Main Points — the most testable ideas, short bullets
  ## Memory Hooks — 2-3 mnemonics or associations (invent freely; they are study aids)
  ## Practice Questions — 5-7 reworded questions from the cards (no answers here)
  ## Answer Key — short answers to the practice questions
- Keep it tight: roughly 300-600 words. Prioritize what an exam would test.
- If a card is off-topic, skip it silently."""


def _ollama(messages: list[dict]) -> str:
    import requests

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.3, "num_ctx": 16384, "num_predict": 4096},
        "keep_alive": "5m",
    }
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=1800)
    if r.status_code == 400 and "think" in payload:
        payload.pop("think")
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=1800)
    r.raise_for_status()
    content = r.json()["message"]["content"]
    return re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def notebook_cards_with_topics(notebook_id: int) -> list:
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT c.question, c.answer, c.topic FROM cards c
               JOIN recordings r ON r.id = c.recording_id
               WHERE r.notebook_id=? ORDER BY r.id, c.position""",
            (notebook_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def generate_reviewer(notebook_id: int, notebook_name: str, notebook_topics: str | None, topic: str) -> str:
    cards = notebook_cards_with_topics(notebook_id)
    if not cards:
        raise ValueError("no flashcards in this notebook yet")

    chosen = None
    if topic and topic != "__all__":
        tn = _norm(topic)
        chosen = [c for c in cards if c["topic"] and (_norm(c["topic"]) == tn or tn in _norm(c["topic"]))]
        if not chosen:  # fallback: fuzzy contains either direction
            chosen = [c for c in cards if c["topic"] and (_norm(c["topic"]) in tn or tn in _norm(c["topic"]))]
        if not chosen:
            chosen = cards  # honest fallback
    else:
        chosen = cards

    card_lines = "\n".join(
        f"Q: {c['question']}\nA: {c['answer']}" + (f"\nTopic: {c['topic']}" if c.get("topic") else "")
        for c in chosen
    )
    user = (
        f"Course: {notebook_name}\n"
        f"Syllabus topics: {notebook_topics or '(none set)'}\n"
        f"Reviewer topic requested: {topic if topic and topic != '__all__' else 'ALL topics'}\n\n"
        f"Flashcards ({len(chosen)} of {len(cards)} total):\n{card_lines}"
    )
    return _ollama([{"role": "system", "content": REVIEWER_PROMPT}, {"role": "user", "content": user}])