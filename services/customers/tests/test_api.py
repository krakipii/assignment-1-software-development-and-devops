"""Tests for the HTTP API (app.py, routes.py) through Flask's test client."""
import logging

import pytest

from app import create_app

UI_ORIGIN = "http://localhost:8080"


@pytest.fixture
def app(database_url, conn):
    # conn is requested so the tables are emptied again after each test.
    return create_app({
        "DATABASE_URL": database_url,
        "AUTH_SECRET": "test-secret",
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "admin-pass",
        "CORS_ORIGINS": [UI_ORIGIN],
        "VERSION": "abc123",
    })


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def headers(client):
    """Authorization header of a logged-in staff member."""
    response = client.post("/auth/login", json={"username": "admin", "password": "admin-pass"})
    return {"Authorization": f"Bearer {response.get_json()['token']}"}


def new_student(client, headers, **changes):
    data = {"name": "Ana Hoxha", "guardian_phone": "+355 69 123 4567"}
    data.update(changes)
    return client.post("/students", json=data, headers=headers)


# ---------- health and logging ----------

def test_health_reports_ok_and_the_version(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "db": "ok", "version": "abc123"}


def test_health_is_503_when_the_database_is_unreachable(app, client):
    app.config["DATABASE_URL"] = "mssql://nobody:wrong@127.0.0.1:1/customers"
    response = client.get("/health")
    assert response.status_code == 503
    assert response.get_json()["db"] == "error"


def test_every_request_is_logged_with_method_path_status_and_duration(client, caplog):
    with caplog.at_level(logging.INFO, logger="customers"):
        client.get("/health")
    assert any(
        "GET /health 200" in record.getMessage() and record.getMessage().endswith("ms")
        for record in caplog.records
    )


# ---------- login ----------

def test_login_with_the_wrong_password_is_refused(client):
    response = client.post("/auth/login", json={"username": "admin", "password": "nope"})
    assert response.status_code == 401


def test_requests_without_a_valid_token_are_refused(client):
    assert client.get("/students").status_code == 401
    bad = {"Authorization": "Bearer not-a-token"}
    assert client.get("/students", headers=bad).status_code == 401


# ---------- students ----------

def test_create_read_update_and_delete_a_student(client, headers):
    created = new_student(client, headers)
    assert created.status_code == 201
    student = created.get_json()
    assert student["name"] == "Ana Hoxha"

    url = f"/students/{student['id']}"
    assert client.get(url, headers=headers).get_json() == student

    changed = client.put(url, json={"name": "Ana H.", "guardian_phone": "+355 69 123 4567"},
                         headers=headers)
    assert changed.status_code == 200
    assert changed.get_json()["name"] == "Ana H."

    assert client.delete(url, headers=headers).status_code == 204
    assert client.get(url, headers=headers).status_code == 404


def test_list_and_search_students(client, headers):
    new_student(client, headers, name="Ana Hoxha")
    new_student(client, headers, name="Dritan Kola")
    everyone = client.get("/students", headers=headers).get_json()
    assert [s["name"] for s in everyone] == ["Ana Hoxha", "Dritan Kola"]
    found = client.get("/students?q=kol", headers=headers).get_json()
    assert [s["name"] for s in found] == ["Dritan Kola"]


def test_invalid_student_gives_400_with_the_reason(client, headers):
    response = new_student(client, headers, name="")
    assert response.status_code == 400
    assert response.get_json() == {"error": "Student name is required."}
    not_json = client.post("/students", data="hello", headers=headers)
    assert not_json.status_code == 400


def test_unknown_student_gives_404(client, headers):
    assert client.get("/students/999999", headers=headers).status_code == 404
    assert client.delete("/students/999999", headers=headers).status_code == 404
    response = client.put("/students/999999", json={"name": "X", "guardian_phone": "0691234567"},
                          headers=headers)
    assert response.status_code == 404
    bad_update = client.put("/students/999999", json={"name": ""}, headers=headers)
    assert bad_update.status_code == 400


def test_errors_are_json_not_html(client, headers):
    response = client.get("/no-such-page", headers=headers)
    assert response.status_code == 404
    assert "error" in response.get_json()


# ---------- CORS ----------

def test_the_ui_origin_may_call_the_api_from_a_browser(client):
    response = client.options("/students", headers={
        "Origin": UI_ORIGIN,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Content-Type, Authorization",
    })
    assert response.headers.get("Access-Control-Allow-Origin") == UI_ORIGIN


def test_other_origins_get_no_cors_permission(client):
    response = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in response.headers
