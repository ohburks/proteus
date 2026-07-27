import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from app.audit import record_audit_event
from app.auth import CurrentUser, get_current_user
from app.db import get_connection
from app.schemas import RubricImport

router = APIRouter(prefix="/api/rubrics", tags=["rubrics"])


@router.get("")
def list_rubrics(user: CurrentUser = Depends(get_current_user)):
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT rubric_id, version, genre, notes,
                      CASE WHEN owner_instructor_id IS NULL THEN 0 ELSE 1 END AS is_custom
               FROM rubrics
               WHERE owner_instructor_id IS NULL OR owner_instructor_id = ?
               ORDER BY is_custom DESC, rubric_id, version""",
            (user.instructor_id,),
        ).fetchall()
    return [
        {
            **dict(row),
            "is_custom": bool(row["is_custom"]),
        }
        for row in rows
    ]


@router.post("")
def import_rubric(
    body: RubricImport,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
    if user.role != "instructor" or not user.instructor_id:
        raise HTTPException(403, "Instructor account required to import a rubric")
    raw = body.model_dump()
    now = datetime.now(UTC).isoformat()
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM rubrics WHERE rubric_id = ? AND version = ?",
            (body.rubricId, body.version),
        ).fetchone()
        if existing:
            raise HTTPException(409, "That rubric ID and version already exist")
        conn.execute(
            """INSERT INTO rubrics
               (rubric_id, version, owner_instructor_id, genre, notes,
                assignment_guidance, raw_json, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                body.rubricId,
                body.version,
                user.instructor_id,
                body.genre,
                body.notes,
                body.assignmentGuidance,
                json.dumps(raw),
                now,
            ),
        )
        for criterion in body.criteria:
            conn.execute(
                """INSERT INTO criteria
                   (rubric_id, rubric_version, criterion_id, standard, dimension,
                    statement, scale, referenceability, source, anchors_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    body.rubricId,
                    body.version,
                    criterion.criterionId,
                    criterion.standard,
                    criterion.dimension,
                    criterion.statement,
                    criterion.scale,
                    criterion.referenceability,
                    criterion.source,
                    json.dumps(criterion.anchors),
                ),
            )
        conn.commit()
    record_audit_event(
        action="rubric.imported",
        outcome="success",
        request=request,
        actor=user,
        target_type="rubric",
        target_id=f"{body.rubricId}:{body.version}",
        metadata={"criteria_count": len(body.criteria)},
    )
    return {
        "rubric_id": body.rubricId,
        "version": body.version,
        "genre": body.genre,
        "notes": body.notes,
        "is_custom": True,
    }


@router.get("/{rubric_id}/{version}")
def get_rubric(rubric_id: str, version: str, user: CurrentUser = Depends(get_current_user)):
    with get_connection() as conn:
        rubric = conn.execute(
            """SELECT * FROM rubrics
               WHERE rubric_id = ? AND version = ?
                 AND (owner_instructor_id IS NULL OR owner_instructor_id = ?)""",
            (rubric_id, version, user.instructor_id),
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
        "assignmentGuidance": rubric["assignment_guidance"],
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
