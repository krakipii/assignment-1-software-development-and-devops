"""Entry point of the tutoring app. Start it with:  python app.py

Configuration (all optional, set as environment variables):
    PORT            port to listen on (default 8000)
    DATA_DIR        folder that holds tutoring.db (default: ./data next to this file)
    SECRET_KEY      key that signs session cookies (default: random on every start)
    ADMIN_USERNAME  username of the staff account created at start (default: admin)
    ADMIN_PASSWORD  its password (default: a random one, printed once at first start)
"""
import os
import secrets

from flask import Flask, jsonify, redirect, render_template, url_for
from werkzeug.exceptions import HTTPException

import auth.routes
import database
from customers.routes import bp as customers_bp
from lessons.routes import bp as lessons_bp

# Friendly pages for the errors a user can run into: (title, explanation).
ERROR_PAGES = {
    400: ("This request could not be handled",
          "Something in the address or the form was not valid. Go back and try again."),
    404: ("Page not found",
          "The page or record you asked for does not exist. "
          "It may have been deleted, or the address may be mistyped."),
    405: ("That action is not possible here",
          "This page cannot be used in that way, for example by opening a delete link directly."),
    500: ("Something went wrong",
          "An unexpected error happened. Try again, and if it keeps happening, "
          "contact the person who runs this app."),
}


def show_error_page(error):
    """Show an error as a normal page in the app's layout, with the right status code."""
    code = error.code if isinstance(error, HTTPException) else 500
    title, message = ERROR_PAGES.get(code, ERROR_PAGES[500])
    return render_template("error.html", code=code, title=title, message=message), code


def create_app(db_path=None):
    """Build and configure the Flask app. Tests pass their own db_path."""
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path or database.get_db_path()
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    app.config["ADMIN_USERNAME"] = os.environ.get("ADMIN_USERNAME", "").strip() or "admin"
    app.config["ADMIN_PASSWORD"] = os.environ.get("ADMIN_PASSWORD")
    
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    database.init_app(app)
    auth.routes.init_app(app)
    app.register_blueprint(customers_bp)
    app.register_blueprint(lessons_bp)
    for code in ERROR_PAGES:
        app.register_error_handler(code, show_error_page)

    @app.get("/")
    def index():
        return redirect(url_for("lessons.list_lessons"))

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    # 0.0.0.0 so the app is reachable from outside a container later.
    # No debug=True: the reloader would start a second process.
    create_app().run(host="0.0.0.0", port=port)
