from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import CurrentUser, create_token, get_current_user, verify_password
from app.db import get_connection
from app.schemas import LoginRequest, LoginResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (body.username,)).fetchone()
    if row is None or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    if not row["is_active"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This account has been deactivated")
    token = create_token(row["id"], row["role"], row["instructor_id"])
    return LoginResponse(
        token=token, role=row["role"], instructor_id=row["instructor_id"],
        theme_preference=row["theme_preference"],
    )


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)):
    return {"user_id": user.user_id, "role": user.role, "instructor_id": user.instructor_id}
