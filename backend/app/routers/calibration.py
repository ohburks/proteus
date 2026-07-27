"""Assignment-level professor examples and calibration readiness."""
from fastapi import APIRouter, Depends, HTTPException, Request

from app.audit import record_audit_event
from app.auth import CurrentUser, get_current_user
from app.db import get_connection
from app.repositories.calibration import (
    delete_calibration_example,
    insert_calibration_example,
)
from app.schemas import CalibrationExampleCreate

router = APIRouter(
    prefix="/api/assignments/{assignment_id}/calibration-examples",
    tags=["calibration"],
)

MIN_READY_EXAMPLES = 3


def _owned_assignment(conn, assignment_id: str, instructor_id: str):
    row = conn.execute(
        """SELECT a.*, c.instructor_id
           FROM assignments a
           JOIN courses c ON c.id = a.course_id
           WHERE a.id = ?""",
        (assignment_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Assignment not found")
    if row["instructor_id"] != instructor_id:
        raise HTTPException(403, "Not your assignment")
    return row


def _calibration_payload(conn, assignment) -> dict:
    example_rows = conn.execute(
        """SELECT e.id, e.name, e.source, e.source_assessment_id,
                  length(e.essay_text) AS character_count,
                  CASE WHEN length(e.essay_text) > 220
                       THEN substr(e.essay_text, 1, 220) || '…'
                       ELSE e.essay_text END AS text_preview,
                  e.created_at, e.updated_at
           FROM calibration_examples e
           WHERE e.assignment_id = ?
           ORDER BY e.updated_at DESC, e.id DESC""",
        (assignment["id"],),
    ).fetchall()
    score_rows = conn.execute(
        """SELECT s.* FROM calibration_example_scores s
           JOIN calibration_examples e ON e.id = s.example_id
           WHERE e.assignment_id = ?
           ORDER BY s.criterion_id, s.score, s.example_id""",
        (assignment["id"],),
    ).fetchall()
    scores_by_example: dict[str, list[dict]] = {row["id"]: [] for row in example_rows}
    for row in score_rows:
        scores_by_example.setdefault(row["example_id"], []).append(
            {
                "criterion_id": row["criterion_id"],
                "score": row["score"],
                "rationale": row["rationale"],
            }
        )

    criteria = conn.execute(
        """SELECT criterion_id FROM criteria
           WHERE rubric_id = ? AND rubric_version = ?
           ORDER BY criterion_id""",
        (assignment["rubric_id"], assignment["rubric_version"]),
    ).fetchall()
    criterion_coverage = []
    for criterion in criteria:
        criterion_id = criterion["criterion_id"]
        rows = [row for row in score_rows if row["criterion_id"] == criterion_id]
        distinct_scores = sorted({row["score"] for row in rows})
        criterion_coverage.append(
            {
                "criterion_id": criterion_id,
                "n_examples": len(rows),
                "scores_present": distinct_scores,
                "ready": len(rows) >= MIN_READY_EXAMPLES and len(distinct_scores) >= 2,
            }
        )

    feedback = conn.execute(
        """SELECT
             COUNT(*) AS n_reviewed,
             SUM(CASE WHEN f.action = 'approved' THEN 1 ELSE 0 END) AS n_approved,
             SUM(CASE WHEN f.action = 'overridden' THEN 1 ELSE 0 END) AS n_overridden,
             AVG(CASE WHEN f.action = 'overridden' AND f.model_score IS NOT NULL
                      THEN abs(f.professor_score - f.model_score) END) AS mean_abs_adjustment
           FROM grading_feedback f
           JOIN assessments ass ON ass.id = f.assessment_id
           JOIN essays e ON e.id = ass.essay_id
           WHERE e.assignment_id = ?""",
        (assignment["id"],),
    ).fetchone()
    n_reviewed = feedback["n_reviewed"] or 0
    n_approved = feedback["n_approved"] or 0

    return {
        "examples": [
            {
                **dict(row),
                "scores": scores_by_example.get(row["id"], []),
            }
            for row in example_rows
        ],
        "n_examples": len(example_rows),
        "criteria": criterion_coverage,
        "ready": bool(criterion_coverage) and all(item["ready"] for item in criterion_coverage),
        "minimum_recommended_examples": MIN_READY_EXAMPLES,
        "feedback": {
            "n_reviewed": n_reviewed,
            "n_approved": n_approved,
            "n_overridden": feedback["n_overridden"] or 0,
            "acceptance_rate": n_approved / n_reviewed if n_reviewed else None,
            "mean_abs_adjustment": feedback["mean_abs_adjustment"],
        },
    }


@router.get("")
def list_calibration_examples(
    assignment_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        assignment = _owned_assignment(conn, assignment_id, instructor_id)
        return _calibration_payload(conn, assignment)


@router.post("")
def create_calibration_example(
    assignment_id: str,
    body: CalibrationExampleCreate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        assignment = _owned_assignment(conn, assignment_id, instructor_id)
        expected = {
            row["criterion_id"]
            for row in conn.execute(
                """SELECT criterion_id FROM criteria
                   WHERE rubric_id = ? AND rubric_version = ?""",
                (assignment["rubric_id"], assignment["rubric_version"]),
            )
        }
        supplied = {item.criterion_id for item in body.scores}
        if supplied != expected:
            missing = sorted(expected - supplied)
            unknown = sorted(supplied - expected)
            details = []
            if missing:
                details.append(f"missing criteria: {', '.join(missing)}")
            if unknown:
                details.append(f"unknown criteria: {', '.join(unknown)}")
            raise HTTPException(422, "; ".join(details))
        example_id = insert_calibration_example(
            conn,
            assignment_id=assignment_id,
            instructor_id=instructor_id,
            name=body.name,
            essay_text=body.essay_text,
            scores=[item.model_dump() for item in body.scores],
        )
        conn.commit()
        payload = _calibration_payload(conn, assignment)
    record_audit_event(
        action="calibration_example.created",
        outcome="success",
        request=request,
        actor=user,
        target_type="calibration_example",
        target_id=example_id,
        metadata={"assignment_id": assignment_id, "criteria_count": len(body.scores)},
    )
    return {"id": example_id, **payload}


@router.delete("/{example_id}")
def remove_calibration_example(
    assignment_id: str,
    example_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        assignment = _owned_assignment(conn, assignment_id, instructor_id)
        row = conn.execute(
            """SELECT * FROM calibration_examples
               WHERE id = ? AND assignment_id = ?""",
            (example_id, assignment_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Calibration example not found")
        delete_calibration_example(conn, example_id)
        conn.commit()
        payload = _calibration_payload(conn, assignment)
    record_audit_event(
        action="calibration_example.deleted",
        outcome="success",
        request=request,
        actor=user,
        target_type="calibration_example",
        target_id=example_id,
        metadata={"assignment_id": assignment_id, "name": row["name"]},
    )
    return payload
