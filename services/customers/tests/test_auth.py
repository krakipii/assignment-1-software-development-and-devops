"""Tests for staff accounts, password checks and login tokens (auth.py)."""
import auth


def stored_hash(conn, username):
    cursor = conn.cursor(as_dict=True)
    cursor.execute("SELECT password_hash FROM staff WHERE username = %s", (username,))
    return cursor.fetchone()["password_hash"]


def test_first_start_creates_admin_with_a_random_password(conn):
    generated = auth.ensure_admin(conn, "admin")
    assert generated
    assert auth.check_login(conn, "admin", generated) is not None


def test_empty_admin_password_counts_as_not_set(conn):
    generated = auth.ensure_admin(conn, "admin", "")
    assert generated
    assert auth.check_login(conn, "admin", "") is None


def test_later_starts_without_a_password_keep_the_account(conn):
    first = auth.ensure_admin(conn, "admin")
    assert auth.ensure_admin(conn, "admin") is None
    assert auth.check_login(conn, "admin", first) is not None


def test_admin_password_from_the_environment_is_used(conn):
    assert auth.ensure_admin(conn, "admin", "s3cret-pass") is None
    assert auth.check_login(conn, "admin", "s3cret-pass") is not None


def test_admin_password_from_the_environment_resets_the_old_one(conn):
    auth.ensure_admin(conn, "admin", "old-pass")
    auth.ensure_admin(conn, "admin", "new-pass")
    assert auth.check_login(conn, "admin", "old-pass") is None
    assert auth.check_login(conn, "admin", "new-pass") is not None


def test_password_is_stored_as_a_hash_not_as_text(conn):
    auth.ensure_admin(conn, "admin", "s3cret-pass")
    assert "s3cret-pass" not in stored_hash(conn, "admin")


def test_check_login_returns_id_and_username(conn):
    auth.ensure_admin(conn, "admin", "s3cret-pass")
    staff = auth.check_login(conn, "  admin ", "s3cret-pass")
    assert staff["username"] == "admin"
    assert isinstance(staff["id"], int)


def test_check_login_rejects_wrong_password_and_unknown_user(conn):
    auth.ensure_admin(conn, "admin", "s3cret-pass")
    assert auth.check_login(conn, "admin", "wrong") is None
    assert auth.check_login(conn, "nobody", "s3cret-pass") is None
    assert auth.check_login(conn, None, None) is None


# ---------- tokens (no database needed) ----------

def test_token_round_trip_gives_back_the_staff_member():
    token = auth.make_token("secret-a", {"id": 7, "username": "admin"})
    assert auth.read_token("secret-a", token) == {"id": 7, "username": "admin"}


def test_token_signed_with_another_secret_is_refused():
    token = auth.make_token("secret-a", {"id": 7, "username": "admin"})
    assert auth.read_token("secret-b", token) is None


def test_changed_or_missing_token_is_refused():
    token = auth.make_token("secret-a", {"id": 7, "username": "admin"})
    assert auth.read_token("secret-a", token[:-2] + "xx") is None
    assert auth.read_token("secret-a", None) is None


def test_expired_token_is_refused():
    token = auth.make_token("secret-a", {"id": 7, "username": "admin"})
    assert auth.read_token("secret-a", token, max_age=-1) is None
