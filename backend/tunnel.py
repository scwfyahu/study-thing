"""Cloudflared quick-tunnel management — share link from the web UI."""
from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tunnel", tags=["tunnel"])

_state: Dict[str, Any] = {
    "proc": None, "url": None, "lock": threading.Lock(),
}


def _port() -> int:
    return int(os.environ.get("STUDYTHING_PORT", "8765"))


def _is_local(request: Request) -> bool:
    return (request.client.host if request.client else "") in {
        "127.0.0.1", "::1", "testclient"}


def _watch_url(proc: subprocess.Popen, log_path: str) -> None:
    """Poll the cloudflared log for the public URL (up to ~30s)."""
    deadline = time.time() + 30
    pat = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
    while time.time() < deadline and proc.poll() is None:
        try:
            with open(log_path) as f:
                m = pat.search(f.read())
        except OSError:
            m = None
        if m:
            with _state["lock"]:
                _state["url"] = m.group(0)
            logger.info("tunnel url: %s", _state["url"])
            return
        time.sleep(0.5)


@router.get("")
@router.get("/")
def tunnel_status() -> Dict[str, Any]:
    proc = _state["proc"]
    running = proc is not None and proc.poll() is None
    if not running:
        _state["url"] = None
        _state["proc"] = None
    return {"running": bool(running), "url": _state["url"]}


@router.post("/start")
def tunnel_start(request: Request) -> Dict[str, Any]:
    if not _is_local(request):
        raise HTTPException(403, "tunnel control is localhost-only")
    with _state["lock"]:
        if _state["proc"] and _state["proc"].poll() is None:
            return {"started": True, "url": _state["url"]}
        log_path = os.path.join(
            tempfile.gettempdir(), "studything-cloudflared.log")
        with open(log_path, "w") as logf:
            try:
                proc = subprocess.Popen(
                    ["cloudflared", "tunnel", "--url",
                     f"http://127.0.0.1:{_port()}"],
                    stdout=logf, stderr=subprocess.STDOUT,
                    start_new_session=True)
            except FileNotFoundError:
                raise HTTPException(500, "cloudflared is not installed")
        _state["proc"] = proc
        _state["url"] = None
        threading.Thread(target=_watch_url, args=(proc, log_path),
                         daemon=True).start()
    logger.info("tunnel starting (pid %d)", proc.pid)
    return {"started": True, "url": None}


@router.post("/stop")
def tunnel_stop(request: Request) -> Dict[str, Any]:
    if not _is_local(request):
        raise HTTPException(403, "tunnel control is localhost-only")
    with _state["lock"]:
        proc = _state["proc"]
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        _state["proc"] = None
        _state["url"] = None
    return {"stopped": True}