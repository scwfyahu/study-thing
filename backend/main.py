"""StudyThing API — notebooks (classes) contain recordings; recordings produce flashcards."""
import json
import re
import shutil
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from . import db, deckgen, exams, notes, pipeline, quizzes, reviewers, srs, syllabus
from .tunnel import router as tunnel_router
from .config import (
    ASR_BACKEND,
    AUDIO_DIR,
    OLLAMA_MODEL,
    OLLAMA_URL,
    ROOT,
    WHISPERCPP_BIN,
    WHISPERCPP_MODEL,
    WHISPER_MODEL,
)
from .exporters import cards_to_apkg, cards_to_csv

ALLOWED_EXT = {
    ".m4a", ".mp3", ".wav", ".webm", ".mp4", ".aac", ".ogg", ".oga",
    ".flac", ".opus", ".mov", ".m4b", ".wma", ".aif", ".aiff",
    ".png", ".jpg", ".jpeg", ".webp", ".heic", ".pdf",
}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_schema()
    yield


app = FastAPI(title="StudyThing", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(tunnel_router)


@app.get("/api/processing")
def processing_status():
    with db.get_conn() as conn:
        rec = conn.execute(
            "SELECT COUNT(*) AS n FROM recordings WHERE status IN"
            " ('queued','denoising','splitting','transcribing','reading','classifying')"
        ).fetchone()["n"]
        decks = conn.execute(
            "SELECT COUNT(*) AS n FROM decks WHERE status='generating'"
        ).fetchone()["n"]
        waiting = conn.execute(
            "SELECT COUNT(*) AS n FROM tests WHERE confirmed=0"
        ).fetchone()["n"]
    return {"recordings": rec, "decks": decks, "tests_waiting": waiting,
            "busy": (rec + decks) > 0}


@app.get("/api/llm/status")
def llm_status():
    from . import llm
    try:
        return llm.status()
    except Exception as e:  # noqa: BLE001
        return {"provider": "unknown", "available": False,
                "model": None, "error": str(e)}



def _nb_or_404(conn, nb_id: int):
    nb = conn.execute("SELECT id, name FROM notebooks WHERE id=?", (nb_id,)).fetchone()
    if nb is None:
        raise HTTPException(404, "notebook not found")
    return nb


# ---------------------------------------------------------------- notebooks

@app.get("/api/notebooks")
def list_notebooks():
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT n.id, n.name, n.created_at,
                 (SELECT COUNT(*) FROM recordings r WHERE r.notebook_id = n.id) AS recording_count,
                 (SELECT COUNT(*) FROM cards c WHERE c.notebook_id = n.id) AS card_count
               FROM notebooks n ORDER BY n.created_at DESC, n.id DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def _auto_focus(nb_id: int, syllabus_text: str) -> None:
    """Background task: build the detailed Focus from a syllabus. Never blocks
    the create route (hits the LLM). Bounded retries inside focus.generate."""
    from . import focus

    try:
        focus.generate(nb_id, syllabus_text)
    except Exception:
        pass


@app.post("/api/notebooks", status_code=201)
def create_notebook(body: dict, background_tasks: BackgroundTasks):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "name is required")
    topics = (body.get("topics") or "").strip() or None
    syllabus = (body.get("syllabus") or "").strip() or None
    # Build detailed Focus from the syllabus without blocking: the create
    # route returns instantly; generation runs in a background task.
    with db.get_conn() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO notebooks(name, topics, syllabus) VALUES (?,?,?)", (name, topics, syllabus)
            )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "a notebook with that name already exists")
        nb_id = cur.lastrowid
    if syllabus:
        background_tasks.add_task(_auto_focus, nb_id, syllabus)
    return {"id": nb_id, "name": name, "topics": topics}


@app.post("/api/notebooks/parse-syllabus")
def parse_syllabus(file: UploadFile = File(...)):
    data = file.file.read()
    text = syllabus.extract_text(file.filename or "syllabus.txt", data)
    if len(text.strip()) < 20:
        raise HTTPException(422, "could not read text from this file — PDF/DOCX/TXT/MD only")
    topics = syllabus.extract_topics(text)
    return {"topics": topics, "text": text[:200_000]}


@app.patch("/api/notebooks/{nb_id}")
def rename_notebook(nb_id: int, body: dict):
    fields = {}
    if "name" in body:
        name = (body.get("name") or "").strip()
        if not name:
            raise HTTPException(422, "name is required")
        fields["name"] = name
    if "topics" in body:
        fields["topics"] = (body.get("topics") or "").strip() or None
    if "syllabus" in body:
        fields["syllabus"] = (body.get("syllabus") or "").strip() or None
    if not fields:
        raise HTTPException(422, "nothing to update")
    with db.get_conn() as conn:
        _nb_or_404(conn, nb_id)
        try:
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE notebooks SET {sets} WHERE id=?", (*fields.values(), nb_id))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "a notebook with that name already exists")
    return {"id": nb_id, **fields}


