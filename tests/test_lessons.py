"""Tests for the business logic of the lessons domain (lessons/service.py)."""
import pytest

from customers import service as customers
from lessons import service as lessons


def make_student(conn, name="Ana Hoxha"):
    """Create a student through the customers domain and return the id."""
    return customers.create_student(conn, {"name": name, "guardian_phone": "069 123 4567"})


def valid_tutor(**changes):
    """Valid tutor data that passes all rules and each test changes one field at a time."""
    data = {
        "name": "Mira Kola",
        "email": "mira@example.com",
        "subjects": "Maths, Physics",
        "hourly_rate": "25",
    }
    data.update(changes)
    return data


def make_tutor(conn, **changes):
    return lessons.create_tutor(conn, valid_tutor(**changes))


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


# ---------- tutors ----------

def test_validate_tutor_cleans_the_input():
    cleaned = lessons.validate_tutor(valid_tutor(
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
    cleaned = lessons.validate_tutor(valid_tutor(subjects="  ", email=""))
    assert cleaned["subjects"] is None
    assert cleaned["email"] is None


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"name": None}, "name is required"),
        ({"name": "a" * 101}, "at most 100"),
        ({"email": "not-an-email"}, "email address is not valid"),
        ({"hourly_rate": None}, "must be a number"),
        ({"hourly_rate": "abc"}, "must be a number"),
        ({"hourly_rate": "-1"}, "between 0 and 1000"),
        ({"hourly_rate": "1001"}, "between 0 and 1000"),
    ],
)
def test_validate_tutor_rejects_invalid_data(changes, message):
    with pytest.raises(lessons.ValidationError, match=message):
        lessons.validate_tutor(valid_tutor(**changes))


def test_create_and_get_tutor(conn):
    tutor_id = make_tutor(conn)
    tutor = lessons.get_tutor(conn, tutor_id)
    assert tutor["name"] == "Mira Kola"
    assert tutor["hourly_rate"] == 25


def test_get_tutor_that_does_not_exist(conn):
    with pytest.raises(lessons.TutorNotFound):
        lessons.get_tutor(conn, 999)


def test_list_tutors_is_sorted_by_name(conn):
    make_tutor(conn, name="Mira")
    make_tutor(conn, name="arben")
    make_tutor(conn, name="Leon")
    assert [t["name"] for t in lessons.list_tutors(conn)] == ["arben", "Leon", "Mira"]


def test_update_tutor(conn):
    tutor_id = make_tutor(conn)
    lessons.update_tutor(conn, tutor_id, valid_tutor(hourly_rate="30"))
    assert lessons.get_tutor(conn, tutor_id)["hourly_rate"] == 30


def test_update_tutor_that_does_not_exist(conn):
    with pytest.raises(lessons.TutorNotFound):
        lessons.update_tutor(conn, 999, valid_tutor())


# Scheduling : Validation

def test_schedule_lesson_stores_clean_data(conn):
    tutor_id = make_tutor(conn)
    student_id = make_student(conn)
    lesson_id = lessons.schedule_lesson(
        conn, lesson_data(tutor_id, student_id, subject=" maths ", start_time="2030-10-05 16:00:45")
    )
    lesson = lessons.get_lesson(conn, lesson_id)
    assert lesson["subject"] == "Maths"  
    assert lesson["start_time"] == "2030-10-05T16:00"  
    assert lesson["duration_minutes"] == 60
    assert lesson["status"] == "scheduled"


def test_tutor_without_subjects_can_teach_any_subject(conn):
    tutor_id = make_tutor(conn, subjects="")
    student_id = make_student(conn)
    lesson_id = lessons.schedule_lesson(conn, lesson_data(tutor_id, student_id, subject="Chess"))
    assert lessons.get_lesson(conn, lesson_id)["subject"] == "Chess"


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"tutor_id": ""}, "Choose a tutor"),
        ({"student_id": "abc"}, "Choose a student"),
        ({"tutor_id": 999}, "existing tutor"),
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
def test_schedule_lesson_rejects_invalid_data(conn, changes, message):
    data = lesson_data(make_tutor(conn), make_student(conn))
    data.update(changes)  
    with pytest.raises(lessons.ValidationError, match=message):
        lessons.schedule_lesson(conn, data)
    assert lessons.list_lessons(conn) == []


# Scheduling : Double Bookings

def test_tutor_cannot_be_double_booked(conn):
    tutor_id = make_tutor(conn)
    ana = make_student(conn, "Ana")
    bob = make_student(conn, "Bob")
    lessons.schedule_lesson(conn, lesson_data(tutor_id, ana))
    with pytest.raises(lessons.ScheduleConflict, match="tutor already has a lesson"):
        lessons.schedule_lesson(conn, lesson_data(tutor_id, bob, start_time="2030-10-05T16:30"))
    assert len(lessons.list_lessons(conn)) == 1


def test_student_cannot_be_double_booked(conn):
    mira = make_tutor(conn, name="Mira")
    leon = make_tutor(conn, name="Leon")
    student_id = make_student(conn)
    lessons.schedule_lesson(conn, lesson_data(mira, student_id))
    with pytest.raises(lessons.ScheduleConflict, match="student already has a lesson"):
        lessons.schedule_lesson(conn, lesson_data(leon, student_id, start_time="2030-10-05T15:30"))


