"""SQLite persistence layer.

SQLite (stdlib, zero-config, one file) rather than DuckDB: the workload is a few
thousand rows of transactional read/write from a Streamlit session, not
analytical scans. The file is created on first use.

The schema keeps a queryable column set *and* the full JSON document, so the
tables stay sortable without the model having to be flattened.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..config import get_db_path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS startups (
    id                  TEXT PRIMARY KEY,
    dataset             TEXT NOT NULL,
    company_name        TEXT NOT NULL,
    normalized_name     TEXT,
    domain              TEXT,
    website             TEXT,
    hq_country          TEXT,
    sector              TEXT,
    stage               TEXT,
    founded_year        INTEGER,
    total_funding_eur   REAL,
    funding_status      TEXT,
    eligibility_status  TEXT,
    score_total         REAL,
    data_confidence     TEXT,
    red_flag_count      INTEGER DEFAULT 0,
    shortlisted         INTEGER DEFAULT 0,
    source_adapter      TEXT,
    created_at          TEXT,
    updated_at          TEXT,
    document            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_startups_dataset ON startups(dataset);
CREATE INDEX IF NOT EXISTS idx_startups_domain  ON startups(dataset, domain);
CREATE INDEX IF NOT EXISTS idx_startups_name    ON startups(dataset, normalized_name);

CREATE TABLE IF NOT EXISTS evidence (
    id                  TEXT PRIMARY KEY,
    startup_id          TEXT NOT NULL,
    field_name          TEXT NOT NULL,
    source_url          TEXT,
    source_type         TEXT,
    source_tier         TEXT,
    verification_status TEXT,
    confidence          REAL,
    human_verified      INTEGER DEFAULT 0,
    retrieved_at        TEXT,
    document            TEXT NOT NULL,
    FOREIGN KEY (startup_id) REFERENCES startups(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_evidence_startup ON evidence(startup_id);
CREATE INDEX IF NOT EXISTS idx_evidence_field   ON evidence(startup_id, field_name);

CREATE TABLE IF NOT EXISTS overrides (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    startup_id  TEXT NOT NULL,
    field_name  TEXT NOT NULL,
    old_value   TEXT,
    new_value   TEXT,
    reason      TEXT,
    author      TEXT,
    created_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_overrides_startup ON overrides(startup_id);

CREATE TABLE IF NOT EXISTS shortlist (
    startup_id  TEXT PRIMARY KEY,
    position    INTEGER,
    added_at    TEXT,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    startup_id  TEXT NOT NULL,
    body        TEXT NOT NULL,
    author      TEXT,
    created_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_notes_startup ON notes(startup_id);

CREATE TABLE IF NOT EXISTS theses (
    name        TEXT PRIMARY KEY,
    document    TEXT NOT NULL,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key         TEXT PRIMARY KEY,
    value       TEXT
);
"""


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open (and if necessary create) the database."""
    path = Path(db_path) if db_path else get_db_path()
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def initialise(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return conn


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    return initialise(connect(db_path))


def reset(conn: sqlite3.Connection) -> None:
    """Drop everything. Used by tests and by the UI's 'clear workspace' action."""
    for table in ("evidence", "overrides", "shortlist", "notes", "startups", "theses", "meta"):
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.commit()
    initialise(conn)
