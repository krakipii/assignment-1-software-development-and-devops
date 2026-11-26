"""Lesson Management: tutors, lessons and each lesson's status.

This is the business logic of the lessons service. Student data is not in this
service's database: the functions that need it receive `students`, a client
for the customers service (customers_client.CustomersClient, or a stand-in in
the tests), and never read a students table (ADR-2, ADR-6).

Every function takes an open database connection, so the logic can be tested
without running Flask.
"""
import re
from datetime import datetime, timedelta

from customers_client import CustomersUnavailable, StudentNotFound

MAX_NAME_LENGTH = 100
MAX_EMAIL_LENGTH = 254
MAX_SUBJECTS_LENGTH = 500
MAX_HOURLY_RATE = 1000
MIN_DURATION = 15
MAX_DURATION = 240
STATUSES = ("scheduled", "completed", "cancelled")
# The statuses a lesson can change to from its current status.
# Completed and cancelled lessons cannot be changed again.
ALLOWED_STATUS_CHANGES = {"scheduled": ("completed", "cancelled")}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TUTOR_COLUMNS = "id, name, email, subjects, hourly_rate"
# start_time is stored as DATETIME2 and read back as text like '2030-10-05T16:00'
# (style 126 is ISO 8601; 16 characters stop at the minutes).
START_TIME_TEXT = "CONVERT(VARCHAR(16), {column}, 126) AS start_time"
LESSON_COLUMNS = (
    "id, tutor_id, student_id, subject, "
    + START_TIME_TEXT.format(column="start_time")
    + ", duration_minutes, status"
)


class LessonError(Exception):
    """Base class for every error raised by the lessons domain."""


class ValidationError(LessonError):
    """The submitted tutor or lesson data breaks a business rule."""


class TutorNotFound(LessonError):
    """No tutor exists with the requested id."""


class LessonNotFound(LessonError):
    """No lesson exists with the requested id."""


class ScheduleConflict(LessonError):
    """The tutor or the student already has a lesson at that time."""


class InvalidStatusChange(LessonError):
    """The lesson cannot move from its current status to the requested one."""


def _clean(value):
    """Remove extra spaces and use None for empty values.

    customers/service.py has its own copy: the two services share no code.
    """
    if value is None:
        return None
    value = str(value).strip()
    return value if value else None


def _subject_list(subjects):
    """Turn 'Maths, Physics' into ['Maths', 'Physics'] (None gives [])."""
    if not subjects:
        return []
    return [part.strip() for part in subjects.split(",") if part.strip()]


# ---------- tutors ----------

def validate_tutor(data):
    """Check the tutor information and return it in a clean format."""
    name = _clean(data.get("name"))
    email = _clean(data.get("email"))
    subjects = ", ".join(_subject_list(_clean(data.get("subjects")))) or None

    if name is None:
        raise ValidationError("Tutor name is required.")
    if len(name) > MAX_NAME_LENGTH:
        raise ValidationError(f"Tutor name can be at most {MAX_NAME_LENGTH} characters.")

    if email is not None:
        email = email.lower()
        if len(email) > MAX_EMAIL_LENGTH or not EMAIL_PATTERN.match(email):
            raise ValidationError("Tutor email address is not valid.")

    # SQL Server columns have a maximum length (SQLite's TEXT had none).
    if subjects is not None and len(subjects) > MAX_SUBJECTS_LENGTH:
        raise ValidationError(f"Subjects can be at most {MAX_SUBJECTS_LENGTH} characters.")

    try:
        hourly_rate = float(data.get("hourly_rate"))
    except (TypeError, ValueError):
        raise ValidationError("Hourly rate must be a number.") from None
    if not 0 <= hourly_rate <= MAX_HOURLY_RATE:
        raise ValidationError(f"Hourly rate must be between 0 and {MAX_HOURLY_RATE}.")

    return {
        "name": name,
        "email": email,
        "subjects": subjects,
        "hourly_rate": round(hourly_rate, 2),
    }


def _tutor_row(row):
    """hourly_rate is DECIMAL in SQL Server; give it back as a plain number."""
    row["hourly_rate"] = float(row["hourly_rate"])
    return row


def create_tutor(conn, data):
    """Validate and store a new tutor. Returns the new tutor's id."""
    tutor = validate_tutor(data)
    cursor = conn.cursor(as_dict=True)
    cursor.execute(
        "INSERT INTO tutors (name, email, subjects, hourly_rate) OUTPUT INSERTED.id "
        "VALUES (%(name)s, %(email)s, %(subjects)s, %(hourly_rate)s)",
        tutor,
    )
    tutor_id = cursor.fetchone()["id"]
    conn.commit()
    return tutor_id


