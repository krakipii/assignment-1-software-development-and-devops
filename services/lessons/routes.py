"""HTTP API of the lessons service: JSON in, JSON out.

This is only the HTTP layer. It reads the request, calls service.py and turns
the result or the error into a JSON response with a status code. It also
decides what the user sees when the customers service is unavailable.
"""
from flask import Blueprint, current_app, g, jsonify, request

import auth
import service
from customers_client import CustomersClient, CustomersUnavailable
from db import get_db

bp = Blueprint("api", __name__)

PUBLIC_ENDPOINTS = {"health"}
SCHEDULING_UNAVAILABLE = (
    "The customers service is not responding, so the student cannot be checked. "
    "The lesson was not scheduled. Try again in a minute."
)
NAMES_UNAVAILABLE = (
    "Student names are not available right now because the customers service "
    "is not responding. The lessons themselves are up to date."
)


def require_login():
    """Runs before every request: refuse it with 401 unless it carries a valid token."""
    if request.method == "OPTIONS" or request.endpoint in PUBLIC_ENDPOINTS:
        return None  # OPTIONS is the browser's CORS check, which never carries the token
    header = request.headers.get("Authorization", "")
    token = header[len("Bearer "):] if header.startswith("Bearer ") else None
    staff = auth.read_token(current_app.config["AUTH_SECRET"], token)
    if staff is None:
        return jsonify(error="Log in first."), 401
    g.staff, g.token = staff, token
    return None


def students():
    """A client for the customers service, carrying this request's login token."""
    return CustomersClient(
        current_app.config["CUSTOMERS_URL"],
        timeout=current_app.config["CUSTOMERS_TIMEOUT_S"],
        token=g.get("token"),
    )


def _json_body():
    """The request's JSON object, or {} if the body is missing or not JSON."""
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


# ---------- lessons ----------

@bp.get("/lessons")
def list_lessons():
    conn = get_db()
    status = request.args.get("status") or None
    tutor_id = request.args.get("tutor_id", type=int)
    if tutor_id is not None:
        try:
            service.get_tutor(conn, tutor_id)
        except service.TutorNotFound as error:
            return jsonify(error=str(error)), 404
    try:
        result = service.list_lessons(conn, students(), status=status, tutor_id=tutor_id)
    except service.ValidationError as error:
        return jsonify(error=str(error)), 400
    # Degraded, not failed: the lessons are shown, the names are missing.
    result["notice"] = None if result["students_available"] else NAMES_UNAVAILABLE
    return jsonify(result)


@bp.post("/lessons")
def schedule_lesson():
    conn = get_db()
    try:
        lesson_id = service.schedule_lesson(conn, students(), _json_body())
    except service.ValidationError as error:
        return jsonify(error=str(error)), 400
    except service.ScheduleConflict as error:
        return jsonify(error=str(error)), 409
    except CustomersUnavailable:
        # Fail, by design: a lesson for a student nobody could check is worse
        # than no lesson (ADR-6).
        return jsonify(error=SCHEDULING_UNAVAILABLE), 503
    return jsonify(service.get_lesson(conn, lesson_id)), 201


@bp.get("/lessons/<int:lesson_id>")
def get_lesson(lesson_id):
    try:
        return jsonify(service.get_lesson(get_db(), lesson_id))
    except service.LessonNotFound as error:
        return jsonify(error=str(error)), 404


@bp.post("/lessons/<int:lesson_id>/status")
def change_status(lesson_id):
    conn = get_db()
    try:
        service.change_status(conn, lesson_id, _json_body().get("status", ""))
    except service.LessonNotFound as error:
        return jsonify(error=str(error)), 404
    except service.InvalidStatusChange as error:
        return jsonify(error=str(error)), 409
    return jsonify(service.get_lesson(conn, lesson_id))


# ---------- tutors ----------

@bp.get("/tutors")
def list_tutors():
    return jsonify(service.list_tutors(get_db()))


@bp.post("/tutors")
def create_tutor():
    conn = get_db()
    try:
        tutor_id = service.create_tutor(conn, _json_body())
    except service.ValidationError as error:
        return jsonify(error=str(error)), 400
    return jsonify(service.get_tutor(conn, tutor_id)), 201


@bp.get("/tutors/<int:tutor_id>")
def get_tutor(tutor_id):
    try:
        return jsonify(service.get_tutor(get_db(), tutor_id))
    except service.TutorNotFound as error:
        return jsonify(error=str(error)), 404


@bp.put("/tutors/<int:tutor_id>")
def update_tutor(tutor_id):
    conn = get_db()
    try:
        service.update_tutor(conn, tutor_id, _json_body())
    except service.ValidationError as error:
        return jsonify(error=str(error)), 400
    except service.TutorNotFound as error:
        return jsonify(error=str(error)), 404
    return jsonify(service.get_tutor(conn, tutor_id))
