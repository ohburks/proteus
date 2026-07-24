from fastapi.testclient import TestClient

import app.db as db
from app.audit import record_audit_event
from app.auth import CurrentUser, get_current_user, hash_password
from app.main import app


def _isolated_db(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "audit.sqlite3")
    db.init_db()


def test_audit_event_is_persisted_and_user_values_are_bounded(monkeypatch, tmp_path):
    _isolated_db(monkeypatch, tmp_path)

    record_audit_event(
        action="auth.login",
        outcome="failure",
        actor_username="x" * 1000,
        metadata={"reason": "invalid_credentials", "supplied": "y" * 2000},
    )

    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM audit_events").fetchone()
    assert row["action"] == "auth.login"
    assert row["outcome"] == "failure"
    assert len(row["actor_username"]) == 200
    assert len(row["metadata_json"]) < 700


def test_audit_api_is_admin_only(monkeypatch, tmp_path):
    _isolated_db(monkeypatch, tmp_path)
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


def test_successful_login_records_redacted_event(monkeypatch, tmp_path):
    _isolated_db(monkeypatch, tmp_path)
    with db.get_connection() as conn:
        conn.execute(
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
        conn.commit()

    response = TestClient(app).post(
        "/api/auth/login",
        json={"username": "admin", "password": "correct-password"},
    )
    assert response.status_code == 200

    with db.get_connection() as conn:
        event = conn.execute("SELECT * FROM audit_events").fetchone()
    assert event["action"] == "auth.login"
    assert event["outcome"] == "success"
    assert event["actor_user_id"] == "admin-user"
    assert "password" not in event["metadata_json"]
    assert "token" not in event["metadata_json"]
