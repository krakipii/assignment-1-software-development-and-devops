"""Customer Management handles students and their guardian contact details.

Other parts of the application use these functions instead of accessing the students table directly, 
which keeps the domain separate and makes it easier to test the logic without running Flask.
"""
import re
import sqlite3

MAX_NAME_LENGTH = 100
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_PATTERN = re.compile(r"^\+?[0-9 ()-]{7,20}$")
STUDENT_COLUMNS = "id, name, guardian_name, guardian_email, guardian_phone"


class CustomerError(Exception):
    """Base class for every error raised by the customers domain."""


class ValidationError(CustomerError):
    """The submitted student data breaks a business rule."""


class StudentNotFound(CustomerError):
    """No student exists with the requested id."""


class StudentHasLessons(CustomerError):
    """The student cannot be deleted because lessons still refer to them."""


def _clean(value):
    """Remove extra spaces and use None for empty values."""
    if value is None:
        return None
    value = str(value).strip()
    return value if value else None


def validate_student(data):
    """Check the input values and return them in a consistent format"""
    name = _clean(data.get("name"))
    guardian_name = _clean(data.get("guardian_name"))
    guardian_email = _clean(data.get("guardian_email"))
    guardian_phone = _clean(data.get("guardian_phone"))

    if name is None:
        raise ValidationError("Student name is required.")
    if len(name) > MAX_NAME_LENGTH:
        raise ValidationError(f"Student name can be at most {MAX_NAME_LENGTH} characters.")

    if guardian_email is not None:
        guardian_email = guardian_email.lower()
        if not EMAIL_PATTERN.match(guardian_email):
            raise ValidationError("Guardian email address is not valid.")

    if guardian_phone is not None and not PHONE_PATTERN.match(guardian_phone):
        raise ValidationError("Guardian phone number is not valid.")

    # At least one contact method is required so the company can contact the 
    # guardian if a lesson is changed or cancelled.
    if guardian_email is None and guardian_phone is None:
        raise ValidationError("Enter a guardian email or phone number.")

    return {
        "name": name,
        "guardian_name": guardian_name,
        "guardian_email": guardian_email,
        "guardian_phone": guardian_phone,
    }


def create_student(conn, data):
    """Validate and store a new student. Returns the new student's id."""
    student = validate_student(data)
    cursor = conn.execute(
        "INSERT INTO students (name, guardian_name, guardian_email, guardian_phone) "
        "VALUES (:name, :guardian_name, :guardian_email, :guardian_phone)",
        student,
    )
    conn.commit()
    return cursor.lastrowid


def get_student(conn, student_id):
    """Find a student by ID and return their details, or raise an error if not found."""
    row = conn.execute(
        f"SELECT {STUDENT_COLUMNS} FROM students WHERE id = ?", (student_id,)
    ).fetchone()
    if row is None:
        raise StudentNotFound(f"Student {student_id} does not exist.")
    return dict(row)


def list_students(conn, search=None):
    """Return all students sorted by name, optionally filtered by part of the name."""
    search = _clean(search)
    if search is None:
        rows = conn.execute(
            f"SELECT {STUDENT_COLUMNS} FROM students ORDER BY name COLLATE NOCASE"
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {STUDENT_COLUMNS} FROM students "
            "WHERE name LIKE ? ORDER BY name COLLATE NOCASE",
            (f"%{search}%",),
        ).fetchall()
    return [dict(row) for row in rows]


def update_student(conn, student_id, data):
    """Validate and overwrite an existing student's details."""
    student = validate_student(data)
    student["id"] = student_id
    cursor = conn.execute(
        "UPDATE students SET name = :name, guardian_name = :guardian_name, "
        "guardian_email = :guardian_email, guardian_phone = :guardian_phone "
        "WHERE id = :id",
        student,
    )
    conn.commit()
    if cursor.rowcount == 0:
        raise StudentNotFound(f"Student {student_id} does not exist.")


def delete_student(conn, student_id):
    """Delete a student. Refused if any lesson still references them."""
    try:
        cursor = conn.execute("DELETE FROM students WHERE id = ?", (student_id,))
        conn.commit()
    except sqlite3.IntegrityError:
        # The foreign key lessons.student_id blocks the delete.
        conn.rollback()
        raise StudentHasLessons(
            f"Student {student_id} still has lessons and cannot be deleted."
        )
    if cursor.rowcount == 0:
        raise StudentNotFound(f"Student {student_id} does not exist.")