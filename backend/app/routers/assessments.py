"""Grading trigger + output grade retrieval (design doc §7)."""
import json
import re
import sqlite3
import threading
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse

from app import chroma_store
from app.audit import record_audit_event
from app.auth import CurrentUser, get_current_user
from app.db import get_connection, write_with_retry
from app.pdf_report import build_assessment_pdf
from app.grading import cancellation, progress
from app.grading.engine import criteria_batch_size, run_calibrated_for_criteria_batch
from app.grading.relevance import run_relevance_check
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
            if cancellation.is_cancelled(assessment_id):
                _mark_cancelled(conn, assessment_id)
                return
            relevance = run_relevance_check(
                conn,
                client,
                assessment_id=assessment_id,
                assignment_id=assignment_dict["id"],
                essay_text=essay_text,
                emit=lambda msg, aid=assessment_id: progress.emit(aid, msg),
            )
            if cancellation.is_cancelled(assessment_id):
                _mark_cancelled(conn, assessment_id)
                return
            if relevance.decision != "grade":
                progress.emit(
                    assessment_id,
                    "Relevance check flagged this submission; continuing rubric grading.",
                )

            prepared_criteria = [
                {
                    "criterionId": row["criterion_id"],
                    "statement": row["statement"],
                    "anchors": json.loads(row["anchors_json"]),
                }
                for row in criteria_rows_dicts
            ]
            batch_size = criteria_batch_size()
            # The relevance check above is a distinct, non-RAG provider call and
            # shares no grading prompt. Its decision is advisory: retrieval and
            # rubric grading continue for every outcome.
            query_embedding = chroma_store.embed_text(essay_text)
            for start in range(0, len(prepared_criteria), batch_size):
                # Cancellation is checked between batches (not mid-provider call): an
                # in-flight LLM call can't be interrupted, but the loop stops before
                # starting the next batch. Completed batches stay checkpointed.
                if cancellation.is_cancelled(assessment_id):
                    _mark_cancelled(conn, assessment_id)
                    return
                run_calibrated_for_criteria_batch(
                    conn, client,
                    assessment_id=assessment_id,
                    criteria=prepared_criteria[start:start + batch_size],
                    rubric_id=assignment_dict["rubric_id"], rubric_version=assignment_dict["rubric_version"],
                    essay_text=essay_text, assignment_id=assignment_dict["id"],
                    instructor_id=instructor_id, course_id=assignment_dict["course_id"],
                    query_embedding=query_embedding,
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
def start_assessment(
    body: GradeRequest,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
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
    record_audit_event(
        action="grading.started",
        outcome="success",
        request=request,
        actor=user,
        target_type="assessment",
        target_id=assessment_id,
        metadata={
            "essay_id": essay["id"],
            "assignment_id": assignment["id"],
            "provider": config.provider,
            "model": config.model,
            "criteria_count": len(criteria_rows_dicts),
        },
    )
    return {"id": assessment_id, "status": "running"}


@router.post("/{assessment_id}/cancel")
def cancel_assessment(
    assessment_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
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
    record_audit_event(
        action="grading.cancel_requested",
        outcome="success",
        request=request,
        actor=user,
        target_type="assessment",
        target_id=assessment_id,
        metadata={"previous_status": assessment["status"]},
    )
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
def list_assessments(
    essay_id: str,
    user: CurrentUser = Depends(get_current_user),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, status, created_at FROM assessments "
            "WHERE essay_id = ? AND instructor_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (essay_id, instructor_id, limit, offset),
        ).fetchall()
    return [dict(r) for r in rows]


def _criterion_outputs(conn, assessment) -> list[dict]:
    """Load every criterion output for an assessment in one joined query."""
    rows = conn.execute(
        """WITH criterion_ids AS (
             SELECT DISTINCT criterion_id
             FROM score_aggregates
             WHERE assessment_id = ?
           )
           SELECT
             ids.criterion_id,
             p.score AS personalized_score,
             p.is_no_evidence AS personalized_no_evidence,
             p.evidence_json AS personalized_evidence_json,
             p.high_spread AS personalized_high_spread,
             x.assessment_id AS exemplar_assessment_id,
             x.high_spread AS exemplar_high_spread,
             o.new_score AS override_score,
             d.exceeds_threshold,
             c.referenceability
           FROM criterion_ids ids
           LEFT JOIN score_aggregates p
             ON p.assessment_id = ? AND p.criterion_id = ids.criterion_id AND p.path = 'personalized'
           LEFT JOIN score_aggregates x
             ON x.assessment_id = ? AND x.criterion_id = ids.criterion_id AND x.path = 'exemplar'
           LEFT JOIN score_overrides o
             ON o.assessment_id = ? AND o.criterion_id = ids.criterion_id
           LEFT JOIN divergence_records d
             ON d.assessment_id = ? AND d.criterion_id = ids.criterion_id
           LEFT JOIN criteria c
             ON c.rubric_id = ?
            AND c.rubric_version = ?
            AND c.criterion_id = ids.criterion_id
           ORDER BY ids.criterion_id""",
        (
            assessment["id"],
            assessment["id"],
            assessment["id"],
            assessment["id"],
            assessment["id"],
            assessment["rubric_id"],
            assessment["rubric_version"],
        ),
    ).fetchall()
    outputs = []
    for row in rows:
        if row["override_score"] is not None:
            output_score, output_source = row["override_score"], "override"
        elif row["personalized_score"] is not None or row["personalized_no_evidence"]:
            output_score = row["personalized_score"]
            output_source = (
                "personalized" if row["exemplar_assessment_id"] is not None else "calibrated"
            )
        else:
            output_score, output_source = None, "incomplete"
        exceeds_threshold = bool(row["exceeds_threshold"])
        high_spread = bool(row["personalized_high_spread"] or row["exemplar_high_spread"])
        unsupported_evidence = bool(
            row["personalized_evidence_json"]
            and not row["personalized_no_evidence"]
            and json.loads(row["personalized_evidence_json"]) == []
        )
        review_reasons = [
            reason for reason, present in [
                ("divergent", exceeds_threshold),
                ("high_spread", high_spread),
                ("weak_referenceability", row["referenceability"] == "weak"),
                ("unsupported_evidence", unsupported_evidence),
            ] if present
        ]
        outputs.append({
            "criterion_id": row["criterion_id"],
            "output_score": output_score,
            "output_source": output_source,
            "exceeds_threshold": exceeds_threshold,
            "high_spread": high_spread,
            "needs_review": bool(review_reasons),
            "review_reasons": review_reasons,
        })
    return outputs


def _relevance_output(conn, assessment_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM relevance_checks WHERE assessment_id = ?",
        (assessment_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "decision": row["decision"],
        "submission_type": row["submission_type"],
        "responds_to_prompt": bool(row["responds_to_prompt"]),
        "has_sufficient_content": bool(row["has_sufficient_content"]),
        "rationale": row["rationale"],
        "evidence": json.loads(row["evidence_json"]),
        "created_at": row["created_at"],
    }


@router.get("/{assessment_id}")
def get_assessment(assessment_id: str, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        assessment = conn.execute("SELECT * FROM assessments WHERE id = ?", (assessment_id,)).fetchone()
        if assessment is None or assessment["instructor_id"] != instructor_id:
            raise HTTPException(404, "Assessment not found")

        results = _criterion_outputs(conn, assessment)
        relevance = _relevance_output(conn, assessment_id)
        essay = conn.execute(
            "SELECT assignment_id FROM essays WHERE id = ?", (assessment["essay_id"],)
        ).fetchone()
    return {
        "id": assessment["id"], "assignment_id": essay["assignment_id"], "status": assessment["status"],
        "rubric_id": assessment["rubric_id"], "rubric_version": assessment["rubric_version"],
        "relevance_check": relevance, "criteria": results,
    }


def _safe_filename(name: str) -> str:
    """Keep the download filename to a safe, header-injection-proof charset."""
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip().strip(".")
    return cleaned or "grade_report.pdf"


@router.get("/{assessment_id}/report.pdf")
def download_assessment_report(assessment_id: str, user: CurrentUser = Depends(get_current_user)):
    """Full grade report — the original essay plus every criterion's result — as
    a downloadable PDF (assembled here, rendered by app.pdf_report)."""
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        assessment = conn.execute("SELECT * FROM assessments WHERE id = ?", (assessment_id,)).fetchone()
        if assessment is None or assessment["instructor_id"] != instructor_id:
            raise HTTPException(404, "Assessment not found")

        essay = conn.execute("SELECT * FROM essays WHERE id = ?", (assessment["essay_id"],)).fetchone()
        assignment = (
            conn.execute("SELECT * FROM assignments WHERE id = ?", (essay["assignment_id"],)).fetchone()
            if essay else None
        )
        student = (
            conn.execute("SELECT * FROM students WHERE id = ?", (essay["student_id"],)).fetchone()
            if essay and essay["student_id"] else None
        )

        # Rubric criteria give each output its statement + dimension (and the
        # dimension grouping/order used in the report and the results UI).
        crit_rows = conn.execute(
            "SELECT criterion_id, dimension, statement FROM criteria WHERE rubric_id=? AND rubric_version=?",
            (assessment["rubric_id"], assessment["rubric_version"]),
        ).fetchall()
        meta_by_id = {r["criterion_id"]: r for r in crit_rows}
        dim_order = list(dict.fromkeys(r["dimension"] for r in crit_rows))

        outputs = {o["criterion_id"]: o for o in _criterion_outputs(conn, assessment)}
        detail = {}
        for cid in outputs:
            p = conn.execute(
                "SELECT score, rationale, evidence_json, is_no_evidence FROM score_aggregates "
                "WHERE assessment_id=? AND criterion_id=? AND path='personalized'",
                (assessment_id, cid),
            ).fetchone()
            x = conn.execute(
                "SELECT score, is_no_evidence FROM score_aggregates "
                "WHERE assessment_id=? AND criterion_id=? AND path='exemplar'",
                (assessment_id, cid),
            ).fetchone()
            d = conn.execute(
                "SELECT score_diff FROM divergence_records WHERE assessment_id=? AND criterion_id=?",
                (assessment_id, cid),
            ).fetchone()
            o = conn.execute(
                "SELECT new_score, new_rationale FROM score_overrides WHERE assessment_id=? AND criterion_id=?",
                (assessment_id, cid),
            ).fetchone()
            detail[cid] = {
                "legacy_dual_path": x is not None,
                "personalized_score": None if (p is None or p["is_no_evidence"]) else p["score"],
                "exemplar_score": None if (x is None or x["is_no_evidence"]) else x["score"],
                "score_diff": d["score_diff"] if d else None,
                "rationale": p["rationale"] if p else None,
                "evidence": json.loads(p["evidence_json"]) if p and p["evidence_json"] else [],
                "override": {"new_score": o["new_score"], "new_rationale": o["new_rationale"]} if o else None,
            }
        essay_text = essay["text"] if essay else ""

    def _row(cid: str) -> dict:
        out = outputs[cid]
        return {
            "criterion_id": cid,
            "statement": meta_by_id[cid]["statement"] if cid in meta_by_id else None,
            **out,
            **detail[cid],
        }

    dims, seen = [], set()
    for dim in dim_order:
        crits = [_row(r["criterion_id"]) for r in crit_rows if r["dimension"] == dim and r["criterion_id"] in outputs]
        if crits:
            dims.append({"dimension": dim, "criteria": crits})
            seen.update(c["criterion_id"] for c in crits)
    leftover = [_row(cid) for cid in outputs if cid not in seen]
    if leftover:
        dims.append({"dimension": "Other", "criteria": leftover})

    scores = [o["output_score"] for o in outputs.values() if o["output_score"] is not None]
    student_name = student["display_name"] if student else "Unlinked essay"
    report = {
        "title": "Grade Report",
        "assignment_name": assignment["name"] if assignment else None,
        "student_name": student_name,
        "external_ref": student["external_ref"] if student else None,
        "rubric": f"{assessment['rubric_id']} v{assessment['rubric_version']}",
        "status": assessment["status"],
        "provider": assessment["provider"],
        "model": assessment["model"],
        "created_at": assessment["created_at"],
        "avg_score": (sum(scores) / len(scores)) if scores else None,
        "n_criteria": len(scores),
        "essay_text": essay_text,
        "dimensions": dims,
    }
    pdf = build_assessment_pdf(report)
    filename = _safe_filename(f"{student_name}_{assignment['name'] if assignment else 'essay'}_grade_report.pdf")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
