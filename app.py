"""Entry point of the tutoring app. Start it with:  python app.py

Configuration (all optional, set as environment variables):
    PORT        port to listen on (default 8000)
    DATA_DIR    folder that holds tutoring.db (default: ./data next to this file)
    SECRET_KEY  key that signs session cookies (default: random on every start)
"""
import os
import secrets
 
from flask import Flask, jsonify, redirect, url_for
 
import database
from customers.routes import bp as customers_bp
 
 
def create_app(db_path=None):
    """Build and configure the Flask app. Tests pass their own db_path."""
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path or database.get_db_path()
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
 
    database.init_app(app)
    app.register_blueprint(customers_bp)
 
    @app.get("/")
    def index():
        return redirect(url_for("customers.list_students"))
 
    @app.get("/health")
    def health():
        return jsonify(status="ok")
 
    return app
 
 
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    # 0.0.0.0 so the app is reachable from outside a container later.
    # No debug=True: the reloader would start a second process.
    create_app().run(host="0.0.0.0", port=port)