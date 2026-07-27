from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.audit import record_audit_event
from app.auth import (
    DUMMY_PASSWORD_HASH,
    CurrentUser,
    create_token,
    get_current_user,
    login_throttle,
    verify_password,
)
from app.db import get_connection
from app.schemas import LoginRequest, LoginResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    try:
        login_throttle.check(client_ip)
    except HTTPException:
        record_audit_event(
            action="auth.login",
            outcome="denied",
            request=request,
            actor_username=body.username,
            target_type="account",
            metadata={"reason": "rate_limited"},
        )
        raise
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (body.username,)).fetchone()
    # Always run bcrypt — against a dummy hash when the user doesn't exist — so
    # the response takes the same time either way and can't be used to
    # enumerate valid usernames.
    password_ok = verify_password(body.password, row["password_hash"] if row else DUMMY_PASSWORD_HASH)
    if row is None or not password_ok:
        login_throttle.record_failure(client_ip)
        record_audit_event(
            action="auth.login",
            outcome="failure",
            request=request,
            actor_user_id=row["id"] if row else None,
            actor_username=row["username"] if row else body.username,
            actor_role=row["role"] if row else None,
            instructor_id=row["instructor_id"] if row else None,
            target_type="account",
            target_id=row["id"] if row else None,
            metadata={"reason": "invalid_credentials"},
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    if not row["is_active"]:
        record_audit_event(
            action="auth.login",
            outcome="denied",
            request=request,
            actor_user_id=row["id"],
            actor_username=row["username"],
            actor_role=row["role"],
            instructor_id=row["instructor_id"],
            target_type="account",
            target_id=row["id"],
            metadata={"reason": "account_deactivated"},
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This account has been deactivated")
    login_throttle.reset(client_ip)
    token = create_token(row["id"], row["role"], row["instructor_id"])
    record_audit_event(
        action="auth.login",
        outcome="success",
        request=request,
        actor_user_id=row["id"],
        actor_username=row["username"],
        actor_role=row["role"],
        instructor_id=row["instructor_id"],
        target_type="account",
        target_id=row["id"],
    )
    return LoginResponse(
        token=token, role=row["role"], instructor_id=row["instructor_id"],
        theme_preference=row["theme_preference"],
    )


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)):
    return {"user_id": user.user_id, "role": user.role, "instructor_id": user.instructor_id}
