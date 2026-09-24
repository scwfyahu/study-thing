"""Reviewer generation: selected recordings' transcripts + Focus lessons ->
a detailed hierarchical study guide, verified line-by-line against its source.

Flashcards are gone; the transcript IS the source of truth now.

Pipeline (background task):
  1. MAP:   every ~6000-char transcript block -> dense study-note bullets
            (LLM, exact terms preserved, no outside knowledge)
  2. REDUCE: all bullets + Focus key-terms/exam-questions + confirmed test
            scopes -> hierarchical numbered outline (details: never drop facts)
  3. VERIFY: Jev noul per outline line against the notes ("is this claim
            supported?") -> unsupported lines get an [unverified] tag.
            Runs only when Jev is available; failures keep the guide as-is.
"""
import json
import logging
import re

from . import db

logger = logging.getLogger("studything.reviewers")

NOTES_PROMPT = """Extract dense study notes from ONE block of a student's lecture transcript.
- EVERY testable fact: definitions, numbers, names, dates, formulas, process steps, examples, distinctions.
- Keep exact wording for key terms (incl. Taglish terms), names, and numbers as spoken.
- One fact per bullet, "- " prefix. No filler, no meta commentary.
- Chit-chat / attendance / noise blocks: return only [].
- Transcript only. Never add outside knowledge. Output a JSON array of strings."""

OUTLINE_PROMPT = """You write a STUDY REVIEWER as a hierarchical numbered outline, from study notes extracted from a student's own lecture recordings.

Rules:
- Use ONLY facts present in the provided notes. Never invent or add outside knowledge.
- Format: HIERARCHICAL NUMBERED OUTLINE — 1. / 1.1 / 1.1.1, indented EXACTLY 2 spaces per level.
- PLAIN TEXT ONLY: no markdown. Never use # headings, **bold**, *, ---, or bullet dashes.
- Structure:
  1. Overview (what the material covers; what the lecturer emphasized)
  2. Key Concepts (each term with its one-line definition as given in class)
  3. Main Points (grouped by theme, deeply nested — every testable fact from the notes lands here)
  4. Examples & Cases (concrete examples/numbers the lecturer used)
  5. Memory Hooks (2-4 mnemonics grounded in class content)
  6. Practice Questions (question, then indented answer — answerable from this material)
- DETAIL IS THE POINT: cover every note bullet; merge duplicates, never drop facts.
- Weave in Focus exam material and confirmed test scopes where they align.
Target roughly {words} words. Output only the outline."""

VERIFY_CHUNK = 40  # outline lines per Jev call
VERIFY_THRESHOLD = 0.45


def _llm(messages: list[dict], schema=None, num_ctx=16384, num_predict=4096,
         temperature=0.2, timeout=240) -> str:
    """timeout is PER CALL — a hung connection must fail over, not stall the
    whole map loop for 30 minutes (that bug stalled reviewer id8)."""
    from . import llm
    return llm.chat(messages, schema=schema, num_ctx=num_ctx,
                    num_predict=num_predict, temperature=temperature,
                    timeout=timeout)


def _fetch_source(recording_ids: list[int]) -> tuple[str, int, list[str]]:
    """Joined transcript (with recording headers), notebook_id (most common,
    -1 if none), and per-recording names. Raises when nothing transcribed."""
    with db.get_conn() as conn:
        parts, names, nb_votes = [], [], []
        for rid in recording_ids:
            rec = conn.execute(
                "SELECT id, original_name, notebook_id FROM recordings WHERE id=?",
                (rid,)).fetchone()
            if rec is None:
                continue
            chunks = conn.execute(
                "SELECT text FROM chunks WHERE recording_id=? ORDER BY idx",
                (rid,)).fetchall()
            if not chunks:
                continue
            parts.append(f"=== Recording: {rec['original_name']} ===\n"
                         + "\n".join(c["text"] for c in chunks))
            names.append(rec["original_name"])
            if rec["notebook_id"]:
                nb_votes.append(rec["notebook_id"])
    if not parts:
        raise ValueError("selected recordings have no transcript yet")
    notebook_id = max(set(nb_votes), key=nb_votes.count) if nb_votes else -1
    return "\n\n".join(parts), notebook_id, names


