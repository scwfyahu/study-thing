"""Deck lifecycle: scope guessing + on-demand flashcard generation per quiz deck."""
import json
import logging
import re

from . import db
from .config import OLLAMA_MODEL, OLLAMA_URL

SCOPE_SCHEMA = {
    "type": "object",
    "properties": {"scope": {"type": "array", "items": {"type": "string"}}},
    "required": ["scope"],
}


def _ollama(messages: list[dict], schema=None, timeout=600, retries=0) -> str:
    from . import llm
    return llm.chat(messages, schema=schema, num_ctx=65536, num_predict=8192,
                    temperature=0.2, timeout=timeout, retries=retries)


def guess_scope(notebook_name: str, syllabus_topics: list[str], announcement: str,
                 retries: int = 0) -> list[str]:
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
        ], SCOPE_SCHEMA, timeout=300, retries=retries)
        data = json.loads(raw)
        scope = [str(t).strip() for t in data.get("scope", []) if str(t).strip()]
        # fall back to the full syllabus rather than an empty scope
        return scope or syllabus_topics
    except Exception:
        # LLM unreachable/flaky — scope = everything on the syllabus
        return syllabus_topics


logger = logging.getLogger(__name__)


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
            with db.get_conn() as conn:
                conn.execute(
                    "UPDATE decks SET progress=? WHERE id=?",
                    (0.05 + 0.9 * (k / max(n, 1)), deck_id))
            raw = pipeline.extract_cards(ch["text"], nb["name"], "\n".join(scope) if scope else None)
            for q, a, topic in pipeline.clean_cards(raw, seen):
                with db.get_conn() as conn:
                    conn.execute(
                        "INSERT INTO cards(notebook_id, recording_id, deck_id, question, answer, topic, position) "
                        "SELECT notebook_id, id, ?, ?, ?, ? FROM recordings WHERE id = ?",
                        (deck_id, q, a, topic, total, ch["recording_id"]),
                    )
                total += 1
        except Exception:
            continue
    with db.get_conn() as conn:
        conn.execute("UPDATE decks SET status='ready', error=NULL WHERE id=?", (deck_id,))
    return total

def auto_decks_for_tests(nb_id: int, test_ids: list) -> None:
    """Generate the deck for each CONFIRMED test. Reuses the draft deck
    created at scan time (no duplicate decks). No prompts."""
    import json as _json
    for tid in test_ids:
        try:
            with db.get_conn() as conn:
                t = conn.execute("SELECT * FROM tests WHERE id=?", (tid,)).fetchone()
            if t is None or not t["confirmed"]:
                continue  # wait for user to confirm the scope first
            nb = conn.execute(
                "SELECT name, topics, syllabus FROM notebooks WHERE id=?",
                (nb_id,)).fetchone()
            syllabus_topics = [t.strip() for t in (nb["topics"] or "").splitlines() if t.strip()]
            ann = f"{t['title']} ({t['date_text'] or ''})"
            try:
                sc = _json.loads(t["scope"] or "[]")
                if sc:
                    ann += f". Scope mentioned: {', '.join(sc)}"
            except Exception:
                pass
            with db.get_conn() as conn:
                deck = conn.execute(
                    "SELECT id FROM decks WHERE quiz_id=? ORDER BY id DESC LIMIT 1",
                    (tid,)).fetchone()
                did = deck["id"] if deck else None
            if did is None:
                cur = conn.execute(
                    "INSERT INTO decks(notebook_id, quiz_id, title, scope,"
                    " status) VALUES (?,?,?,?,'generating')",
                    (nb_id, tid, t["title"], _json.dumps([])))
                conn.commit()
                did = cur.lastrowid
            # apply the confirmed scope to the deck, then generate
            scope = guess_scope(nb["name"], syllabus_topics, ann)
            conn.execute("UPDATE decks SET scope=?, status='generating' WHERE id=?",
                         (_json.dumps(scope, ensure_ascii=False), did))
            conn.commit()
            generate_deck_cards(did)
            logger.info("auto-deck %s (%s) generated for test %s", did,
                        t["title"], tid)
        except Exception:
            logger.exception("auto deck failed for test %s", tid)
