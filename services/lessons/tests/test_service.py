"""Tests for the lessons business logic (service.py), against SQL Server.

Student data comes from FakeStudents (conftest.py), which stands in for the
customers service, so these tests need no HTTP.
"""
import pytest

import service
from customers_client import CustomersUnavailable


def valid_tutor(**changes):
    """Valid tutor data that passes all rules; each test changes one field at a time."""
    data = {
        "name": "Mira Kola",
        "email": "mira@example.com",
        "subjects": "Maths, Physics",
        "hourly_rate": "25",
    }
    data.update(changes)
    return data


def make_tutor(conn, **changes):
    return service.create_tutor(conn, valid_tutor(**changes))


def lesson_data(tutor_id, student_id, **changes):
    """Data for a valid 60-minute Maths lesson on 5 October 2030 at 16:00."""
    data = {
        "tutor_id": tutor_id,
        "student_id": student_id,
        "subject": "Maths",
        "start_time": "2030-10-05T16:00",
        "duration_minutes": "60",
    }
    data.update(changes)
    return data


def listed(conn, students, **filters):
    return service.list_lessons(conn, students, **filters)["lessons"]


# ---------- tutors ----------

def test_validate_tutor_cleans_the_input():
    cleaned = service.validate_tutor(valid_tutor(
        name="  Mira ", email=" Mira@Example.COM ",
        subjects=" Maths ,Physics,, ", hourly_rate=" 25.5 ",
    ))
    assert cleaned == {
        "name": "Mira",
        "email": "mira@example.com",
        "subjects": "Maths, Physics",
        "hourly_rate": 25.5,
    }


def test_validate_tutor_without_subjects_or_email():
    cleaned = service.validate_tutor(valid_tutor(subjects="  ", email=""))
    assert cleaned["subjects"] is None
    assert cleaned["email"] is None


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"name": None}, "name is required"),
        ({"name": "a" * 101}, "at most 100"),
        ({"email": "not-an-email"}, "email address is not valid"),
        ({"email": "a" * 250 + "@x.com"}, "email address is not valid"),
        ({"subjects": "Maths, " * 100}, "Subjects can be at most 500"),
        ({"hourly_rate": None}, "must be a number"),
        ({"hourly_rate": "abc"}, "must be a number"),
        ({"hourly_rate": "-1"}, "between 0 and 1000"),
        ({"hourly_rate": "1001"}, "between 0 and 1000"),
    ],
)
def test_validate_tutor_rejects_invalid_data(changes, message):
    with pytest.raises(service.ValidationError, match=message):
        service.validate_tutor(valid_tutor(**changes))


def test_create_and_get_tutor(conn):
    tutor_id = make_tutor(conn, hourly_rate="25.5")
    tutor = service.get_tutor(conn, tutor_id)
    assert tutor["name"] == "Mira Kola"
    assert tutor["hourly_rate"] == 25.5
    assert isinstance(tutor["hourly_rate"], float)


def test_get_tutor_that_does_not_exist(conn):
    with pytest.raises(service.TutorNotFound):
        service.get_tutor(conn, 999999)


def test_list_tutors_is_sorted_by_name(conn):
    make_tutor(conn, name="Mira")
    make_tutor(conn, name="arben")
    make_tutor(conn, name="Leon")
    assert [t["name"] for t in service.list_tutors(conn)] == ["arben", "Leon", "Mira"]


def test_update_tutor(conn):
    tutor_id = make_tutor(conn)
    service.update_tutor(conn, tutor_id, valid_tutor(hourly_rate="30"))
    assert service.get_tutor(conn, tutor_id)["hourly_rate"] == 30


def test_update_tutor_that_does_not_exist(conn):
    with pytest.raises(service.TutorNotFound):
        service.update_tutor(conn, 999999, valid_tutor())


# ---------- scheduling: validation ----------

def test_schedule_lesson_stores_clean_data(conn, students):
    tutor_id = make_tutor(conn)
    student_id = students.add()
    lesson_id = service.schedule_lesson(
        conn, students,
        lesson_data(tutor_id, student_id, subject=" maths ", start_time="2030-10-05 16:00:45"),
    )
    lesson = service.get_lesson(conn, lesson_id)
    assert lesson["subject"] == "Maths"
    assert lesson["start_time"] == "2030-10-05T16:00"
    assert lesson["duration_minutes"] == 60
    assert lesson["status"] == "scheduled"
    assert lesson["student_id"] == student_id


