"""Handles staff accounts and password checks.

Passwords are not stored directly. Instead, the app stores a salted hash created by werkzeug.security, 
which comes with Flask and does not add another dependency.
"""

import secrets

from werkzeug.security import check_password_hash, generate_password_hash


def check_login(conn, username, password):
    """Return the staff member as {id, username} if the password is right, else None."""
    username = (username or "").strip()
    row = conn.execute(
        "SELECT id, username, password_hash FROM staff WHERE username = ?", (username,)
    ).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password or ""):
        return None
    return {"id": row["id"], "username": row["username"]}


def ensure_admin(conn, username, password=None):
    """Make sure the admin account exists when the app starts.

If a password is provided, create the account or update its password. 
If no password is provided, keep an existing account or create one with a random password.

Returns the random password if one was created, otherwise None.
    """
    password = password or None  # treat an empty ADMIN_PASSWORD as "not set"
    row = conn.execute("SELECT id FROM staff WHERE username = ?", (username,)).fetchone()

    generated = None
    if password is None:
        if row is not None:
            return None
        password = generated = secrets.token_urlsafe(9)

    password_hash = generate_password_hash(password)
    if row is None:
        conn.execute(
            "INSERT INTO staff (username, password_hash) VALUES (?, ?)", (username, password_hash)
        )
    else:
        conn.execute("UPDATE staff SET password_hash = ? WHERE id = ?", (password_hash, row["id"]))
    conn.commit()
    return generated