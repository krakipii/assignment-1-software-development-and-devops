"""Shared test setup. Tests run against a real SQL Server, never against Azure.

Locally that is the SQL Server container from docker compose; in CI it is a
SQL Server service container. The tests sign in as sa, create their own
database customers_test, and never touch the customers database itself.

Settings, read from the environment, or else from the .env file at the
repository root:
    MSSQL_SA_PASSWORD   password of sa (required)
    TEST_DB_HOST        default localhost
    TEST_DB_PORT        default 1433
"""
import os
from pathlib import Path
from urllib.parse import quote

import pymssql
import pytest

import db
from migrate import apply_migrations

REPO_ROOT = Path(__file__).resolve().parents[3]
TEST_DATABASES = ("customers_test", "customers_migrations_test")


def _setting(name, default=None):
    """An environment variable, or else the same line in the repository's .env file."""
    if os.environ.get(name):
        return os.environ[name]
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name and value.strip():
                return value.strip()
    return default


def _server():
    password = _setting("MSSQL_SA_PASSWORD")
    if not password:
        pytest.exit("Set MSSQL_SA_PASSWORD (or put it in .env) and start the db container.")
    return {
        "server": _setting("TEST_DB_HOST", "localhost"),
        "port": _setting("TEST_DB_PORT", "1433"),
        "user": "sa",
        "password": password,
    }


def _url(database):
    server = _server()
    return (f"mssql://sa:{quote(server['password'], safe='')}@{server['server']}:"
            f"{server['port']}/{database}")


def recreate_database(name):
    """Drop the test database if it exists and create it again, empty."""
    master = pymssql.connect(**_server(), database="master", autocommit=True)
    try:
        cursor = master.cursor()
        cursor.execute(
            f"IF DB_ID(N'{name}') IS NOT NULL BEGIN "
            f"ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
            f"DROP DATABASE [{name}]; END"
        )
        cursor.execute(f"CREATE DATABASE [{name}]")
    finally:
        master.close()
    return _url(name)


@pytest.fixture(scope="session")
def database_url():
    """URL of a fresh customers_test database with all migrations applied."""
    url = recreate_database("customers_test")
    conn = db.connect(url, attempts=1)
    try:
        apply_migrations(conn)
    finally:
        conn.close()
    return url


@pytest.fixture
def conn(database_url):
    """An open connection to the test database. Every test starts with empty tables."""
    connection = db.connect(database_url, attempts=1)
    yield connection
    connection.rollback()
    cursor = connection.cursor()
    cursor.execute("DELETE FROM students; DELETE FROM staff;")
    connection.commit()
    connection.close()


@pytest.fixture
def empty_database_url():
    """URL of a brand-new database without any migrations, for the migration tests."""
    return recreate_database("customers_migrations_test")
