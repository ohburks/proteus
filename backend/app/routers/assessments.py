"""Grading trigger + output grade retrieval (design doc §7)."""
import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.auth import CurrentUser, get_current_user
from app.db import get_connection, write_with_retry
from app.grading import cancellation, progress
from app.grading.engine import run_dual_path_for_criterion
from app.llm.key_resolution import KeyResolutionError, resolve_provider_config
from app.llm.providers import build_client, check_api_key
from app.schemas import BYOKConfig, GradeRequest

router = APIRouter(prefix="/api/assessments", tags=["assessments"])


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _grading_error_detail(e: KeyResolutionError) -> str:
    """Rewrite the "nothing configured anywhere" resolver message into
    something Settings-actionable (M10). Every other KeyResolutionError
    (unsupported provider, a misconfigured server .env) isn't fixable by an
    instructor via Settings, so those pass through unchanged."""
    if str(e).startswith("No LLM provider configured"):
        return "No LLM provider configured."
    return str(e)


def _mark_cancelled(conn, assessment_id: str) -> None:
    """Roll back any partial work and move the run to a terminal 'cancelled'
    state. Only the grading thread ever writes a terminal status, so this can't
    race the cancel endpoint (which only sets the in-memory flag)."""
    try:
        conn.rollback()
    except sqlite3.Error:
        pass
    try:
        write_with_retry(
            conn, lambda: conn.execute("UPDATE assessments SET status = 'cancelled' WHERE id = ?", (assessment_id,))
        )
    except sqlite3.Error:
        pass
    progress.emit(assessment_id, "Assessment cancelled.")
    progress.finish(assessment_id, "cancelled")


def _run_assessment(assessment_id: str, client, criteria_rows_dicts, assignment_dict, essay_text, instructor_id):
    with get_connection() as conn:
        try:
            for c in criteria_rows_dicts:
                # Cancellation is checked between criteria (not mid-criterion): an
                # in-flight LLM call can't be interrupted, but the loop stops before
                # starting the next one. Completed criteria stay checkpointed.
                if cancellation.is_cancelled(assessment_id):
                    _mark_cancelled(conn, assessment_id)
                    return
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
            # A cancel that lands after the last criterion but before the complete
            # write still wins — don't report a run the instructor asked to stop
            # as complete.
            if cancellation.is_cancelled(assessment_id):
                _mark_cancelled(conn, assessment_id)
                return
            write_with_retry(
                conn, lambda: conn.execute("UPDATE assessments SET status = 'complete' WHERE id = ?", (assessment_id,))
            )
            progress.emit(assessment_id, "Assessment complete.")
            progress.finish(assessment_id, "complete")
        except Exception as e:
            # Discard any half-written transaction from the failed criterion,
            # then mark failed — with retry so the status update itself can't die
            # on a transient lock (which would leave the row stuck 'running').
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            try:
                write_with_retry(
                    conn, lambda: conn.execute("UPDATE assessments SET status = 'failed' WHERE id = ?", (assessment_id,))
                )
            except sqlite3.Error:
                pass
            progress.emit(assessment_id, f"Assessment FAILED: {e}")
            progress.finish(assessment_id, "failed")
        finally:
            # Drop the flag whether the run cancelled, completed, or failed, so a
            # late cancel for this id can't linger and clip a future run that
            # happens to reuse it (ids are UUIDs, so this is belt-and-suspenders).
            cancellation.clear(assessment_id)