@app.patch("/api/recordings/{rec_id}")
def update_recording(rec_id: int, body: dict):
    if "notebook_id" not in body:
        raise HTTPException(422, "notebook_id required")
    target = body["notebook_id"]
    with db.get_conn() as conn:
        if conn.execute("SELECT 1 FROM recordings WHERE id=?", (rec_id,)).fetchone() is None:
            raise HTTPException(404, "recording not found")
        _nb_or_404(conn, target)
        conn.execute("UPDATE recordings SET notebook_id=? WHERE id=?", (target, rec_id))
    return {"id": rec_id, "notebook_id": target}


@app.get("/api/notebooks/{nb_id}")
def get_notebook(nb_id: int):
    with db.get_conn() as conn:
        nb = conn.execute("SELECT id, name, created_at, topics, syllabus FROM notebooks WHERE id=?", (nb_id,)).fetchone()
        if nb is None:
            raise HTTPException(404, "notebook not found")
        has_syllabus = bool((nb["syllabus"] or "").strip())
        recs = conn.execute(
            """SELECT id, original_name, kind, status, progress, error, note, duration_sec, created_at
               FROM recordings WHERE notebook_id=? ORDER BY id DESC""",
            (nb_id,),
        ).fetchall()
        stats = conn.execute(
            """SELECT
                 SUM(CASE WHEN c.reps=0 THEN 1 ELSE 0 END) AS new_count,
                 SUM(CASE WHEN c.reps>0 AND c.due_date <= date('now') THEN 1 ELSE 0 END) AS due_count
               FROM cards c
               WHERE c.notebook_id=?""",
            (nb_id,),
        ).fetchone()
    out_recs = []
    active_ids = sorted(r["id"] for r in recs if r["status"] in ("queued", "denoising", "splitting", "transcribing", "reading", "extracting"))
    for r in recs:
        d = dict(r)
        if r["status"] == "queued":
            d["queue_pos"] = active_ids.index(r["id"]) + 1
        out_recs.append(d)
    return {**dict(nb), "recordings": out_recs,
            "new_count": stats["new_count"] or 0, "due_count": stats["due_count"] or 0,
            "has_syllabus": has_syllabus}


@app.get("/api/notebooks/{nb_id}/study")
def study_queue(nb_id: int, recording_id: int | None = None, topic: str | None = None, deck_id: int | None = None):
    with db.get_conn() as conn:
        _nb_or_404(conn, nb_id)
        where = "c.notebook_id=?"
        args: list = [nb_id]
        if recording_id:
            where += " AND c.recording_id=?"
            args.append(recording_id)
        if topic:
            where += " AND COALESCE(NULLIF(c.topic, ''), 'Untagged')=?"
            args.append(topic)
        if deck_id:
            where += " AND c.deck_id=?"
            args.append(deck_id)
        rows = conn.execute(
            f"""SELECT c.id, c.question, c.answer, c.topic, c.reps, c.interval_days, c.due_date
               FROM cards c
               WHERE {where} AND (c.reps=0 OR c.due_date <= date('now'))
               ORDER BY (c.reps=0) DESC, c.due_date, c.id""",
            args,
        ).fetchall()
    cards = [dict(r) for r in rows]
    return {
        "cards": cards,
        "new_count": sum(1 for c in cards if c["reps"] == 0),
        "due_count": sum(1 for c in cards if c["reps"] > 0),
    }


@app.post("/api/ratings")
def rate_card(body: dict):
    import datetime as _dt

    card_id = body.get("card_id")
    rating = body.get("rating")
    if rating not in ("again", "hard", "good", "easy"):
        raise HTTPException(422, "rating must be again|hard|good|easy")
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT id, ease, interval_days, reps, lapses, due_date FROM cards WHERE id=?", (card_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "card not found")
        upd = srs.apply_rating(dict(row), rating, _dt.date.today())
        conn.execute(
            """UPDATE cards SET ease=?, interval_days=?, reps=?, lapses=?, due_date=?
               WHERE id=?""",
            (upd["ease"], upd["interval_days"], upd["reps"], upd["lapses"], upd["due_date"], card_id),
        )
    return {"ok": True, **upd}


@app.delete("/api/notebooks/{nb_id}")
def delete_notebook(nb_id: int):
    with db.get_conn() as conn:
        _nb_or_404(conn, nb_id)
        files = conn.execute("SELECT id, stored_path FROM recordings WHERE notebook_id=?", (nb_id,)).fetchall()
        conn.execute("DELETE FROM notebooks WHERE id=?", (nb_id,))  # cascades
    for f in files:
        try:
            Path(f["stored_path"]).unlink(missing_ok=True)
        except OSError:
            pass
        shutil.rmtree(AUDIO_DIR / f"work_{f['id']}", ignore_errors=True)
    return {"ok": True}


