"""Shared test setup. Tests run against a real SQL Server, never against Azure.

Locally that is the SQL Server container from docker compose; in CI it is a
SQL Server service container. The tests sign in as sa, create their own
database lessons_test, and never touch the lessons database itself.

Settings, read from the environment, or else from the .env file at the
repository root:
    MSSQL_SA_PASSWORD   password of sa (required)
    TEST_DB_HOST        default localhost
    TEST_DB_PORT        default 1433
"""
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import pymssql
import pytest

import db
from customers_client import CustomersUnavailable, StudentNotFound
from migrate import apply_migrations

REPO_ROOT = Path(__file__).resolve().parents[3]


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
    """URL of a fresh lessons_test database with all migrations applied."""
    url = recreate_database("lessons_test")
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
    cursor.execute("DELETE FROM lessons; DELETE FROM tutors;")
    connection.commit()
    connection.close()


@pytest.fixture
def empty_database_url():
    """URL of a brand-new database without any migrations, for the migration tests."""
    return recreate_database("lessons_migrations_test")


# ---------- stand-ins for the customers service ----------

class FakeStudents:
    """Stands in for CustomersClient in the business-logic tests, without HTTP.

    Set down = True to behave like a customers service that is not responding.
    """

    def __init__(self):
        self.students = {}
        self.down = False
        self.calls = []

    def add(self, name="Ana Hoxha", archived=False):
        student_id = len(self.students) + 1
        self.students[student_id] = {"id": student_id, "name": name, "archived": archived}
        return student_id

    def get_student(self, student_id):
        self.calls.append(("get_student", student_id))
        if self.down:
            raise CustomersUnavailable("down")
        if student_id not in self.students:
            raise StudentNotFound(student_id)
        return self.students[student_id]

    def list_students(self):
        self.calls.append(("list_students",))
        if self.down:
            raise CustomersUnavailable("down")
        return list(self.students.values())


@pytest.fixture
def students():
    return FakeStudents()


class StubCustomersService:
    """A real HTTP server on a free local port that answers like the customers service.

    It answers GET /students and GET /students/{id} with the same JSON shapes as
    the customers service's API, so the lessons service's real HTTP calls,
    timeouts and error handling are tested without running the customers service.
    """

    def __init__(self):
        self.students = {}
        self.delay = 0           # seconds to wait before answering (to test the timeout)
        self.status = None       # answer every request with this status instead
        self.auth_headers = []   # the Authorization header of every request received
        self.paths = []          # the path, with query, of every request received
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                stub.auth_headers.append(self.headers.get("Authorization"))
                time.sleep(stub.delay)
                stub.paths.append(self.path)
                path = self.path.split("?")[0]
                match = re.fullmatch(r"/students/(\d+)", path)
                if stub.status is not None:
                    self._send(stub.status, {"error": "stub error"})
                elif path == "/students":
                    self._send(200, list(stub.students.values()))
                elif match and int(match.group(1)) in stub.students:
                    self._send(200, stub.students[int(match.group(1))])
                else:
                    self._send(404, {"error": "Student does not exist."})

            def _send(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):  # keep the test output quiet
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.running = True

    def add(self, name="Ana Hoxha", **fields):
        student_id = len(self.students) + 1
        self.students[student_id] = {
            "id": student_id, "name": name, "guardian_name": None,
            "guardian_email": None, "guardian_phone": "+355 69 123 4567", "archived": False,
            **fields,
        }
        return student_id

    def stop(self):
        """Like docker compose stop customers: nothing listens on the port any more."""
        if self.running:
            self.server.shutdown()
            self.server.server_close()
            self.running = False


@pytest.fixture
def customers_stub():
    stub = StubCustomersService()
    yield stub
    stub.stop()
