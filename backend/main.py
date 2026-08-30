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

from . import db, exams, pipeline, quizzes, reviewers, srs
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
                 (SELECT COUNT(*) FROM cards c JOIN recordings r ON c.recording_id = r.id
                   WHERE r.notebook_id = n.id) AS card_count
               FROM notebooks n ORDER BY n.created_at DESC, n.id DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/notebooks", status_code=201)
def create_notebook(body: dict):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "name is required")
    topics = (body.get("topics") or "").strip() or None
    with db.get_conn() as conn:
        try:
            cur = conn.execute("INSERT INTO notebooks(name, topics) VALUES (?,?)", (name, topics))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "a notebook with that name already exists")
        return {"id": cur.lastrowid, "name": name, "topics": topics}


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
        nb = conn.execute("SELECT id, name, created_at, topics FROM notebooks WHERE id=?", (nb_id,)).fetchone()
        if nb is None:
            raise HTTPException(404, "notebook not found")
        recs = conn.execute(
            """SELECT id, original_name, status, progress, error, note, duration_sec, created_at
               FROM recordings WHERE notebook_id=? ORDER BY id DESC""",
            (nb_id,),
        ).fetchall()
        stats = conn.execute(
            """SELECT
                 SUM(CASE WHEN c.reps=0 THEN 1 ELSE 0 END) AS new_count,
                 SUM(CASE WHEN c.reps>0 AND c.due_date <= date('now') THEN 1 ELSE 0 END) AS due_count
               FROM cards c JOIN recordings r ON r.id=c.recording_id
               WHERE r.notebook_id=?""",
            (nb_id,),
        ).fetchone()
    return {**dict(nb), "recordings": [dict(r) for r in recs],
            "new_count": stats["new_count"] or 0, "due_count": stats["due_count"] or 0}


@app.get("/api/notebooks/{nb_id}/study")
def study_queue(nb_id: int, recording_id: int | None = None):
    with db.get_conn() as conn:
        _nb_or_404(conn, nb_id)
        if recording_id:
            extra = "AND c.recording_id=?"
            args = (nb_id, recording_id)
        else:
            extra = ""
            args = (nb_id,)
        rows = conn.execute(
            f"""SELECT c.id, c.question, c.answer, c.topic, c.reps, c.interval_days, c.due_date
               FROM cards c JOIN recordings r ON r.id = c.recording_id
               WHERE r.notebook_id=? AND (c.reps=0 OR c.due_date <= date('now')) {extra}
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
def notebook_cards(nb_id: int):
    with db.get_conn() as conn:
        _nb_or_404(conn, nb_id)
        rows = conn.execute(
            """SELECT c.id, c.question, c.answer, r.id AS recording_id, r.original_name
               FROM cards c JOIN recordings r ON r.id = c.recording_id
               WHERE r.notebook_id=? ORDER BY r.id, c.position""",
            (nb_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------- recordings

@app.post("/api/notebooks/{nb_id}/recordings", status_code=201)
async def upload_recording(nb_id: int, background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    with db.get_conn() as conn:
        _nb_or_404(conn, nb_id)
    ext = Path(file.filename or "").suffix.lower()
    if ext and ext not in ALLOWED_EXT:
        raise HTTPException(415, f"unsupported file type {ext}")
    safe_base = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(file.filename or "recording").stem)[:80] or "recording"

    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO recordings(notebook_id, original_name, stored_path, status) VALUES (?,?,?,'queued')",
            (nb_id, file.filename or "recording", ""),
        )
        rec_id = cur.lastrowid

    dest = AUDIO_DIR / f"{rec_id}_{safe_base}{ext or '.m4a'}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as out:
        while chunk := await file.read(4 * 1024 * 1024):
            out.write(chunk)
    with db.get_conn() as conn:
        conn.execute("UPDATE recordings SET stored_path=? WHERE id=?", (str(dest), rec_id))

    background_tasks.add_task(pipeline.process_recording, rec_id)
    return {"id": rec_id, "status": "queued"}


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
            JOIN recordings r ON r.id = c.recording_id WHERE {where} ORDER BY r.id, c.position""",
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
            """SELECT t.id, t.title, t.date_text, t.date_iso, t.scope, t.created_at,
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
    return {"ok": True, "scanned": n}


@app.delete("/api/tests/{tid}")
def delete_test(tid: int):
    with db.get_conn() as conn:
        cur = conn.execute("DELETE FROM tests WHERE id=?", (tid,))
    if cur.rowcount == 0:
        raise HTTPException(404, "test not found")
    return {"ok": True}


# ---------------------------------------------------------------- reviewers

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