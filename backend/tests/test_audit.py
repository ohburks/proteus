from fastapi.testclient import TestClient

from app.audit import record_audit_event
from app.auth import CurrentUser, get_current_user, hash_password
from app.main import app


def test_audit_event_is_persisted_and_user_values_are_bounded(isolated_db):
    record_audit_event(
        action="auth.login",
        outcome="failure",
        actor_username="x" * 1000,
        metadata={"reason": "invalid_credentials", "supplied": "y" * 2000},
    )

    row = isolated_db.execute("SELECT * FROM audit_events").fetchone()
    assert row["action"] == "auth.login"
    assert row["outcome"] == "failure"
    assert len(row["actor_username"]) == 200
    assert len(row["metadata_json"]) < 700


def test_audit_api_is_admin_only(isolated_db):
    record_audit_event(action="auth.login", outcome="success", actor_username="admin")

    client = TestClient(app)
    try:
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            "instructor-user", "instructor", "instructor-id", "teacher"
        )
        assert client.get("/api/audit-events").status_code == 403

        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            "admin-user", "admin", None, "admin"
        )
        response = client.get("/api/audit-events?limit=10")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["action"] == "auth.login"
        assert body["items"][0]["metadata"] == {}
    finally:
        app.dependency_overrides.clear()


def test_successful_login_records_redacted_event(isolated_db):
    isolated_db.execute(
        """INSERT INTO users
           (id, username, password_hash, role, instructor_id, is_active, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (
            "admin-user",
            "admin",
            hash_password("correct-password"),
            "admin",
            None,
            1,
            "2026-01-01T00:00:00+00:00",
        ),
    )
    isolated_db.commit()

    response = TestClient(app).post(
        "/api/auth/login",
        json={"username": "admin", "password": "correct-password"},
    )
    assert response.status_code == 200

    event = isolated_db.execute("SELECT * FROM audit_events").fetchone()
    assert event["action"] == "auth.login"
    assert event["outcome"] == "success"
    assert event["actor_user_id"] == "admin-user"
    assert "password" not in event["metadata_json"]
    assert "token" not in event["metadata_json"]
