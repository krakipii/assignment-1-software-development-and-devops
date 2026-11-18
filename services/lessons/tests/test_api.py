"""Tests for the HTTP API (app.py, routes.py), including the flow across the seam.

The lessons service runs through Flask's test client against its real SQL
Server test database. The customers service is replaced by
StubCustomersService (conftest.py), a real HTTP server answering with the same
JSON shapes, so these are integration tests of the cross-seam calls: real
HTTP, real timeouts, and the customers service stopped half-way (ADR-9).
"""
import logging
import time

import pytest
from itsdangerous import URLSafeTimedSerializer

import auth
import routes
from app import create_app

UI_ORIGIN = "http://localhost:8080"
SECRET = "shared-test-secret"


@pytest.fixture
def app(database_url, conn, customers_stub):
    # conn is requested so the tables are emptied again after each test.
    return create_app({
        "DATABASE_URL": database_url,
        "AUTH_SECRET": SECRET,
        "CUSTOMERS_URL": customers_stub.url,
        "CUSTOMERS_TIMEOUT_S": 0.5,
        "CORS_ORIGINS": [UI_ORIGIN],
        "VERSION": "abc123",
    })


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def token():
    """A token like the one the customers service hands out at login."""
    return URLSafeTimedSerializer(SECRET, salt=auth.TOKEN_SALT).dumps(
        {"id": 1, "username": "admin"})


@pytest.fixture
def headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def tutor(client, headers):
    response = client.post("/tutors", headers=headers, json={
        "name": "Mira Kola", "subjects": "Maths, Physics", "hourly_rate": 25})
    return response.get_json()


def book(client, headers, tutor_id, student_id, **changes):
    data = {"tutor_id": tutor_id, "student_id": student_id, "subject": "Maths",
            "start_time": "2030-10-05T16:00", "duration_minutes": 60}
    data.update(changes)
    return client.post("/lessons", json=data, headers=headers)


# ---------- health, logging, login ----------

def test_health_reports_ok_and_the_version(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "db": "ok", "version": "abc123"}


def test_health_does_not_depend_on_the_customers_service(client, customers_stub):
    customers_stub.stop()
    assert client.get("/health").status_code == 200


def test_health_is_503_when_the_database_is_unreachable(app, client):
    app.config["DATABASE_URL"] = "mssql://nobody:wrong@127.0.0.1:1/lessons"
    response = client.get("/health")
    assert response.status_code == 503
    assert response.get_json()["db"] == "error"


def test_every_request_is_logged_with_method_path_status_and_duration(client, caplog):
    with caplog.at_level(logging.INFO, logger="lessons"):
        client.get("/health")
    assert any("GET /health 200" in r.getMessage() and r.getMessage().endswith("ms")
               for r in caplog.records)


def test_requests_without_a_valid_token_are_refused(client):
    assert client.get("/lessons").status_code == 401
    other = URLSafeTimedSerializer("another-secret", salt=auth.TOKEN_SALT).dumps({"id": 1})
    assert client.get("/lessons", headers={"Authorization": f"Bearer {other}"}).status_code == 401


def test_the_service_refuses_to_start_without_auth_secret(database_url):
    with pytest.raises(RuntimeError, match="AUTH_SECRET"):
        create_app({"DATABASE_URL": database_url, "AUTH_SECRET": None})


def test_the_service_refuses_to_start_without_database_url():
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app({"DATABASE_URL": None, "AUTH_SECRET": SECRET})


# ---------- tutors ----------

def test_create_read_update_and_list_tutors(client, headers, tutor):
    assert tutor["name"] == "Mira Kola"
    assert tutor["hourly_rate"] == 25
    url = f"/tutors/{tutor['id']}"
    assert client.get(url, headers=headers).get_json() == tutor
    changed = client.put(url, headers=headers, json={"name": "Mira K.", "hourly_rate": 30})
    assert changed.status_code == 200
    assert changed.get_json()["name"] == "Mira K."
    assert [t["name"] for t in client.get("/tutors", headers=headers).get_json()] == ["Mira K."]


def test_tutor_errors(client, headers, tutor):
    assert client.post("/tutors", headers=headers, json={"name": ""}).status_code == 400
    assert client.get("/tutors/999999", headers=headers).status_code == 404
    missing = client.put("/tutors/999999", headers=headers, json={"name": "X", "hourly_rate": 1})
    assert missing.status_code == 404
    invalid = client.put(f"/tutors/{tutor['id']}", headers=headers, json={"hourly_rate": "x"})
    assert invalid.status_code == 400


# ---------- across the seam: scheduling ----------

