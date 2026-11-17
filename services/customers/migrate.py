"""Applies the numbered SQL files in migrations/ to the database, in order.

- Applied migrations are recorded in the table schema_migrations, so each file
  runs exactly once and a second start applies nothing.
- Each file runs inside one transaction: if any statement fails, nothing of
  that file is kept and the error stops the service from starting.
- A file can contain several batches separated by lines that say GO. SQL Server
  needs this when a statement uses a column added earlier in the same file.
- Applied files must never be edited (corrections go in a new file). The runner
  stores each file's checksum and refuses to start if an applied file changed.
"""
import hashlib
import logging
import os
import re

log = logging.getLogger(__name__)

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")
FILE_PATTERN = re.compile(r"^\d{3}_[a-z0-9_]+\.sql$")
GO_LINE = re.compile(r"^\s*GO\s*$", re.IGNORECASE | re.MULTILINE)

CREATE_TABLE = """
IF OBJECT_ID(N'schema_migrations', N'U') IS NULL
    CREATE TABLE schema_migrations (
        version    NVARCHAR(255) NOT NULL PRIMARY KEY,
        checksum   CHAR(64)      NOT NULL,
        applied_at DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
    )
"""


class MigrationError(Exception):
    """An applied migration file was changed after it ran."""


def split_batches(sql):
    """Split a migration file on its GO lines and drop empty pieces."""
    return [batch.strip() for batch in GO_LINE.split(sql) if batch.strip()]


def migration_files(folder=MIGRATIONS_DIR):
    """The migration file names in order: 001_..., 002_..., ..."""
    return sorted(name for name in os.listdir(folder) if FILE_PATTERN.match(name))


def apply_migrations(conn, folder=MIGRATIONS_DIR):
    """Apply every migration that has not run yet. Returns the names it applied."""
    cursor = conn.cursor()
    cursor.execute(CREATE_TABLE)
    conn.commit()

    cursor.execute("SELECT version, checksum FROM schema_migrations")
    applied = dict(cursor.fetchall())

    newly_applied = []
    for name in migration_files(folder):
        with open(os.path.join(folder, name), encoding="utf-8") as file:
            sql = file.read()
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()

        if name in applied:
            if applied[name] != checksum:
                raise MigrationError(
                    f"Migration {name} was changed after it was applied. "
                    "Put the correction in a new migration instead."
                )
            continue

        try:
            for batch in split_batches(sql):
                cursor.execute(batch)
            cursor.execute(
                "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                (name, checksum),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            log.error("Migration %s failed; nothing from it was kept.", name)
            raise
        log.info("Applied migration %s", name)
        newly_applied.append(name)

    if not newly_applied:
        log.info("Database schema is up to date (%d migrations applied).", len(applied))
    return newly_applied
