"""Lesson Management handles tutors, lessons and each lesson's status.

The functions in this module are used by the rest of the application.

Student information is always obtained through customers.service instead of
accessing the students table directly, which keeps the two domains separate.

Each function takes an open database connection so the logic can be tested
without running Flask.
"""
import re
from datetime import datetime, timedelta

from customers import service as customers

MAX_NAME_LENGTH = 100
MAX_HOURLY_RATE = 1000
MIN_DURATION = 15
MAX_DURATION = 240
STATUSES = ("scheduled", "completed", "cancelled")
# These are the statues a lesson can change from its current status.
# Completed and cancelled lessons cannot be changed again.
ALLOWED_STATUS_CHANGES = {"scheduled": ("completed", "cancelled")}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TUTOR_COLUMNS = "id, name, email, subjects, hourly_rate"
LESSON_COLUMNS = "id, tutor_id, student_id, subject, start_time, duration_minutes, status"


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

    This helper is also used in customers.service so both domains can work independently.
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
    """Check the tutor information and return it in a clean format"""
    name = _clean(data.get("name"))
    email = _clean(data.get("email"))
    subjects = _subject_list(_clean(data.get("subjects")))

    if name is None:
        raise ValidationError("Tutor name is required.")
    if len(name) > MAX_NAME_LENGTH:
        raise ValidationError(f"Tutor name can be at most {MAX_NAME_LENGTH} characters.")

    if email is not None:
        email = email.lower()
        if not EMAIL_PATTERN.match(email):
            raise ValidationError("Tutor email address is not valid.")

    try:
        hourly_rate = float(data.get("hourly_rate"))
    except (TypeError, ValueError):
        raise ValidationError("Hourly rate must be a number.")
    if not 0 <= hourly_rate <= MAX_HOURLY_RATE:
        raise ValidationError(f"Hourly rate must be between 0 and {MAX_HOURLY_RATE}.")

    return {
        "name": name,
        "email": email,
        "subjects": ", ".join(subjects) or None,
        "hourly_rate": round(hourly_rate, 2),
    }


def create_tutor(conn, data):
    """Validate and store a new tutor. Returns the new tutor's id."""
    tutor = validate_tutor(data)
    cursor = conn.execute(
        "INSERT INTO tutors (name, email, subjects, hourly_rate) "
        "VALUES (:name, :email, :subjects, :hourly_rate)",
        tutor,
    )
    conn.commit()
    return cursor.lastrowid


def get_tutor(conn, tutor_id):
    """Return one tutor as a dict, or raise TutorNotFound."""
    row = conn.execute(
        f"SELECT {TUTOR_COLUMNS} FROM tutors WHERE id = ?", (tutor_id,)
    ).fetchone()
    if row is None:
        raise TutorNotFound(f"Tutor {tutor_id} does not exist.")
    return dict(row)


