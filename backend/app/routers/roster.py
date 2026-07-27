"""Courses, assignments, students, essays — the entities everything else
scopes to (design doc §6, §12)."""
import csv
import io
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.audit import record_audit_event
from app.auth import CurrentUser, get_current_user
from app.db import get_connection
from app.document_import import DocumentImportError, MAX_UPLOAD_BYTES, extract_document_text
from app.llm.key_resolution import KeyResolutionError, resolve_provider_config
from app.llm.providers import build_client
from app.repositories.excerpts import delete_personalized_excerpt
from app.routers.assessments import _grading_error_detail, _launch_assessment
from app.schemas import AssignmentCreate, BulkGradeRequest, CourseCreate, EssayCreate, StudentCreate, StudentUpdate

router = APIRouter(prefix="/api", tags=["roster"])


def _now() -> str:
    return datetime.now(UTC).isoformat()


@router.post("/courses")
def create_course(body: CourseCreate, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    course_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO courses (id, instructor_id, name, created_at) VALUES (?,?,?,?)",
            (course_id, instructor_id, body.name, _now()),
        )
        conn.commit()
    return {"id": course_id, "instructor_id": instructor_id, "name": body.name}


@router.get("/courses")
def list_courses(
    user: CurrentUser = Depends(get_current_user),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    with get_connection() as conn:
        if user.role == "admin":
            rows = conn.execute(
                "SELECT * FROM courses ORDER BY created_at DESC, id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM courses WHERE instructor_id = ? "
                "ORDER BY created_at DESC, id LIMIT ? OFFSET ?",
                (user.instructor_id, limit, offset),
            ).fetchall()
    return [dict(r) for r in rows]


@router.get("/courses/{course_id}")
def get_course(course_id: str, user: CurrentUser = Depends(get_current_user)):
    with get_connection() as conn:
        row = _assert_course_owned(conn, course_id, user.scoped_instructor_id())
    return dict(row)


@router.delete("/courses/{course_id}")
def delete_course(course_id: str, request: Request, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        course = _assert_course_owned(conn, course_id, instructor_id)

        assignment_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM assignments WHERE course_id = ?", (course_id,)
        ).fetchall()]
        for aid in assignment_ids:
            for eid in _assignment_essay_ids(conn, aid):
                if _essay_has_active_assessment(conn, eid):
                    raise HTTPException(409, "Grading is still in progress for an essay in this course")
        for aid in assignment_ids:
            _delete_assignment_cascade(conn, aid)

        _delete_personalized_excerpts_for_course(conn, course_id)
        conn.execute("DELETE FROM course_profile WHERE course_id = ?", (course_id,))
        conn.execute("DELETE FROM students WHERE course_id = ?", (course_id,))
        conn.execute("DELETE FROM courses WHERE id = ?", (course_id,))
        conn.commit()
    record_audit_event(
        action="course.deleted",
        outcome="success",
        request=request,
        actor=user,
        target_type="course",
        target_id=course_id,
        metadata={"name": course["name"], "assignment_count": len(assignment_ids)},
    )
    return {"status": "ok"}


def _assert_course_owned(conn, course_id: str, instructor_id: str):
    row = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Course not found")
    if row["instructor_id"] != instructor_id:
        raise HTTPException(403, "Not your course")
    return row


def _delete_essay_cascade(conn, essay_id: str) -> None:
    assessment_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM assessments WHERE essay_id = ?", (essay_id,)
    ).fetchall()]
    for aid in assessment_ids:
        conn.execute("DELETE FROM relevance_checks WHERE assessment_id = ?", (aid,))
        conn.execute("DELETE FROM divergence_records WHERE assessment_id = ?", (aid,))
        conn.execute("DELETE FROM score_overrides WHERE assessment_id = ?", (aid,))
        conn.execute("DELETE FROM score_aggregates WHERE assessment_id = ?", (aid,))
        conn.execute("DELETE FROM score_records_v2 WHERE assessment_id = ?", (aid,))
    conn.execute("DELETE FROM assessments WHERE essay_id = ?", (essay_id,))
    conn.execute("DELETE FROM essays WHERE id = ?", (essay_id,))


def _essay_has_active_assessment(conn, essay_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM assessments WHERE essay_id = ? AND status IN ('running','pending') LIMIT 1",
        (essay_id,),
    ).fetchone() is not None