def get_tutor(conn, tutor_id):
    """Return one tutor as a dict, or raise TutorNotFound."""
    cursor = conn.cursor(as_dict=True)
    cursor.execute(f"SELECT {TUTOR_COLUMNS} FROM tutors WHERE id = %s", (tutor_id,))
    row = cursor.fetchone()
    if row is None:
        raise TutorNotFound(f"Tutor {tutor_id} does not exist.")
    return _tutor_row(row)


def list_tutors(conn):
    """Return all tutors sorted by name (the database ignores upper and lower case)."""
    cursor = conn.cursor(as_dict=True)
    cursor.execute(f"SELECT {TUTOR_COLUMNS} FROM tutors ORDER BY name, id")
    return [_tutor_row(row) for row in cursor.fetchall()]


def update_tutor(conn, tutor_id, data):
    """Validate and overwrite an existing tutor's details."""
    tutor = validate_tutor(data)
    tutor["id"] = tutor_id
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE tutors SET name = %(name)s, email = %(email)s, subjects = %(subjects)s, "
        "hourly_rate = %(hourly_rate)s WHERE id = %(id)s",
        tutor,
    )
    updated = cursor.rowcount
    conn.commit()
    if updated == 0:
        raise TutorNotFound(f"Tutor {tutor_id} does not exist.")


# ---------- lessons ----------

def _parse_int(value, message):
    """Convert form input to an int, or raise ValidationError with message."""
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError(message) from None


def _parse_start(value):
    """Convert '2026-10-05T16:00' (what an HTML date-time field sends) to a datetime."""
    try:
        return datetime.fromisoformat(_clean(value))
    except (TypeError, ValueError):
        raise ValidationError("Start time must look like 2026-10-05T16:00.") from None


def validate_lesson(conn, students, data):
    """Check a new lesson against the business rules and return a clean dict.

    The student is checked last, because it is the only check that needs a call
    to the customers service: invalid input is reported without that call, and
    still reported when the customers service is down.
    """
    tutor_id = _parse_int(data.get("tutor_id"), "Choose a tutor.")
    student_id = _parse_int(data.get("student_id"), "Choose a student.")
    duration = _parse_int(
        data.get("duration_minutes"), "Duration must be a whole number of minutes."
    )
    subject = _clean(data.get("subject"))
    start = _parse_start(data.get("start_time"))

    try:
        tutor = get_tutor(conn, tutor_id)
    except TutorNotFound:
        raise ValidationError("Choose an existing tutor.") from None

    if subject is None:
        raise ValidationError("Subject is required.")
    # Business rule: a tutor can only teach the subjects they have listed.
    tutor_subjects = _subject_list(tutor["subjects"])
    if tutor_subjects:
        matching = [s for s in tutor_subjects if s.lower() == subject.lower()]
        if not matching:
            raise ValidationError(f"{tutor['name']} teaches {tutor['subjects']}, not {subject}.")
        subject = matching[0]
    if len(subject) > MAX_NAME_LENGTH:
        raise ValidationError(f"Subject can be at most {MAX_NAME_LENGTH} characters.")

    if not MIN_DURATION <= duration <= MAX_DURATION:
        raise ValidationError(
            f"A lesson must last between {MIN_DURATION} and {MAX_DURATION} minutes."
        )

    # Across the seam: the student must exist in the customers service.
    # CustomersUnavailable is not caught here: the route turns it into a 503.
    try:
        student = students.get_student(student_id)
    except StudentNotFound:
        raise ValidationError("Choose an existing student.") from None
    # Archived students keep their past lessons but get no new ones (migration 002).
    if student.get("archived"):
        raise ValidationError(f"{student['name']} is archived and cannot get new lessons.")

    return {
        "tutor_id": tutor_id,
        "student_id": student_id,
        "subject": subject,
        # SQL Server only accepts the ISO format with seconds: 2030-10-05T16:00:00
        "start_time": start.replace(second=0, microsecond=0).isoformat(timespec="seconds"),
        "duration_minutes": duration,
    }


