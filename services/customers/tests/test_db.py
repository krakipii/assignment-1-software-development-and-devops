"""Tests for reading DATABASE_URL and for retrying the connection (db.py)."""
import pymssql
import pytest

import db


def test_parse_database_url_reads_every_part():
    settings = db.parse_database_url("mssql://customers_user:Pa%40ss1@db:1433/customers")
    assert settings == {
        "server": "db", "port": "1433", "user": "customers_user",
        "password": "Pa@ss1", "database": "customers",
    }


def test_parse_database_url_passes_encryption_for_azure():
    settings = db.parse_database_url(
        "mssql://u:p@x.database.windows.net/customers-db?encrypt=require")
    assert settings["encryption"] == "require"
    assert settings["port"] == "1433"


@pytest.mark.parametrize("url", [None, "", "postgres://u:p@h/d", "mssql://u:p@host", "nonsense"])
def test_parse_database_url_rejects_bad_values(url):
    with pytest.raises(ValueError, match="DATABASE_URL"):
        db.parse_database_url(url)


def test_connect_retries_with_a_doubling_wait(monkeypatch):
    calls, waits = [], []

    def fake_connect(**settings):
        calls.append(settings)
        if len(calls) < 3:
            raise pymssql.OperationalError("database is resuming (40613)")
        return "connection"

    monkeypatch.setattr(db.pymssql, "connect", fake_connect)
    result = db.connect("mssql://u:p@h:1433/d", attempts=5, first_delay=2, sleep=waits.append)
    assert result == "connection"
    assert waits == [2, 4]


def test_connect_gives_up_after_the_last_attempt(monkeypatch):
    def always_fails(**settings):
        raise pymssql.OperationalError("down")

    waits = []
    monkeypatch.setattr(db.pymssql, "connect", always_fails)
    with pytest.raises(pymssql.OperationalError):
        db.connect("mssql://u:p@h:1433/d", attempts=3, first_delay=1, sleep=waits.append)
    assert waits == [1, 2]