@app.get("/api/notebooks/{nb_id}/cards")
def notebook_cards(nb_id: int, topic: str | None = None, deck_id: int | None = None):
    with db.get_conn() as conn:
        _nb_or_404(conn, nb_id)
        counts = conn.execute(
            """SELECT COALESCE(NULLIF(c.topic, ''), 'Untagged') AS t, COUNT(*) AS n
               FROM cards c
               WHERE c.notebook_id=? GROUP BY t ORDER BY n DESC""",
            (nb_id,),
        ).fetchall()
        where = "c.notebook_id=?"
        args = [nb_id]
        if topic:
            where += " AND COALESCE(NULLIF(c.topic, ''), 'Untagged')=?"
            args.append(topic)
        if deck_id:
            where += " AND c.deck_id=?"
            args.append(deck_id)
        rows = conn.execute(
            f"""SELECT c.id, c.question, c.answer, c.topic, c.recording_id
               FROM cards c
               WHERE {where} ORDER BY c.recording_id, c.position""",
            args,
        ).fetchall()
    return {"topics": [dict(x) for x in counts], "cards": [dict(x) for x in rows]}


@app.get("/api/schedule")
def schedule_all():
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT t.id, t.title, t.date_text, t.date_iso, t.scope, t.confirmed,
                      n.name AS notebook_name, n.id AS notebook_id,
                      (SELECT d.id FROM decks d WHERE d.quiz_id = t.id
                        ORDER BY d.id DESC LIMIT 1) AS deck_id,
                      (SELECT d.status FROM decks d WHERE d.quiz_id = t.id
                        ORDER BY d.id DESC LIMIT 1) AS deck_status,
                      (SELECT COUNT(*) FROM cards c WHERE c.deck_id IN
                        (SELECT d2.id FROM decks d2 WHERE d2.quiz_id = t.id))
                       AS deck_cards
               FROM tests t JOIN notebooks n ON n.id = t.notebook_id
               WHERE t.date_iso IS NOT NULL
               ORDER BY t.date_iso ASC, t.created_at DESC""",
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["scope"] = json.loads(d["scope"] or "[]")
        except Exception:
            d["scope"] = []
        out.append(d)
    return out


@app.post("/api/schedule/scan")
def schedule_rescan_all():
    import datetime as _dt

    today = _dt.date.today().isoformat()
    with db.get_conn() as conn:
        nbs = conn.execute("SELECT id FROM notebooks").fetchall()
    n = 0
    for nb in nbs:
        with db.get_conn() as conn:
            recs = conn.execute(
                "SELECT id FROM recordings WHERE notebook_id=? AND status='done'", (nb["id"],)
            ).fetchall()
            conn.execute("DELETE FROM tests WHERE notebook_id=?", (nb["id"],))
        for r in recs:
            n += exams.scan_recording(r["id"], nb["id"], today)
    return {"ok": True, "scanned": n}


# ---------------------------------------------------------------- recordings

async def _persist_upload(nb_id, file: UploadFile):
    """Write one uploaded file to disk + insert a recording row. Returns rec dict."""
    with db.get_conn() as conn:
        _nb_or_404(conn, nb_id) if nb_id else None
    ext = Path(file.filename or "").suffix.lower()
    if ext and ext not in ALLOWED_EXT:
        raise HTTPException(415, f"unsupported file type {ext}")
    kind = "notes" if ext in notes.NOTES_EXT else "recording"
    safe_base = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(file.filename or "recording").stem)[:80] or "recording"
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO recordings(notebook_id, original_name, stored_path, kind, status) VALUES (?,?,?,?,'queued')",
            (nb_id, file.filename or "recording", "", kind),
        )
        rec_id = cur.lastrowid
    dest = AUDIO_DIR / f"{rec_id}_{safe_base}{ext or '.m4a'}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as out:
        while chunk := await file.read(4 * 1024 * 1024):
            out.write(chunk)
    with db.get_conn() as conn:
        conn.execute("UPDATE recordings SET stored_path=? WHERE id=?", (str(dest), rec_id))
    return {"id": rec_id, "kind": kind, "notebook_id": nb_id}


@app.post("/api/notebooks/{nb_id}/recordings", status_code=201)
async def upload_recording(nb_id: int, background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    saved = await _persist_upload(nb_id, file)
    background_tasks.add_task(pipeline.process_recording, saved["id"])
    return {"status": "queued", **saved}


@app.post("/api/inbox/recordings", status_code=201)
async def bulk_upload_inbox(background_tasks: BackgroundTasks,
                            files: list[UploadFile] = File(...)):
    """Drop many files at once, unassigned. Each is transcribed (ASR) then
    auto-classified and held in escrow — no LLM during upload, nothing filed."""
    created = []
    for f in files:
        saved = await _persist_upload(None, f)
        created.append(saved)
    for s in created:
        background_tasks.add_task(pipeline.process_recording, s["id"])
    return {"queued": len(created), "created": created}


@app.get("/api/recordings/{rec_id}")
def get_recording(rec_id: int):
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT id, notebook_id, original_name, status, progress, error, note, duration_sec, created_at "
            "FROM recordings WHERE id=?",
            (rec_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "recording not found")
    return dict(row)


@app.delete("/api/recordings/{rec_id}")
def delete_recording(rec_id: int):
    with db.get_conn() as conn:
        row = conn.execute("SELECT stored_path FROM recordings WHERE id=?", (rec_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "recording not found")
        conn.execute("DELETE FROM recordings WHERE id=?", (rec_id,))  # cascades
    try:
        Path(row["stored_path"]).unlink(missing_ok=True)
    except OSError:
        pass
    shutil.rmtree(AUDIO_DIR / f"work_{rec_id}", ignore_errors=True)
    return {"ok": True}


@app.post("/api/recordings/{rec_id}/reprocess")
def reprocess_recording(rec_id: int, background_tasks: BackgroundTasks):
    with db.get_conn() as conn:
        row = conn.execute("SELECT stored_path FROM recordings WHERE id=?", (rec_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "recording not found")
        conn.execute("DELETE FROM cards WHERE recording_id=?", (rec_id,))
        conn.execute("DELETE FROM chunks WHERE recording_id=?", (rec_id,))
    background_tasks.add_task(pipeline.process_recording, rec_id)
    return {"id": rec_id, "status": "queued"}


def _parse_suggestion(rec) -> dict | None:
    try:
        sug = json.loads(rec["suggestion"])
        return sug if isinstance(sug, dict) else None
    except Exception:
        return None


@app.get("/api/inbox")
def list_inbox():
    """Every unassigned (escrow) recording + its classification suggestion."""
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, original_name, kind, status, note, error, suggestion,"
            " duration_sec, created_at FROM recordings WHERE notebook_id IS NULL"
            " ORDER BY id DESC"
        ).fetchall()
        chunks = {}
        for r in rows:
            if r["status"] in ("done", "unclassified", "error"):
                t = conn.execute(
                    "SELECT text FROM chunks WHERE recording_id=? ORDER BY idx", (r["id"],)
                ).fetchall()
                chunks[r["id"]] = "\n\n".join(c["text"] for c in t)
    out = []
    for r in rows:
        d = dict(r)
        d["suggestion"] = _parse_suggestion(r)
        d["transcript_preview"] = (chunks.get(r["id"]) or "")[:800]
        out.append(d)
    return out


@app.get("/api/inbox/count")
def inbox_count():
    with db.get_conn() as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM recordings WHERE notebook_id IS NULL"
        ).fetchone()["n"]
    return {"count": n}


@app.post("/api/recordings/{rec_id}/reclassify")
def reclassify_recording(rec_id: int):
    """Re-run classification on an escrowed recording (idempotent; never files)."""
    import json as _json
    from . import classify as _classify

    with db.get_conn() as conn:
        rec = conn.execute(
            "SELECT id, stored_path, kind, notebook_id FROM recordings WHERE id=?", (rec_id,)
        ).fetchone()
        if rec is None:
            raise HTTPException(404, "recording not found")
        if rec["notebook_id"] is not None:
            raise HTTPException(409, "already assigned to a notebook")
        text = "\n\n".join(
            c["text"] for c in conn.execute(
                "SELECT text FROM chunks WHERE recording_id=? ORDER BY idx", (rec_id,)
            ).fetchall()
        )
    sug = _classify.classify(text)
    with db.get_conn() as conn:
        conn.execute("UPDATE recordings SET suggestion=?, status='unclassified', error=NULL WHERE id=?",
                     (_json.dumps(sug, ensure_ascii=False), rec_id))
    return {"id": rec_id, "suggestion": sug}


@app.post("/api/recordings/{rec_id}/assign")
def assign_recording(rec_id: int, body: dict, background_tasks: BackgroundTasks):
    """Human-assign an escrowed recording to a notebook, then scan its tests.
    Explicitly never auto-files; this is the only path that commits a notebook."""
    target = body.get("notebook_id")
    if target is None:
        raise HTTPException(422, "notebook_id required")
    with db.get_conn() as conn:
        rec = conn.execute(
            "SELECT id, notebook_id, stored_path FROM recordings WHERE id=?", (rec_id,)
        ).fetchone()
        if rec is None:
            raise HTTPException(404, "recording not found")
        _nb_or_404(conn, int(target))
        conn.execute(
            "UPDATE recordings SET notebook_id=?, suggestion=NULL, error=NULL WHERE id=?",
            (int(target), rec_id),
        )
    background_tasks.add_task(pipeline.finish_assignment, rec_id, int(target))
    return {"id": rec_id, "notebook_id": int(target), "status": "assigned"}


@app.get("/api/recordings/{rec_id}/cards")
def recording_cards(rec_id: int):
    with db.get_conn() as conn:
        if conn.execute("SELECT 1 FROM recordings WHERE id=?", (rec_id,)).fetchone() is None:
            raise HTTPException(404, "recording not found")
        rows = conn.execute(
            "SELECT id, question, answer, position FROM cards WHERE recording_id=? ORDER BY position",
            (rec_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/recordings/{rec_id}/transcript")
def recording_transcript(rec_id: int):
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT idx, start_sec, text FROM chunks WHERE recording_id=? ORDER BY idx",
            (rec_id,),
        ).fetchall()
    return {"chunks": [dict(r) for r in rows], "text": "\n\n".join(r["text"] for r in rows)}


# ------------------------------------------------------------------ exports

def _fetch_cards_for(conn, where: str, args: tuple):
    return conn.execute(
        f"""SELECT c.question, c.answer FROM cards c
            WHERE {where} ORDER BY c.recording_id, c.position""",
        args,
    ).fetchall()


def _export(cards, fmt: str, deck_name: str, tags: list[str]):
    if not cards:
        raise HTTPException(400, "no flashcards yet for this item")
    if fmt == "csv":
        return PlainTextResponse(
            cards_to_csv(cards),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{_slug(deck_name)}.csv"'},
        )
    path = cards_to_apkg(cards, deck_name, tags)
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=f"{_slug(deck_name)}.apkg",
        background=BackgroundTask(lambda: shutil.rmtree(path.parent, ignore_errors=True)),
    )


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)[:100] or "deck"


@app.get("/api/recordings/{rec_id}/export")
def export_recording(rec_id: int, format: str = "apkg"):
    with db.get_conn() as conn:
        rec = conn.execute(
            "SELECT r.original_name, r.notebook_id, n.name AS notebook_name "
            "FROM recordings r JOIN notebooks n ON n.id=r.notebook_id WHERE r.id=?",
            (rec_id,),
        ).fetchone()
        if rec is None:
            raise HTTPException(404, "recording not found")
        cards = _fetch_cards_for(conn, "r.id=?", (rec_id,))
    deck = f"{rec['notebook_name']} :: {rec['original_name']}"
    return _export(cards, format, deck, [rec["notebook_name"]])


@app.get("/api/notebooks/{nb_id}/export")
def export_notebook(nb_id: int, format: str = "apkg"):
    with db.get_conn() as conn:
        nb = _nb_or_404(conn, nb_id)
        cards = _fetch_cards_for(conn, "r.notebook_id=?", (nb_id,))
    return _export(cards, format, nb["name"], [nb["name"]])


@app.get("/api/notebooks/{nb_id}/tests")
def list_tests(nb_id: int):
    with db.get_conn() as conn:
        _nb_or_404(conn, nb_id)
        rows = conn.execute(
            """SELECT t.id, t.title, t.date_text, t.date_iso, t.scope, t.confirmed,
                      r.original_name AS recording_name
               FROM tests t LEFT JOIN recordings r ON r.id = t.recording_id
               WHERE t.notebook_id=? ORDER BY
                 CASE WHEN t.date_iso IS NULL THEN 1 ELSE 0 END, t.date_iso ASC, t.id DESC""",
            (nb_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["scope"] = json.loads(d["scope"] or "[]")
        except Exception:
            d["scope"] = []
        out.append(d)
    return out


@app.post("/api/notebooks/{nb_id}/tests/scan")
def scan_tests(nb_id: int, background_tasks: BackgroundTasks):
    import datetime as _dt

    with db.get_conn() as conn:
        _nb_or_404(conn, nb_id)
        recs = conn.execute(
            "SELECT id FROM recordings WHERE notebook_id=? AND status='done'", (nb_id,)
        ).fetchall()
        # remember which tests were already confirmed so a rescan keeps them
        old_confirmed = {r["title"] for r in conn.execute(
            "SELECT title FROM tests WHERE notebook_id=? AND confirmed=1",
            (nb_id,)).fetchall()}
    if not recs:
        return {"ok": True, "scanned": 0}
    conn = db.get_conn()
    conn.execute("DELETE FROM tests WHERE notebook_id=?", (nb_id,))
    conn.commit()
    conn.close()
    today = _dt.date.today().isoformat()
    n = 0
    for r in recs:
        n += exams.scan_recording(r["id"], nb_id, today)
    with db.get_conn() as conn:
        # re-confirm tests whose exact title was already confirmed
        conn.execute(
            "UPDATE tests SET confirmed=1 WHERE notebook_id=? AND title IN ("
            + ",".join("?" for _ in old_confirmed) + ")",
            (nb_id, *old_confirmed)) if old_confirmed else None
        new_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM tests WHERE notebook_id=?", (nb_id,)).fetchall()
            if r["confirmed"] == 1]
    if new_ids:
        background_tasks.add_task(deckgen.auto_decks_for_tests,
                                  nb_id, new_ids)
    return {"ok": True, "scanned": n}


@app.post("/api/tests/{tid}/deck")
def test_deck(tid: int, background_tasks: BackgroundTasks):
    """Create + generate a deck for one scheduled test (idempotent)."""
    import json as _json
    with db.get_conn() as conn:
        t = conn.execute("SELECT * FROM tests WHERE id=?", (tid,)).fetchone()
        if t is None:
            raise HTTPException(404, "test not found")
        if not t["confirmed"]:
            raise HTTPException(409,
                "test scope is not confirmed — confirm it first")
        existing = conn.execute(
            "SELECT id FROM decks WHERE quiz_id=? ORDER BY id DESC LIMIT 1",
            (tid,)).fetchone()
        if existing:
            did = existing["id"]
        else:
            cur = conn.execute(
                "INSERT INTO decks(notebook_id, quiz_id, title, scope, status)"
                " VALUES (?,?,?,?,'generating')",
                (t["notebook_id"], tid, t["title"], _json.dumps([])))
            conn.commit()
            did = cur.lastrowid
    background_tasks.add_task(deckgen.auto_decks_for_tests,
                              t["notebook_id"], [tid])
    return {"deck_id": did, "status": "generating"}


@app.post("/api/tests/{tid}/guess")
def guess_test_scope(tid: int):
    """Auto-guess a test's scope from its announcement + notebook syllabus."""
    import json as _json
    with db.get_conn() as conn:
        t = conn.execute("SELECT * FROM tests WHERE id=?", (tid,)).fetchone()
        if t is None:
            raise HTTPException(404, "test not found")
        nb = conn.execute(
            "SELECT name, topics, syllabus FROM notebooks WHERE id=?",
            (t["notebook_id"],)).fetchone()
    syllabus_topics = [x.strip() for x in (nb["topics"] or "").splitlines() if x.strip()]
    ann = f"{t['title']} ({t['date_text'] or ''})"
    try:
        sc = _json.loads(t["scope"] or "[]")
        if sc:
            ann += f". Scope mentioned: {', '.join(sc)}"
    except Exception:
        pass
    try:
        scope = deckgen.guess_scope(nb["name"], syllabus_topics, ann,
                                    retries=1)
    except Exception as e:
        raise HTTPException(502, f"scope guess failed: {e}")
    return {"scope": scope}


