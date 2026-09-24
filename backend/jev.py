"""TypeSafe Jev — System One typed-decision model.

Jev answers typed questions (choice/noul/score) with calibrated confidence in
~100-500ms instead of generating text. Used for fast structured judgments:
escrow classification (which notebook?) and test-announcement detection
(does this block announce an assessment?). Text generation stays on the LLM.

Disabled unless TYPESAFE_API_KEY (or STUDY_JEV_API_KEY) is set in .env —
every caller must fall back to the existing LLM path on any failure.
"""
import json
import logging
import os

import requests

logger = logging.getLogger("studything.jev")

ENDPOINT_TYPESAFE = "https://api.typesafe.ai/v1/systemone"
ENDPOINT_OPENROUTER = "https://openrouter.ai/api/alpha/decisions"
MODEL = os.environ.get("STUDY_JEV_MODEL", "typesafe/jev-1.13")
TIMEOUT = 20


def _key() -> str:
    return os.environ.get("STUDY_JEV_API_KEY") or os.environ.get("TYPESAFE_API_KEY") or ""


def _or_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY") or ""


def available() -> bool:
    return bool(_key()) or bool(_or_key())


def decide(state: str, questions: dict, model: str | None = None) -> dict:
    """POST a state + typed questions. Returns the raw response dict.

    Routes: dedicated TypeSafe key hits typesafe.ai directly; otherwise the
    OpenRouter alpha System One endpoint (same account as the text LLM).
    Raises on any transport/shape failure — callers treat that as 'Jev off'.
    """
    ts_key = _key()
    if ts_key:
        url, hdrs, mdl = ENDPOINT_TYPESAFE, {
            "Authorization": f"Bearer {ts_key}"}, (model or "jev-latest")
    elif _or_key():
        url, hdrs, mdl = ENDPOINT_OPENROUTER, {
            "Authorization": f"Bearer {_or_key()}",
            "HTTP-Referer": "https://github.com/studything",
            "X-Title": "StudyThing"}, (model or MODEL)
    else:
        raise RuntimeError("Jev disabled (no TYPESAFE_API_KEY / OPENROUTER_API_KEY)")
    hdrs["Content-Type"] = "application/json"
    r = requests.post(url, headers=hdrs,
                      json={"model": mdl, "state": state, "questions": questions},
                      timeout=TIMEOUT)
    r.raise_for_status()
    resp = r.json()
    if isinstance(resp, dict) and resp.get("error"):
        raise RuntimeError(f"Jev API error: {resp['error']}")
    return resp


def choice(state: str, key: str, instructions: str,
           criteria: dict, model: str | None = None) -> dict:
    """Choice question. Returns {choice, confidence, probabilities}."""
    resp = decide(state, {key: {"type": "choice", "instructions": instructions,
                                "criteria": criteria}}, model)
    a = (resp.get("answers") or resp).get(key)
    if not isinstance(a, dict) or "choice" not in a:
        raise RuntimeError(f"unexpected Jev choice shape: {str(resp)[:200]}")
    return {"choice": str(a.get("choice")),
            "confidence": float(a.get("confidence") or 0.0),
            "probabilities": a.get("probabilities") or {}}


def noul(state: str, key: str, instructions: str,
         criteria: str = "", model: str | None = None) -> float:
    """Noul (yes/no) question -> probability of yes, 0..1."""
    q = {"type": "noul", "instructions": instructions}
    if criteria:
        q["criteria"] = criteria
    resp = decide(state, {key: q}, model)
    a = (resp.get("answers") or resp).get(key)
    if not isinstance(a, dict) or "noul" not in a:
        raise RuntimeError(f"unexpected Jev noul shape: {str(resp)[:200]}")
    return float(a["noul"])
