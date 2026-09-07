"""API regression tests — every bug that shipped to production gets a lock here."""
import pytest

from backend import pipeline
from tests._path import *  # noqa
from conftest import seed_notebook, seed_recording  # noqa: E402


def test_home_payload_shape(client, conn):
    seed_notebook(conn, "Home NB")
    r = client.get("/api/home")
    assert r.status_code == 200
    body = r.json()
    assert {"totals", "recent", "tests"} <= set(body)
    assert {"notebooks", "recordings", "cards", "decks", "quizzes",
            "inbox", "active"} <= set(body["totals"])
    assert isinstance(body["recent"], list) and isinstance(body["tests"], list)


def test_reprocess_resets_stopped_row(client, conn, monkeypatch):
    """Stopped rows used to stay dead: reprocess must reset status/progress/note/error."""
    nb = seed_notebook(conn)
    rid = seed_recording(conn, nb, status="stopped")
    conn.execute("INSERT INTO chunks(recording_id, idx, start_sec, text)"
                 " VALUES (?,?,?,?)", (rid, 0, 0.0, "stale chunk"))
    conn.commit()

    monkeypatch.setattr(pipeline, "process_recording", lambda rid: None)
    r = client.post(f"/api/recordings/{rid}/reprocess")
    assert r.status_code == 200
    assert r.json()["status"] == "queued"

    row = conn.execute("SELECT * FROM recordings WHERE id=?", (rid,)).fetchone()
    assert row["status"] == "queued"
    assert row["progress"] == 0
    assert row["note"] is None and row["error"] is None
    assert conn.execute("SELECT COUNT(*) FROM chunks WHERE recording_id=?",
                        (rid,)).fetchone()[0] == 0


def test_reprocess_missing_404(client, conn):
    r = client.post("/api/recordings/999999/reprocess")
    assert r.status_code == 404


def test_stop_all_stamps_active_rows(client, conn):
    nb = seed_notebook(conn)
    r1 = seed_recording(conn, nb, status="transcribing")
    r2 = seed_recording(conn, nb, status="queued")
    r3 = seed_recording(conn, nb, status="done")   # must NOT be touched
    r = client.post("/api/jobs/stop")
    assert r.status_code == 200
    for rid in (r1, r2):
        row = conn.execute("SELECT status, note FROM recordings WHERE id=?",
                           (rid,)).fetchone()
        assert row["status"] == "stopped"
        assert "Stopped" in row["note"]
    assert conn.execute("SELECT status FROM recordings WHERE id=?",
                        (r3,)).fetchone()["status"] == "done"


def test_deck_export_apkg(client, conn):
    nb = seed_notebook(conn, "Export NB")
    cur = conn.execute(
        "INSERT INTO decks(notebook_id, title, status) VALUES (?,?,?)",
        (nb, "Export deck", "ready"))
    did = cur.lastrowid
    for i in range(2):
        conn.execute(
            "INSERT INTO cards(notebook_id, recording_id, deck_id, question, answer, position)"
            " VALUES (?,?,?,?,?,?)", (nb, None, did, f"Q{i}?", f"A{i}", i))
    conn.commit()
    r = client.get(f"/api/decks/{did}/export")
    assert r.status_code == 200
    body = r.content
    assert len(body) > 100  # apkg is a real zip, not an error page
    assert body[:2] == b"PK"


def test_deck_export_csv(client, conn):
    nb = seed_notebook(conn, "Export CSV NB")
    cur = conn.execute(
        "INSERT INTO decks(notebook_id, title, status) VALUES (?,?,?)",
        (nb, "CSV deck", "ready"))
    did = cur.lastrowid
    conn.execute(
        "INSERT INTO cards(notebook_id, recording_id, deck_id, question, answer, position)"
        " VALUES (?,?,?,?,?,?)", (nb, None, did, "Q", "A", 0))
    conn.commit()
    r = client.get(f"/api/decks/{did}/export?format=csv")
    assert r.status_code == 200
    assert b"Q" in r.content


def test_inbox_count_endpoint(client, conn):
    r = client.get("/api/inbox/count")
    assert r.status_code == 200
    assert isinstance(r.json().get("count"), int)


def test_processing_endpoint_shape(client):
    r = client.get("/api/processing")
    assert r.status_code == 200
    body = r.json()
    assert "busy" in body and "progress" in body


def test_tests_table_uses_date_iso(client, conn):
    """The dashboard once 500'd on t.test_date — schema column is date_iso."""
    nb = seed_notebook(conn, "Tests NB")
    conn.execute(
        "INSERT INTO tests(notebook_id, title, date_iso, confirmed)"
        " VALUES (?,?,?,?)", (nb, "Quiz 1", "2099-01-01", 1))
    conn.commit()
    body = client.get("/api/home").json()
    assert any(t["title"] == "Quiz 1" for t in body["tests"])