@app.post("/api/tests/{tid}/confirm")
def confirm_test(tid: int, body: dict, background_tasks: BackgroundTasks):
    """Confirm a test's scope, then generate its deck automatically."""
    import json as _json
    with db.get_conn() as conn:
        t = conn.execute("SELECT * FROM tests WHERE id=?", (tid,)).fetchone()
        if t is None:
            raise HTTPException(404, "test not found")
        scope = body.get("scope")
        if scope is not None:
            scope_list = [str(x).strip() for x in scope if str(x).strip()]
            conn.execute("UPDATE tests SET scope=?, confirmed=1 WHERE id=?",
                         (_json.dumps(scope_list), tid))
        else:
            conn.execute("UPDATE tests SET confirmed=1 WHERE id=?", (tid,))
        conn.commit()
    # scope confirmed -> generate deck for this test now
    background_tasks.add_task(deckgen.auto_decks_for_tests,
                              t["notebook_id"], [tid])
    return {"ok": True}


@app.delete("/api/tests/{tid}")
def delete_test(tid: int):
    with db.get_conn() as conn:
        cur = conn.execute("DELETE FROM tests WHERE id=?", (tid,))
    if cur.rowcount == 0:
        raise HTTPException(404, "test not found")
    return {"ok": True}


# ---------------------------------------------------------------- reviewers

