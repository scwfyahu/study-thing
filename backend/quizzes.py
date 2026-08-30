"""Quiz generation from flashcards, scoped to test scope/topic, MCQ with 4 choices, difficulty 1-10."""
import json
import re

from . import db
from .config import OLLAMA_MODEL, OLLAMA_URL

QUIZ_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "choices": {"type": "array", "items": {"type": "string"}, "minItems": 4, "maxItems": 4},
                    "answer_index": {"type": "integer", "minimum": 0, "maximum": 3},
                    "explanation": {"type": "string"},
                },
                "required": ["question", "choices", "answer_index", "explanation"],
            },
        }
    },
    "required": ["questions"],
}

DIFFICULTY_GUIDE = {
    (1, 3): "easy: direct recall of definitions and facts straight from the notes; obvious correct answer, only one plausible distractor style.",
    (4, 7): "medium: application and comparison; requires understanding, distractors are plausible but wrong.",
    (8, 10): "hard: analysis, inference, and synthesis across concepts; subtle distractors that are partially true, requires careful reasoning.",
}


def _difficulty_guide(d: int) -> str:
    for (lo, hi), txt in DIFFICULTY_GUIDE.items():
        if lo <= d <= hi:
            return txt
    return DIFFICULTY_GUIDE[(4, 7)][1]


def _ollama_json(messages: list[dict]) -> dict:
    import requests

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "format": QUIZ_SCHEMA,
        "options": {"temperature": 0.4, "num_ctx": 16384, "num_predict": 8192},
        "keep_alive": "5m",
    }
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=1800)
    if r.status_code == 400 and "think" in payload:
        payload.pop("think")
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=1800)
    r.raise_for_status()
    content = re.sub(r"<think>.*?</think>", "", r.json()["message"]["content"], flags=re.S)
    return json.loads(content)


def generate_quiz(notebook_id: int, source: str, scope_terms: list[str], difficulty: int, count: int) -> list:
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT c.question, c.answer, c.topic FROM cards c
               JOIN recordings r ON r.id = c.recording_id
               WHERE r.notebook_id=? ORDER BY r.id, c.position""",
            (notebook_id,),
        ).fetchall()
    cards = [dict(r) for r in rows]
    if not cards:
        raise ValueError("no flashcards in this notebook yet")

    terms = [t.strip().lower() for t in scope_terms if str(t).strip()]
    if terms:
        matched = [
            c for c in cards
            if c["topic"] and any(t in c["topic"].lower() or c["topic"].lower() in t for t in terms)
        ]
        if matched:
            cards = matched

    card_lines = "\n".join(f"Q: {c['question']}\nA: {c['answer']}" for c in cards)
    user = (
        f"Source: {source}\n"
        f"Difficulty: {difficulty}/10 — {_difficulty_guide(difficulty)}\n"
        f"Create {count} multiple-choice questions (4 choices each). "
        f"Every question must be answerable ONLY from the flashcards below. "
        f"Vary the position of the correct answer. Provide a short explanation for each.\n\n"
        f"Flashcards ({len(cards)}):\n{card_lines}"
    )
    res = _ollama_json([
        {"role": "system", "content": (
            "You write exam-style multiple-choice questions from lecture flashcards. "
            "Rules: 4 choices per question, exactly one correct; questions test the source "
            "content only; difficulty follows the user's instruction (1-10); answer_index is 0-3; "
            "explanations cite the underlying fact. Return the schema exactly."
        )},
        {"role": "user", "content": user},
    ])

    out = []
    for q in res.get("questions", []):
        choices = [str(c).strip() for c in (q.get("choices") or []) if str(c).strip()]
        if len(choices) != 4:
            continue
        qi = q.get("answer_index")
        if not isinstance(qi, int) or not (0 <= qi < 4):
            continue
        out.append({
            "question": str(q.get("question", "")).strip(),
            "choices": choices,
            "answer_index": qi,
            "explanation": str(q.get("explanation", "")).strip(),
        })
        if len(out) >= count:
            break
    return out