"""Authentication and roles (design doc §11).

instructor: scoped to their own courses/assignments/students/personalized
corpus/settings. admin: sees all instructors; used for setup/seeding/oversight.
"""
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db import get_connection

_FALLBACK_JWT_SECRET = "dev-secret-change-me-please-2026"
JWT_SECRET = os.environ.get("JWT_SECRET", _FALLBACK_JWT_SECRET)
JWT_ALGORITHM = "HS256"
JWT_TTL = timedelta(hours=12)

_bearer = HTTPBearer()
_logger = logging.getLogger("proteus")


def assert_secure_jwt_secret() -> None:
    """Refuse to boot in production on the built-in dev signing secret (D9).

    Keyed on an explicit PROTEUS_ENV=production so local dev (the default) still
    boots on the fallback exactly as before — but a real deployment that forgot
    to set JWT_SECRET fails loudly at startup instead of silently signing tokens
    with a public, source-controlled key. A warning is logged in every other
    case where the fallback is in use, so it never goes unnoticed."""
    if JWT_SECRET != _FALLBACK_JWT_SECRET:
        return
    env = os.environ.get("PROTEUS_ENV", "dev").lower()
    if env in ("production", "prod"):
        raise RuntimeError(
            "JWT_SECRET is unset and PROTEUS_ENV=production — refusing to boot with "
            "the built-in dev signing secret. Set JWT_SECRET to a strong random value."
        )
    _logger.warning(
        "Using the built-in dev JWT secret. Set JWT_SECRET for any non-local deployment."
    )


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_token(user_id: str, role: str, instructor_id: str | None) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "instructor_id": instructor_id,
        "exp": datetime.now(UTC) + JWT_TTL,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


class CurrentUser:
    def __init__(self, user_id: str, role: str, instructor_id: str | None):
        self.user_id = user_id
        self.role = role
        self.instructor_id = instructor_id

    def scoped_instructor_id(self, requested: str | None = None) -> str:
        """Admins may act on behalf of any instructor_id they specify;
        instructors are pinned to their own scope regardless of what's requested."""
        if self.role == "admin":
            if not requested:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "instructor_id is required for admin requests")
            return requested
        return self.instructor_id


def get_current_user(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> CurrentUser:
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from e
    # Re-check the account is still active on every request (D8), not just at
    # login: a token issued before deactivation must stop working immediately
    # (e.g. a compromised or revoked account), rather than staying valid for the
    # rest of its 12h TTL. Cheap primary-key lookup.
    with get_connection() as conn:
        row = conn.execute("SELECT is_active FROM users WHERE id = ?", (payload["sub"],)).fetchone()
    if row is None or not row["is_active"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is deactivated or no longer exists")
    return CurrentUser(payload["sub"], payload["role"], payload.get("instructor_id"))


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return user


def _ensure_user(conn, username: str, password: str, role: str, instructor_id: str | None, now: str) -> None:
    """Insert the account if its username doesn't exist yet; leave it alone if
    it does. Per-username idempotency (not skip-if-any-user-exists) so newly
    added default accounts still seed into an existing DB on `make seed`."""
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        return
    conn.execute(
        "INSERT INTO users (id, username, password_hash, role, instructor_id, created_at) VALUES (?,?,?,?,?,?)",
        (str(uuid.uuid4()), username, hash_password(password), role, instructor_id, now),
    )


def seed_default_accounts() -> None:
    """Seeded default accounts for local testing (§11) — test logins for
    local development, not sensitive credentials."""
    with get_connection() as conn:
        now = datetime.now(UTC).isoformat()
        _ensure_user(conn, "admin", "admin123", "admin", None, now)
        _ensure_user(conn, "instructor", "instruct123", "instructor", str(uuid.uuid4()), now)
        _ensure_user(conn, "instructor_2", "instruct123", "instructor", str(uuid.uuid4()), now)
        conn.commit()
