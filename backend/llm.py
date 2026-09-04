"""Unified LLM access — local (Ollama) or cloud (OpenRouter).

Provider selected by env:
  STUDY_LLM_PROVIDER = ollama | openrouter   (default: ollama)
  OPENROUTER_API_KEY  (required for openrouter)
  STUDY_OPENROUTER_MODEL (default: deepseek/deepseek-chat:free)

OpenRouter free tier gives access to larger models than an 8B local one,
with big contexts — at the cost of privacy (transcripts leave the machine)
and network reliance.
"""
from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    """No working LLM endpoint (provider down / free tier flaky)."""

# Free + zero-retention (ZDR) OpenRouter models — verified against
# https://openrouter.ai/api/v1/models?zdr=true
ZDR_FREE_MODELS = [
    "z-ai/glm-5.2:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "minimax/minimax-m3:free",
    "nvidia/nemotron-3.5-lightning:free",
    "thinkingmachines/inkling:free",
    "thinkingmachines/inkling-small:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "inclusionai/ling-3.0-flash-fin:free",
    "minimax/minimax-m2.7:free",
]


def provider() -> str:
    return os.environ.get("STUDY_LLM_PROVIDER", "ollama")


def status() -> dict:
    """{provider, available, model, error} — cheap liveness check for the UI."""
    from .config import OLLAMA_MODEL
    last = None
    try:
        if provider() == "openrouter":
            # num_predict must be comfortably above the model's minimum or the
            # ping 400s (e.g. some models reject max_tokens=4) -> false "down".
            _openrouter_chat([{"role": "user", "content": "ping"}],
                             None, 0.0, 256, 30)
            available = True
        else:
            import requests
            from .config import OLLAMA_URL
            requests.get(f"{OLLAMA_URL}/api/tags", timeout=3).raise_for_status()
            available = True
    except Exception as e:  # noqa: BLE001
        available = False
        last = e
    return {
        "provider": provider(),
        "available": available,
        "model": os.environ.get("STUDY_OPENROUTER_MODEL", OLLAMA_MODEL),
        "error": "" if available else f"{type(last).__name__}: {last}",
    }


def zdr_enforced() -> bool:
    return os.environ.get("STUDY_LLM_ZDR", "1" if provider() == "openrouter"
                          else "0") == "1"


def chat(messages: list[dict], *, schema=None, num_ctx: int = 65536,
         num_predict: int = 8192, temperature: float = 0.2,
         timeout: int = 1800, retries: int = 0) -> str:
    """Call the LLM, retrying with backoff until an endpoint works.

    Free tiers go down for seconds-to-minutes; transcription already runs
    in background tasks, so retrying self-heals transient outages instead
    of failing the job outright.
    """
    import time as _time

    # infinite retry by default; retries>=1 overrides to a finite max
    max_attempts = retries or int(os.environ.get("STUDY_LLM_RETRIES", "0"))
    attempt = 0
    while max_attempts == 0 or attempt < max_attempts:
        attempt += 1
        try:
            if provider() == "openrouter":
                return _openrouter_chat(messages, schema, temperature,
                                        num_predict, timeout)
            return _ollama_chat(messages, schema, num_ctx, num_predict,
                                temperature, timeout)
        except LLMUnavailable as e:
            if max_attempts and attempt >= max_attempts:
                raise e
            delay = min(2 ** attempt, 30)
            logger.warning("LLM down (attempt %d) — retrying in %ds",
                           attempt, delay)
            _time.sleep(delay)


def _ollama_chat(messages, schema, num_ctx, num_predict, temperature,
                 timeout) -> str:
    from .config import OLLAMA_MODEL, OLLAMA_URL
    import requests

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": temperature, "num_ctx": num_ctx,
                    "num_predict": num_predict},
        "keep_alive": "5m",
    }
    if schema:
        payload["format"] = schema
    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
        if r.status_code == 400 and "think" in payload:
            payload.pop("think")
            r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload,
                              timeout=timeout)
        r.raise_for_status()
    except Exception:
        raise LLMUnavailable(
            f"Local Ollama at {OLLAMA_URL} is not responding — start it "
            "with `ollama serve` (models in project/models/ollama).")
    return re.sub(r"<think>.*?</think>", "",
                  r.json()["message"]["content"], flags=re.S).strip()


def _openrouter_chat(messages, schema, temperature, num_predict,
                     timeout) -> str:
    import requests

    key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get(
        "STUDY_OPENROUTER_KEY")
    if not key:
        raise RuntimeError("STUDY_LLM_PROVIDER=openrouter but "
                           "OPENROUTER_API_KEY is not set")
    model = os.environ.get("STUDY_OPENROUTER_MODEL", "z-ai/glm-5.2:free")
    if zdr_enforced() and model not in ZDR_FREE_MODELS:
        raise RuntimeError(
            f"model '{model}' is not zero-retention. ZDR is enforced "
            f"(STUDY_LLM_ZDR=1). Allowed ZDR models: "
            + ", ".join(ZDR_FREE_MODELS))
    # free tier is flaky (404/429) — walk the ZDR allowlist as fallbacks
    candidates = [model] + [m for m in ZDR_FREE_MODELS if m != model]
    last_err = None
    for attempt in candidates:
        try:
            return _or_call(attempt, messages, schema, temperature,
                            num_predict, timeout)
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning("openrouter %s failed: %s", attempt, e)
    raise LLMUnavailable(
        "No LLM endpoint available — the free model router is down "
        "or rate-limited. Retry later, or set STUDY_LLM_PROVIDER=ollama "
        "for local inference.")


def _or_call(model, messages, schema, temperature, num_predict, timeout):
    import requests

    key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get(
        "STUDY_OPENROUTER_KEY")
    if not key:
        raise RuntimeError("STUDY_LLM_PROVIDER=openrouter but "
                           "OPENROUTER_API_KEY is not set")
    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": temperature,
        "max_tokens": num_predict,
    }
    if schema:
        body["response_format"] = {"type": "json_object"}
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        json=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8765",
            "X-Title": "StudyThing",
        },
        timeout=timeout,
    )
    if r.status_code == 401:
        raise RuntimeError("OpenRouter: invalid API key")
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()
