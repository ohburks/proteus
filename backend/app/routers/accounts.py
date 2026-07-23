"""Admin-only account management (design gap M8)."""
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from app.auth import CurrentUser, hash_password, require_admin
from app.db import get_connection
from app.schemas import AccountCreate, AccountStatusUpdate

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def _now() -> str:
    return datetime.now(UTC).isoformat()


@router.post("")
def create_account(body: AccountCreate, admin: CurrentUser = Depends(require_admin)):
    if not body.username.strip() or not body.password.strip():
        raise HTTPException(400, "Username and password are required")
    with get_connection() as conn:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (body.username,)).fetchone():
            raise HTTPException(409, "Username already taken")
        user_id = str(uuid.uuid4())
        instructor_id = str(uuid.uuid4()) if body.role == "instructor" else None
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, instructor_id, is_active, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (user_id, body.username, hash_password(body.password), body.role, instructor_id, 1, _now()),
        )
        conn.commit()
    return {"id": user_id, "username": body.username, "role": body.role, "instructor_id": instructor_id, "is_active": True}


@router.get("")
def list_accounts(admin: CurrentUser = Depends(require_admin)):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, username, role, instructor_id, is_active, created_at FROM users ORDER BY created_at"
        ).fetchall()
    return [{**dict(r), "is_active": bool(r["is_active"])} for r in rows]


@router.put("/{user_id}/status")
def set_account_status(user_id: str, body: AccountStatusUpdate, admin: CurrentUser = Depends(require_admin)):
    if not body.is_active and user_id == admin.user_id:
        raise HTTPException(400, "Cannot deactivate your own account")
    with get_connection() as conn:
        if conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
            raise HTTPException(404, "Account not found")
        conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (int(body.is_active), user_id))
        conn.commit()
    return {"status": "ok"}