def list_tutors(conn):
    """Return all tutors sorted by name."""
    rows = conn.execute(
        f"SELECT {TUTOR_COLUMNS} FROM tutors ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return [dict(row) for row in rows]


def update_tutor(conn, tutor_id, data):
    """Validate and overwrite an existing tutor's details."""
    tutor = validate_tutor(data)
    tutor["id"] = tutor_id
    cursor = conn.execute(
        "UPDATE tutors SET name = :name, email = :email, subjects = :subjects, "
        "hourly_rate = :hourly_rate WHERE id = :id",
        tutor,
    )
    conn.commit()
    if cursor.rowcount == 0:
        raise TutorNotFound(f"Tutor {tutor_id} does not exist.")


# ---------- lessons ----------

def _parse_int(value, message):
    """Convert form input to an int, or raise ValidationError with message."""
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError(message)


def _parse_start(value):
    """Convert '2026-10-05T16:00' (what an HTML date-time field sends) to a datetime."""
    try:
        return datetime.fromisoformat(_clean(value))
    except (TypeError, ValueError):
        raise ValidationError("Start time must look like 2026-10-05T16:00.")


def validate_lesson(conn, data):
    """Check a new lesson against the business rules and return a clean dict."""
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
        raise ValidationError("Choose an existing tutor.")

    try:
        # Student data is accessed through the customers domain's functions.
        customers.get_student(conn, student_id)
    except customers.StudentNotFound:
        raise ValidationError("Choose an existing student.")

    if subject is None:
        raise ValidationError("Subject is required.")
    # Business rule: A tutor can only teach the subjects they have listed.
    tutor_subjects = _subject_list(tutor["subjects"])
    if tutor_subjects:
        matching = [s for s in tutor_subjects if s.lower() == subject.lower()]
        if not matching:
            raise ValidationError(f"{tutor['name']} teaches {tutor['subjects']}, not {subject}.")
        subject = matching[0]

    if not MIN_DURATION <= duration <= MAX_DURATION:
        raise ValidationError(
            f"A lesson must last between {MIN_DURATION} and {MAX_DURATION} minutes."
        )

    return {
        "tutor_id": tutor_id,
        "student_id": student_id,
        "subject": subject,
        "start_time": start.isoformat(timespec="minutes"),
        "duration_minutes": duration,
    }


def _find_conflict(conn, tutor_id, student_id, start, end):
    """Find a lesson that overlaps with the tutor or student's time, or return None.

    Cancelled lessons are ignored because their time slot is available again.
    """
    rows = conn.execute(
        "SELECT tutor_id, start_time, duration_minutes FROM lessons "
        "WHERE status != 'cancelled' AND (tutor_id = ? OR student_id = ?)",
        (tutor_id, student_id),
    ).fetchall()
    for row in rows:
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


def schedule_lesson(conn, data):
    """Validate a new lesson, check for double bookings and store it. Returns its id."""
    lesson = validate_lesson(conn, data)
    start = datetime.fromisoformat(lesson["start_time"])
    end = start + timedelta(minutes=lesson["duration_minutes"])

    conflict = _find_conflict(conn, lesson["tutor_id"], lesson["student_id"], start, end)
    if conflict is not None:
        raise ScheduleConflict(conflict)

    cursor = conn.execute(
        "INSERT INTO lessons (tutor_id, student_id, subject, start_time, duration_minutes) "
        "VALUES (:tutor_id, :student_id, :subject, :start_time, :duration_minutes)",
        lesson,
    )
    conn.commit()
    return cursor.lastrowid


def get_lesson(conn, lesson_id):
    """Return one lesson as a dict, or raise LessonNotFound."""
    row = conn.execute(
        f"SELECT {LESSON_COLUMNS} FROM lessons WHERE id = ?", (lesson_id,)
    ).fetchone()
    if row is None:
        raise LessonNotFound(f"Lesson {lesson_id} does not exist.")
    return dict(row)


def list_lessons(conn, status=None, tutor_id=None):
    """Return lessons ordered by start time, including tutor and student names.

    Can be filtered by status and/or tutor.
    """
    if status is not None and status not in STATUSES:
        raise ValidationError(f"Unknown lesson status: {status}.")

    # Joining tutors is fine: tutors belong to this domain.
    query = (
        "SELECT lessons.id, lessons.tutor_id, tutors.name AS tutor_name, "
        "lessons.student_id, lessons.subject, lessons.start_time, "
        "lessons.duration_minutes, lessons.status "
        "FROM lessons JOIN tutors ON tutors.id = lessons.tutor_id"
    )
    conditions, params = [], []
    if status is not None:
        conditions.append("lessons.status = ?")
        params.append(status)
    if tutor_id is not None:
        conditions.append("lessons.tutor_id = ?")
        params.append(tutor_id)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY lessons.start_time"

    lessons = [dict(row) for row in conn.execute(query, params).fetchall()]

    # tudent names come from the customers domain instead of joining the students table.
    student_names = {}
    for lesson in lessons:
        student_id = lesson["student_id"]
        if student_id not in student_names:
            student_names[student_id] = customers.get_student(conn, student_id)["name"]
        lesson["student_name"] = student_names[student_id]
    return lessons


def change_status(conn, lesson_id, new_status):
    """Mark a scheduled lesson as completed or cancelled."""
    lesson = get_lesson(conn, lesson_id)
    allowed = ALLOWED_STATUS_CHANGES.get(lesson["status"], ())
    if new_status not in allowed:
        raise InvalidStatusChange(
            f"A {lesson['status']} lesson cannot be marked as {new_status}."
        )
    conn.execute("UPDATE lessons SET status = ? WHERE id = ?", (new_status, lesson_id))
    conn.commit()