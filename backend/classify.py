"""Autoclassifier: pick which class notebook a transcript belongs to.

Runs ONLY at assignment time (never during upload/transcribe). Returns a
*suggestion* (notebook + confidence) — filing is always a human decision in
the "Suggest notebook" inbox. Never auto-moves.
"""
import json
import logging

from . import db

logger = logging.getLogger(__name__)

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "notebook_id": {"type": ["integer", "null"]},
        "confidence": {"type": "number"},
        "topics": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["notebook_id", "confidence", "reason"],
}

# keep a single transcript sample small enough for a cheap, fast call
_SAMPLE_CHARS = 12_000
_MAX_NOTEBOOKS = 40


def _ollama_json(messages: list[dict]) -> dict:
    from . import llm

    content = llm.chat(messages, schema=CLASSIFY_SCHEMA, num_ctx=16384,
                       num_predict=1500, temperature=0.1, timeout=900)
    return json.loads(content)


def _profiles(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT id, name, topics, syllabus FROM notebooks ORDER BY name"
    ).fetchall()
    out = []
    for r in rows:
        topics = [t.strip() for t in (r["topics"] or "").splitlines() if t.strip()]
        syl = (r["syllabus"] or "").strip()
        profile = {
            "id": r["id"],
            "name": r["name"],
            "topics": topics[:30],
            "syllabus": syl[:600],
        }
        out.append(profile)
    return out


def classify(text: str, notebooks: list[dict] | None = None) -> dict:
    """Suggest the best notebook for a transcript. Never files anything.

    Returns {notebook_id, name, confidence, topics, reason}. notebook_id is
    null when nothing matches (confidence low) — the transcript stays escrowed.
    """
    if not notebooks:
        with db.get_conn() as conn:
            notebooks = _profiles(conn)
    notebooks = notebooks[: _MAX_NOTEBOOKS]
    if not notebooks:
        return {"notebook_id": None, "confidence": 0.0, "topics": [],
                "reason": "No notebooks exist yet — create one and assign."}

    sample = (text or "")[:_SAMPLE_CHARS].strip()
    nb_block = "\n\n".join(
        f"#{p['id']} — {p['name']}"
        + (("\nTopics: " + "; ".join(p["topics"])) if p["topics"] else "")
        + (("\nSyllabus: " + p["syllabus"]) if p["syllabus"] else "")
        for p in notebooks
    )
    try:
        res = _ollama_json([
            {"role": "system", "content": (
                "You match a lecture transcript to the course notebook it belongs to. "
                "Notebooks are given as '#<id> — <course name>' with optional topics/syllabus. "
                "Return: notebook_id = the single most likely notebook's <id>, or null if the "
                "transcript clearly does NOT belong to any listed course (e.g. a different subject "
                "not in the list, or noise with no lecture content). "
                "confidence = 0..1 how sure you are (be honest — 0.9+ only for a clear match). "
                "topics = the syllabus topics actually covered in the transcript (exact text). "
                "reason = one sentence justifying the pick. Return the schema exactly."
            )},
            {"role": "user", "content": (
                f"Candidate course notebooks:\n{nb_block}\n\n"
                f"Transcript sample (may be mid-lecture):\n{sample}"
            )},
        ])
        nid = res.get("notebook_id")
        # guard: id must be one of ours or we drop to null
        if nid is not None and not any(p["id"] == nid for p in notebooks):
            nid = None
        try:
            conf = min(1.0, max(0.0, float(res.get("confidence", 0.0))))
        except (TypeError, ValueError):
            conf = 0.0
        return {
            "notebook_id": nid,
            "name": next((p["name"] for p in notebooks if p["id"] == nid), None),
            "confidence": round(conf, 2),
            "topics": [str(t).strip() for t in (res.get("topics") or []) if str(t).strip()],
            "reason": str(res.get("reason") or "").strip(),
        }
    except Exception as e:  # noqa: BLE001 — LLM down: keep escrowed, no suggestion
        logger.warning("classify failed: %s", e)
        return {"notebook_id": None, "confidence": 0.0, "topics": [],
                "reason": f"Classification unavailable (LLM): {type(e).__name__}"}