def _assignment_essay_ids(conn, assignment_id: str) -> list[str]:
    return [r["id"] for r in conn.execute(
        "SELECT id FROM essays WHERE assignment_id = ?", (assignment_id,)
    ).fetchall()]


def _delete_personalized_excerpts_for_assignment(conn, assignment_id: str) -> None:
    # D5: route through delete_personalized_excerpt (not a raw DELETE) so the
    # Chroma embedding backing each excerpt is removed too — a raw SQLite
    # delete here leaves a "ghost" embedding that keeps surfacing as
    # retrievable precedent from an assignment the UI no longer shows.
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM personalized_excerpts_src WHERE assignment_id = ?", (assignment_id,)
    ).fetchall()]
    for excerpt_id in ids:
        delete_personalized_excerpt(conn, excerpt_id)


def _delete_personalized_excerpts_for_course(conn, course_id: str) -> None:
    # Same reasoning as _delete_personalized_excerpts_for_assignment above —
    # this is the course-level catch-all for excerpts added without an
    # assignment context; anything assignment-scoped is already gone by the
    # time this runs (delete_course calls _delete_assignment_cascade first).
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM personalized_excerpts_src WHERE course_id = ?", (course_id,)
    ).fetchall()]
    for excerpt_id in ids:
        delete_personalized_excerpt(conn, excerpt_id)


def _delete_assignment_cascade(conn, assignment_id: str) -> None:
    for eid in _assignment_essay_ids(conn, assignment_id):
        _delete_essay_cascade(conn, eid)
    conn.execute("DELETE FROM assignment_profile WHERE assignment_id = ?", (assignment_id,))
    _delete_personalized_excerpts_for_assignment(conn, assignment_id)
    conn.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))