def _focus_context(notebook_id: int) -> str:
    if notebook_id <= 0:
        return ""
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT name, key_terms, exam_questions FROM focus_topics "
            "WHERE notebook_id=? ORDER BY position, id LIMIT 40",
            (notebook_id,)).fetchall()
        scopes = conn.execute(
            "SELECT title, scope FROM tests WHERE notebook_id=? AND confirmed=1 "
            "ORDER BY date_iso DESC LIMIT 5", (notebook_id,)).fetchall()
    out = []
    for r in rows:
        if r["key_terms"]:
            out.append(f"Topic {r['name']} key terms: {r['key_terms']}")
        if r["exam_questions"]:
            out.append(f"Topic {r['name']} exam questions: {r['exam_questions']}")
    for s in scopes:
        try:
            scope = json.loads(s["scope"] or "[]")
        except Exception:
            scope = []
        if scope:
            out.append(f"Confirmed test '{s['title']}' scope: " + "; ".join(scope))
    return "\n".join(out)


def _notes_for_block(block: str) -> list[str]:
    try:
        raw = _llm(
            [{"role": "system", "content": NOTES_PROMPT},
             {"role": "user", "content": block}],
            schema={"type": "array", "items": {"type": "string"}},
            num_ctx=8192, num_predict=6144, timeout=180)
        t = (raw or "").strip()
        if not t.startswith("["):  # fences / stray prose / object wrappers
            a, b = t.find("["), t.rfind("]")
            if a >= 0 and b > a:
                t = t[a:b + 1]
        parsed = json.loads(t)
        if isinstance(parsed, dict):
            # GLM ignores bare-array schemas and wraps: {"summary": ..., "notes": [...]}
            parsed = next((v for v in parsed.values() if isinstance(v, list)), [])
        if not isinstance(parsed, list):
            parsed = []
        return [str(x).lstrip("- ").strip() for x in parsed if str(x).strip()][:200]
    except Exception as e:  # noqa: BLE001
        logger.warning("notes pass failed for block (%d chars): %s", len(block), e)
        # truth-preserving fallback: keep the raw excerpt as one note
        return [f"(from transcript) {block[:1200].strip()}"]


def _outline(notes: list[str], focus: str, words: int, title: str) -> str:
    user = (f"Course material title: {title}\n\n"
            + (f"FOCUS / EXAM MATERIAL:\n{focus}\n\n" if focus else "")
            + f"STUDY NOTES ({len(notes)} bullets):\n- "
            + "\n- ".join(notes))
    return _llm([{"role": "system", "content": OUTLINE_PROMPT.format(words=words)},
                 {"role": "user", "content": user[:120000]}],
                num_ctx=65536, num_predict=8192, temperature=0.3,
                timeout=900)


def _line_shape(line: str) -> tuple[str, str]:
    """(numbered prefix incl. indent, rest) — headers keep their numbering."""
    m = re.match(r"^(\s*\d+(?:\.\d+)*\.?\s*)(.*)$", line)
    return (m.group(1), m.group(2)) if m else ("", line)


