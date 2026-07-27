"""Durable, redacted security audit events.

Audit writes use their own short-lived SQLite connection so authentication
failures and actions that have already committed can still be recorded. Audit
failures are logged server-side but never make the primary user action fail:
the original action may already be committed, and returning an error would
invite unsafe retries.
"""
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Request

from app.db import get_connection, write_with_retry

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _client_ip(request: Request | None) -> str | None:
    return request.client.host if request and request.client else None


def _bounded_text(value: str | None, limit: int) -> str | None:
    return value[:limit] if value else value


def _safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Keep unauthenticated/user-controlled values from inflating the log."""
    safe: dict[str, Any] = {}
    for key, value in list((metadata or {}).items())[:30]:
        safe_key = str(key)[:80]
        if value is None or isinstance(value, (bool, int, float)):
            safe[safe_key] = value
        elif isinstance(value, str):
            safe[safe_key] = value[:500]
        else:
            safe[safe_key] = json.dumps(value, default=str)[:1000]
    return safe


def record_audit_event(
    *,
    action: str,
    outcome: str,
    request: Request | None = None,
    actor: Any | None = None,
    actor_user_id: str | None = None,
    actor_username: str | None = None,
    actor_role: str | None = None,
    instructor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append one event without ever storing credentials, tokens, or content.

    ``actor`` is intentionally duck-typed to avoid a circular import with
    app.auth, which records login events before a CurrentUser exists.
    """
    if outcome not in {"success", "failure", "denied"}:
        raise ValueError(f"Unsupported audit outcome: {outcome!r}")

    if actor is not None:
        actor_user_id = actor_user_id or getattr(actor, "user_id", None)
        actor_username = actor_username or getattr(actor, "username", None)
        actor_role = actor_role or getattr(actor, "role", None)
        instructor_id = instructor_id or getattr(actor, "instructor_id", None)

    event_id = str(uuid.uuid4())
    values = (
        event_id,
        _now(),
        _bounded_text(actor_user_id, 200),
        _bounded_text(actor_username, 200),
        _bounded_text(actor_role, 40),
        _bounded_text(instructor_id, 200),
        action[:80],
        outcome,
        _bounded_text(target_type, 80),
        _bounded_text(target_id, 500),
        _bounded_text(_client_ip(request), 100),
        json.dumps(_safe_metadata(metadata), separators=(",", ":"), sort_keys=True),
    )
    try:
        with get_connection() as conn:
            write_with_retry(
                conn,
                lambda: conn.execute(
                    """INSERT INTO audit_events
                       (id, occurred_at, actor_user_id, actor_username, actor_role,
                        instructor_id, action, outcome, target_type, target_id,
                        ip_address, metadata_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    values,
                ),
            )
    except Exception:
        logger.exception("Failed to persist audit event %s (%s)", action, event_id)
