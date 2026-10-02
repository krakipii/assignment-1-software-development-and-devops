"""Web pages for lessons and tutors.

This file handles requests and calls lessons.service, while all business rules stay in service.py.
"""
from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from database import get_db
from lessons import service

bp = Blueprint("lessons", __name__)


@bp.app_template_filter("lesson_time")
def lesson_time(value):
    """Show '2026-10-05T16:00' as 'Mon 05 Oct 2026, 16:00' in the templates."""
    return datetime.fromisoformat(value).strftime("%a %d %b %Y, %H:%M")


# ---------- lessons ----------

@bp.get("/lessons/")
def list_lessons():
    conn = get_db()
    status = request.args.get("status") or None
    tutor_id = request.args.get("tutor_id", type=int)

    tutor = None
    if tutor_id is not None:
        try:
            tutor = service.get_tutor(conn, tutor_id)
        except service.TutorNotFound:
            abort(404)
    try:
        lessons = service.list_lessons(conn, status=status, tutor_id=tutor_id)
    except service.ValidationError:
        abort(400)  # unknown status in the URL

    return render_template(
        "lessons/list.html", lessons=lessons, status=status,
        tutor=tutor, statuses=service.STATUSES,
    )


def _lesson_form(conn, lesson, status_code=200):
    """Show the scheduling form with the tutors and students to choose from."""
    return render_template(
        "lessons/form.html", lesson=lesson,
        tutors=service.list_tutors(conn), students=service.student_choices(conn),
    ), status_code


@bp.route("/lessons/new", methods=["GET", "POST"])
def schedule_lesson():
    conn = get_db()
    if request.method == "POST":
        try:
            service.schedule_lesson(conn, request.form)
        except (service.ValidationError, service.ScheduleConflict) as error:
            flash(str(error), "error")
            return _lesson_form(conn, request.form, 400)
        flash("Lesson scheduled.", "success")
        return redirect(url_for("lessons.list_lessons"))

    return _lesson_form(conn, {"duration_minutes": 60})


@bp.post("/lessons/<int:lesson_id>/status")
def change_status(lesson_id):
    new_status = request.form.get("status", "")
    try:
        service.change_status(get_db(), lesson_id, new_status)
    except service.LessonNotFound:
        abort(404)
    except service.InvalidStatusChange as error:
        flash(str(error), "error")
    else:
        flash(f"Lesson marked as {new_status}.", "success")
    return redirect(url_for("lessons.list_lessons"))


# ---------- tutors ----------

@bp.get("/tutors/")
def list_tutors():
    return render_template("lessons/tutors.html", tutors=service.list_tutors(get_db()))


@bp.route("/tutors/new", methods=["GET", "POST"])
def create_tutor():
    if request.method == "POST":
        try:
            service.create_tutor(get_db(), request.form)
        except service.ValidationError as error:
            flash(str(error), "error")
            return render_template(
                "lessons/tutor_form.html", tutor=request.form,
                title="Add tutor", submit_label="Save tutor",
            ), 400
        flash("Tutor added.", "success")
        return redirect(url_for("lessons.list_tutors"))

    return render_template(
        "lessons/tutor_form.html", tutor={},
        title="Add tutor", submit_label="Save tutor",
    )


@bp.route("/tutors/<int:tutor_id>/edit", methods=["GET", "POST"])
def edit_tutor(tutor_id):
    conn = get_db()
    try:
        tutor = service.get_tutor(conn, tutor_id)
    except service.TutorNotFound:
        abort(404)
    title = f"Edit {tutor['name']}"

    if request.method == "POST":
        try:
            service.update_tutor(conn, tutor_id, request.form)
        except service.ValidationError as error:
            flash(str(error), "error")
            return render_template(
                "lessons/tutor_form.html", tutor=request.form,
                title=title, submit_label="Save changes",
            ), 400
        flash("Changes saved.", "success")
        return redirect(url_for("lessons.list_tutors"))

    return render_template(
        "lessons/tutor_form.html", tutor=tutor,
        title=title, submit_label="Save changes",
    )