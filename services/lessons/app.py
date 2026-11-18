"""Entry point of the lessons service. Start it with:  python app.py

Configuration, all through environment variables:
    DATABASE_URL        required: mssql://user:password@host:1433/lessons
    PORT                port to listen on (default 8000)
    AUTH_SECRET         checks the login tokens; must be the same value as in the
                        customers service, which signs them (no default)
    CUSTOMERS_URL       base URL of the customers service (default http://customers:8000)
    CUSTOMERS_TIMEOUT_S seconds to wait for the customers service (default 3)
    CORS_ORIGINS        comma-separated origins allowed to call the API from a browser
                        (default: http://localhost:8080, the UI in docker compose)
    GIT_SHA             commit the image was built from, shown by /health (default: dev)
"""
import logging
import os
import sys
import time

import pymssql
from flask import Flask, g, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

import db
from migrate import apply_migrations
from routes import bp, require_login

log = logging.getLogger("lessons")


def settings_from_environment():
    """Read the configuration from environment variables."""
    origins = os.environ.get("CORS_ORIGINS", "http://localhost:8080")
    return {
        "DATABASE_URL": os.environ.get("DATABASE_URL"),
        "AUTH_SECRET": os.environ.get("AUTH_SECRET"),
        "CUSTOMERS_URL": os.environ.get("CUSTOMERS_URL", "http://customers:8000"),
        "CUSTOMERS_TIMEOUT_S": float(os.environ.get("CUSTOMERS_TIMEOUT_S", "3")),
        "CORS_ORIGINS": [origin.strip() for origin in origins.split(",") if origin.strip()],
        "VERSION": os.environ.get("GIT_SHA", "dev"),
    }


def prepare_database(app):
    """At start: wait for the database and apply pending migrations."""
    conn = db.connect(app.config["DATABASE_URL"])
    try:
        apply_migrations(conn)
    finally:
        conn.close()


def create_app(overrides=None):
    """Build the Flask app. Tests pass overrides instead of environment variables."""
    logging.basicConfig(
        level=logging.INFO, stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = Flask(__name__)
    app.config.update(settings_from_environment())
    app.config.update(overrides or {})

    if not app.config["DATABASE_URL"]:
        raise RuntimeError("Set DATABASE_URL, e.g. mssql://user:password@localhost:1433/lessons")
    if not app.config["AUTH_SECRET"]:
        # Without the customers service's secret no token can ever be checked.
        raise RuntimeError("Set AUTH_SECRET to the same value as in the customers service.")

    # Browsers may call this API only from the UI's origin(s).
    CORS(app, origins=app.config["CORS_ORIGINS"], allow_headers=["Content-Type", "Authorization"])

    prepare_database(app)

    @app.before_request
    def start_timer():
        g.started = time.perf_counter()

    app.register_blueprint(bp)
    app.before_request(require_login)  # registered after start_timer, so it runs after it
    app.teardown_appcontext(db.close_db)

    @app.after_request
    def log_request(response):
        # One line per request on stdout: method, path, status, duration.
        duration_ms = (time.perf_counter() - g.get("started", time.perf_counter())) * 1000
        log.info("%s %s %s %.0fms", request.method, request.path, response.status_code,
                 duration_ms)
        return response

    @app.errorhandler(Exception)
    def json_error(error):
        """Every error becomes JSON, never an HTML page or a stack trace."""
        if isinstance(error, HTTPException):
            return jsonify(error=error.description), error.code
        log.exception("Unexpected error")
        return jsonify(error="Something went wrong in the lessons service."), 500

    @app.get("/health")
    def health():
        """200 if this service can read and write its own database, 503 if not."""
        body = {"status": "ok", "db": "ok", "version": app.config["VERSION"]}
        try:
            conn = db.connect(app.config["DATABASE_URL"], attempts=2, first_delay=1)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM schema_migrations")   # read
                cursor.fetchone()
                cursor.execute(                                             # write ...
                    "UPDATE health_check SET checked_at = SYSUTCDATETIME() WHERE id = 1")
                conn.rollback()                                             # ... and undo it
            finally:
                conn.close()
        except (pymssql.Error, ValueError) as error:  # the database is not usable
            log.warning("Health check failed: %s", error)
            body.update(status="error", db="error")
            return jsonify(body), 503
        return jsonify(body)

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    # 0.0.0.0 so the service is reachable from outside its container.
    create_app().run(host="0.0.0.0", port=port)