def test_tutor_without_subjects_can_teach_any_subject(conn, students):
    tutor_id = make_tutor(conn, subjects="")
    lesson_id = service.schedule_lesson(
        conn, students, lesson_data(tutor_id, students.add(), subject="Chess"))
    assert service.get_lesson(conn, lesson_id)["subject"] == "Chess"


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"tutor_id": ""}, "Choose a tutor"),
        ({"student_id": "abc"}, "Choose a student"),
        ({"tutor_id": 999999}, "existing tutor"),
        ({"student_id": 999}, "existing student"),
        ({"subject": "  "}, "Subject is required"),
        ({"subject": "Chemistry"}, "teaches Maths, Physics, not Chemistry"),
        ({"start_time": "next Monday"}, "Start time must look like"),
        ({"start_time": None}, "Start time must look like"),
        ({"duration_minutes": "10"}, "between 15 and 240"),
        ({"duration_minutes": "241"}, "between 15 and 240"),
        ({"duration_minutes": "1.5"}, "whole number of minutes"),
    ],
)
def test_schedule_lesson_rejects_invalid_data(conn, students, changes, message):
    data = lesson_data(make_tutor(conn), students.add())
    data.update(changes)
    with pytest.raises(service.ValidationError, match=message):
        service.schedule_lesson(conn, students, data)
    assert listed(conn, students) == []


def test_long_subject_for_a_tutor_without_subjects_is_rejected(conn, students):
    data = lesson_data(make_tutor(conn, subjects=""), students.add(), subject="x" * 101)
    with pytest.raises(service.ValidationError, match="Subject can be at most 100"):
        service.schedule_lesson(conn, students, data)


def test_invalid_input_is_reported_without_calling_the_customers_service(conn, students):
    data = lesson_data(make_tutor(conn), students.add(), duration_minutes="5")
    with pytest.raises(service.ValidationError):
        service.schedule_lesson(conn, students, data)
    assert students.calls == []


def test_scheduling_fails_when_the_customers_service_is_down(conn, students):
    data = lesson_data(make_tutor(conn), students.add())
    students.down = True
    with pytest.raises(CustomersUnavailable):
        service.schedule_lesson(conn, students, data)
    assert listed(conn, students) == []


# ---------- scheduling: double bookings ----------

def test_tutor_cannot_be_double_booked(conn, students):
    tutor_id = make_tutor(conn)
    ana, bob = students.add("Ana"), students.add("Bob")
    service.schedule_lesson(conn, students, lesson_data(tutor_id, ana))
    with pytest.raises(service.ScheduleConflict, match="tutor already has a lesson"):
        service.schedule_lesson(
            conn, students, lesson_data(tutor_id, bob, start_time="2030-10-05T16:30"))
    assert len(listed(conn, students)) == 1


def test_student_cannot_be_double_booked(conn, students):
    mira, leon = make_tutor(conn, name="Mira"), make_tutor(conn, name="Leon")
    student_id = students.add()
    service.schedule_lesson(conn, students, lesson_data(mira, student_id))
    with pytest.raises(service.ScheduleConflict, match="student already has a lesson"):
        service.schedule_lesson(
            conn, students, lesson_data(leon, student_id, start_time="2030-10-05T15:30"))


def test_back_to_back_lessons_are_allowed(conn, students):
    tutor_id, student_id = make_tutor(conn), students.add()
    for start in ["2030-10-05T16:00", "2030-10-05T17:00", "2030-10-05T15:00"]:
        service.schedule_lesson(conn, students, lesson_data(tutor_id, student_id, start_time=start))
    assert len(listed(conn, students)) == 3


def test_cancelled_lesson_frees_its_time_slot(conn, students):
    tutor_id, student_id = make_tutor(conn), students.add()
    first = service.schedule_lesson(conn, students, lesson_data(tutor_id, student_id))
    service.change_status(conn, first, "cancelled")
    second = service.schedule_lesson(conn, students, lesson_data(tutor_id, student_id))
    assert service.get_lesson(conn, second)["status"] == "scheduled"


def test_completed_lesson_still_blocks_its_time_slot(conn, students):
    tutor_id, student_id = make_tutor(conn), students.add()
    first = service.schedule_lesson(conn, students, lesson_data(tutor_id, student_id))
    service.change_status(conn, first, "completed")
    with pytest.raises(service.ScheduleConflict):
        service.schedule_lesson(
            conn, students, lesson_data(tutor_id, student_id, start_time="2030-10-05T16:45"))


# ---------- status changes ----------

@pytest.mark.parametrize("new_status", ["completed", "cancelled"])
def test_scheduled_lesson_can_be_completed_or_cancelled(conn, students, new_status):
    lesson_id = service.schedule_lesson(
        conn, students, lesson_data(make_tutor(conn), students.add()))
    service.change_status(conn, lesson_id, new_status)
    assert service.get_lesson(conn, lesson_id)["status"] == new_status


