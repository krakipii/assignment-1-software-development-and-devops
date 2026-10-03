"""Tests for staff accounts and password checks (auth/service.py)."""
from auth import service


def stored_hash(conn, username):
    return conn.execute(
        "SELECT password_hash FROM staff WHERE username = ?", (username,)
    ).fetchone()["password_hash"]


def test_first_start_creates_admin_with_a_random_password(conn):
    generated = service.ensure_admin(conn, "admin")
    assert generated 
    assert service.check_login(conn, "admin", generated) is not None


def test_empty_admin_password_counts_as_not_set(conn):
    generated = service.ensure_admin(conn, "admin", "")
    assert generated
    assert service.check_login(conn, "admin", "") is None


def test_later_starts_without_a_password_keep_the_account(conn):
    first = service.ensure_admin(conn, "admin")
    assert service.ensure_admin(conn, "admin") is None
    assert service.check_login(conn, "admin", first) is not None


def test_admin_password_from_the_environment_is_used(conn):
    assert service.ensure_admin(conn, "admin", "s3cret-pass") is None
    assert service.check_login(conn, "admin", "s3cret-pass") is not None


def test_admin_password_from_the_environment_resets_the_old_one(conn):
    service.ensure_admin(conn, "admin", "old-pass")
    service.ensure_admin(conn, "admin", "new-pass")
    assert service.check_login(conn, "admin", "old-pass") is None
    assert service.check_login(conn, "admin", "new-pass") is not None


def test_password_is_stored_as_a_hash_not_as_text(conn):
    service.ensure_admin(conn, "admin", "s3cret-pass")
    assert "s3cret-pass" not in stored_hash(conn, "admin")


def test_check_login_returns_id_and_username(conn):
    service.ensure_admin(conn, "admin", "s3cret-pass")
    staff = service.check_login(conn, "  admin ", "s3cret-pass")
    assert staff["username"] == "admin"
    assert isinstance(staff["id"], int)


def test_check_login_rejects_wrong_password_and_unknown_user(conn):
    service.ensure_admin(conn, "admin", "s3cret-pass")
    assert service.check_login(conn, "admin", "wrong") is None
    assert service.check_login(conn, "nobody", "s3cret-pass") is None
    assert service.check_login(conn, None, None) is None