def test_scheduling_checks_the_student_with_the_customers_service(
        client, headers, tutor, customers_stub, token):
    student_id = customers_stub.add("Ana")
    response = book(client, headers, tutor["id"], student_id)
    assert response.status_code == 201
    assert response.get_json()["student_id"] == student_id
    # The staff member's token was passed on to the customers service.
    assert customers_stub.auth_headers == [f"Bearer {token}"]


def test_scheduling_for_a_student_the_customers_service_does_not_know(client, headers, tutor):
    response = book(client, headers, tutor["id"], 42)
    assert response.status_code == 400
    assert response.get_json() == {"error": "Choose an existing student."}


def test_double_booking_gives_409(client, headers, tutor, customers_stub):
    student_id = customers_stub.add()
    book(client, headers, tutor["id"], student_id)
    response = book(client, headers, tutor["id"], student_id, start_time="2030-10-05T16:30")
    assert response.status_code == 409
    assert "already has a lesson" in response.get_json()["error"]


def test_scheduling_is_refused_clearly_when_the_customers_service_is_stopped(
        client, headers, tutor, customers_stub):
    student_id = customers_stub.add()
    customers_stub.stop()
    response = book(client, headers, tutor["id"], student_id)
    assert response.status_code == 503
    assert response.get_json() == {"error": routes.SCHEDULING_UNAVAILABLE}
    assert client.get("/lessons", headers=headers).get_json()["lessons"] == []


def test_a_slow_customers_service_fails_fast_instead_of_hanging(
        client, headers, tutor, customers_stub):
    student_id = customers_stub.add()
    customers_stub.delay = 2  # longer than the 0.5 s timeout
    started = time.perf_counter()
    response = book(client, headers, tutor["id"], student_id)
    assert response.status_code == 503
    assert time.perf_counter() - started < 1.5


# ---------- across the seam: the lesson list ----------

def test_lesson_list_has_student_names_from_the_customers_service(
        client, headers, tutor, customers_stub):
    book(client, headers, tutor["id"], customers_stub.add("Ana"))
    body = client.get("/lessons", headers=headers).get_json()
    assert body["students_available"] is True
    assert body["notice"] is None
    assert body["lessons"][0]["student_name"] == "Ana"
    assert body["lessons"][0]["tutor_name"] == "Mira Kola"


def test_lesson_list_degrades_when_the_customers_service_is_stopped(
        client, headers, tutor, customers_stub):
    book(client, headers, tutor["id"], customers_stub.add("Ana"))
    customers_stub.stop()
    response = client.get("/lessons", headers=headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body["students_available"] is False
    assert body["notice"] == routes.NAMES_UNAVAILABLE
    assert body["lessons"][0]["student_name"] is None
    assert body["lessons"][0]["subject"] == "Maths"


def test_lesson_list_filters(client, headers, tutor, customers_stub):
    lesson = book(client, headers, tutor["id"], customers_stub.add()).get_json()
    url = f"/lessons?status=scheduled&tutor_id={tutor['id']}"
    assert [x["id"] for x in client.get(url, headers=headers).get_json()["lessons"]] == [
        lesson["id"]]
    assert client.get("/lessons?status=postponed", headers=headers).status_code == 400
    assert client.get("/lessons?tutor_id=999999", headers=headers).status_code == 404


# ---------- lesson status ----------

def test_changing_a_lesson_status(client, headers, tutor, customers_stub):
    lesson = book(client, headers, tutor["id"], customers_stub.add()).get_json()
    url = f"/lessons/{lesson['id']}"
    done = client.post(f"{url}/status", headers=headers, json={"status": "completed"})
    assert done.status_code == 200
    assert done.get_json()["status"] == "completed"
    again = client.post(f"{url}/status", headers=headers, json={"status": "cancelled"})
    assert again.status_code == 409
    assert client.get(url, headers=headers).get_json()["status"] == "completed"


def test_unknown_lesson_gives_404(client, headers):
    assert client.get("/lessons/999999", headers=headers).status_code == 404
    response = client.post("/lessons/999999/status", headers=headers, json={"status": "completed"})
    assert response.status_code == 404


def test_errors_are_json_not_html(client, headers):
    response = client.get("/no-such-page", headers=headers)
    assert response.status_code == 404
    assert "error" in response.get_json()


# ---------- CORS ----------

def test_the_ui_origin_may_call_the_api_from_a_browser(client):
    response = client.options("/lessons", headers={
        "Origin": UI_ORIGIN,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Content-Type, Authorization",
    })
    assert response.headers.get("Access-Control-Allow-Origin") == UI_ORIGIN


def test_other_origins_get_no_cors_permission(client):
    response = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in response.headers
