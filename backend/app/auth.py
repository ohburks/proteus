"""Authentication and roles (design doc §11).

instructor: scoped to their own courses/assignments/students/personalized
corpus/settings. admin: sees all instructors; used for setup/seeding/oversight.
"""
import os
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db import get_connection

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_TTL = timedelta(hours=12)

_bearer = HTTPBearer()


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
    return CurrentUser(payload["sub"], payload["role"], payload.get("instructor_id"))


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return user


def seed_default_accounts() -> None:
    """Seeded default accounts for local testing (§11) — test logins for
    local development, not sensitive credentials."""
    with get_connection() as conn:
        existing = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
        if existing:
            return
        now = datetime.now(UTC).isoformat()
        admin_id = str(uuid.uuid4())
        instructor_user_id = str(uuid.uuid4())
        instructor_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, instructor_id, created_at) VALUES (?,?,?,?,?,?)",
            (admin_id, "admin", hash_password("admin123"), "admin", None, now),
        )
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, instructor_id, created_at) VALUES (?,?,?,?,?,?)",
            (instructor_user_id, "instructor", hash_password("instruct123"), "instructor", instructor_id, now),
        )
        conn.commit()
