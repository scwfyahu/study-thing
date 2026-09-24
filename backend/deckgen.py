"""Test scope guessing (syllabus + lesson content). Flashcards are gone; scope now feeds reviewer accuracy."""
import json
import logging
import re

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
                 lesson_content: str = "", retries: int = 0,
                 candidate_subtopics: list[str] | None = None) -> list[str]:
    """Auto-guess a quiz's scope from the syllabus AND the actual lesson content
    (slide outlines / transcript slices), so scopes stay detailed and grounded."""
    lesson_note = ''
    if lesson_content:
        lesson_note = ('\n\nACTUAL LESSON CONTENT from this class (outlines / '
                       'transcripts):\n' + lesson_content[:24000])
    try:
        raw = _ollama([
            {"role": "system", "content": (
                "You estimate the study scope for an upcoming assessment. Given the "
                "course topics, what the teacher announced, and the ACTUAL lesson "
                "content, return a DETAILED study scope: 6-12 specific subtopics the "
                "student must master, in plain line form (one per item). Ground it in "
                "the lesson content whenever it's available. Use precise terms, not "
                "vague lines. If a topic isn't in the syllabus but is in the lessons, "
                "PHRASE IT AS IT APPEARS in the lesson content."
                "\n\nRELEVANCE DISCIPLINE: only include subtopics a teacher would "
                "actually put on THIS assessment given its announcement topic. Skip "
                "subtopics that merely co-occur in the recording but belong to a "
                "different subject/lesson (a science tangent in a history recording "
                "does not belong in a history quiz scope). Prefer breadth over "
                "trivia: each line should map to a studyable unit of knowledge, "
                "not a one-sentence anecdote."
                "\n\nFORBIDDEN: returning the course/unit name as the whole scope. "
                "FORBIDDEN: fewer than 6 items when relevant lesson content is present. "
                "Each scope line must be a single concrete subtopic."
                "\n\nReturn the schema exactly."
            )},
            {"role": "user", "content": (
                f"Course: {notebook_name}\n"
                f"Syllabus topics:\n" + "\n".join(f"- {t}" for t in syllabus_topics) +
                f"\n\nTeacher's announcement:\n{announcement}"
                f"{lesson_content}"
            )},
        ], SCOPE_SCHEMA, timeout=300, retries=retries)
        data = json.loads(raw)
        scope = [str(t).strip() for t in data.get("scope", []) if str(t).strip()]
        # a weak model ignoring the 6-12 mandate gets the deterministic
        # lesson-grounded candidates instead (detailed > terse)
        if len(scope) < 6 and candidate_subtopics and len(candidate_subtopics) >= 6:
            return candidate_subtopics[:12]
        # fall back to the full syllabus rather than an empty scope
        return scope or syllabus_topics
    except Exception:
        # LLM unreachable/flaky — use lesson-grounded candidates if present
        if candidate_subtopics and len(candidate_subtopics) >= 6:
            return candidate_subtopics[:12]
        return syllabus_topics


logger = logging.getLogger(__name__)
