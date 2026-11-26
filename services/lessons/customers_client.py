"""The lessons service's only way to student data: HTTP calls to the customers service.

These two calls replace the direct calls to customers/service.py of the
monolith (ADR-2, ADR-6):
    GET /students/{id}   replaces get_student
    GET /students?include_archived=true   replaces list_students

Every call has a timeout. If the customers service does not answer in time,
is down, or answers with an error, the call raises CustomersUnavailable, and
the caller decides what the user sees: scheduling is refused with a clear
message, the lesson list is shown without student names.
"""
import logging

import requests

log = logging.getLogger(__name__)


class CustomersUnavailable(Exception):
    """The customers service could not be reached or did not answer properly."""


class StudentNotFound(Exception):
    """The customers service says this student does not exist."""


class CustomersClient:
    def __init__(self, base_url, timeout, token=None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # The staff member's own login token is passed on, so the customers
        # service sees the same logged-in user as the lessons service.
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}

    def _get(self, path):
        url = self.base_url + path
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
        except requests.RequestException as error:  # refused, timed out, DNS, ...
            log.warning("Customers service unavailable: GET %s failed: %s", path, error)
            raise CustomersUnavailable(str(error)) from error
        if response.status_code == 404:
            raise StudentNotFound(path)
        if response.status_code != 200:
            log.warning("Customers service answered GET %s with %s", path, response.status_code)
            raise CustomersUnavailable(f"customers service answered {response.status_code}")
        try:
            return response.json()
        except ValueError as error:
            raise CustomersUnavailable("customers service did not answer with JSON") from error

    def get_student(self, student_id):
        """One student as a dict. Raises StudentNotFound or CustomersUnavailable."""
        return self._get(f"/students/{int(student_id)}")

    def list_students(self):
        """All students, archived ones included, as a list of dicts.

        Archived students are asked for too, so past lessons of a student who
        was archived still show the name. Raises CustomersUnavailable.
        """
        return self._get("/students?include_archived=true")