def _find_conflict(conn, tutor_id, student_id, start, end):
    """Find a lesson that overlaps with the tutor or student's time, or return None.

    Cancelled lessons are ignored because their time slot is available again.
    """
    cursor = conn.cursor(as_dict=True)
    cursor.execute(
        "SELECT tutor_id, " + START_TIME_TEXT.format(column="start_time")
        + ", duration_minutes FROM lessons "
        "WHERE status <> 'cancelled' AND (tutor_id = %s OR student_id = %s)",
        (tutor_id, student_id),
    )
    for row in cursor.fetchall():
        other_start = datetime.fromisoformat(row["start_time"])
        other_end = other_start + timedelta(minutes=row["duration_minutes"])
        # Two time ranges overlap when each one starts before the other ends.
        if start < other_end and other_start < end:
            who = "tutor" if row["tutor_id"] == tutor_id else "student"
            return (
                f"The {who} already has a lesson on {other_start:%d %b %Y} "
                f"from {other_start:%H:%M} to {other_end:%H:%M}."
            )
    return None


def schedule_lesson(conn, students, data):
    """Validate a new lesson, check for double bookings and store it. Returns its id."""
    lesson = validate_lesson(conn, students, data)
    start = datetime.fromisoformat(lesson["start_time"])
    end = start + timedelta(minutes=lesson["duration_minutes"])

    conflict = _find_conflict(conn, lesson["tutor_id"], lesson["student_id"], start, end)
    if conflict is not None:
        raise ScheduleConflict(conflict)

    cursor = conn.cursor(as_dict=True)
    cursor.execute(
        "INSERT INTO lessons (tutor_id, student_id, subject, start_time, duration_minutes) "
        "OUTPUT INSERTED.id VALUES "
        "(%(tutor_id)s, %(student_id)s, %(subject)s, %(start_time)s, %(duration_minutes)s)",
        lesson,
    )
    lesson_id = cursor.fetchone()["id"]
    conn.commit()
    return lesson_id


def get_lesson(conn, lesson_id):
    """Return one lesson as a dict, or raise LessonNotFound."""
    cursor = conn.cursor(as_dict=True)
    cursor.execute(f"SELECT {LESSON_COLUMNS} FROM lessons WHERE id = %s", (lesson_id,))
    row = cursor.fetchone()
    if row is None:
        raise LessonNotFound(f"Lesson {lesson_id} does not exist.")
    return row


def list_lessons(conn, students, status=None, tutor_id=None):
    """Return lessons ordered by start time, with tutor and student names.

    Can be filtered by status and/or tutor. Returns a dict:
        lessons             the lessons, each with tutor_name and student_name
        students_available  False if the customers service could not be reached;
                            the lessons are still returned, with student_name None
    A student_name of None while students_available is True means the student
    no longer exists in the customers service.
    """
    if status is not None and status not in STATUSES:
        raise ValidationError(f"Unknown lesson status: {status}.")

    # Joining tutors is fine: tutors belong to this service.
    query = (
        "SELECT lessons.id, lessons.tutor_id, tutors.name AS tutor_name, "
        "lessons.student_id, lessons.subject, "
        + START_TIME_TEXT.format(column="lessons.start_time")
        + ", lessons.duration_minutes, lessons.status "
        "FROM lessons JOIN tutors ON tutors.id = lessons.tutor_id"
    )
    conditions, params = [], []
    if status is not None:
        conditions.append("lessons.status = %s")
        params.append(status)
    if tutor_id is not None:
        conditions.append("lessons.tutor_id = %s")
        params.append(tutor_id)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY lessons.start_time, lessons.id"

    cursor = conn.cursor(as_dict=True)
    cursor.execute(query, tuple(params))
    lessons = cursor.fetchall()

    # Across the seam: one call for all the names, instead of one per lesson.
    students_available = True
    names = {}
    if lessons:
        try:
            names = {s["id"]: s["name"] for s in students.list_students()}
        except CustomersUnavailable:
            students_available = False
    for lesson in lessons:
        lesson["student_name"] = names.get(lesson["student_id"])
    return {"lessons": lessons, "students_available": students_available}


def change_status(conn, lesson_id, new_status):
    """Mark a scheduled lesson as completed or cancelled."""
    lesson = get_lesson(conn, lesson_id)
    allowed = ALLOWED_STATUS_CHANGES.get(lesson["status"], ())
    if new_status not in allowed:
        raise InvalidStatusChange(
            f"A {lesson['status']} lesson cannot be marked as {new_status}."
        )
    cursor = conn.cursor()
    cursor.execute("UPDATE lessons SET status = %s WHERE id = %s", (new_status, lesson_id))
    conn.commit()
