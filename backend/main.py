"""StudyThing API — notebooks (classes) contain recordings; recordings produce flashcards."""
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

from . import db, pipeline
from .config import AUDIO_DIR, OLLAMA_MODEL, OLLAMA_URL, ROOT, WHISPER_MODEL
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
    with db.get_conn() as conn:
        try:
            cur = conn.execute("INSERT INTO notebooks(name) VALUES (?)", (name,))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "a notebook with that name already exists")
        return {"id": cur.lastrowid, "name": name}


@app.patch("/api/notebooks/{nb_id}")
def rename_notebook(nb_id: int, body: dict):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "name is required")
    with db.get_conn() as conn:
        _nb_or_404(conn, nb_id)
        try:
            conn.execute("UPDATE notebooks SET name=? WHERE id=?", (name, nb_id))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "a notebook with that name already exists")
    return {"id": nb_id, "name": name}


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
        nb = conn.execute("SELECT id, name, created_at FROM notebooks WHERE id=?", (nb_id,)).fetchone()
        if nb is None:
            raise HTTPException(404, "notebook not found")
        recs = conn.execute(
            """SELECT id, original_name, status, progress, error, note, duration_sec, created_at
               FROM recordings WHERE notebook_id=? ORDER BY id DESC""",
            (nb_id,),
        ).fetchall()
    return {**dict(nb), "recordings": [dict(r) for r in recs]}


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
    return {
        "ok": True,
        "whisper_model": WHISPER_MODEL,
        "whisper_installed": importlib.util.find_spec("mlx_whisper") is not None,
        "ollama_model": OLLAMA_MODEL,
        "ollama_running": ollama_up,
    }


# -------------------------------------------------- static frontend (build)

_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")