@app.get("/api/notebooks/{nb_id}/focus")
def get_focus(nb_id: int):
    from . import focus

    with db.get_conn() as conn:
        if conn.execute("SELECT 1 FROM notebooks WHERE id=?", (nb_id,)).fetchone() is None:
            raise HTTPException(404, "notebook not found")
    return {"focus": focus.get(nb_id)}


@app.post("/api/notebooks/{nb_id}/auto-focus")
def auto_focus(nb_id: int, background_tasks: BackgroundTasks):
    """Regenerate the detailed Focus from the notebook's stored syllabus."""
    from . import focus

    with db.get_conn() as conn:
        nb = conn.execute("SELECT id, name, syllabus FROM notebooks WHERE id=?",
                          (nb_id,)).fetchone()
        if nb is None:
            raise HTTPException(404, "notebook not found")
    if not (nb["syllabus"] or "").strip():
        raise HTTPException(400, "no syllabus stored for this notebook — upload one in Edit")
    background_tasks.add_task(focus.generate, nb_id, nb["syllabus"])
    return {"ok": True, "generating": True}


@app.get("/api/notebooks/{nb_id}/reviewers")
def list_reviewers(nb_id: int):
    with db.get_conn() as conn:
        _nb_or_404(conn, nb_id)
        rows = conn.execute(
            "SELECT id, topic, created_at, length(content) AS chars FROM reviewers WHERE notebook_id=? ORDER BY id DESC",
            (nb_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/notebooks/{nb_id}/reviewers", status_code=201)
def create_reviewer(nb_id: int, body: dict, background_tasks: BackgroundTasks):
    with db.get_conn() as conn:
        nb = _nb_or_404(conn, nb_id)
        nb = conn.execute("SELECT id, name, topics FROM notebooks WHERE id=?", (nb_id,)).fetchone()
    topic = (body.get("topic") or "__all__").strip() or "__all__"
    try:
        content = reviewers.generate_reviewer(nb_id, nb["name"], nb["topics"], topic)
    except ValueError as e:
        raise HTTPException(400, str(e))
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO reviewers(notebook_id, topic, content) VALUES (?,?,?)",
            (nb_id, topic if topic != "__all__" else "All topics", content),
        )
        rid = cur.lastrowid
    return {"id": rid, "topic": topic, "content": content}


@app.get("/api/reviewers/{rid}")
def get_reviewer(rid: int):
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT id, notebook_id, topic, content, created_at FROM reviewers WHERE id=?", (rid,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "reviewer not found")
    return dict(row)


@app.delete("/api/reviewers/{rid}")
def delete_reviewer(rid: int):
    with db.get_conn() as conn:
        cur = conn.execute("DELETE FROM reviewers WHERE id=?", (rid,))
    if cur.rowcount == 0:
        raise HTTPException(404, "reviewer not found")
    return {"ok": True}


@app.get("/api/reviewers/{rid}/download")
def download_reviewer(rid: int, format: str = "md"):
    with db.get_conn() as conn:
        row = conn.execute("SELECT topic, content FROM reviewers WHERE id=?", (rid,)).fetchone()
    if row is None:
        raise HTTPException(404, "reviewer not found")
    ext = "md" if format == "md" else "txt"
    return PlainTextResponse(
        row["content"],
        media_type="text/markdown" if ext == "md" else "text/plain",
        headers={"Content-Disposition": f'attachment; filename="reviewer-{_slug(row["topic"])}.{ext}"'},
    )


# ------------------------------------------------------------------ decks

@app.get("/api/notebooks/{nb_id}/decks")
def list_decks(nb_id: int):
    with db.get_conn() as conn:
        _nb_or_404(conn, nb_id)
        rows = conn.execute(
            """SELECT d.id, d.title, d.scope, d.status, d.error, d.progress, d.created_at, d.quiz_id,
                      (SELECT COUNT(*) FROM cards c WHERE c.deck_id = d.id) AS card_count
               FROM decks d WHERE d.notebook_id=? ORDER BY d.id DESC""",
            (nb_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["scope"] = json.loads(d["scope"] or "[]")
        except Exception:
            d["scope"] = []
        out.append(d)
    return out


@app.post("/api/notebooks/{nb_id}/decks", status_code=201)
def create_deck(nb_id: int, body: dict):
    with db.get_conn() as conn:
        _nb_or_404(conn, nb_id)
    title = (body.get("title") or "Untitled deck").strip()
    scope = [str(s) for s in (body.get("scope") or [])]
    quiz_id = body.get("quiz_id")
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO decks(notebook_id, quiz_id, title, scope, status) VALUES (?,?,?,?,'draft')",
            (nb_id, quiz_id, title, json.dumps(scope, ensure_ascii=False)),
        )
        did = cur.lastrowid
    return {"id": did, "title": title, "scope": scope, "status": "draft"}


@app.post("/api/decks/{did}/guess")
def guess_deck_scope(did: int):
    with db.get_conn() as conn:
        deck = conn.execute("SELECT * FROM decks WHERE id=?", (did,)).fetchone()
        if deck is None:
            raise HTTPException(404, "deck not found")
        nb = conn.execute(
            "SELECT name, topics, syllabus FROM notebooks WHERE id=?", (deck["notebook_id"],)
        ).fetchone()
        test = conn.execute(
            "SELECT title, date_text, scope FROM tests WHERE id=?", (deck["quiz_id"],)
        ).fetchone()
    syllabus_topics = [t.strip() for t in (nb["topics"] or "").splitlines() if t.strip()]
    ann = ""
    if test:
        scope_txt = ""
        try:
            scope_txt = ", ".join(json.loads(test["scope"] or "[]"))
        except Exception:
            pass
        ann = f"{test['title']} ({test['date_text'] or ''}). Scope mentioned: {scope_txt}"
    elif nb["syllabus"]:
        ann = "Syllabus outline available."
    scope = deckgen.guess_scope(nb["name"], syllabus_topics, ann)
    return {"scope": scope}


@app.patch("/api/decks/{did}")
def update_deck(did: int, body: dict):
    with db.get_conn() as conn:
        deck = conn.execute("SELECT id FROM decks WHERE id=?", (did,)).fetchone()
        if deck is None:
            raise HTTPException(404, "deck not found")
        fields = {}
        if "title" in body:
            fields["title"] = str(body["title"]).strip()
        if "scope" in body:
            fields["scope"] = json.dumps([str(s) for s in body["scope"]], ensure_ascii=False)
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE decks SET {sets} WHERE id=?", (*fields.values(), did))
    return {"ok": True}


@app.post("/api/decks/{did}/confirm", status_code=202)
def confirm_deck(did: int, background_tasks: BackgroundTasks):
    with db.get_conn() as conn:
        deck = conn.execute("SELECT * FROM decks WHERE id=?", (did,)).fetchone()
        if deck is None:
            raise HTTPException(404, "deck not found")
    background_tasks.add_task(deckgen.generate_deck_cards, did)
    return {"ok": True, "status": "generating"}


@app.delete("/api/decks/{did}")
def delete_deck(did: int):
    with db.get_conn() as conn:
        deck = conn.execute("SELECT id FROM decks WHERE id=?", (did,)).fetchone()
        if deck is None:
            raise HTTPException(404, "deck not found")
        conn.execute("DELETE FROM cards WHERE deck_id=?", (did,))
        conn.execute("DELETE FROM decks WHERE id=?", (did,))
    return {"ok": True}


@app.get("/api/decks/{did}/export")
def export_deck(did: int, format: str = "apkg"):
    with db.get_conn() as conn:
        deck = conn.execute("SELECT * FROM decks WHERE id=?", (did,)).fetchone()
        if deck is None:
            raise HTTPException(404, "deck not found")
        nb = conn.execute("SELECT name FROM notebooks WHERE id=?", (deck["notebook_id"],)).fetchone()
        cards = conn.execute(
            "SELECT question, answer FROM cards WHERE deck_id=? ORDER BY position", (did,)
        ).fetchall()
    return _export([(c["question"], c["answer"]) for c in cards], format, f"{nb['name']} :: {deck['title']}", [nb["name"]])


# ------------------------------------------------------------------ quizzes

@app.get("/api/notebooks/{nb_id}/quizzes")
def list_quizzes(nb_id: int):
    with db.get_conn() as conn:
        _nb_or_404(conn, nb_id)
        rows = conn.execute(
            "SELECT id, title, difficulty, created_at FROM quizzes WHERE notebook_id=? ORDER BY id DESC",
            (nb_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/notebooks/{nb_id}/quizzes", status_code=201)
def create_quiz(nb_id: int, body: dict):
    with db.get_conn() as conn:
        _nb_or_404(conn, nb_id)
    source = str(body.get("source") or "All cards").strip()
    scope = [str(s) for s in (body.get("scope") or [])]
    try:
        difficulty = int(body.get("difficulty", 5))
    except (TypeError, ValueError):
        difficulty = 5
    difficulty = max(1, min(10, difficulty))
    try:
        count = int(body.get("num_questions", 10))
    except (TypeError, ValueError):
        count = 10
    count = max(1, min(25, count))
    try:
        questions = quizzes.generate_quiz(nb_id, source, scope, difficulty, count)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not questions:
        raise HTTPException(400, "could not generate any valid questions — try fewer questions or different scope")
    title = f"{source} · diff {difficulty}"
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO quizzes(notebook_id, title, difficulty, questions) VALUES (?,?,?,?)",
            (nb_id, title, difficulty, json.dumps(questions, ensure_ascii=False)),
        )
        qid = cur.lastrowid
    return {"id": qid, "title": title, "difficulty": difficulty, "questions": questions}


@app.get("/api/quizzes/{qid}")
def get_quiz(qid: int):
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT id, notebook_id, title, difficulty, questions, created_at FROM quizzes WHERE id=?",
            (qid,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "quiz not found")
    d = dict(row)
    d["questions"] = json.loads(d["questions"])
    return d


@app.delete("/api/quizzes/{qid}")
def delete_quiz(qid: int):
    with db.get_conn() as conn:
        cur = conn.execute("DELETE FROM quizzes WHERE id=?", (qid,))
    if cur.rowcount == 0:
        raise HTTPException(404, "quiz not found")
    return {"ok": True}


# ------------------------------------------------------------------- health

@app.get("/api/health")
def health():
    import importlib.util

    ollama_up = False
    try:
        import requests

        ollama_up = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2).ok
    except Exception:
        pass
    asr_mod = "mlx_whisper" if ASR_BACKEND == "mlx" else "faster_whisper"
    asr_installed = importlib.util.find_spec(asr_mod) is not None
    if ASR_BACKEND == "whisper.cpp":
        import shutil
        from pathlib import Path

        from .config import WHISPERCPP_MODEL
        asr_installed = bool(
            WHISPERCPP_BIN or shutil.which("whisper-cli")
        ) and Path(WHISPERCPP_MODEL).exists()
    return {
        "ok": True,
        "asr_backend": ASR_BACKEND,
        "whisper_model": WHISPER_MODEL if ASR_BACKEND != "whisper.cpp" else str(WHISPERCPP_MODEL),
        "whisper_installed": asr_installed,
        "ollama_model": OLLAMA_MODEL,
        "ollama_running": ollama_up,
    }


# -------------------------------------------------- static frontend (build)

_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")