"""Tests for the HTTP calls to the customers service (customers_client.py).

They use StubCustomersService (conftest.py): a real HTTP server that answers
like the customers service, so real requests, timeouts and errors are tested.
"""
import time

import pytest

from customers_client import CustomersClient, CustomersUnavailable, StudentNotFound


def test_get_student_returns_the_student(customers_stub):
    student_id = customers_stub.add("Ana")
    client = CustomersClient(customers_stub.url, timeout=2)
    assert client.get_student(student_id)["name"] == "Ana"


def test_unknown_student_raises_student_not_found(customers_stub):
    with pytest.raises(StudentNotFound):
        CustomersClient(customers_stub.url, timeout=2).get_student(99)


def test_list_students_returns_everyone(customers_stub):
    customers_stub.add("Ana")
    customers_stub.add("Bob")
    names = [s["name"] for s in CustomersClient(customers_stub.url, timeout=2).list_students()]
    assert names == ["Ana", "Bob"]


def test_list_students_asks_for_archived_students_too(customers_stub):
    customers_stub.add("Ana", archived=True)
    students = CustomersClient(customers_stub.url, timeout=2).list_students()
    assert customers_stub.paths == ["/students?include_archived=true"]
    assert students[0]["archived"] is True


def test_the_login_token_is_passed_on(customers_stub):
    CustomersClient(customers_stub.url, timeout=2, token="abc").list_students()
    assert customers_stub.auth_headers == ["Bearer abc"]


def test_a_stopped_service_raises_customers_unavailable(customers_stub):
    customers_stub.stop()
    with pytest.raises(CustomersUnavailable):
        CustomersClient(customers_stub.url, timeout=2).list_students()


def test_a_slow_service_raises_customers_unavailable_after_the_timeout(customers_stub):
    customers_stub.delay = 2
    started = time.perf_counter()
    with pytest.raises(CustomersUnavailable):
        CustomersClient(customers_stub.url, timeout=0.3).list_students()
    assert time.perf_counter() - started < 1.5  # gave up at the timeout, did not wait 2 s


@pytest.mark.parametrize("status", [401, 500, 503])
def test_an_error_answer_raises_customers_unavailable(customers_stub, status):
    customers_stub.status = status
    with pytest.raises(CustomersUnavailable, match=str(status)):
        CustomersClient(customers_stub.url, timeout=2).list_students()


def test_an_answer_that_is_not_json_raises_customers_unavailable(monkeypatch):
    class NotJson:
        status_code = 200

        def json(self):
            raise ValueError("no JSON")

    monkeypatch.setattr("customers_client.requests.get", lambda *a, **k: NotJson())
    with pytest.raises(CustomersUnavailable, match="JSON"):
        CustomersClient("http://customers:8000", timeout=2).list_students()