def _launch_assessment(essay_row, assignment_dict, criteria_rows_dicts, config, client, instructor_id) -> str:
    """Insert an assessments row (status='running'), snapshot state, and spawn
    the background grading thread. Opens its own connection so callers looping
    over many essays (bulk grading) don't share a connection across the batch."""
    assessment_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO assessments
               (id, essay_id, instructor_id, student_id, rubric_id, rubric_version, provider, model, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                assessment_id, essay_row["id"], instructor_id, essay_row["student_id"],
                assignment_dict["rubric_id"], assignment_dict["rubric_version"], config.provider, config.model,
                "running", _now(),
            ),
        )
        conn.commit()
        essay_text = essay_row["text"]

    progress.start(assessment_id)
    progress.emit(assessment_id, f"Assessment started — provider={config.provider} model={config.model}, {len(criteria_rows_dicts)} criteria")
    thread = threading.Thread(
        target=_run_assessment,
        args=(assessment_id, client, criteria_rows_dicts, assignment_dict, essay_text, instructor_id),
        daemon=True,
    )
    thread.start()
    return assessment_id


@router.post("/validate-byok")
def validate_byok(body: BYOKConfig, user: CurrentUser = Depends(get_current_user)):
    """Live check of a BYOK provider/key pair for the grading form's key
    indicator. Resolves the config the same way grading would (so a missing
    key or unknown provider reports invalid, and blank provider validates the
    server default), then makes a token-free authenticated call."""
    try:
        config = resolve_provider_config(
            byok_provider=body.provider, byok_key=body.api_key,
            byok_model=body.model, byok_base_url=body.base_url,
        )
    except KeyResolutionError as e:
        return {"valid": False, "detail": str(e)}
    valid, detail = check_api_key(config)
    return {"valid": valid, "detail": detail}


