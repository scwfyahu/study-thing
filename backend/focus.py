"""Detailed Focus: a structured syllabus-derived model per notebook.

Replaces the flat "topics" line with per-topic depth (summary, subtopics,
weight, chapters, notes). Auto-generated from the full syllabus in a single
LLM pass tuned for fidelity, written as focus_topics rows. notebooks.topics is
kept in sync (joined names) so existing consumers (classification, scope
guessing, dropdowns) keep working unchanged.

Best-accuracy design: one detailed prompt that asks the LLM to read the actual
syllabus structure (units, sections, emphasis) and emit an outline whose units
carry summary + concrete subtopics + exam weight + chapter ranges, rather than
just a bare topic-name list.
"""
import json
import logging
import os
import re

from . import db

logger = logging.getLogger(__name__)

FOCUS_SCHEMA = {
    "type": "object",
    "properties": {
        "units": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "summary": {"type": "string"},
                    "subtopics": {"type": "array", "items": {"type": "string"}},
                    "weight": {"type": "integer"},
                    "chapters": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["name", "summary", "subtopics", "weight"],
            },
        }
    },
    "required": ["units"],
}

_SYSTEM = """You build a precise study Focus for a course from its syllabus.
Read the FULL syllabus structure (units/modules/sections, page ranges, grading
weights) and produce the course's focus units.

For EACH unit return exactly:
- name: the unit's exact/direct title from the syllabus.
- summary: 1-3 sentences on what this unit actually teaches (its core ideas).
- subtopics: 4-10 CONCRETE concepts/skills the student must master (specific,
  not vague — "linear regression assumptions", not "regression"). This is the
  highest-leverage field: be accurate and granular.
- weight: 1-5 exam priority. Base it on stated grading emphasis, contact time,
  or section depth; default 3 when unclear. Do not inflate.
- chapters: syllabus section/page range or chapter numbers for this unit, as
  stated (empty if not given).
- notes: instructor emphasis / caveats / commonly-tested wrinkles, when the
  syllabus or tone implies them (e.g. "teacher stresses definitions", "formula
  sheet provided"). Omit if nothing.

Return the schema exactly. Do not invent units not in the syllabus; if the
syllabus is too thin, still return what's there. Administrative sections
(grading, policies, schedule, references) are NOT units — skip them."""


def _loads_robust(content: str) -> dict:
    """Parse LLM output that may carry markdown fences / prose around JSON."""
    c = re.sub(r"```(?:json)?", "", content or "", flags=re.I).strip()
    c = re.sub(r"<think>.*?</think>", "", c, flags=re.S).strip()
    try:
        return json.loads(c)
    except Exception:
        s, e = c.find("{"), c.rfind("}")
        if s < 0 or e < 0:
            raise
        return json.loads(c[s : e + 1])


def _bounded_llm(messages) -> dict:
    """LLM call with bounded retries so a flaky provider can't hold a worker."""
    from . import llm

    prior = os.environ.get("STUDY_LLM_RETRIES")
    os.environ["STUDY_LLM_RETRIES"] = "1"
    try:
        content = llm.chat(messages, schema=FOCUS_SCHEMA, num_ctx=32768,
                           num_predict=4096, temperature=0.1, timeout=900)
        return _loads_robust(content)
    finally:
        if prior is None:
            os.environ.pop("STUDY_LLM_RETRIES", None)
        else:
            os.environ["STUDY_LLM_RETRIES"] = prior


def _heuristic_units(syllabus_text: str) -> list[dict]:
    """Fallback if the LLM is down: parse outline lines into name + weight +
    crude summary/subtopics so the Focus is still structured-ish."""
    ADMIN = ("grading", "polic", "reference", "textbook", "schedule",
             "attend", "quiz schedule", "course outline", "welcome",
             "instructor", "office hour", "course description")
    units = []
    for line in (syllabus_text or "").splitlines():
        s = line.strip()
        if not s or len(s) > 200:
            continue
        low = s.lower()
        if any(k in low for k in ADMIN):
            continue
        # clean leading bullets / plain numbering (keep "Unit N: Title" label)
        s = re.sub(r"^[\s\-•*]+\s*", "", s).strip()
        s = re.sub(r"^\d{1,2}[.)]\s*", "", s).strip()
        if not s:
            continue
        # weight from 'N%'
        wm = re.search(r"(\d{1,2})\s*%", s)
        weight = 3
        if wm:
            pct = int(wm.group(1))
            weight = 5 if pct >= 20 else 4 if pct >= 15 else 3 if pct >= 10 else 2
        # split name / description at first '. ' or ':'
        name = s
        desc = ""
        m = re.split(r"\.\s+|:\s+", s, maxsplit=1)
        if len(m) == 2 and len(m[0]) <= 70:
            name, desc = m[0].strip(), m[1].strip()
        # crude subtopics from the description
        subs = [x.strip().rstrip(".") for x in re.split(r"[,;]", desc)
                if x.strip() and len(x.strip()) > 3][:8]
        if not subs and desc:
            subs = [desc[:60]]
        units.append({"name": name[:90], "summary": desc[:220],
                      "subtopics": subs, "weight": weight, "chapters": "",
                      "notes": ""})
    return units


def generate(notebook_id: int, syllabus_text: str) -> int:
    """Build detailed focus_topics for a notebook from its syllabus.

    Idempotent: replaces existing rows. Returns the number of units written
    (0 on total failure — leaves prior focus intact).
    """
    units = None
    try:
        units = _bounded_llm([
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"Syllabus text:\n{(syllabus_text or '')[:24000]}"},
        ]).get("units")
    except Exception as e:  # noqa: BLE001
        logger.warning("focus LLM failed: %s", e)
    if not units:
        units = _heuristic_units(syllabus_text) or None
    if not units:
        return 0

    rows = []
    for u in units:
        name = str(u.get("name") or "").strip()
        if not name:
            continue
        subs = [str(s).strip() for s in (u.get("subtopics") or []) if str(s).strip()]
        try:
            weight = max(1, min(5, int(u.get("weight", 3))))
        except (TypeError, ValueError):
            weight = 3
        rows.append((str(u.get("summary") or "").strip(),
                     json.dumps(subs, ensure_ascii=False),
                     weight,
                     str(u.get("chapters") or "").strip(),
                     str(u.get("notes") or "").strip(), name))
    if not rows:
        return 0

    with db.get_conn() as conn:
        conn.execute("DELETE FROM focus_topics WHERE notebook_id=?", (notebook_id,))
        conn.executemany(
            "INSERT INTO focus_topics(notebook_id, position, summary, subtopics,"
            " weight, chapters, notes, name) VALUES (?,?,?,?,?,?,?,?)",
            [(notebook_id, i, *r) for i, r in enumerate(rows)],
        )
        # keep notebooks.topics (flat names) in sync for existing consumers
        conn.execute("UPDATE notebooks SET topics=? WHERE id=?",
                     ("\n".join(r[5] for r in rows), notebook_id))
    return len(rows)


def get(notebook_id: int) -> list[dict]:
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, position, name, summary, subtopics, weight, chapters, notes"
            " FROM focus_topics WHERE notebook_id=? ORDER BY position", (notebook_id,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["subtopics"] = json.loads(d["subtopics"] or "[]")
        except Exception:
            d["subtopics"] = []
        out.append(d)
    return out
