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
  notebook_id INTEGER REFERENCES notebooks(id) ON DELETE CASCADE,
  original_name TEXT NOT NULL,
  stored_path TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT 'recording',
  status TEXT NOT NULL DEFAULT 'queued',
  progress REAL NOT NULL DEFAULT 0,
  note TEXT,
  error TEXT,
  duration_sec REAL,
  suggestion TEXT,
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
  ease REAL NOT NULL DEFAULT 2.5,
  interval_days INTEGER NOT NULL DEFAULT 0,
  reps INTEGER NOT NULL DEFAULT 0,
  lapses INTEGER NOT NULL DEFAULT 0,
  due_date TEXT NOT NULL DEFAULT (date('now')),
  UNIQUE(recording_id, question)
);
CREATE TABLE IF NOT EXISTS reviewers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  notebook_id INTEGER NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
  topic TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS focus_topics(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  notebook_id INTEGER NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
  position INTEGER NOT NULL DEFAULT 0,
  name TEXT NOT NULL,
  summary TEXT,
  subtopics TEXT NOT NULL DEFAULT '[]',
  weight INTEGER NOT NULL DEFAULT 3,
  chapters TEXT,
  notes TEXT
);
CREATE TABLE IF NOT EXISTS tests(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  notebook_id INTEGER NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
  recording_id INTEGER REFERENCES recordings(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  date_text TEXT,
  date_iso TEXT,
  scope TEXT NOT NULL DEFAULT '[]',
  confirmed INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS quizzes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  notebook_id INTEGER NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  difficulty INTEGER NOT NULL DEFAULT 5,
  questions TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS decks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  notebook_id INTEGER NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
  quiz_id INTEGER REFERENCES tests(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  scope TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'draft',
  error TEXT,
  progress REAL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_recordings_notebook ON recordings(notebook_id);
CREATE INDEX IF NOT EXISTS idx_cards_recording ON cards(recording_id);
CREATE INDEX IF NOT EXISTS idx_reviewers_notebook ON reviewers(notebook_id);
CREATE INDEX IF NOT EXISTS idx_tests_notebook ON tests(notebook_id);
CREATE INDEX IF NOT EXISTS idx_quizzes_notebook ON quizzes(notebook_id);
CREATE INDEX IF NOT EXISTS idx_decks_notebook ON decks(notebook_id);
CREATE INDEX IF NOT EXISTS idx_focus_notebook ON focus_topics(notebook_id);
"""

def _migrate(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(cards)")}
    if "topic" not in cols:
        conn.execute("ALTER TABLE cards ADD COLUMN topic TEXT")
    for col, ddl in (
        ("ease", "REAL NOT NULL DEFAULT 2.5"),
        ("interval_days", "INTEGER NOT NULL DEFAULT 0"),
        ("reps", "INTEGER NOT NULL DEFAULT 0"),
        ("lapses", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if col not in cols:
            conn.execute(f"ALTER TABLE cards ADD COLUMN {col} {ddl}")
    if "due_date" not in cols:
        conn.execute("ALTER TABLE cards ADD COLUMN due_date TEXT")
        conn.execute("UPDATE cards SET due_date = date('now') WHERE due_date IS NULL")
    if "deck_id" not in cols:
        conn.execute("ALTER TABLE cards ADD COLUMN deck_id INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cards_deck ON cards(deck_id)")
    # cards belong to NOTEBOOKS; recording_id is optional provenance only
    if "notebook_id" not in cols:
        conn.executescript("""
          CREATE TABLE cards_new(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notebook_id INTEGER NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
            recording_id INTEGER REFERENCES recordings(id) ON DELETE SET NULL,
            deck_id INTEGER,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            topic TEXT,
            position INTEGER NOT NULL DEFAULT 0,
            ease REAL NOT NULL DEFAULT 2.5,
            interval_days INTEGER NOT NULL DEFAULT 0,
            reps INTEGER NOT NULL DEFAULT 0,
            lapses INTEGER NOT NULL DEFAULT 0,
            due_date TEXT NOT NULL DEFAULT (date('now')),
            UNIQUE(notebook_id, question)
          );
          INSERT INTO cards_new(id, notebook_id, recording_id, question, answer,
            topic, position, ease, interval_days, reps, lapses, due_date, deck_id)
            SELECT c.id, r.notebook_id, c.recording_id, c.question, c.answer,
              c.topic, c.position, c.ease, c.interval_days, c.reps, c.lapses,
              COALESCE(c.due_date, date('now')), c.deck_id
            FROM cards c JOIN recordings r ON r.id = c.recording_id;
          DROP TABLE cards;
          ALTER TABLE cards_new RENAME TO cards;
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cards_notebook ON cards(notebook_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cards_deck ON cards(deck_id)")
    rcols = {r[1] for r in conn.execute("PRAGMA table_info(recordings)")}
    if "kind" not in rcols:
        conn.execute("ALTER TABLE recordings ADD COLUMN kind TEXT NOT NULL DEFAULT 'recording'")
    if "suggestion" not in rcols:
        conn.execute("ALTER TABLE recordings ADD COLUMN suggestion TEXT")
    _drop_not_null_notebook_id(conn)


def _drop_not_null_notebook_id(conn) -> None:
    """recordings.notebook_id must become nullable (escrow recordings sit unassigned)."""
    info = {r[1]: r for r in conn.execute("PRAGMA table_info(recordings)")}
    if "notebook_id" not in info or info["notebook_id"][3] == 0:
        return  # already nullable
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.executescript("""
      CREATE TABLE recordings_new(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        notebook_id INTEGER REFERENCES notebooks(id) ON DELETE CASCADE,
        original_name TEXT NOT NULL,
        stored_path TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT 'recording',
        status TEXT NOT NULL DEFAULT 'queued',
        progress REAL NOT NULL DEFAULT 0,
        note TEXT,
        error TEXT,
        duration_sec REAL,
        suggestion TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
      );
      INSERT INTO recordings_new(id, notebook_id, original_name, stored_path, kind, status,
        progress, note, error, duration_sec, created_at)
        SELECT id, notebook_id, original_name, stored_path, kind, status,
          progress, note, error, duration_sec, created_at FROM recordings;
      DROP TABLE recordings;
      ALTER TABLE recordings_new RENAME TO recordings;
    """)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_recordings_notebook ON recordings(notebook_id)")
    ncols = {r[1] for r in conn.execute("PRAGMA table_info(notebooks)")}
    if "syllabus" not in ncols:
        conn.execute("ALTER TABLE notebooks ADD COLUMN syllabus TEXT")
    tcols = {r[1] for r in conn.execute("PRAGMA table_info(tests)")}
    if "confirmed" not in tcols:
        conn.execute("ALTER TABLE tests ADD COLUMN confirmed INTEGER NOT NULL DEFAULT 0")
    dcols = {r[1] for r in conn.execute("PRAGMA table_info(decks)")}
    if "progress" not in dcols:
        conn.execute("ALTER TABLE decks ADD COLUMN progress REAL")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(cards)")}


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