@router.post("")
def start_assessment(body: GradeRequest, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    byok = body.byok
    # A missing/misconfigured provider (no BYOK given and no server default set)
    # is a client-actionable error, not a server fault — return 400 with the
    # resolver's own message instead of letting it surface as a 500.
    try:
        config = resolve_provider_config(
            byok_provider=byok.provider if byok else None,
            byok_key=byok.api_key if byok else None,
            byok_model=byok.model if byok else None,
            byok_base_url=byok.base_url if byok else None,
        )
    except KeyResolutionError as e:
        raise HTTPException(400, _grading_error_detail(e)) from e
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

        criteria_rows_dicts = [dict(c) for c in criteria_rows]
        assignment_dict = dict(assignment)

    assessment_id = _launch_assessment(essay, assignment_dict, criteria_rows_dicts, config, client, instructor_id)
    return {"id": assessment_id, "status": "running"}


@router.post("/{assessment_id}/cancel")
def cancel_assessment(assessment_id: str, user: CurrentUser = Depends(get_current_user)):
    """Request cancellation of an in-progress grading run.

    Only signals the run's in-memory flag; the grading thread owns the terminal
    status transition (it flips the row to 'cancelled' before its next criterion).
    Doing it that way avoids racing the thread — if the endpoint wrote the status
    itself, a criterion finishing at the same moment could overwrite it. So the
    response is 'cancelling', not 'cancelled': the row lands in 'cancelled' once
    the thread reaches its next checkpoint (it can't interrupt an in-flight LLM
    call, so a run stuck in one call stops only when that call returns)."""
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        assessment = conn.execute("SELECT * FROM assessments WHERE id = ?", (assessment_id,)).fetchone()
        if assessment is None or assessment["instructor_id"] != instructor_id:
            raise HTTPException(404, "Assessment not found")
        if assessment["status"] not in ("running", "pending"):
            # Already terminal (complete/failed/cancelled) — nothing to stop.
            raise HTTPException(409, f"Assessment is not in progress (status: {assessment['status']})")
    cancellation.request(assessment_id)
    progress.emit(assessment_id, "Cancellation requested — stopping after the current criterion…")
    return {"id": assessment_id, "status": "cancelling"}


@router.get("/{assessment_id}/stream")
def stream_assessment_progress(assessment_id: str, request: Request, user: CurrentUser = Depends(get_current_user)):
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
        progress.stream(assessment_id, request),
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


def _criterion_output(conn, assessment_id: str, criterion_id: str) -> dict:
    personalized = conn.execute(
        "SELECT * FROM score_aggregates WHERE assessment_id = ? AND criterion_id = ? AND path = 'personalized'",
        (assessment_id, criterion_id),
    ).fetchone()
    exemplar = conn.execute(
        "SELECT * FROM score_aggregates WHERE assessment_id = ? AND criterion_id = ? AND path = 'exemplar'",
        (assessment_id, criterion_id),
    ).fetchone()
    override = conn.execute(
        "SELECT * FROM score_overrides WHERE assessment_id = ? AND criterion_id = ?", (assessment_id, criterion_id)
    ).fetchone()
    divergence = conn.execute(
        "SELECT * FROM divergence_records WHERE assessment_id = ? AND criterion_id = ?", (assessment_id, criterion_id)
    ).fetchone()
    # A criterion can have one path's aggregate without the other: the engine
    # persists exemplar before personalized, and a failure in between still
    # commits the partial rows via the failed-status commit. Guard rather
    # than 500 on such criteria.
    if override:
        output_score, output_source = override["new_score"], "override"
    elif personalized:
        output_score, output_source = personalized["score"], "personalized"
    else:
        output_score, output_source = None, "incomplete"

    exceeds_threshold = bool(divergence["exceeds_threshold"]) if divergence else False
    # High spread is an additive signal, separate from divergence: it flags a
    # path that wasn't consistent with its own repeated passes, not
    # disagreement between the two paths.
    high_spread = bool(personalized and personalized["high_spread"]) or bool(exemplar and exemplar["high_spread"])

    # needs_review (B3, soft flag — doesn't affect output_score or grading
    # completion, purely a "an instructor should look at this" signal):
    # weak-referenceability criteria are the rubric's own documented
    # teacher-reserve routing (H3), and an evidence-empty score is D1's gap
    # made visible instead of silently indistinguishable from a well-
    # evidenced one.
    assessment_row = conn.execute(
        "SELECT rubric_id, rubric_version FROM assessments WHERE id = ?", (assessment_id,)
    ).fetchone()
    criterion_row = conn.execute(
        "SELECT referenceability FROM criteria WHERE rubric_id = ? AND rubric_version = ? AND criterion_id = ?",
        (assessment_row["rubric_id"], assessment_row["rubric_version"], criterion_id),
    ).fetchone()
    weak_referenceability = bool(criterion_row and criterion_row["referenceability"] == "weak")
    unsupported_evidence = bool(
        personalized and not personalized["is_no_evidence"] and json.loads(personalized["evidence_json"]) == []
    )
    review_reasons = [
        reason for reason, present in [
            ("divergent", exceeds_threshold), ("high_spread", high_spread),
            ("weak_referenceability", weak_referenceability), ("unsupported_evidence", unsupported_evidence),
        ] if present
    ]

    return {
        "output_score": output_score,
        "output_source": output_source,
        "exceeds_threshold": exceeds_threshold,
        "high_spread": high_spread,
        "needs_review": bool(review_reasons),
        "review_reasons": review_reasons,
    }


@router.get("/{assessment_id}")
def get_assessment(assessment_id: str, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        assessment = conn.execute("SELECT * FROM assessments WHERE id = ?", (assessment_id,)).fetchone()
        if assessment is None or assessment["instructor_id"] != instructor_id:
            raise HTTPException(404, "Assessment not found")

        criteria_ids = [
            r["criterion_id"] for r in conn.execute(
                "SELECT DISTINCT criterion_id FROM score_aggregates WHERE assessment_id = ?", (assessment_id,)
            ).fetchall()
        ]
        results = [
            {"criterion_id": cid, **_criterion_output(conn, assessment_id, cid)}
            for cid in criteria_ids
        ]
    return {
        "id": assessment["id"], "status": assessment["status"],
        "rubric_id": assessment["rubric_id"], "rubric_version": assessment["rubric_version"],
        "criteria": results,
    }
