"""Customer Management: students and their guardians' contact details.

This is the business logic of the customers service. The HTTP layer
(routes.py) and the lessons service, through this service's API, are the only
ways in; nothing else reads or writes the students table (ADR-2, ADR-6).

Every function takes an open database connection, so the logic can be tested
without running Flask.
"""
import re

MAX_NAME_LENGTH = 100
MAX_EMAIL_LENGTH = 254
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_PATTERN = re.compile(r"^\+?[0-9 ()-]{7,20}$")
STUDENT_COLUMNS = "id, name, guardian_name, guardian_email, guardian_phone, archived"


class CustomerError(Exception):
    """Base class for every error raised by the customers domain."""


class ValidationError(CustomerError):
    """The submitted student data breaks a business rule."""


class StudentNotFound(CustomerError):
    """No student exists with the requested id."""


def _clean(value):
    """Remove extra spaces and use None for empty values."""
    if value is None:
        return None
    value = str(value).strip()
    return value if value else None


def validate_student(data):
    """Check the input values and return them in a consistent format."""
    name = _clean(data.get("name"))
    guardian_name = _clean(data.get("guardian_name"))
    guardian_email = _clean(data.get("guardian_email"))
    guardian_phone = _clean(data.get("guardian_phone"))

    if name is None:
        raise ValidationError("Student name is required.")
    if len(name) > MAX_NAME_LENGTH:
        raise ValidationError(f"Student name can be at most {MAX_NAME_LENGTH} characters.")

    # SQL Server columns have a maximum length (SQLite's TEXT had none),
    # so the guardian's name and email are checked too.
    if guardian_name is not None and len(guardian_name) > MAX_NAME_LENGTH:
        raise ValidationError(f"Guardian name can be at most {MAX_NAME_LENGTH} characters.")

    if guardian_email is not None:
        guardian_email = guardian_email.lower()
        if len(guardian_email) > MAX_EMAIL_LENGTH or not EMAIL_PATTERN.match(guardian_email):
            raise ValidationError("Guardian email address is not valid.")

    if guardian_phone is not None and not PHONE_PATTERN.match(guardian_phone):
        raise ValidationError("Guardian phone number is not valid.")

    # At least one contact method is required, so the company can reach the
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
    cursor = conn.cursor(as_dict=True)
    # OUTPUT INSERTED.id returns the id SQL Server just generated.
    cursor.execute(
        "INSERT INTO students (name, guardian_name, guardian_email, guardian_phone) "
        "OUTPUT INSERTED.id "
        "VALUES (%(name)s, %(guardian_name)s, %(guardian_email)s, %(guardian_phone)s)",
        student,
    )
    student_id = cursor.fetchone()["id"]
    conn.commit()
    return student_id


def get_student(conn, student_id):
    """Find a student by id and return their details, or raise StudentNotFound."""
    cursor = conn.cursor(as_dict=True)
    cursor.execute(f"SELECT {STUDENT_COLUMNS} FROM students WHERE id = %s", (student_id,))
    row = cursor.fetchone()
    if row is None:
        raise StudentNotFound(f"Student {student_id} does not exist.")
    return _student_row(row)


def _student_row(row):
    """archived is a BIT in SQL Server; give it back as True or False."""
    row["archived"] = bool(row["archived"])
    return row


def list_students(conn, search=None, include_archived=False):
    """Return students sorted by name, optionally filtered by part of the name.

    Archived students are left out unless include_archived is True: the lessons
    service asks for them too, to show the names on their past lessons.
    The database's default collation ignores case, so 'ana' sorts next to 'Ana'
    and the search 'hox' finds 'Hoxha'.
    """
    search = _clean(search)
    conditions, params = [], []
    if not include_archived:
        conditions.append("archived = 0")
    if search is not None:
        conditions.append("name LIKE %s")
        params.append(f"%{search}%")
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    cursor = conn.cursor(as_dict=True)
    cursor.execute(
        f"SELECT {STUDENT_COLUMNS} FROM students{where} ORDER BY name, id", tuple(params)
    )
    return [_student_row(row) for row in cursor.fetchall()]


def update_student(conn, student_id, data):
    """Validate and overwrite an existing student's details."""
    student = validate_student(data)
    student["id"] = student_id
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE students SET name = %(name)s, guardian_name = %(guardian_name)s, "
        "guardian_email = %(guardian_email)s, guardian_phone = %(guardian_phone)s "
        "WHERE id = %(id)s",
        student,
    )
    updated = cursor.rowcount
    conn.commit()
    if updated == 0:
        raise StudentNotFound(f"Student {student_id} does not exist.")


def archive_student(conn, student_id):
    """Archive a student instead of deleting them (migration 002, ADR-7).

    In the monolith a foreign key stopped a student with lessons from being
    deleted. Lessons now live in another database, so the student's row is
    kept and only marked as archived: their lessons keep pointing at a student
    who exists, and the lessons service can still show the name.
    """
    cursor = conn.cursor()
    cursor.execute("UPDATE students SET archived = 1 WHERE id = %s", (student_id,))
    archived = cursor.rowcount
    conn.commit()
    if archived == 0:
        raise StudentNotFound(f"Student {student_id} does not exist.")
