"""Laya — local System One typed-decision engine (Apache 2.0, open weights).

Zero-shot decision model: typed questions in (choice/noul/score) -> typed
answers with calibrated probabilities. Runs entirely on this machine — no
transcript sample ever leaves, unlike a hosted decision API.

Mirrors backend.jev's surface (choice/noul) so call sites do:
    try laya -> try jev -> LLM fallback.
First call downloads the checkpoint (~1.7GB) via huggingface_hub; a warm-up
thread at startup pre-fetches it.
"""
import logging
import os
import threading

logger = logging.getLogger("studything.laya")

MODEL_ID = os.environ.get("STUDY_LAYA_MODEL", "convaiinnovations/laya")
SUBFOLDER = os.environ.get("STUDY_LAYA_SUBFOLDER", "multilingual")  # mmBERT, 1024 ctx, 100+ langs
# Benchmarked on 24 labeled recordings: zero-shot Laya scored 42% exact vs
# LLM ~86% — OFF by default until fine-tuned or the noul prefilter earns it.
DISABLED = os.environ.get("STUDY_LAYA", "0") != "1"

_agent = None
_agent_lock = threading.Lock()


def available() -> bool:
    """Importable and not explicitly disabled. Weight download happens lazily."""
    if DISABLED:
        return False
    try:
        import laya  # noqa: F401
        import torch  # noqa: F401
        return True
    except Exception:
        return False


def _get_agent():
    global _agent
    if _agent is not None:
        return _agent
    with _agent_lock:
        if _agent is None:
            import laya
            logger.warning("laya: loading %s/%s (first run downloads ~1.7GB)",
                           MODEL_ID, SUBFOLDER or "root")
            _agent = laya.load(MODEL_ID, subfolder=SUBFOLDER or None)
    return _agent


def warm_up() -> None:
    """Pre-download/load in a daemon thread so the first classify is fast."""
    if not available():
        return
    def _w():
        try:
            _get_agent()
        except Exception as e:  # noqa: BLE001
            logger.warning("laya warm-up failed: %s", e)
    threading.Thread(target=_w, daemon=True).start()


def decide(state: str, questions: dict) -> dict:
    """One forward pass over all questions. Returns {answers: {...}} shape."""
    if not available():
        raise RuntimeError("laya disabled or unavailable")
    agent = _get_agent()
    return agent.predict(state, questions)


def _answer(resp: dict, key: str) -> dict:
    a = (resp.get("answers") or resp).get(key)
    if not isinstance(a, dict):
        raise RuntimeError(f"unexpected laya answer shape: {str(resp)[:200]}")
    return a


def choice(state: str, key: str, instructions: str, criteria: dict) -> dict:
    """Choice question -> {choice, confidence, probabilities}."""
    resp = decide(state, {key: {"type": "choice", "instructions": instructions,
                                "criteria": criteria}})
    a = _answer(resp, key)
    ch = a.get("choice")
    if ch is None:
        raise RuntimeError(f"laya choice missing: {str(a)[:200]}")
    probs = a.get("probabilities") or a.get("probs") or {}
    conf = a.get("confidence")
    if conf is None and probs:
        conf = max(probs.values())
    return {"choice": str(ch), "confidence": float(conf or 0.0),
            "probabilities": probs}


def noul(state: str, key: str, instructions: str, criteria: str = "") -> float:
    """Noul (yes/no) -> probability of yes."""
    q = {"type": "noul", "instructions": instructions}
    if criteria:
        q["criteria"] = criteria
    resp = decide(state, {key: q})
    a = _answer(resp, key)
    if "noul" in a:
        return float(a["noul"])
    probs = a.get("probabilities") or {}
    if probs:  # calibrated yes/no as two options
        return float(probs.get("yes", probs.get("true", 0.0)))
    raise RuntimeError(f"laya noul missing: {str(a)[:200]}")


def _ids_to_choice_criteria(notebooks: list[dict]) -> dict:
    return {
        str(p["id"]): (
            p["name"]
            + (f" — topics: {'; '.join(p['topics'][:8])}" if p.get("topics") else "")
            + (f" — syllabus: {p['syllabus'][:150]}" if p.get("syllabus") else "")
        )
        for p in notebooks
    }
