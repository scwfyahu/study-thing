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
    assert {"notebooks", "recordings", "inbox", "active"} <= set(body["totals"])
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


def test_reviewer_pick_and_generate_flow(client, conn, monkeypatch):
    from backend import reviewers as rv
    monkeypatch.setattr(rv, "generate", lambda ids, title, on_stage=None: {
        "content": "1. Overview\\n  1.1 done", "notebook_id": 1,
        "notes_count": 1, "words": 4, "sources": ["s"]})
    """Reviewer is the flagship now: pick transcribed recordings, queue guide."""
    nb = seed_notebook(conn, "Review NB")
    rec_id = seed_recording(conn, nb)
    conn.execute("INSERT INTO chunks(recording_id, idx, start_sec, text) VALUES (?,?,?,?)",
                 (rec_id, 0, 0.0, "Adolescence is a transition period."))
    conn.commit()
    # eligible only when done
    pick = client.get("/api/reviewers/pick", params={"notebook_id": nb}).json()
    assert pick["recordings"] == []  # seed_recording status != done
    conn.execute("UPDATE recordings SET status='done' WHERE id=?", (rec_id,))
    conn.commit()
    pick = client.get("/api/reviewers/pick", params={
        "notebook_id": nb, "date_from": "2000-01-01"}).json()
    assert [r["id"] for r in pick["recordings"]] == [rec_id]
    # empty pick rejected
    assert client.post("/api/reviewers/generate",
                       json={"recording_ids": []}).status_code == 400
    # queued row lands with status generating
    r = client.post("/api/reviewers/generate",
                    json={"recording_ids": [rec_id], "title": "T1"})
    assert r.status_code == 201
    rid = r.json()["id"]
    listing = client.get("/api/reviewers").json()
    # TestClient runs background tasks inline -> job already completed
    assert any(x["id"] == rid and x["status"] == "ready" for x in listing)
    assert client.get(f"/api/reviewers/{rid}").status_code == 200


def test_reviewers_survive_recordings_without_class(client, conn):
    """Unassigned (escrow) picks must be rejected, not crash on NULL notebook."""
    rec_id = seed_recording(conn, None)
    conn.execute("UPDATE recordings SET status='done' WHERE id=?", (rec_id,))
    conn.execute("INSERT INTO chunks(recording_id, idx, start_sec, text) VALUES (?,?,?,?)",
                 (rec_id, 0, 0.0, "noise"))
    conn.commit()
    assert client.post("/api/reviewers/generate",
                       json={"recording_ids": [rec_id]}).status_code == 400


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