@pytest.mark.parametrize(
    "first, then",
    [("completed", "cancelled"), ("cancelled", "completed"), ("cancelled", "scheduled")],
)
def test_completed_and_cancelled_lessons_are_final(conn, students, first, then):
    lesson_id = service.schedule_lesson(
        conn, students, lesson_data(make_tutor(conn), students.add()))
    service.change_status(conn, lesson_id, first)
    with pytest.raises(service.InvalidStatusChange):
        service.change_status(conn, lesson_id, then)
    assert service.get_lesson(conn, lesson_id)["status"] == first


def test_unknown_status_is_rejected(conn, students):
    lesson_id = service.schedule_lesson(
        conn, students, lesson_data(make_tutor(conn), students.add()))
    with pytest.raises(service.InvalidStatusChange):
        service.change_status(conn, lesson_id, "postponed")


def test_change_status_of_lesson_that_does_not_exist(conn):
    with pytest.raises(service.LessonNotFound):
        service.change_status(conn, 999999, "completed")


# ---------- listing ----------

def test_list_lessons_is_sorted_by_time_and_includes_names(conn, students):
    tutor_id, student_id = make_tutor(conn), students.add("Ana")
    for start in ["2030-10-06T10:00", "2030-10-05T10:00"]:
        service.schedule_lesson(conn, students, lesson_data(tutor_id, student_id, start_time=start))
    result = service.list_lessons(conn, students)
    assert result["students_available"] is True
    lessons = result["lessons"]
    assert [lesson["start_time"] for lesson in lessons] == ["2030-10-05T10:00", "2030-10-06T10:00"]
    assert lessons[0]["tutor_name"] == "Mira Kola"
    assert lessons[0]["student_name"] == "Ana"


def test_list_lessons_asks_the_customers_service_once_for_all_names(conn, students):
    tutor_id, student_id = make_tutor(conn), students.add("Ana")
    for start in ["2030-10-05T10:00", "2030-10-05T12:00", "2030-10-05T14:00"]:
        service.schedule_lesson(conn, students, lesson_data(tutor_id, student_id, start_time=start))
    students.calls.clear()
    listed(conn, students)
    assert students.calls == [("list_students",)]


def test_list_lessons_shows_the_current_student_name(conn, students):
    """Names come from the customers service, so a changed name appears immediately."""
    student_id = students.add("Ana")
    service.schedule_lesson(conn, students, lesson_data(make_tutor(conn), student_id))
    students.students[student_id]["name"] = "Ana H."
    assert listed(conn, students)[0]["student_name"] == "Ana H."


def test_list_lessons_of_a_deleted_student_has_no_name(conn, students):
    student_id = students.add("Ana")
    service.schedule_lesson(conn, students, lesson_data(make_tutor(conn), student_id))
    del students.students[student_id]
    result = service.list_lessons(conn, students)
    assert result["students_available"] is True
    assert result["lessons"][0]["student_name"] is None


def test_list_lessons_still_works_when_the_customers_service_is_down(conn, students):
    service.schedule_lesson(conn, students, lesson_data(make_tutor(conn), students.add()))
    students.down = True
    result = service.list_lessons(conn, students)
    assert result["students_available"] is False
    assert len(result["lessons"]) == 1
    assert result["lessons"][0]["student_name"] is None
    assert result["lessons"][0]["tutor_name"] == "Mira Kola"


def test_empty_list_does_not_call_the_customers_service(conn, students):
    assert service.list_lessons(conn, students) == {"lessons": [], "students_available": True}
    assert students.calls == []


def test_list_lessons_filters_by_status_and_tutor(conn, students):
    mira, leon = make_tutor(conn, name="Mira"), make_tutor(conn, name="Leon")
    student_id = students.add()
    a = service.schedule_lesson(
        conn, students, lesson_data(mira, student_id, start_time="2030-10-05T10:00"))
    b = service.schedule_lesson(
        conn, students, lesson_data(mira, student_id, start_time="2030-10-05T12:00"))
    c = service.schedule_lesson(
        conn, students, lesson_data(leon, student_id, start_time="2030-10-05T14:00"))
    service.change_status(conn, b, "completed")

    def ids(**filters):
        return [lesson["id"] for lesson in listed(conn, students, **filters)]

    assert ids(status="scheduled") == [a, c]
    assert ids(tutor_id=mira) == [a, b]
    assert ids(status="scheduled", tutor_id=mira) == [a]


def test_list_lessons_with_unknown_status(conn, students):
    with pytest.raises(service.ValidationError):
        service.list_lessons(conn, students, status="postponed")


def test_get_lesson_that_does_not_exist(conn):
    with pytest.raises(service.LessonNotFound):
        service.get_lesson(conn, 999999)