@router.post("/assignments")
def create_assignment(body: AssignmentCreate, user: CurrentUser = Depends(get_current_user)):
    with get_connection() as conn:
        instructor_id = user.scoped_instructor_id()
        _assert_course_owned(conn, body.course_id, instructor_id)
        rubric = conn.execute(
            "SELECT 1 FROM rubrics WHERE rubric_id = ? AND version = ?", (body.rubric_id, body.rubric_version)
        ).fetchone()
        if rubric is None:
            raise HTTPException(400, "Unknown rubric_id/version")
        assignment_id = str(uuid.uuid4())
        now = _now()
        conn.execute(
            "INSERT INTO assignments (id, course_id, name, rubric_id, rubric_version, created_at) VALUES (?,?,?,?,?,?)",
            (assignment_id, body.course_id, body.name, body.rubric_id, body.rubric_version, now),
        )
        conn.execute(
            """INSERT INTO assignment_profile
               (assignment_id, course_id, prompt_text, format_expectations, criterion_emphasis_notes, common_pitfalls, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                assignment_id, body.course_id, body.prompt_text, body.format_expectations,
                body.criterion_emphasis_notes, body.common_pitfalls, now,
            ),
        )
        conn.commit()
    return {"id": assignment_id, "course_id": body.course_id, "name": body.name,
            "rubric_id": body.rubric_id, "rubric_version": body.rubric_version}


@router.get("/assignments")
def list_assignments(
    course_id: str,
    user: CurrentUser = Depends(get_current_user),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    with get_connection() as conn:
        _assert_course_owned(conn, course_id, user.scoped_instructor_id())
        rows = conn.execute(
            "SELECT * FROM assignments WHERE course_id = ? "
            "ORDER BY created_at DESC, id LIMIT ? OFFSET ?",
            (course_id, limit, offset),
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/assignments/{assignment_id}")
def get_assignment(assignment_id: str, user: CurrentUser = Depends(get_current_user)):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Assignment not found")
        _assert_course_owned(conn, row["course_id"], user.scoped_instructor_id())
    return dict(row)


@router.delete("/assignments/{assignment_id}")
def delete_assignment(assignment_id: str, request: Request, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if assignment is None:
            raise HTTPException(404, "Assignment not found")
        _assert_course_owned(conn, assignment["course_id"], instructor_id)
        for eid in _assignment_essay_ids(conn, assignment_id):
            if _essay_has_active_assessment(conn, eid):
                raise HTTPException(409, "Grading is still in progress for an essay in this assignment")
        _delete_assignment_cascade(conn, assignment_id)
        conn.commit()
    record_audit_event(
        action="assignment.deleted",
        outcome="success",
        request=request,
        actor=user,
        target_type="assignment",
        target_id=assignment_id,
        metadata={"name": assignment["name"], "course_id": assignment["course_id"]},
    )
    return {"status": "ok"}


@router.post("/students")
def create_student(body: StudentCreate, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    student_id = str(uuid.uuid4())
    with get_connection() as conn:
        if body.course_id:
            _assert_course_owned(conn, body.course_id, instructor_id)
        conn.execute(
            "INSERT INTO students (id, instructor_id, course_id, display_name, external_ref, status, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (student_id, instructor_id, body.course_id, body.display_name, body.external_ref, "active", _now()),
        )
        conn.commit()
    return {"id": student_id, "instructor_id": instructor_id, "course_id": body.course_id,
            "display_name": body.display_name, "external_ref": body.external_ref, "status": "active"}


@router.get("/students")
def list_students(
    user: CurrentUser = Depends(get_current_user),
    course_id: str | None = None,
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        if course_id:
            rows = conn.execute(
                "SELECT * FROM students WHERE instructor_id = ? AND course_id = ? "
                "ORDER BY created_at, id LIMIT ? OFFSET ?",
                (instructor_id, course_id, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM students WHERE instructor_id = ? "
                "ORDER BY created_at, id LIMIT ? OFFSET ?",
                (instructor_id, limit, offset),
            ).fetchall()
    return [dict(r) for r in rows]


@router.put("/students/{student_id}")
def update_student(student_id: str, body: StudentUpdate, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        if student is None:
            raise HTTPException(404, "Student not found")
        if student["instructor_id"] != instructor_id:
            raise HTTPException(403, "Not your student")
        conn.execute(
            "UPDATE students SET external_ref = ?, status = ? WHERE id = ?",
            (body.external_ref, body.status, student_id),
        )
        conn.commit()
    return {"status": "ok"}


def _latest_criterion_rows(conn, essay_ids: list[str]):
    """One set-based read for latest-assessment criterion output across essays."""
    if not essay_ids:
        return []
    return conn.execute(
        """WITH requested AS (
             SELECT value AS essay_id FROM json_each(?)
           ),
           ranked AS (
             SELECT a.*,
                    ROW_NUMBER() OVER (
                      PARTITION BY a.essay_id ORDER BY a.created_at DESC, a.id DESC
                    ) AS rn
             FROM assessments a
             JOIN requested r ON r.essay_id = a.essay_id
           ),
           latest AS (
             SELECT * FROM ranked WHERE rn = 1
           )
           SELECT
             r.essay_id,
             l.id AS assessment_id,
             l.status,
             rc.decision AS relevance_decision,
             p.criterion_id,
             COALESCE(o.new_score, p.score) AS output_score,
             CASE WHEN o.assessment_id IS NOT NULL THEN 'override' ELSE 'personalized' END AS output_source,
             COALESCE(d.exceeds_threshold, 0) AS exceeds_threshold,
             CASE WHEN COALESCE(p.high_spread, 0) = 1 OR COALESCE(x.high_spread, 0) = 1
                  THEN 1 ELSE 0 END AS high_spread,
             CASE WHEN c.referenceability = 'weak' THEN 1 ELSE 0 END AS weak_referenceability,
             CASE WHEN p.assessment_id IS NOT NULL
                        AND p.is_no_evidence = 0
                        AND json_array_length(p.evidence_json) = 0
                  THEN 1 ELSE 0 END AS unsupported_evidence
           FROM requested r
           LEFT JOIN latest l ON l.essay_id = r.essay_id
           LEFT JOIN relevance_checks rc ON rc.assessment_id = l.id
           LEFT JOIN score_aggregates p
             ON p.assessment_id = l.id AND p.path = 'personalized'
           LEFT JOIN score_aggregates x
             ON x.assessment_id = l.id
            AND x.criterion_id = p.criterion_id
            AND x.path = 'exemplar'
           LEFT JOIN score_overrides o
             ON o.assessment_id = l.id AND o.criterion_id = p.criterion_id
           LEFT JOIN divergence_records d
             ON d.assessment_id = l.id AND d.criterion_id = p.criterion_id
           LEFT JOIN criteria c
             ON c.rubric_id = l.rubric_id
            AND c.rubric_version = l.rubric_version
            AND c.criterion_id = p.criterion_id
           ORDER BY r.essay_id, p.criterion_id""",
        (json.dumps(essay_ids),),
    ).fetchall()


def _criterion_out_from_row(row) -> dict:
    reasons = []
    if row["exceeds_threshold"]:
        reasons.append("divergent")
    if row["high_spread"]:
        reasons.append("high_spread")
    if row["weak_referenceability"]:
        reasons.append("weak_referenceability")
    if row["unsupported_evidence"]:
        reasons.append("unsupported_evidence")
    return {
        "output_score": row["output_score"],
        "output_source": row["output_source"],
        "exceeds_threshold": bool(row["exceeds_threshold"]),
        "high_spread": bool(row["high_spread"]),
        "needs_review": bool(reasons),
        "review_reasons": reasons,
    }


def _essay_grade_summaries(conn, essay_ids: list[str]) -> dict[str, dict]:
    summaries = {
        essay_id: {
            "assessment_id": None,
            "status": None,
            "avg_score": None,
            "n_criteria": 0,
            "n_divergent": 0,
            "n_high_spread": 0,
            "needs_review": False,
            "relevance_decision": None,
        }
        for essay_id in essay_ids
    }
    scores_by_essay: dict[str, list[float]] = {essay_id: [] for essay_id in essay_ids}
    for row in _latest_criterion_rows(conn, essay_ids):
        summary = summaries[row["essay_id"]]
        summary["assessment_id"] = row["assessment_id"]
        summary["status"] = row["status"]
        summary["relevance_decision"] = row["relevance_decision"]
        if row["relevance_decision"] in ("reject", "manual_review"):
            summary["needs_review"] = True
        if row["status"] != "complete" or row["criterion_id"] is None:
            continue
        out = _criterion_out_from_row(row)
        summary["needs_review"] = summary["needs_review"] or out["needs_review"]
        if out["output_score"] is None:
            continue
        scores_by_essay[row["essay_id"]].append(out["output_score"])
        if out["exceeds_threshold"]:
            summary["n_divergent"] += 1
        if out["high_spread"]:
            summary["n_high_spread"] += 1

    for essay_id, scores in scores_by_essay.items():
        if scores:
            summaries[essay_id]["avg_score"] = sum(scores) / len(scores)
            summaries[essay_id]["n_criteria"] = len(scores)
    return summaries


def _essay_grade_summary(conn, essay_id: str) -> dict:
    return _essay_grade_summaries(conn, [essay_id])[essay_id]


@router.get("/students/{student_id}/history")
def get_student_history(
    student_id: str,
    user: CurrentUser = Depends(get_current_user),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        if student is None or student["instructor_id"] != instructor_id:
            raise HTTPException(404, "Student not found")

        essays = conn.execute(
            "SELECT e.id AS essay_id, e.assignment_id, e.created_at, a.name AS assignment_name "
            "FROM essays e JOIN assignments a ON e.assignment_id = a.id "
            "WHERE e.student_id = ? ORDER BY e.created_at DESC, e.id DESC LIMIT ? OFFSET ?",
            (student_id, limit, offset),
        ).fetchall()

        summaries = _essay_grade_summaries(conn, [e["essay_id"] for e in essays])
        history = []
        for e in essays:
            summary = summaries[e["essay_id"]]
            history.append({
                "essay_id": e["essay_id"], "assignment_id": e["assignment_id"],
                "assignment_name": e["assignment_name"], "created_at": e["created_at"],
                **summary,
            })

    return {
        "student": {
            "id": student["id"], "course_id": student["course_id"],
            "display_name": student["display_name"],
            "external_ref": student["external_ref"], "status": student["status"],
        },
        "history": history,
    }


@router.delete("/students/{student_id}")
def delete_student(student_id: str, request: Request, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        if student is None:
            raise HTTPException(404, "Student not found")
        if student["instructor_id"] != instructor_id:
            raise HTTPException(403, "Not your student")
        conn.execute("UPDATE essays SET student_id = NULL WHERE student_id = ?", (student_id,))
        # D6: assessments.student_id is a separate FK to students(id), never
        # read anywhere in this codebase (write-only, set at assessment
        # creation) — nulling it here is safe and, unlike essays.student_id
        # above, was previously missing entirely, so deleting a student who'd
        # ever been graded threw a raw FK constraint violation.
        conn.execute("UPDATE assessments SET student_id = NULL WHERE student_id = ?", (student_id,))
        conn.execute("DELETE FROM students WHERE id = ?", (student_id,))
        conn.commit()
    record_audit_event(
        action="student.deleted",
        outcome="success",
        request=request,
        actor=user,
        target_type="student",
        target_id=student_id,
        metadata={"display_name": student["display_name"], "course_id": student["course_id"]},
    )
    return {"status": "ok"}


@router.get("/essays")
def list_essays(
    assignment_id: str,
    user: CurrentUser = Depends(get_current_user),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    with get_connection() as conn:
        assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if assignment is None:
            raise HTTPException(404, "Assignment not found")
        _assert_course_owned(conn, assignment["course_id"], user.scoped_instructor_id())
        rows = conn.execute(
            """SELECT id, assignment_id, student_id, created_at,
                      CASE WHEN length(text) > 280
                           THEN substr(text, 1, 280) || '…'
                           ELSE text END AS text
               FROM essays
               WHERE assignment_id = ?
               ORDER BY created_at, id LIMIT ? OFFSET ?""",
            (assignment_id, limit, offset),
        ).fetchall()
    # Grading re-reads the full text by id; list views never transfer it out of
    # SQLite, which keeps a large class page proportional to preview size.
    return [dict(row) for row in rows]


@router.post("/essays")
def create_essay(body: EssayCreate, user: CurrentUser = Depends(get_current_user)):
    essay_id = str(uuid.uuid4())
    with get_connection() as conn:
        assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (body.assignment_id,)).fetchone()
        if assignment is None:
            raise HTTPException(404, "Assignment not found")
        _assert_course_owned(conn, assignment["course_id"], user.scoped_instructor_id())
        if body.student_id is not None:
            student = conn.execute("SELECT * FROM students WHERE id = ?", (body.student_id,)).fetchone()
            if student is None:
                raise HTTPException(404, "Student not found")
            if student["course_id"] != assignment["course_id"]:
                raise HTTPException(400, "Student does not belong to this assignment's course")
        conn.execute(
            "INSERT INTO essays (id, assignment_id, student_id, text, created_at) VALUES (?,?,?,?,?)",
            (essay_id, body.assignment_id, body.student_id, body.text, _now()),
        )
        conn.commit()
    return {"id": essay_id, "assignment_id": body.assignment_id, "student_id": body.student_id, "text": body.text}


@router.post("/essays/import-text")
async def import_essay_text(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
):
    """Extract an upload into the editable essay field without persisting it."""
    filename = Path(file.filename or "").name
    try:
        data = await file.read(MAX_UPLOAD_BYTES + 1)
    finally:
        await file.close()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413,
            f"Documents are limited to {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )
    try:
        text, file_type = extract_document_text(filename, data)
    except DocumentImportError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "text": text,
        "filename": filename,
        "file_type": file_type,
        "character_count": len(text),
    }


@router.delete("/essays/{essay_id}")
def delete_essay(essay_id: str, request: Request, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        essay = conn.execute("SELECT * FROM essays WHERE id = ?", (essay_id,)).fetchone()
        if essay is None:
            raise HTTPException(404, "Essay not found")
        assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (essay["assignment_id"],)).fetchone()
        _assert_course_owned(conn, assignment["course_id"], instructor_id)
        if _essay_has_active_assessment(conn, essay_id):
            raise HTTPException(409, "Grading is still in progress for this essay")
        _delete_essay_cascade(conn, essay_id)
        conn.commit()
    record_audit_event(
        action="essay.deleted",
        outcome="success",
        request=request,
        actor=user,
        target_type="essay",
        target_id=essay_id,
        metadata={
            "assignment_id": essay["assignment_id"],
            "student_id": essay["student_id"],
        },
    )
    return {"status": "ok"}


@router.post("/assignments/{assignment_id}/bulk-grade")
def bulk_grade(
    assignment_id: str,
    body: BulkGradeRequest,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
    instructor_id = user.scoped_instructor_id()
    byok = body.byok
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

    results = []
    with get_connection() as conn:
        assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if assignment is None:
            raise HTTPException(404, "Assignment not found")
        _assert_course_owned(conn, assignment["course_id"], instructor_id)

        criteria_rows = conn.execute(
            "SELECT * FROM criteria WHERE rubric_id = ? AND rubric_version = ?",
            (assignment["rubric_id"], assignment["rubric_version"]),
        ).fetchall()
        if not criteria_rows:
            raise HTTPException(400, "Rubric has no criteria loaded")
        criteria_rows_dicts = [dict(c) for c in criteria_rows]
        assignment_dict = dict(assignment)
        essay_rows = conn.execute(
            """WITH requested AS (
                 SELECT value AS essay_id FROM json_each(?)
               ),
               ranked AS (
                 SELECT a.essay_id, a.status,
                        ROW_NUMBER() OVER (
                          PARTITION BY a.essay_id ORDER BY a.created_at DESC, a.id DESC
                        ) AS rn
                 FROM assessments a
                 JOIN requested r ON r.essay_id = a.essay_id
               )
               SELECT e.*, ranked.status AS latest_status
               FROM requested r
               LEFT JOIN essays e ON e.id = r.essay_id
               LEFT JOIN ranked ON ranked.essay_id = r.essay_id AND ranked.rn = 1""",
            (json.dumps(body.essay_ids),),
        ).fetchall()
        essays_by_id = {
            row["essay_id"]: row
            for row in essay_rows
            if row["id"] is not None
        }

        for essay_id in body.essay_ids:
            essay = essays_by_id.get(essay_id)
            if essay is None:
                results.append({"essay_id": essay_id, "status": "error", "detail": "Essay not found"})
                continue
            if essay["assignment_id"] != assignment_id:
                results.append({"essay_id": essay_id, "status": "error", "detail": "Essay does not belong to this assignment"})
                continue
            if essay["latest_status"] in ("running", "pending"):
                results.append({"essay_id": essay_id, "status": "skipped", "detail": "Already in progress"})
                continue
            assessment_id = _launch_assessment(essay, assignment_dict, criteria_rows_dicts, config, client, instructor_id)
            results.append({"essay_id": essay_id, "status": "started", "assessment_id": assessment_id})

    record_audit_event(
        action="grading.bulk_started",
        outcome="success",
        request=request,
        actor=user,
        target_type="assignment",
        target_id=assignment_id,
        metadata={
            "provider": config.provider,
            "model": config.model,
            "requested_count": len(body.essay_ids),
            "started_count": sum(r["status"] == "started" for r in results),
            "skipped_count": sum(r["status"] == "skipped" for r in results),
            "error_count": sum(r["status"] == "error" for r in results),
        },
    )
    return {"results": results}


@router.get("/assignments/{assignment_id}/queue")
def get_queue(assignment_id: str, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if assignment is None:
            raise HTTPException(404, "Assignment not found")
        _assert_course_owned(conn, assignment["course_id"], instructor_id)

        rows = conn.execute(
            """WITH ranked AS (
                 SELECT a.*,
                        ROW_NUMBER() OVER (
                          PARTITION BY a.essay_id ORDER BY a.created_at DESC, a.id DESC
                        ) AS rn
                 FROM assessments a
                 JOIN essays e ON e.id = a.essay_id
                 WHERE e.assignment_id = ?
               ),
               latest AS (
                 SELECT * FROM ranked WHERE rn = 1
               ),
               signals AS (
                 SELECT
                   l.id AS assessment_id,
                   MAX(COALESCE(d.exceeds_threshold, 0)) AS exceeds_threshold,
                   MAX(COALESCE(sa.high_spread, 0)) AS high_spread,
                   MAX(CASE WHEN c.referenceability = 'weak' THEN 1 ELSE 0 END) AS weak_referenceability,
                   MAX(CASE WHEN sa.path = 'personalized'
                                 AND sa.is_no_evidence = 0
                                 AND json_array_length(sa.evidence_json) = 0
                            THEN 1 ELSE 0 END) AS unsupported_evidence
                 FROM latest l
                 LEFT JOIN score_aggregates sa ON sa.assessment_id = l.id
                 LEFT JOIN divergence_records d
                   ON d.assessment_id = l.id AND d.criterion_id = sa.criterion_id
                 LEFT JOIN criteria c
                   ON c.rubric_id = l.rubric_id
                  AND c.rubric_version = l.rubric_version
                  AND c.criterion_id = sa.criterion_id
                 GROUP BY l.id
               )
               SELECT
                 e.id AS essay_id,
                 e.student_id,
                 l.id AS latest_assessment_id,
                 l.status,
                 COALESCE(s.exceeds_threshold, 0) AS exceeds_threshold,
                 COALESCE(s.high_spread, 0) AS high_spread,
                 rc.decision AS relevance_decision,
                 CASE WHEN COALESCE(s.exceeds_threshold, 0) = 1
                           OR COALESCE(s.high_spread, 0) = 1
                           OR COALESCE(s.weak_referenceability, 0) = 1
                           OR COALESCE(s.unsupported_evidence, 0) = 1
                           OR rc.decision IN ('reject', 'manual_review')
                      THEN 1 ELSE 0 END AS needs_review
               FROM essays e
               LEFT JOIN latest l ON l.essay_id = e.id
               LEFT JOIN signals s ON s.assessment_id = l.id
               LEFT JOIN relevance_checks rc ON rc.assessment_id = l.id
               WHERE e.assignment_id = ?
               ORDER BY e.created_at, e.id""",
            (assignment_id, assignment_id),
        ).fetchall()
    return [
        {
            **dict(row),
            "exceeds_threshold": bool(row["exceeds_threshold"]),
            "high_spread": bool(row["high_spread"]),
            "needs_review": bool(row["needs_review"]),
        }
        for row in rows
    ]


@router.get("/assignments/{assignment_id}/breakdown")
def get_assignment_breakdown(assignment_id: str, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if assignment is None:
            raise HTTPException(404, "Assignment not found")
        _assert_course_owned(conn, assignment["course_id"], instructor_id)

        essays = conn.execute("SELECT id, student_id FROM essays WHERE assignment_id = ?", (assignment_id,)).fetchall()
        n_essays = len(essays)
        essay_by_id = {essay["id"]: essay for essay in essays}
        criterion_rows = _latest_criterion_rows(conn, list(essay_by_id))
        n_graded_essays = len({
            row["essay_id"]
            for row in criterion_rows
            if row["status"] == "complete"
        })
        criterion_stats: dict[str, dict] = {}

        for row in criterion_rows:
            if (
                row["status"] != "complete"
                or row["criterion_id"] is None
            ):
                continue
            out = _criterion_out_from_row(row)
            if out["output_score"] is None:
                continue
            stats = criterion_stats.setdefault(
                row["criterion_id"], {
                    "scores": [], "n_divergent": 0, "n_high_spread": 0,
                    "n_weak_referenceability": 0, "n_unsupported_evidence": 0, "flagged": [],
                }
            )
            stats["scores"].append(out["output_score"])
            if out["needs_review"]:
                essay = essay_by_id[row["essay_id"]]
                stats["flagged"].append({
                    "essay_id": row["essay_id"], "assessment_id": row["assessment_id"],
                    "student_id": essay["student_id"],
                    "exceeds_threshold": out["exceeds_threshold"], "high_spread": out["high_spread"],
                    "review_reasons": out["review_reasons"],
                })
            if out["exceeds_threshold"]:
                stats["n_divergent"] += 1
            if out["high_spread"]:
                stats["n_high_spread"] += 1
            if "weak_referenceability" in out["review_reasons"]:
                stats["n_weak_referenceability"] += 1
            if "unsupported_evidence" in out["review_reasons"]:
                stats["n_unsupported_evidence"] += 1

    criteria = [
        {
            "criterion_id": cid,
            "n_graded": len(s["scores"]),
            "avg_score": sum(s["scores"]) / len(s["scores"]),
            "min_score": min(s["scores"]),
            "max_score": max(s["scores"]),
            "n_divergent": s["n_divergent"],
            "n_high_spread": s["n_high_spread"],
            "n_weak_referenceability": s["n_weak_referenceability"],
            "n_unsupported_evidence": s["n_unsupported_evidence"],
            "flagged": s["flagged"],
        }
        for cid, s in criterion_stats.items()
    ]
    return {"n_essays": n_essays, "n_graded_essays": n_graded_essays, "criteria": criteria}


def _csv_chunk(rows: list[dict], fieldnames: list[str], *, include_header: bool = False) -> str:
    """Render a bounded CSV chunk instead of retaining the entire export."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    if include_header:
        writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def _essay_csv_row(essay, summary: dict) -> dict:
    return {
        "student_name": essay["display_name"] or "",
        "external_ref": essay["external_ref"] or "",
        "status": summary["status"] or "ungraded",
        "relevance_decision": summary["relevance_decision"] or "",
        "avg_score": f"{summary['avg_score']:.2f}" if summary["avg_score"] is not None else "",
        "n_criteria": summary["n_criteria"],
        "n_divergent": summary["n_divergent"],
        "n_high_spread": summary["n_high_spread"],
    }


def _assignment_csv_stream(assignment_id: str, fieldnames: list[str]):
    yield _csv_chunk([], fieldnames, include_header=True)
    with get_connection() as conn:
        cursor = conn.execute(
            """SELECT e.id, s.display_name, s.external_ref
               FROM essays e
               LEFT JOIN students s ON s.id = e.student_id
               WHERE e.assignment_id = ?
               ORDER BY e.created_at, e.id""",
            (assignment_id,),
        )
        while batch := cursor.fetchmany(200):
            summaries = _essay_grade_summaries(conn, [essay["id"] for essay in batch])
            yield _csv_chunk(
                [_essay_csv_row(essay, summaries[essay["id"]]) for essay in batch],
                fieldnames,
            )


def _course_csv_stream(course_id: str, fieldnames: list[str]):
    yield _csv_chunk([], fieldnames, include_header=True)
    with get_connection() as conn:
        cursor = conn.execute(
            """SELECT e.id, a.name AS assignment_name, s.display_name, s.external_ref
               FROM essays e
               JOIN assignments a ON a.id = e.assignment_id
               LEFT JOIN students s ON s.id = e.student_id
               WHERE a.course_id = ?
               ORDER BY a.created_at, a.id, e.created_at, e.id""",
            (course_id,),
        )
        while batch := cursor.fetchmany(200):
            summaries = _essay_grade_summaries(conn, [essay["id"] for essay in batch])
            rows = []
            for essay in batch:
                row = _essay_csv_row(essay, summaries[essay["id"]])
                row["assignment_name"] = essay["assignment_name"]
                rows.append(row)
            yield _csv_chunk(rows, fieldnames)


@router.get("/assignments/{assignment_id}/export.csv")
def export_assignment_csv(
    assignment_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if assignment is None:
            raise HTTPException(404, "Assignment not found")
        _assert_course_owned(conn, assignment["course_id"], instructor_id)
        row_count = conn.execute(
            "SELECT COUNT(*) FROM essays WHERE assignment_id = ?", (assignment_id,)
        ).fetchone()[0]
    record_audit_event(
        action="export.assignment_csv",
        outcome="success",
        request=request,
        actor=user,
        target_type="assignment",
        target_id=assignment_id,
        metadata={"name": assignment["name"], "row_count": row_count},
    )
    fieldnames = [
        "student_name", "external_ref", "status", "relevance_decision",
        "avg_score", "n_criteria", "n_divergent", "n_high_spread",
    ]
    return StreamingResponse(
        _assignment_csv_stream(assignment_id, fieldnames),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{assignment["name"]}_scores.csv"'},
    )


@router.get("/courses/{course_id}/export.csv")
def export_course_csv(course_id: str, request: Request, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        _assert_course_owned(conn, course_id, instructor_id)
        counts = conn.execute(
            """SELECT COUNT(DISTINCT a.id), COUNT(e.id)
               FROM assignments a
               LEFT JOIN essays e ON e.assignment_id = a.id
               WHERE a.course_id = ?""",
            (course_id,),
        ).fetchone()
    record_audit_event(
        action="export.course_csv",
        outcome="success",
        request=request,
        actor=user,
        target_type="course",
        target_id=course_id,
        metadata={"assignment_count": counts[0], "row_count": counts[1]},
    )
    fieldnames = [
        "assignment_name", "student_name", "external_ref", "status", "relevance_decision",
        "avg_score", "n_criteria", "n_divergent", "n_high_spread",
    ]
    return StreamingResponse(
        _course_csv_stream(course_id, fieldnames),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="course_scores.csv"'},
    )
