"""Web pages of the customers domain.

This is only the HTTP layer. It reads the request, calls customers.service,
and decides which page to show. All business rules are in service.py.
"""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from customers import service
from database import get_db

bp = Blueprint("customers", __name__, url_prefix="/students")


@bp.get("/")
def list_students():
    search = request.args.get("q", "")
    students = service.list_students(get_db(), search)
    return render_template("customers/list.html", students=students, search=search)


@bp.route("/new", methods=["GET", "POST"])
def create_student():
    if request.method == "POST":
        try:
            service.create_student(get_db(), request.form)
        except service.ValidationError as error:
            flash(str(error), "error")
            return render_template(
                "customers/form.html", student=request.form,
                title="Add student", submit_label="Save student",
            ), 400
        flash("Student added.", "success")
        return redirect(url_for("customers.list_students"))

    return render_template(
        "customers/form.html", student={},
        title="Add student", submit_label="Save student",
    )


@bp.route("/<int:student_id>/edit", methods=["GET", "POST"])
def edit_student(student_id):
    conn = get_db()
    try:
        student = service.get_student(conn, student_id)
    except service.StudentNotFound:
        abort(404)
    title = f"Edit {student['name']}"

    if request.method == "POST":
        try:
            service.update_student(conn, student_id, request.form)
        except service.ValidationError as error:
            flash(str(error), "error")
            return render_template(
                "customers/form.html", student=request.form,
                title=title, submit_label="Save changes",
            ), 400
        flash("Changes saved.", "success")
        return redirect(url_for("customers.list_students"))

    return render_template(
        "customers/form.html", student=student,
        title=title, submit_label="Save changes",
    )


@bp.post("/<int:student_id>/delete")
def delete_student(student_id):
    try:
        service.delete_student(get_db(), student_id)
    except service.StudentNotFound:
        abort(404)
    except service.StudentHasLessons as error:
        flash(str(error), "error")
    else:
        flash("Student deleted.", "success")
    return redirect(url_for("customers.list_students"))