"""Main entry point for the tutoring app. Start it with: python app.py

Optional settings can be changed using environment variables such as 
PORT, DATA_DIR, SECRET_KEY, ADMIN_USERNAME, and ADMIN_PASSWORD.
"""

import os
import secrets

from flask import Flask, jsonify, redirect, url_for

import auth.routes
import database
from customers.routes import bp as customers_bp
from lessons.routes import bp as lessons_bp


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