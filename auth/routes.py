"""Handles login and logout pages and protects the other pages from unauthorised users."""
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from auth import service
from database import get_connection, get_db

bp = Blueprint("auth", __name__)

PUBLIC_ENDPOINTS = {"auth.login", "static", "health"}


def require_login():
    """Runs before each request and sends users who are not logged in to the login page."""
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if "staff_id" not in session:
        return redirect(url_for("auth.login"))
    return None


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        staff = service.check_login(get_db(), username, request.form.get("password"))
        if staff is None:
            flash("Wrong username or password.", "error")
            return render_template("auth/login.html", username=username), 401
        session.clear() 
        session["staff_id"] = staff["id"]
        session["username"] = staff["username"]
        return redirect(url_for("index"))

    if "staff_id" in session:
        return redirect(url_for("index"))
    return render_template("auth/login.html", username="")


@bp.post("/logout")
def logout():
    session.clear()
    flash("You are logged out.", "success")
    return redirect(url_for("auth.login"))


def init_app(app):
    """Switch on the login pages and the login check, and create the admin account."""
    app.register_blueprint(bp)
    app.before_request(require_login)

    username = app.config["ADMIN_USERNAME"]
    conn = get_connection(app.config["DB_PATH"])
    try:
        generated = service.ensure_admin(conn, username, app.config["ADMIN_PASSWORD"])
    finally:
        conn.close()
    if generated:
        print(f"Created staff account '{username}' with password: {generated}", flush=True)
        print("Set ADMIN_PASSWORD to choose your own password.", flush=True)