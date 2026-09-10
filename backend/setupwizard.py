"""First-launch setup wizard backend.

Removes every manual step: the web UI collects the OpenRouter key (or walks
the user through installing Ollama + pulling the model), validates live, and
writes .env next to the exe + sets runtime env immediately (no restart).
"""
import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

import requests

from .config import DATA_DIR, OLLAMA_URL

logger = logging.getLogger("studything.setup")

_state_lock = threading.Lock()
_pull = {"running": False, "pct": 0.0, "done": False,
         "state": "idle", "error": None, "model": None}


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    try:
        return Path(__file__).resolve().parent.parent
    except NameError:
        return Path.cwd()


def _appdata_env() -> Path:
    return _app_dir() / ".env"


def _configured() -> bool:
    """True once a brain is chosen in this install's .env or env."""
    if os.environ.get("STUDY_LLM_PROVIDER") in ("ollama", "openrouter"):
        return True
    envf = _appdata_env()
    if envf.exists():
        txt = envf.read_text(encoding="utf-8", errors="replace")
        if "STUDY_LLM_PROVIDER=" in txt and "SETUP_DONE" in txt.upper():
            return True
    return False


def status() -> dict:
    prov = os.environ.get("STUDY_LLM_PROVIDER", "")
    ollama_up = _ollama_up()
    has_model = ollama_up and _has_model("qwen3:8b")
    has_key = bool(os.environ.get("OPENROUTER_API_KEY"))
    return {
        "needed": not _configured() and not (ollama_up and has_model) and not has_key,
        "provider": prov or None,
        "ollama_running": ollama_up,
        "ollama_has_model": has_model,
        "openrouter_key_set": has_key,
        "env_path": str(_appdata_env()),
        "pull": dict(_pull),
        "ollama_installer_url": "https://ollama.com/download/OllamaSetup.exe",
        "model": (os.environ.get("STUDY_OPENROUTER_MODEL")
                  or os.environ.get("STUDY_OLLAMA_MODEL", "qwen3:8b")),
    }


def _ollama_up() -> bool:
    try:
        return requests.get(f"{OLLAMA_URL}/api/tags", timeout=3).ok
    except Exception:
        return False


def _has_model(name: str) -> bool:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        return any(t.get("name") == name for t in r.json().get("models", []))
    except Exception:
        return False


def _set_env(pairs: dict) -> None:
    """Apply immediately in this process + persist to .env next to the exe."""
    env_path = _appdata_env()
    lines = []
    if env_path.exists():
        lines = [l.rstrip("\n") for l in env_path.read_text(
            encoding="utf-8", errors="replace").splitlines()]
    for k, v in pairs.items():
        os.environ[k] = v
        found = False
        for i, l in enumerate(lines):
            if l.strip().startswith(f"{k}="):
                lines[i] = f"{k}={v}"
                found = True
                break
        if not found:
            lines.append(f"{k}={v}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.warning("setup: wrote %s", env_path)


def set_cloud(key: str, model: str = "") -> dict:
    key = (key or "").strip()
    # validate the key with the smallest possible call BEFORE wiring it in
    prev_prov = os.environ.get("STUDY_LLM_PROVIDER")
    prev_key = os.environ.get("OPENROUTER_API_KEY")
    os.environ["STUDY_LLM_PROVIDER"] = "openrouter"
    os.environ["OPENROUTER_API_KEY"] = key
    err = None
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "z-ai/glm-5.3-flash",
                  "max_tokens": 4, "messages": [{"role": "user", "content": "ping"}]},
            timeout=30)
        if r.status_code >= 400:
            err = f"key rejected by OpenRouter ({r.status_code})"
    except Exception as e:  # noqa: BLE001
        err = f"OpenRouter unreachable: {e}"
    if err:
        os.environ["STUDY_LLM_PROVIDER"] = prev_prov or ""
        os.environ["OPENROUTER_API_KEY"] = prev_key or ""
        return {"ok": False, "error": err}
    pairs = {"STUDY_LLM_PROVIDER": "openrouter", "OPENROUTER_API_KEY": key,
             "STUDY_OPENROUTER_MODEL": model or "z-ai/glm-5.3-flash",
             "SETUP_DONE": "1"}
    _set_env(pairs)
    return {"ok": True}


def _pull_worker(model: str) -> None:
    try:
        req = requests.post(f"{OLLAMA_URL}/api/pull",
                            json={"model": model, "stream": True}, stream=True, timeout=3600)
        req.raise_for_status()
        for line in req.iter_lines():
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("error"):
                raise RuntimeError(d["error"])
            if "total" in d and "completed" in d:
                _pull["pct"] = round(100.0 * d["completed"] / d["total"], 1)
            _pull["state"] = d.get("status") or _pull["state"]
        _pull["pct"] = 100.0
        _pull["done"] = _has_model(model)
        _pull["state"] = "done" if _pull["done"] else "missing after pull"
    except Exception as e:  # noqa: BLE001
        _pull["error"] = str(e)
        _pull["state"] = "error"
    finally:
        _pull["running"] = False


def start_local(model: str = "") -> dict:
    """Ensure Ollama has the default model; start a background pull if not."""
    model = model or "qwen3:8b"
    if not _ollama_up():
        return {"ok": False, "error":
                "Ollama isn't running yet — install it, open the Ollama app once, "
                "then come back (the wizard auto-detects it)."}
    if _has_model(model):
        _set_env({"STUDY_LLM_PROVIDER": "ollama", "SETUP_DONE": "1"})
        return {"ok": True, "already": True}
    if not _pull["running"]:
        _pull.update(running=True, pct=0.0, done=False, error=None, model=model)
        threading.Thread(target=_pull_worker, args=(model,), daemon=True).start()
    return {"ok": True, "pulling": True}


def local_progress() -> dict:
    d = dict(_pull)
    done = _has_model(d.get("model") or "qwen3:8b")
    return {"progress": d.get("pct", 0.0), "state": d.get("state"),
            "error": d.get("error"), "done": done}


def _check_ollama_running() -> bool:
    return _ollama_up()
