from fastapi import APIRouter, Depends, HTTPException, Request, status

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
    login_throttle.check(client_ip)
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (body.username,)).fetchone()
    # Always run bcrypt — against a dummy hash when the user doesn't exist — so
    # the response takes the same time either way and can't be used to
    # enumerate valid usernames.
    password_ok = verify_password(body.password, row["password_hash"] if row else DUMMY_PASSWORD_HASH)
    if row is None or not password_ok:
        login_throttle.record_failure(client_ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    if not row["is_active"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This account has been deactivated")
    login_throttle.reset(client_ip)
    token = create_token(row["id"], row["role"], row["instructor_id"])
    return LoginResponse(
        token=token, role=row["role"], instructor_id=row["instructor_id"],
        theme_preference=row["theme_preference"],
    )


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)):
    return {"user_id": user.user_id, "role": user.role, "instructor_id": user.instructor_id}
