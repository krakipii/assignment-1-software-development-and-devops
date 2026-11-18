"""Checks the login tokens that the customers service hands out (ADR-6).

The customers service signs {id, username} with AUTH_SECRET when a staff member
logs in. This service checks the signature with the same AUTH_SECRET, so it
never needs to ask the customers service whether someone is logged in.
"""
from itsdangerous import BadSignature, URLSafeTimedSerializer

# Must match the customers service's auth.py.
TOKEN_SALT = "staff-login"
TOKEN_MAX_AGE = 8 * 60 * 60  # a working day, in seconds


def read_token(secret, token, max_age=TOKEN_MAX_AGE):
    """Return {id, username} from a valid token, or None if it is wrong or expired."""
    serializer = URLSafeTimedSerializer(secret, salt=TOKEN_SALT)
    try:
        return serializer.loads(token or "", max_age=max_age)
    except BadSignature:  # SignatureExpired is a kind of BadSignature
        return None
