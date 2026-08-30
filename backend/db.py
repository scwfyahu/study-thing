import sqlite3

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS notebooks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  topics TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS recordings(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  notebook_id INTEGER NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
  original_name TEXT NOT NULL,
  stored_path TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'queued',
  progress REAL NOT NULL DEFAULT 0,
  note TEXT,
  error TEXT,
  duration_sec REAL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS chunks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
  idx INTEGER NOT NULL,
  start_sec REAL NOT NULL,
  text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cards(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  topic TEXT,
  position INTEGER NOT NULL DEFAULT 0,
  UNIQUE(recording_id, question)
);
CREATE TABLE IF NOT EXISTS reviewers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  notebook_id INTEGER NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
  topic TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_recordings_notebook ON recordings(notebook_id);
CREATE INDEX IF NOT EXISTS idx_cards_recording ON cards(recording_id);
CREATE INDEX IF NOT EXISTS idx_reviewers_notebook ON reviewers(notebook_id);
"""

def _migrate(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(cards)")}
    if "topic" not in cols:
        conn.execute("ALTER TABLE cards ADD COLUMN topic TEXT")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_schema() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)