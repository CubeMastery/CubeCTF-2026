import base64
import hashlib
import hmac
import secrets
from typing import Optional

from fastapi import Cookie, HTTPException

from database import db


sessions = {}


def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120000)
    return base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    salt_b64, digest_b64 = stored.split("$", 1)
    salt = base64.urlsafe_b64decode(salt_b64)
    expected = base64.urlsafe_b64decode(digest_b64)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120000)
    return hmac.compare_digest(actual, expected)


def current_user(session: Optional[str] = Cookie(default=None)):
    if not session or session not in sessions:
        return None
    with db() as conn:
        return conn.execute("select * from users where id = ?", (sessions[session],)).fetchone()


def require_user(session: Optional[str] = Cookie(default=None)):
    user = current_user(session)
    if not user:
        raise HTTPException(status_code=401, detail="login required")
    return user
