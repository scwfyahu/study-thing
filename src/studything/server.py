"""HTTP mirror of Study Thing for remote access (cloudflared).

Run:  uv run python -m studything.server            # server + GUI window
      uv run python -m studything.server --headless # server only

Binds 127.0.0.1 only — reach it remotely via `cloudflared tunnel --url`.
Read-only API: browsing transcripts/teachers/schedules remotely; imports,
deletes and profile generation stay desktop-only.
"""
from __future__ import annotations

import json
import logging
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import db
from .app import Api

logger = logging.getLogger(__name__)

READ_ONLY = {
    "get_sources", "get_source", "open_transcript", "get_state",
    "get_jobs", "list_transcripts", "list_teachers", "get_teacher",
    "get_schedule", "get_lessons", "get_study_guides", "get_study_guide",
}


def _token() -> str:
    tok = db.get_setting("serve_token")
    if not tok:
        tok = secrets.token_urlsafe(16)
        db.set_setting("serve_token", tok)
    return tok


def serve(port: int = 8765, headless: bool = False) -> None:
    db.init_db()
    api = Api()
    token = _token()
    html = (Path(__file__).parent / "web" / "index.html").read_text(
        encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/api/ping"):
                self._send(200, b'{"ok": true}', "application/json")
                return
            if self.path.split("?")[0] == "/":
                if f"t={token}" not in self.path:
                    self._send(403, b"forbidden — use the token link",
                               "text/plain")
                    return
                self._send(200,
                           html.replace(
                               "</head>",
                               f"<script>sessionStorage.setItem('t',"
                               f" '{token}')</script></head>").encode(),
                           "text/html")
                return
            self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:  # noqa: N802
            if self.path.split("?")[0] != "/api/call":
                self._send(404, b"not found", "text/plain")
                return
            if f"t={token}" not in (self.headers.get("X-Token") or ""):
                self._send(403, b"forbidden", "text/plain")
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                method = payload.get("method", "")
                if method not in READ_ONLY:
                    self._send(403, json.dumps(
                        {"error": f"'{method}' not available remotely"}),
                        "application/json")
                    return
                result = getattr(api, method)(*(payload.get("args") or []))
                body = json.dumps(result).encode()
                self._send(200, body, "application/json")
            except Exception as e:  # noqa: BLE001
                self._send(500, json.dumps(
                    {"error": f"{type(e).__name__}: {e}"}), "application/json")

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: ANN401
            logger.info("http %s", fmt % args)

    import threading
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logger.info("HTTP mirror ready on 127.0.0.1:%d (token %s…)", port,
                token[:6])

    if headless:
        import time
        while True:
            time.sleep(3600)
    else:
        import webview
        webview.create_window(
            "Study Thing", html=html, js_api=api, width=920, height=680,
            min_size=(560, 420), background_color="#F8F4EB")
        webview.start()


def main() -> None:
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    serve(headless="--headless" in sys.argv)


if __name__ == "__main__":
    main()