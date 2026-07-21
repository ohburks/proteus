import json

from fastapi import APIRouter, Depends, HTTPException

from app.auth import CurrentUser, get_current_user
from app.db import get_connection

router = APIRouter(prefix="/api/rubrics", tags=["rubrics"])


@router.get("")
def list_rubrics(user: CurrentUser = Depends(get_current_user)):
    with get_connection() as conn:
        rows = conn.execute("SELECT rubric_id, version, genre, notes FROM rubrics").fetchall()
    return [dict(r) for r in rows]


@router.get("/{rubric_id}/{version}")
def get_rubric(rubric_id: str, version: str, user: CurrentUser = Depends(get_current_user)):
    with get_connection() as conn:
        rubric = conn.execute(
            "SELECT * FROM rubrics WHERE rubric_id = ? AND version = ?", (rubric_id, version)
        ).fetchone()
        if rubric is None:
            raise HTTPException(404, "Rubric not found")
        criteria = conn.execute(
            "SELECT * FROM criteria WHERE rubric_id = ? AND rubric_version = ?", (rubric_id, version)
        ).fetchall()
    return {
        "rubricId": rubric["rubric_id"],
        "version": rubric["version"],
        "genre": rubric["genre"],
        "notes": rubric["notes"],
        "criteria": [
            {
                "criterionId": c["criterion_id"],
                "standard": c["standard"],
                "dimension": c["dimension"],
                "statement": c["statement"],
                "scale": c["scale"],
                "referenceability": c["referenceability"],
                "anchors": json.loads(c["anchors_json"]),
            }
            for c in criteria
        ],
    }
