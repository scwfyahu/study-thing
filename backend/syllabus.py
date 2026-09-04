"""Extract text + topics from syllabus/study-guide files (PDF, DOCX, TXT/MD)."""
import json
import re

from .config import OLLAMA_MODEL, OLLAMA_URL

TOPIC_SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["topics"],
}


def extract_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        from io import BytesIO

        from pypdf import PdfReader

        r = PdfReader(BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in r.pages)
    if name.endswith(".docx"):
        from io import BytesIO

        from docx import Document

        d = Document(BytesIO(data))
        return "\n".join(p.text for p in d.paragraphs if p.text.strip())
    # txt / md / anything else
    return data.decode("utf-8", errors="replace")


def extract_topics(text: str) -> list[str]:
    """Syllabus outline topics via LLM; fall back to a line heuristic."""
    try:
        topics = _llm_topics(text)
        if topics:
            return topics
    except Exception:
        pass
    return _heuristic_topics(text)


def _llm_topics(text: str) -> list[str]:
    import requests

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": (
                "You read a course syllabus / study guide and extract the course outline topics. "
                "Output each topic as one concise numbered line, e.g. '1. Understanding the Self'. "
                "If there is a Course Outline / Topics section, use it; otherwise infer from "
                "section headings. Skip administrative sections (grading, policies, references). "
                "Return the schema exactly."
            )},
            {"role": "user", "content": f"Syllabus text:\n{text[:9000]}"},
        ],
    }
    from . import llm
    content = llm.chat(payload["messages"], schema=TOPIC_SCHEMA,
                       num_ctx=16384, num_predict=2048, temperature=0.1,
                       timeout=600)
    data = json.loads(content)
    return [str(t).strip() for t in data.get("topics", []) if str(t).strip()]


def _heuristic_topics(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        s = line.strip()
        if re.match(r"^\d{1,2}[.)]\s+\S", s) and len(s) < 140 and not re.search(r"(grading|percent|reference|textbook|quarter|week|lesson)", s, re.I):
            out.append(s)
    return out[:30]