"""SQLite database used by the application.

The database file is called tutoring.db. 
By default it is stored in the data folder next to this file, 
but the location can be changed using the DATA_DIR environment variable.
"""
import os
import sqlite3

from flask import current_app, g

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILENAME = "tutoring.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS staff (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);

-- Customer Management domain
CREATE TABLE IF NOT EXISTS students (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    guardian_name  TEXT,
    guardian_email TEXT,
    guardian_phone TEXT
);

-- Lesson Management domain
CREATE TABLE IF NOT EXISTS tutors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    email       TEXT,
    subjects    TEXT,
    hourly_rate REAL NOT NULL CHECK (hourly_rate >= 0)
);

CREATE TABLE IF NOT EXISTS lessons (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    tutor_id         INTEGER NOT NULL REFERENCES tutors(id),
    -- student_id is the only link that crosses the domain seam (see ADR-3)
    student_id       INTEGER NOT NULL REFERENCES students(id),
    subject          TEXT    NOT NULL,
    start_time       TEXT    NOT NULL,  -- ISO 8601, e.g. 2026-10-05T16:00
    duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0),
    status           TEXT    NOT NULL DEFAULT 'scheduled'
                     CHECK (status IN ('scheduled', 'completed', 'cancelled'))
);
"""


def get_db_path():
    """Full path of the SQLite file, read from the environment at call time."""
    data_dir = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
    return os.path.join(data_dir, DB_FILENAME)


def get_connection(db_path):
    """Open a new connection. Rows behave like dicts; foreign keys are enforced."""
    folder = os.path.dirname(db_path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # SQLite ignores REFERENCES unless this is switched on for every connection.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    """Create any missing tables. Safe to run on every start."""
    conn.executescript(SCHEMA)
    conn.commit()


def get_db():
    """The connection for the current request, opened the first time it is needed."""
    if "db" not in g:
        g.db = get_connection(current_app.config["DB_PATH"])
    return g.db


def close_db(exception=None):
    """Close the request's connection (Flask calls this after every request)."""
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_app(app):
    """Create the schema at startup and register the connection clean-up."""
    conn = get_connection(app.config["DB_PATH"])
    try:
        init_db(conn)
    finally:
        conn.close()
    app.teardown_appcontext(close_db)