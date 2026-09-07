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
                    "key_terms": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "term": {"type": "string"},
                                "definition": {"type": "string"},
                            },
                            "required": ["term", "definition"],
                        },
                    },
                    "exam_questions": {"type": "array", "items": {"type": "string"}},
                    "mistakes": {"type": "array", "items": {"type": "string"}},
                    "weight": {"type": "integer"},
                    "chapters": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["name", "summary", "subtopics", "key_terms", "exam_questions", "mistakes", "weight"],
            },
        }
    },
    "required": ["units"],
}

_SYSTEM = """You build a precise, deeply detailed study Focus for a course.
You get the syllabus AND the actual lesson content (slide outlines / lecture
transcripts from this class). Use BOTH: the syllabus gives structure and
priority; the lesson content tells you what was actually taught.

For EACH unit return exactly:
- name: the unit's exact/direct title from the syllabus (or, if the syllabus is
  thin, the major theme the lessons actually cover).
- summary: 3-5 sentences on what this unit teaches — core ideas, how concepts
  connect, and why it matters in the course. Ground it in the lesson content.
- subtopics: 6-12 CONCRETE concepts/skills the student must master (specific,
  not vague — "linear regression assumptions", not "regression"). Cover the
  unit's full breadth as actually taught, not just what the syllabus lists.
- key_terms: 5-15 terms a student must be able to DEFINE, each with a precise
  1-2 sentence definition drawn from the lesson content (never vague). These
  are the memorization layer of the Focus.
- exam_questions: 3-6 plausible exam-style questions for this unit (mix of
  define/compare/explain/apply). Phrase them the way a teacher would ask.
- mistakes: 2-5 common mistakes or confusions students make in this unit
  (e.g. confusing mitosis vs meiosis outcomes), phrased as a warning.
- weight: 1-5 exam priority. Base it on stated grading emphasis, contact time,
  or section depth; default 3 when unclear. Do not inflate.
- chapters: syllabus section/page range or chapter numbers for this unit, as
  stated (empty if not given).
- notes: instructor emphasis / caveats / commonly-tested wrinkles, when the
  syllabus, tone, or lesson content implies them. Omit if nothing.

Return the schema exactly. Never invent facts not present in the material; if
the material is thin, return fewer units with less depth instead of padding.
Administrative syllabus sections (grading, policies, schedule, references) are
NOT units — skip them."""


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
                           num_predict=8192, temperature=0.1, timeout=900)
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


def _lesson_context(notebook_id: int, limit: int = 24000) -> str:
    """Lesson content actually taught in this notebook (slide outlines /
    transcripts), head + tail sampled to stay within the context budget."""
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT c.text FROM chunks c JOIN recordings r ON r.id=c.recording_id"
            " WHERE r.notebook_id=? ORDER BY r.id, c.idx", (notebook_id,)
        ).fetchall()
    text = "\n\n".join(r["text"] for r in rows if r["text"])
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-limit // 2 :]
    return head + "\n\n[…middle omitted for length…]\n\n" + tail


def generate(notebook_id: int, syllabus_text: str) -> int:
    """Build detailed focus_topics for a notebook from its syllabus.

    Idempotent: replaces existing rows. Returns the number of units written
    (0 on total failure — leaves prior focus intact).
    """
    units = None
    lessons = ""
    try:
        lessons = _lesson_context(notebook_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("focus lesson context failed: %s", e)
    llm_ok = True
    try:
        units = _bounded_llm([
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content":
                f"Syllabus text:\n{(syllabus_text or '')[:16000]}"
                + (f"\n\nLesson content from this class (slide outlines / transcripts):\n{lessons}"
                   if lessons else "\n\n(No lesson content yet — use the syllabus only.)")},
        ]).get("units")
    except Exception as e:  # noqa: BLE001
        logger.warning("focus LLM failed: %s", e)
        llm_ok = False
    if not units:
        return 0  # no heuristic fallback: a thin outline beats garbage units

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
                     str(u.get("notes") or "").strip(),
                     json.dumps([
                         {"term": str(t.get("term") or "").strip(),
                          "definition": str(t.get("definition") or "").strip()}
                         for t in (u.get("key_terms") or [])
                         if str(t.get("term") or "").strip() and str(t.get("definition") or "").strip()
                     ], ensure_ascii=False),
                     json.dumps([str(q).strip() for q in (u.get("exam_questions") or []) if str(q).strip()], ensure_ascii=False),
                     json.dumps([str(m).strip() for m in (u.get("mistakes") or []) if str(m).strip()], ensure_ascii=False),
                     name))
    if not rows:
        return 0

    with db.get_conn() as conn:
        conn.execute("DELETE FROM focus_topics WHERE notebook_id=?", (notebook_id,))
        conn.executemany(
            "INSERT INTO focus_topics(notebook_id, position, summary, subtopics,"
            " weight, chapters, notes, key_terms, exam_questions, mistakes, name)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(notebook_id, i, *r) for i, r in enumerate(rows)],
        )
        # keep notebooks.topics (flat names) in sync for existing consumers
        conn.execute("UPDATE notebooks SET topics=? WHERE id=?",
                     ("\n".join(r[-1] for r in rows), notebook_id))
    return len(rows)


def get(notebook_id: int) -> list[dict]:
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, position, name, summary, subtopics, weight, chapters, notes,"
            " key_terms, exam_questions, mistakes"
            " FROM focus_topics WHERE notebook_id=? ORDER BY position", (notebook_id,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["subtopics"] = json.loads(d["subtopics"] or "[]")
        except Exception:
            d["subtopics"] = []
        for k in ("key_terms", "exam_questions", "mistakes"):
            try:
                d[k] = json.loads(d.get(k) or "[]")
            except Exception:
                d[k] = []
        out.append(d)
    return out
