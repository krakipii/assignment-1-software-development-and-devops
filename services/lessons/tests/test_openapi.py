"""Checks that openapi.yaml documents exactly the endpoints the code has.

If a route is added, removed or renamed without updating openapi.yaml, this
test fails, so the document cannot silently drift away from the code.
"""
import re
from pathlib import Path

import yaml
from flask import Flask

import routes

OPENAPI = Path(__file__).resolve().parents[1] / "openapi.yaml"
HTTP_METHODS = {"get", "post", "put", "delete", "patch"}


def _normalise(path):
    """'/students/<int:student_id>' and '/students/{id}' both become '/students/{}'."""
    return re.sub(r"<[^>]+>|\{[^}]+\}", "{}", path)


def documented_endpoints():
    paths = yaml.safe_load(OPENAPI.read_text())["paths"]
    return {
        (_normalise(path), method.upper())
        for path, item in paths.items()
        for method in item
        if method in HTTP_METHODS
    }


def code_endpoints():
    app = Flask("openapi-check")
    app.register_blueprint(routes.bp)
    found = {
        (_normalise(rule.rule), method)
        for rule in app.url_map.iter_rules()
        if rule.endpoint != "static"
        for method in rule.methods - {"HEAD", "OPTIONS"}
    }
    found.add(("/health", "GET"))  # defined in app.py, not in routes.py
    return found


def test_openapi_documents_exactly_the_endpoints_in_the_code():
    assert documented_endpoints() == code_endpoints()


def test_the_stub_answers_with_the_shape_the_customers_service_documents(customers_stub):
    """The stand-in for the customers service must answer like the real one."""
    customers_openapi = Path(__file__).resolve().parents[2] / "customers" / "openapi.yaml"
    schemas = yaml.safe_load(customers_openapi.read_text())["components"]["schemas"]
    documented_fields = set(schemas["Student"]["required"])
    student = customers_stub.students[customers_stub.add()]
    assert set(student) == documented_fields
