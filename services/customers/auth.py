"""Staff accounts, password checks and login tokens.

Passwords are stored as salted hashes made by werkzeug, which comes with Flask.

After a successful login the service hands out a token: the staff member's id
and username, signed with AUTH_SECRET by itsdangerous (also part of Flask).
The browser sends it with every request as "Authorization: Bearer <token>".
The lessons service checks the same token with the same AUTH_SECRET, so
checking a login never needs a call across the seam (ADR-6).
"""
import secrets

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

TOKEN_SALT = "staff-login"
TOKEN_MAX_AGE = 8 * 60 * 60  # a working day, in seconds


def check_login(conn, username, password):
    """Return the staff member as {id, username} if the password is right, else None."""
    username = (username or "").strip()
    cursor = conn.cursor(as_dict=True)
    cursor.execute(
        "SELECT id, username, password_hash FROM staff WHERE username = %s", (username,)
    )
    row = cursor.fetchone()
    if row is None or not check_password_hash(row["password_hash"], password or ""):
        return None
    return {"id": row["id"], "username": row["username"]}


def ensure_admin(conn, username, password=None):
    """Make sure the admin account exists when the service starts.

    If a password is given, create the account or reset its password.
    If not, keep an existing account, or create one with a random password.
    Returns the random password if one was created, otherwise None.
    """
    password = password or None  # an empty ADMIN_PASSWORD counts as "not set"
    cursor = conn.cursor(as_dict=True)
    cursor.execute("SELECT id FROM staff WHERE username = %s", (username,))
    row = cursor.fetchone()

    generated = None
    if password is None:
        if row is not None:
            return None
        password = generated = secrets.token_urlsafe(9)

    password_hash = generate_password_hash(password)
    if row is None:
        cursor.execute(
            "INSERT INTO staff (username, password_hash) VALUES (%s, %s)",
            (username, password_hash),
        )
    else:
        cursor.execute(
            "UPDATE staff SET password_hash = %s WHERE id = %s", (password_hash, row["id"])
        )
    conn.commit()
    return generated


def make_token(secret, staff):
    """Sign {id, username} into a token the browser can send back."""
    serializer = URLSafeTimedSerializer(secret, salt=TOKEN_SALT)
    return serializer.dumps({"id": staff["id"], "username": staff["username"]})


def read_token(secret, token, max_age=TOKEN_MAX_AGE):
    """Return {id, username} from a valid token, or None if it is wrong or expired."""
    serializer = URLSafeTimedSerializer(secret, salt=TOKEN_SALT)
    try:
        return serializer.loads(token or "", max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
