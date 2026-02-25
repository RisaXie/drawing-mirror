"""SQLite database connection and schema initialization."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from app.config import get_settings

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    username     TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    dataset_path TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS drawings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename       TEXT NOT NULL,
    filepath       TEXT NOT NULL,
    drawn_date     TEXT,
    title          TEXT,
    file_ext       TEXT,
    thumbnail_path TEXT,
    width          INTEGER,
    height         INTEGER,
    analysis_text  TEXT,
    analysis_json  TEXT,
    analyzed_at    TEXT,
    UNIQUE(user_id, filename)
);

CREATE INDEX IF NOT EXISTS idx_drawings_user_date ON drawings(user_id, drawn_date);

CREATE TABLE IF NOT EXISTS archive_analyses (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status         TEXT NOT NULL DEFAULT 'pending',
    phase          TEXT,
    total_drawings INTEGER DEFAULT 0,
    analyzed_count INTEGER DEFAULT 0,
    error_message  TEXT,
    model_used     TEXT,
    started_at     TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at   TEXT
);

CREATE TABLE IF NOT EXISTS lenses (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    archive_analysis_id INTEGER REFERENCES archive_analyses(id),
    name                TEXT NOT NULL,
    description         TEXT NOT NULL,
    sort_order          INTEGER DEFAULT 0,
    raw_claude_output   TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, name)
);

CREATE TABLE IF NOT EXISTS lens_drawing_links (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    lens_id                 INTEGER NOT NULL REFERENCES lenses(id) ON DELETE CASCADE,
    drawing_id              INTEGER NOT NULL REFERENCES drawings(id) ON DELETE CASCADE,
    relevance_score         REAL NOT NULL DEFAULT 0.0,
    annotation              TEXT,
    annotation_generated_at TEXT,
    UNIQUE(lens_id, drawing_id)
);

CREATE INDEX IF NOT EXISTS idx_ldl_lens ON lens_drawing_links(lens_id, relevance_score DESC);
CREATE INDEX IF NOT EXISTS idx_ldl_drawing ON lens_drawing_links(drawing_id);

CREATE TABLE IF NOT EXISTS reactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    drawing_id      INTEGER NOT NULL REFERENCES drawings(id) ON DELETE CASCADE,
    target_type     TEXT NOT NULL,
    target_id       TEXT,
    reaction_type   TEXT NOT NULL,
    annotation_text TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    -- uniqueness enforced at app layer (delete then insert) to handle NULL target_id
);

CREATE INDEX IF NOT EXISTS idx_reactions_drawing ON reactions(drawing_id);

CREATE TABLE IF NOT EXISTS embeddings (
    drawing_id  INTEGER PRIMARY KEY REFERENCES drawings(id) ON DELETE CASCADE,
    vector_blob BLOB NOT NULL,
    model_name  TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS situated_feedbacks (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    new_drawing_path  TEXT NOT NULL,
    archive_context   TEXT,
    feedback_text     TEXT,
    model_used        TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def get_db_connection() -> sqlite3.Connection:
    """Open a new SQLite connection. Caller is responsible for closing."""
    settings = get_settings()
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def get_db():
    """Context manager for use in route handlers."""
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create all tables. Safe to call multiple times (CREATE IF NOT EXISTS)."""
    conn = get_db_connection()
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
