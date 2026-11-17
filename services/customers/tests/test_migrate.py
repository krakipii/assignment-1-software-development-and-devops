"""Tests for the migration runner (migrate.py), each on a brand-new database."""
import shutil

import pymssql
import pytest

import db
import migrate


def copy_migrations(tmp_path):
    """A copy of the real migrations folder that a test can add files to."""
    folder = tmp_path / "migrations"
    shutil.copytree(migrate.MIGRATIONS_DIR, folder)
    return folder


def scalar(conn, sql):
    cursor = conn.cursor()
    cursor.execute(sql)
    return cursor.fetchone()[0]


# ---------- no database needed ----------

def test_split_batches_splits_on_go_lines_only():
    sql = "CREATE TABLE a (x INT);\nGO\nUPDATE a SET x = 1; -- not a GO line: GOOD\n  go  \n\n"
    assert migrate.split_batches(sql) == [
        "CREATE TABLE a (x INT);", "UPDATE a SET x = 1; -- not a GO line: GOOD"]


def test_migration_files_are_numbered_sql_files_in_order(tmp_path):
    for name in ["010_later.sql", "002_second.sql", "001_first.sql", "notes.txt", "3_bad.sql"]:
        (tmp_path / name).write_text("SELECT 1")
    assert migrate.migration_files(tmp_path) == [
        "001_first.sql", "002_second.sql", "010_later.sql"]


# ---------- against SQL Server ----------

def test_first_start_applies_everything_and_second_start_nothing(empty_database_url):
    conn = db.connect(empty_database_url, attempts=1)
    try:
        assert migrate.apply_migrations(conn) == ["001_init.sql"]
        assert migrate.apply_migrations(conn) == []
        assert scalar(conn, "SELECT COUNT(*) FROM schema_migrations") == 1
    finally:
        conn.close()


def test_a_migration_changes_a_table_and_keeps_its_rows(empty_database_url, tmp_path):
    folder = copy_migrations(tmp_path)
    conn = db.connect(empty_database_url, attempts=1)
    try:
        migrate.apply_migrations(conn, folder)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO students (name, guardian_phone) VALUES (N'Ana', N'0691234567')")
        conn.commit()

        # Adds a column and fills it in a second batch: the GO is required by SQL Server.
        (folder / "002_add_notes.sql").write_text(
            "ALTER TABLE students ADD notes NVARCHAR(50) NULL;\nGO\n"
            "UPDATE students SET notes = N'from before 002' WHERE notes IS NULL;\n"
        )
        assert migrate.apply_migrations(conn, folder) == ["002_add_notes.sql"]
        cursor.execute("SELECT name, notes FROM students")
        assert cursor.fetchall() == [("Ana", "from before 002")]
    finally:
        conn.close()


def test_a_failing_migration_leaves_nothing_behind(empty_database_url, tmp_path):
    folder = copy_migrations(tmp_path)
    (folder / "002_broken.sql").write_text(
        "CREATE TABLE half_done (x INT);\nGO\nTHIS IS NOT SQL;\n")
    conn = db.connect(empty_database_url, attempts=1)
    try:
        with pytest.raises(pymssql.Error):
            migrate.apply_migrations(conn, folder)
        assert scalar(conn, "SELECT COUNT(*) FROM sys.tables WHERE name = 'half_done'") == 0
        assert scalar(
            conn, "SELECT COUNT(*) FROM schema_migrations WHERE version = '002_broken.sql'") == 0
    finally:
        conn.close()


def test_editing_an_applied_migration_stops_the_start(empty_database_url, tmp_path):
    folder = copy_migrations(tmp_path)
    conn = db.connect(empty_database_url, attempts=1)
    try:
        migrate.apply_migrations(conn, folder)
        with open(folder / "001_init.sql", "a", encoding="utf-8") as file:
            file.write("\n-- edited afterwards\n")
        with pytest.raises(migrate.MigrationError, match="001_init.sql was changed"):
            migrate.apply_migrations(conn, folder)
    finally:
        conn.close()
