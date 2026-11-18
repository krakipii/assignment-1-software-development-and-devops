"""Connection to the lessons database (SQL Server).

The connection string comes from DATABASE_URL, for example
    mssql://lessons_user:PASSWORD@localhost:1433/lessons
and, on Azure, with ?encrypt=require at the end, because Azure SQL only
accepts encrypted connections.

On Azure the serverless database pauses when idle. The first connection after
a pause fails for up to about a minute while it resumes (error 40613), so
connect() retries with a growing wait instead of giving up at once.
"""
import logging
import time
from urllib.parse import parse_qs, unquote, urlparse

import pymssql
from flask import current_app, g

log = logging.getLogger(__name__)

CONNECT_ATTEMPTS = 6        # waits of 2, 4, 8, 16 and 32 seconds: about a minute in total
FIRST_RETRY_DELAY = 2


def parse_database_url(url):
    """Turn 'mssql://user:password@host:port/database?encrypt=require' into connect() arguments."""
    parts = urlparse(url or "")
    if parts.scheme != "mssql" or not parts.hostname or not parts.path.strip("/"):
        raise ValueError(
            "DATABASE_URL must look like mssql://user:password@host:1433/database"
        )
    settings = {
        "server": parts.hostname,
        "port": str(parts.port or 1433),
        "user": unquote(parts.username or ""),
        "password": unquote(parts.password or ""),
        "database": parts.path.strip("/"),
    }
    encrypt = parse_qs(parts.query).get("encrypt")
    if encrypt:
        settings["encryption"] = encrypt[0]
    return settings


def connect(url, attempts=CONNECT_ATTEMPTS, first_delay=FIRST_RETRY_DELAY, sleep=time.sleep):
    """Open a connection, retrying with a doubling wait while the database is unavailable."""
    settings = parse_database_url(url)
    delay = first_delay
    for attempt in range(1, attempts + 1):
        try:
            return pymssql.connect(**settings, login_timeout=15, timeout=30)
        except pymssql.Error as error:
            if attempt == attempts:
                raise
            log.warning(
                "Database not reachable (attempt %d of %d): %s. Retrying in %d s.",
                attempt, attempts, error, delay,
            )
            sleep(delay)
            delay *= 2
    return None  # not reached: the last attempt either returns or raises


def get_db():
    """The connection for the current request, opened the first time it is needed."""
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE_URL"])
    return g.db


def close_db(exception=None):
    """Close the request's connection. Flask calls this after every request."""
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()
