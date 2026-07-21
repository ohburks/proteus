"""Grading trigger + output grade retrieval (design doc §7)."""
import json
import threading
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.auth import CurrentUser, get_current_user
from app.db import get_connection
from app.grading import progress
from app.grading.engine import run_dual_path_for_criterion
from app.llm.key_resolution import resolve_provider_config
from app.llm.providers import build_client
from app.schemas import GradeRequest

router = APIRouter(prefix="/api/assessments", tags=["assessments"])


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _run_assessment(assessment_id: str, client, criteria_rows_dicts, assignment_dict, essay_text, instructor_id):
    with get_connection() as conn:
        try:
            for c in criteria_rows_dicts:
                criterion = {
                    "criterionId": c["criterion_id"],
                    "statement": c["statement"],
                    "anchors": json.loads(c["anchors_json"]),
                }
                run_dual_path_for_criterion(
                    conn, client,
                    assessment_id=assessment_id, criterion=criterion,
                    rubric_id=assignment_dict["rubric_id"], rubric_version=assignment_dict["rubric_version"],
                    essay_text=essay_text, assignment_id=assignment_dict["id"],
                    instructor_id=instructor_id, course_id=assignment_dict["course_id"],
                    emit=lambda msg, aid=assessment_id: progress.emit(aid, msg),
                )
            conn.execute("UPDATE assessments SET status = 'complete' WHERE id = ?", (assessment_id,))
            conn.commit()
            progress.emit(assessment_id, "Assessment complete.")
            progress.finish(assessment_id, "complete")
        except Exception as e:
            conn.execute("UPDATE assessments SET status = 'failed' WHERE id = ?", (assessment_id,))
            conn.commit()
            progress.emit(assessment_id, f"Assessment FAILED: {e}")
            progress.finish(assessment_id, "failed")


@router.post("")
def start_assessment(body: GradeRequest, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    byok = body.byok
    config = resolve_provider_config(
        byok_provider=byok.provider if byok else None,
        byok_key=byok.api_key if byok else None,
        byok_model=byok.model if byok else None,
        byok_base_url=byok.base_url if byok else None,
    )
    client = build_client(config)

    with get_connection() as conn:
        essay = conn.execute("SELECT * FROM essays WHERE id = ?", (body.essay_id,)).fetchone()
        if essay is None:
            raise HTTPException(404, "Essay not found")
        assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (essay["assignment_id"],)).fetchone()
        course = conn.execute("SELECT * FROM courses WHERE id = ?", (assignment["course_id"],)).fetchone()
        if course["instructor_id"] != instructor_id:
            raise HTTPException(403, "Not your assignment")

        criteria_rows = conn.execute(
            "SELECT * FROM criteria WHERE rubric_id = ? AND rubric_version = ?",
            (assignment["rubric_id"], assignment["rubric_version"]),
        ).fetchall()
        if not criteria_rows:
            raise HTTPException(400, "Rubric has no criteria loaded")

        assessment_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO assessments
               (id, essay_id, instructor_id, student_id, rubric_id, rubric_version, provider, model, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                assessment_id, body.essay_id, instructor_id, essay["student_id"],
                assignment["rubric_id"], assignment["rubric_version"], config.provider, config.model,
                "running", _now(),
            ),
        )
        conn.commit()

        # Snapshot everything the background thread needs — it opens its own
        # sqlite connection rather than sharing this request's connection.
        criteria_rows_dicts = [dict(c) for c in criteria_rows]
        assignment_dict = dict(assignment)
        essay_text = essay["text"]

    progress.start(assessment_id)
    progress.emit(assessment_id, f"Assessment started — provider={config.provider} model={config.model}, {len(criteria_rows_dicts)} criteria")
    thread = threading.Thread(
        target=_run_assessment,
        args=(assessment_id, client, criteria_rows_dicts, assignment_dict, essay_text, instructor_id),
        daemon=True,
    )
    thread.start()

    return {"id": assessment_id, "status": "running"}


@router.get("/{assessment_id}/stream")
def stream_assessment_progress(assessment_id: str, user: CurrentUser = Depends(get_current_user)):
    """Live grading terminal feed (SSE) — TESTING ONLY.

    In-memory only (see app.grading.progress): dev/demo aid, not a durable
    audit trail and not safe to rely on with multiple server workers.
    """
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        assessment = conn.execute("SELECT * FROM assessments WHERE id = ?", (assessment_id,)).fetchone()
        if assessment is None or assessment["instructor_id"] != instructor_id:
            raise HTTPException(404, "Assessment not found")
    return StreamingResponse(
        progress.stream(assessment_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("")
def list_assessments(essay_id: str, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, status, created_at FROM assessments WHERE essay_id = ? AND instructor_id = ? ORDER BY created_at DESC",
            (essay_id, instructor_id),
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/{assessment_id}")
def get_assessment(assessment_id: str, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        assessment = conn.execute("SELECT * FROM assessments WHERE id = ?", (assessment_id,)).fetchone()
        if assessment is None or assessment["instructor_id"] != instructor_id:
            raise HTTPException(404, "Assessment not found")

        criteria_ids = [
            r["criterion_id"] for r in conn.execute(
                "SELECT DISTINCT criterion_id FROM score_records_v2 WHERE assessment_id = ?", (assessment_id,)
            ).fetchall()
        ]
        results = []
        for cid in criteria_ids:
            personalized = conn.execute(
                "SELECT * FROM score_records_v2 WHERE assessment_id = ? AND criterion_id = ? AND path = 'personalized'",
                (assessment_id, cid),
            ).fetchone()
            override = conn.execute(
                "SELECT * FROM score_overrides WHERE assessment_id = ? AND criterion_id = ?", (assessment_id, cid)
            ).fetchone()
            divergence = conn.execute(
                "SELECT * FROM divergence_records WHERE assessment_id = ? AND criterion_id = ?", (assessment_id, cid)
            ).fetchone()
            output_score = override["new_score"] if override else personalized["score"]
            results.append({
                "criterion_id": cid,
                "output_score": output_score,
                "output_source": "override" if override else "personalized",
                "exceeds_threshold": bool(divergence["exceeds_threshold"]) if divergence else False,
            })
    return {"id": assessment["id"], "status": assessment["status"], "criteria": results}
