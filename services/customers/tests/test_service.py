"""Tests for the customers business logic (service.py), against SQL Server."""
import pytest

import service


def valid_student(**changes):
    """Data for a student that passes every rule. Tests change one field at a time."""
    data = {
        "name": "Ana Hoxha",
        "guardian_name": "Elira Hoxha",
        "guardian_email": "elira@example.com",
        "guardian_phone": "+355 69 123 4567",
    }
    data.update(changes)
    return data


# ---------- validate_student (no database needed) ----------

def test_validate_trims_spaces_and_lowercases_email():
    cleaned = service.validate_student(
        valid_student(name="  Ana  ", guardian_email=" Elira@Example.COM ")
    )
    assert cleaned["name"] == "Ana"
    assert cleaned["guardian_email"] == "elira@example.com"


def test_validate_turns_empty_fields_into_none():
    cleaned = service.validate_student(valid_student(guardian_name="   ", guardian_phone=""))
    assert cleaned["guardian_name"] is None
    assert cleaned["guardian_phone"] is None


def test_validate_accepts_names_of_exactly_100_characters():
    cleaned = service.validate_student(valid_student(name="a" * 100, guardian_name="b" * 100))
    assert len(cleaned["name"]) == 100
    assert len(cleaned["guardian_name"]) == 100


def test_validate_accepts_phone_without_email():
    cleaned = service.validate_student(valid_student(guardian_email=None))
    assert cleaned["guardian_email"] is None


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"name": None}, "name is required"),
        ({"name": "   "}, "name is required"),
        ({"name": "a" * 101}, "Student name can be at most 100"),
        ({"guardian_name": "a" * 101}, "Guardian name can be at most 100"),
        ({"guardian_email": "not-an-email"}, "email address is not valid"),
        ({"guardian_email": "a" * 250 + "@x.com"}, "email address is not valid"),
        ({"guardian_phone": "call me"}, "phone number is not valid"),
        ({"guardian_phone": "123"}, "phone number is not valid"),
        ({"guardian_email": "", "guardian_phone": ""}, "email or phone"),
    ],
)
def test_validate_rejects_invalid_data(changes, message):
    with pytest.raises(service.ValidationError, match=message):
        service.validate_student(valid_student(**changes))


# ---------- create and read ----------

def test_create_student_stores_cleaned_data(conn):
    student_id = service.create_student(conn, valid_student(name=" Ana "))
    student = service.get_student(conn, student_id)
    assert student["name"] == "Ana"
    assert student["guardian_email"] == "elira@example.com"


def test_create_student_keeps_non_english_letters(conn):
    student_id = service.create_student(conn, valid_student(name="Ëngjëll Çela"))
    assert service.get_student(conn, student_id)["name"] == "Ëngjëll Çela"


def test_create_student_with_invalid_data_saves_nothing(conn):
    with pytest.raises(service.ValidationError):
        service.create_student(conn, valid_student(name=""))
    assert service.list_students(conn) == []


def test_get_student_that_does_not_exist(conn):
    with pytest.raises(service.StudentNotFound):
        service.get_student(conn, 999999)


def test_list_students_is_sorted_by_name_ignoring_case(conn):
    for name in ["sara", "Ana", "Dritan"]:
        service.create_student(conn, valid_student(name=name))
    names = [s["name"] for s in service.list_students(conn)]
    assert names == ["Ana", "Dritan", "sara"]


def test_list_students_search_matches_part_of_the_name(conn):
    service.create_student(conn, valid_student(name="Ana Hoxha"))
    service.create_student(conn, valid_student(name="Dritan Kola"))
    names = [s["name"] for s in service.list_students(conn, search="hox")]
    assert names == ["Ana Hoxha"]


def test_list_students_blank_search_returns_everyone(conn):
    service.create_student(conn, valid_student(name="Ana"))
    service.create_student(conn, valid_student(name="Dritan"))
    assert len(service.list_students(conn, search="   ")) == 2


# ---------- update ----------

def test_update_student_changes_the_stored_data(conn):
    student_id = service.create_student(conn, valid_student())
    service.update_student(conn, student_id, valid_student(name="Ana H."))
    assert service.get_student(conn, student_id)["name"] == "Ana H."


def test_update_with_invalid_data_keeps_the_old_data(conn):
    student_id = service.create_student(conn, valid_student(name="Ana"))
    with pytest.raises(service.ValidationError):
        service.update_student(conn, student_id, valid_student(name=""))
    assert service.get_student(conn, student_id)["name"] == "Ana"


def test_update_student_that_does_not_exist(conn):
    with pytest.raises(service.StudentNotFound):
        service.update_student(conn, 999999, valid_student())


# ---------- archive (migration 002) ----------

def test_new_students_are_not_archived(conn):
    student_id = service.create_student(conn, valid_student())
    assert service.get_student(conn, student_id)["archived"] is False


def test_archiving_keeps_the_student_but_hides_them_from_the_list(conn):
    student_id = service.create_student(conn, valid_student(name="Ana"))
    service.create_student(conn, valid_student(name="Dritan"))
    service.archive_student(conn, student_id)
    # Still there, so lessons that point at this student stay valid.
    student = service.get_student(conn, student_id)
    assert student["name"] == "Ana"
    assert student["archived"] is True
    assert [s["name"] for s in service.list_students(conn)] == ["Dritan"]
    assert [s["name"] for s in service.list_students(conn, search="ana")] == []


def test_list_with_archived_students_includes_them(conn):
    student_id = service.create_student(conn, valid_student(name="Ana"))
    service.create_student(conn, valid_student(name="Dritan"))
    service.archive_student(conn, student_id)
    everyone = service.list_students(conn, include_archived=True)
    assert [(s["name"], s["archived"]) for s in everyone] == [("Ana", True), ("Dritan", False)]


def test_archive_student_that_does_not_exist(conn):
    with pytest.raises(service.StudentNotFound):
        service.archive_student(conn, 999999)
