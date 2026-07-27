"""Admin-only security audit log."""
import json

from fastapi import APIRouter, Depends, Query

from app.auth import CurrentUser, require_admin
from app.db import get_connection

router = APIRouter(prefix="/api/audit-events", tags=["audit"])


@router.get("")
def list_audit_events(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    action: str | None = Query(None, max_length=80),
    outcome: str | None = Query(None, pattern="^(success|failure|denied)$"),
    search: str | None = Query(None, max_length=100),
    admin: CurrentUser = Depends(require_admin),
):
    needle = f"%{search.strip()}%" if search and search.strip() else None
    params: list[object] = [
        action, action,
        outcome, outcome,
        needle, needle, needle, needle, needle,
    ]
    with get_connection() as conn:
        total = conn.execute(
            """SELECT COUNT(*) FROM audit_events
               WHERE (? IS NULL OR action = ?)
                 AND (? IS NULL OR outcome = ?)
                 AND (
                   ? IS NULL
                   OR actor_username LIKE ?
                   OR target_type LIKE ?
                   OR target_id LIKE ?
                   OR ip_address LIKE ?
                 )""",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            """SELECT * FROM audit_events
               WHERE (? IS NULL OR action = ?)
                 AND (? IS NULL OR outcome = ?)
                 AND (
                   ? IS NULL
                   OR actor_username LIKE ?
                   OR target_type LIKE ?
                   OR target_id LIKE ?
                   OR ip_address LIKE ?
                 )
               ORDER BY occurred_at DESC, id DESC LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
        actions = [
            row["action"]
            for row in conn.execute(
                "SELECT DISTINCT action FROM audit_events ORDER BY action"
            ).fetchall()
        ]

    items = []
    for row in rows:
        item = dict(row)
        try:
            item["metadata"] = json.loads(item.pop("metadata_json"))
        except (TypeError, json.JSONDecodeError):
            item["metadata"] = {}
            item.pop("metadata_json", None)
        items.append(item)
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "actions": actions,
    }
