"""HTTP API of the customers service: JSON in, JSON out.

This is only the HTTP layer. It reads the request, calls service.py or auth.py
and turns the result or the error into a JSON response with a status code.
"""
from flask import Blueprint, current_app, g, jsonify, request

import auth
import service
from db import get_db

bp = Blueprint("api", __name__)

# Endpoints anyone may call without a login token.
PUBLIC_ENDPOINTS = {"health", "api.login"}


def require_login():
    """Runs before every request: refuse it with 401 unless it carries a valid token."""
    if request.method == "OPTIONS" or request.endpoint in PUBLIC_ENDPOINTS:
        return None  # OPTIONS is the browser's CORS check, which never carries the token
    header = request.headers.get("Authorization", "")
    token = header[len("Bearer "):] if header.startswith("Bearer ") else None
    staff = auth.read_token(current_app.config["AUTH_SECRET"], token)
    if staff is None:
        return jsonify(error="Log in first."), 401
    g.staff = staff
    return None


def _json_body():
    """The request's JSON object, or {} if the body is missing or not JSON."""
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


@bp.post("/auth/login")
def login():
    body = _json_body()
    staff = auth.check_login(get_db(), body.get("username"), body.get("password"))
    if staff is None:
        return jsonify(error="Wrong username or password."), 401
    token = auth.make_token(current_app.config["AUTH_SECRET"], staff)
    return jsonify(token=token, username=staff["username"])


@bp.get("/students")
def list_students():
    include_archived = request.args.get("include_archived") == "true"
    return jsonify(service.list_students(get_db(), request.args.get("q"), include_archived))


@bp.post("/students")
def create_student():
    conn = get_db()
    try:
        student_id = service.create_student(conn, _json_body())
    except service.ValidationError as error:
        return jsonify(error=str(error)), 400
    return jsonify(service.get_student(conn, student_id)), 201


@bp.get("/students/<int:student_id>")
def get_student(student_id):
    try:
        return jsonify(service.get_student(get_db(), student_id))
    except service.StudentNotFound as error:
        return jsonify(error=str(error)), 404


@bp.put("/students/<int:student_id>")
def update_student(student_id):
    conn = get_db()
    try:
        service.update_student(conn, student_id, _json_body())
    except service.ValidationError as error:
        return jsonify(error=str(error)), 400
    except service.StudentNotFound as error:
        return jsonify(error=str(error)), 404
    return jsonify(service.get_student(conn, student_id))


@bp.delete("/students/<int:student_id>")
def archive_student(student_id):
    """DELETE archives the student (migration 002): the row and its lessons stay."""
    try:
        service.archive_student(get_db(), student_id)
    except service.StudentNotFound as error:
        return jsonify(error=str(error)), 404
    return "", 204