def _verify(guide: str, notes: list[str]) -> str:
    """Tag outline lines Jev says are unsupported by the notes. Best-effort."""
    from . import jev
    if not jev.available() or not notes:
        return guide
    evidence = ("- " + "\n- ".join(notes))[:60000]
    lines = guide.split("\n")
    for start in range(0, len(lines), VERIFY_CHUNK):
        batch = lines[start:start + VERIFY_CHUNK]
        questions = {}
        idx_map = {}
        for i, line in enumerate(batch):
            body = _line_shape(line)[1].strip()
            if not body or len(body) < 12:  # short fragments: skip
                continue
            if body.startswith("#") or set(body) <= set("-—– "):
                continue  # markdown decoration, not a claim
            qid = f"l{i}"
            idx_map[qid] = i
            questions[qid] = {
                "type": "noul",
                "instructions": ("Is this claim supported by the lecture notes? "
                                 f"Claim: {body[:400]}")}
        if not questions:
            continue
        try:
            from . import jev as _jev
            resp = _jev.decide(f"LECTURE NOTES:\n{evidence}", questions)
        except Exception as e:  # noqa: BLE001
            logger.warning("verify pass failed, guide kept as-is: %s", e)
            return guide
        ans = (resp.get("answers") or resp)
        for qid, i in idx_map.items():
            a = ans.get(qid) or {}
            p = a.get("noul")
            if p is None:
                probs = a.get("probabilities") or {}
                p = probs.get("yes", probs.get("true"))
            if p is not None and float(p) < VERIFY_THRESHOLD:
                orig = batch[i]
                if "[unverified]" not in orig:
                    prefix, _ = _line_shape(orig)
                    rest = orig[len(prefix):] if prefix else orig
                    indent = orig[:len(orig) - len(orig.lstrip(" "))]
                    batch[i] = indent + prefix + rest.rstrip() + "  [unverified]"
        lines[start:start + VERIFY_CHUNK] = batch
    return "\n".join(lines)


def flatten_md(guide: str) -> str:
    """Models drift toward markdown; the Outline renderer wants indented plain
    text. Strip decoration, re-derive indent from numbering level."""
    out = []
    for raw in guide.split("\n"):
        line = raw.rstrip()
        t = line.strip()
        if not t or set(t) <= set("-—– *"):
            continue  # blank / --- / *** separator lines
        t = t.lstrip("#").strip()               # ## 2. Key -> 2. Key
        t = t.replace("**", "").replace("__", "")
        t = re.sub(r"^[*•-]\s+", "", t)         # leading bullet chars
        if not t:
            continue
        m = re.match(r"^(\d+(?:\.\d+)+)\.?\s+.*", t) or re.match(r"^(\d+)\.?\s+.*", t)
        if m:
            level = len(re.match(r"^(\d+(?:\.\d+)*)", t).group(1).split("."))
            t = "  " * min(level - 1, 4) + t   # numbering wins over any raw indent
        else:
            lead = len(line) - len(line.lstrip(" "))
            if lead:
                t = "  " * min(lead // 2, 4) + t   # preserve model's own indent
        out.append(t)
    return "\n".join(out)


def generate(recording_ids: list[int], title: str,
             on_stage=None) -> dict:
    """Full background job: map -> reduce -> verify. Returns saved fields.
    on_stage(str) reports progress: mapping | outlining | verifying."""
    from . import laya_client  # noqa: F401  (import parity; Jev does verify)
    full, notebook_id, names = _fetch_source(recording_ids)
    from .pipeline import split_text

    blocks = split_text(full, 6000)
    if on_stage:
        on_stage("mapping")
    notes: list[str] = []
    for i, b in enumerate(blocks):
        logger.info("reviewer map pass %d/%d", i + 1, len(blocks))
        if on_stage:
            on_stage(f"mapping {i + 1}/{len(blocks)}")
        notes.extend(_notes_for_block(b))
    if not notes:
        raise ValueError("transcripts produced no notes — transcripts may be empty")
    focus = _focus_context(notebook_id)
    words = max(600, min(1800, 400 + len(notes) * 6))
    if on_stage:
        on_stage("outlining")
    guide = _outline(notes, focus, words, title)
    if on_stage:
        on_stage("verifying")
    guide = flatten_md(guide)
    guide = _verify(guide, notes)
    return {"content": guide.strip(), "notebook_id": notebook_id,
            "notes_count": len(notes), "words": len(guide.split()),
            "sources": names}
