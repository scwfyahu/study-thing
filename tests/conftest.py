import os
import tempfile

# Isolate every test run from the real data dir. Must run before any backend import:
# config.py reads STUDY_DATA_DIR at import time.
_TMP = tempfile.mkdtemp(prefix="studything-test-")
os.environ["STUDY_DATA_DIR"] = _TMP
# never let a real key/config leak into tests
os.environ["STUDY_LLM_PROVIDER"] = "ollama"
os.environ["OPENROUTER_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import db  # noqa: E402
from backend.main import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def conn():
    con = db.get_conn()
    yield con
    con.close()


def seed_notebook(conn, name="Test Notebook"):
    conn.execute("INSERT OR IGNORE INTO notebooks(name) VALUES (?)", (name,))
    conn.commit()
    return conn.execute(
        "SELECT id FROM notebooks WHERE name=?", (name,)).fetchone()["id"]


def seed_recording(conn, nb_id=None, status="stopped", kind="recording"):
    cur = conn.execute(
        "INSERT INTO recordings(notebook_id, original_name, stored_path, kind,"
        " status, progress, note, error) VALUES (?,?,?,?,?,?,?,?)",
        (nb_id, "test-audio.mp3", "/nonexistent/test-audio.mp3", kind,
         status, 0.9, "old note", "old error"),
    )
    conn.commit()
    return cur.lastrowid