def test_back_to_back_lessons_are_allowed(conn):
    tutor_id = make_tutor(conn)
    student_id = make_student(conn)
    lessons.schedule_lesson(conn, lesson_data(tutor_id, student_id)) 
    lessons.schedule_lesson(conn, lesson_data(tutor_id, student_id, start_time="2030-10-05T17:00"))
    lessons.schedule_lesson(conn, lesson_data(tutor_id, student_id, start_time="2030-10-05T15:00"))
    assert len(lessons.list_lessons(conn)) == 3


def test_cancelled_lesson_frees_its_time_slot(conn):
    tutor_id = make_tutor(conn)
    student_id = make_student(conn)
    first = lessons.schedule_lesson(conn, lesson_data(tutor_id, student_id))
    lessons.change_status(conn, first, "cancelled")
    second = lessons.schedule_lesson(conn, lesson_data(tutor_id, student_id))
    assert lessons.get_lesson(conn, second)["status"] == "scheduled"


def test_completed_lesson_still_blocks_its_time_slot(conn):
    tutor_id = make_tutor(conn)
    student_id = make_student(conn)
    first = lessons.schedule_lesson(conn, lesson_data(tutor_id, student_id))
    lessons.change_status(conn, first, "completed")
    with pytest.raises(lessons.ScheduleConflict):
        lessons.schedule_lesson(conn, lesson_data(tutor_id, student_id, start_time="2030-10-05T16:45"))


# Status Changes

@pytest.mark.parametrize("new_status", ["completed", "cancelled"])
def test_scheduled_lesson_can_be_completed_or_cancelled(conn, new_status):
    lesson_id = lessons.schedule_lesson(conn, lesson_data(make_tutor(conn), make_student(conn)))
    lessons.change_status(conn, lesson_id, new_status)
    assert lessons.get_lesson(conn, lesson_id)["status"] == new_status


@pytest.mark.parametrize(
    "first, then",
    [
        ("completed", "cancelled"),
        ("cancelled", "completed"),
        ("cancelled", "scheduled"),
    ],
)
def test_completed_and_cancelled_lessons_are_final(conn, first, then):
    lesson_id = lessons.schedule_lesson(conn, lesson_data(make_tutor(conn), make_student(conn)))
    lessons.change_status(conn, lesson_id, first)
    with pytest.raises(lessons.InvalidStatusChange):
        lessons.change_status(conn, lesson_id, then)
    assert lessons.get_lesson(conn, lesson_id)["status"] == first


def test_unknown_status_is_rejected(conn):
    lesson_id = lessons.schedule_lesson(conn, lesson_data(make_tutor(conn), make_student(conn)))
    with pytest.raises(lessons.InvalidStatusChange):
        lessons.change_status(conn, lesson_id, "postponed")


def test_change_status_of_lesson_that_does_not_exist(conn):
    with pytest.raises(lessons.LessonNotFound):
        lessons.change_status(conn, 999, "completed")


# Listing

def test_list_lessons_is_sorted_by_time_and_includes_names(conn):
    tutor_id = make_tutor(conn)
    student_id = make_student(conn, "Ana")
    lessons.schedule_lesson(conn, lesson_data(tutor_id, student_id, start_time="2030-10-06T10:00"))
    lessons.schedule_lesson(conn, lesson_data(tutor_id, student_id, start_time="2030-10-05T10:00"))
    listed = lessons.list_lessons(conn)
    assert [l["start_time"] for l in listed] == ["2030-10-05T10:00", "2030-10-06T10:00"]
    assert listed[0]["tutor_name"] == "Mira Kola"
    assert listed[0]["student_name"] == "Ana"


def test_list_lessons_shows_the_current_student_name(conn):
    """Student names come from the customers domain, so a changes to a name appear immediately."""
    tutor_id = make_tutor(conn)
    student_id = make_student(conn, "Ana")
    lessons.schedule_lesson(conn, lesson_data(tutor_id, student_id))
    customers.update_student(conn, student_id, {"name": "Ana H.", "guardian_phone": "0691234567"})
    assert lessons.list_lessons(conn)[0]["student_name"] == "Ana H."


def test_list_lessons_filters_by_status_and_tutor(conn):
    mira = make_tutor(conn, name="Mira")
    leon = make_tutor(conn, name="Leon")
    student_id = make_student(conn)
    a = lessons.schedule_lesson(conn, lesson_data(mira, student_id, start_time="2030-10-05T10:00"))
    b = lessons.schedule_lesson(conn, lesson_data(mira, student_id, start_time="2030-10-05T12:00"))
    c = lessons.schedule_lesson(conn, lesson_data(leon, student_id, start_time="2030-10-05T14:00"))
    lessons.change_status(conn, b, "completed")

    def ids(**filters):
        return [l["id"] for l in lessons.list_lessons(conn, **filters)]

    assert ids(status="scheduled") == [a, c]
    assert ids(tutor_id=mira) == [a, b]
    assert ids(status="scheduled", tutor_id=mira) == [a]


def test_list_lessons_with_unknown_status(conn):
    with pytest.raises(lessons.ValidationError):
        lessons.list_lessons(conn, status="postponed")


def test_get_lesson_that_does_not_exist(conn):
    with pytest.raises(lessons.LessonNotFound):
        lessons.get_lesson(conn, 999)


def test_student_choices_gives_ids_and_names_from_customers(conn):
    ana = make_student(conn, "Ana")
    bob = make_student(conn, "Bob")
    assert lessons.student_choices(conn) == [
        {"id": ana, "name": "Ana"},
        {"id": bob, "name": "Bob"},
    ]