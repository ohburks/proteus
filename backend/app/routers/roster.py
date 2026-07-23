"""Courses, assignments, students, essays — the entities everything else
scopes to (design doc §6, §12)."""
import csv
import io
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.auth import CurrentUser, get_current_user
from app.db import get_connection
from app.llm.key_resolution import KeyResolutionError, resolve_provider_config
from app.llm.providers import build_client
from app.routers.assessments import _criterion_output, _grading_error_detail, _launch_assessment
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
def list_courses(user: CurrentUser = Depends(get_current_user)):
    with get_connection() as conn:
        if user.role == "admin":
            rows = conn.execute("SELECT * FROM courses").fetchall()
        else:
            rows = conn.execute("SELECT * FROM courses WHERE instructor_id = ?", (user.instructor_id,)).fetchall()
    return [dict(r) for r in rows]


@router.delete("/courses/{course_id}")
def delete_course(course_id: str, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        _assert_course_owned(conn, course_id, instructor_id)

        assignment_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM assignments WHERE course_id = ?", (course_id,)
        ).fetchall()]
        for aid in assignment_ids:
            for eid in _assignment_essay_ids(conn, aid):
                if _essay_has_active_assessment(conn, eid):
                    raise HTTPException(409, "Grading is still in progress for an essay in this course")
        for aid in assignment_ids:
            _delete_assignment_cascade(conn, aid)

        conn.execute("DELETE FROM personalized_excerpts_src WHERE course_id = ?", (course_id,))
        conn.execute("DELETE FROM course_profile WHERE course_id = ?", (course_id,))
        conn.execute("DELETE FROM students WHERE course_id = ?", (course_id,))
        conn.execute("DELETE FROM courses WHERE id = ?", (course_id,))
        conn.commit()
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


def _delete_assignment_cascade(conn, assignment_id: str) -> None:
    for eid in _assignment_essay_ids(conn, assignment_id):
        _delete_essay_cascade(conn, eid)
    conn.execute("DELETE FROM assignment_profile WHERE assignment_id = ?", (assignment_id,))
    conn.execute("DELETE FROM personalized_excerpts_src WHERE assignment_id = ?", (assignment_id,))
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
def list_assignments(course_id: str, user: CurrentUser = Depends(get_current_user)):
    with get_connection() as conn:
        _assert_course_owned(conn, course_id, user.scoped_instructor_id())
        rows = conn.execute("SELECT * FROM assignments WHERE course_id = ?", (course_id,)).fetchall()
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
def delete_assignment(assignment_id: str, user: CurrentUser = Depends(get_current_user)):
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
def list_students(user: CurrentUser = Depends(get_current_user), course_id: str | None = None):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        if course_id:
            rows = conn.execute(
                "SELECT * FROM students WHERE instructor_id = ? AND course_id = ?", (instructor_id, course_id)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM students WHERE instructor_id = ?", (instructor_id,)).fetchall()
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


def _essay_grade_summary(conn, essay_id: str) -> dict:
    latest = conn.execute(
        "SELECT * FROM assessments WHERE essay_id = ? ORDER BY created_at DESC LIMIT 1", (essay_id,)
    ).fetchone()
    summary = {
        "assessment_id": latest["id"] if latest else None,
        "status": latest["status"] if latest else None,
        "avg_score": None, "n_criteria": 0, "n_divergent": 0, "n_high_spread": 0, "needs_review": False,
    }
    if latest and latest["status"] == "complete":
        criteria_ids = [r["criterion_id"] for r in conn.execute(
            "SELECT DISTINCT criterion_id FROM score_aggregates WHERE assessment_id = ?", (latest["id"],)
        ).fetchall()]
        scores = []
        for cid in criteria_ids:
            out = _criterion_output(conn, latest["id"], cid)
            if out["needs_review"]:
                summary["needs_review"] = True
            if out["output_score"] is None:
                continue
            scores.append(out["output_score"])
            if out["exceeds_threshold"]:
                summary["n_divergent"] += 1
            if out["high_spread"]:
                summary["n_high_spread"] += 1
        if scores:
            summary["avg_score"] = sum(scores) / len(scores)
            summary["n_criteria"] = len(scores)
    return summary


@router.get("/students/{student_id}/history")
def get_student_history(student_id: str, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        if student is None or student["instructor_id"] != instructor_id:
            raise HTTPException(404, "Student not found")

        essays = conn.execute(
            "SELECT e.id AS essay_id, e.assignment_id, e.created_at, a.name AS assignment_name "
            "FROM essays e JOIN assignments a ON e.assignment_id = a.id "
            "WHERE e.student_id = ? ORDER BY e.created_at",
            (student_id,),
        ).fetchall()

        history = []
        for e in essays:
            summary = _essay_grade_summary(conn, e["essay_id"])
            history.append({
                "essay_id": e["essay_id"], "assignment_id": e["assignment_id"],
                "assignment_name": e["assignment_name"], "created_at": e["created_at"],
                **summary,
            })

    return {
        "student": {
            "id": student["id"], "display_name": student["display_name"],
            "external_ref": student["external_ref"], "status": student["status"],
        },
        "history": history,
    }


@router.delete("/students/{student_id}")
def delete_student(student_id: str, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        if student is None:
            raise HTTPException(404, "Student not found")
        if student["instructor_id"] != instructor_id:
            raise HTTPException(403, "Not your student")
        conn.execute("UPDATE essays SET student_id = NULL WHERE student_id = ?", (student_id,))
        conn.execute("DELETE FROM students WHERE id = ?", (student_id,))
        conn.commit()
    return {"status": "ok"}


@router.get("/essays")
def list_essays(assignment_id: str, user: CurrentUser = Depends(get_current_user)):
    with get_connection() as conn:
        assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if assignment is None:
            raise HTTPException(404, "Assignment not found")
        _assert_course_owned(conn, assignment["course_id"], user.scoped_instructor_id())
        rows = conn.execute("SELECT * FROM essays WHERE assignment_id = ?", (assignment_id,)).fetchall()
    # The list view only renders a short preview, so send a truncated `text`
    # instead of every essay's full body (which can be many KB each). Grading
    # re-reads the full text from the DB by id, so nothing downstream needs it.
    _PREVIEW_LEN = 280
    out = []
    for r in rows:
        d = dict(r)
        text = d.get("text") or ""
        d["text"] = text[:_PREVIEW_LEN] + "…" if len(text) > _PREVIEW_LEN else text
        out.append(d)
    return out


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


@router.delete("/essays/{essay_id}")
def delete_essay(essay_id: str, user: CurrentUser = Depends(get_current_user)):
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
    return {"status": "ok"}


@router.post("/assignments/{assignment_id}/bulk-grade")
def bulk_grade(assignment_id: str, body: BulkGradeRequest, user: CurrentUser = Depends(get_current_user)):
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

        for essay_id in body.essay_ids:
            essay = conn.execute("SELECT * FROM essays WHERE id = ?", (essay_id,)).fetchone()
            if essay is None:
                results.append({"essay_id": essay_id, "status": "error", "detail": "Essay not found"})
                continue
            if essay["assignment_id"] != assignment_id:
                results.append({"essay_id": essay_id, "status": "error", "detail": "Essay does not belong to this assignment"})
                continue
            latest = conn.execute(
                "SELECT status FROM assessments WHERE essay_id = ? ORDER BY created_at DESC LIMIT 1",
                (essay_id,),
            ).fetchone()
            if latest is not None and latest["status"] in ("running", "pending"):
                results.append({"essay_id": essay_id, "status": "skipped", "detail": "Already in progress"})
                continue
            assessment_id = _launch_assessment(essay, assignment_dict, criteria_rows_dicts, config, client, instructor_id)
            results.append({"essay_id": essay_id, "status": "started", "assessment_id": assessment_id})

    return {"results": results}


@router.get("/assignments/{assignment_id}/queue")
def get_queue(assignment_id: str, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if assignment is None:
            raise HTTPException(404, "Assignment not found")
        _assert_course_owned(conn, assignment["course_id"], instructor_id)

        essays = conn.execute("SELECT * FROM essays WHERE assignment_id = ?", (assignment_id,)).fetchall()
        entries = []
        for essay in essays:
            latest = conn.execute(
                "SELECT * FROM assessments WHERE essay_id = ? ORDER BY created_at DESC LIMIT 1",
                (essay["id"],),
            ).fetchone()
            if latest is None:
                entries.append({
                    "essay_id": essay["id"], "student_id": essay["student_id"],
                    "latest_assessment_id": None, "status": None,
                    "exceeds_threshold": False, "high_spread": False, "needs_review": False,
                })
                continue
            exceeds = conn.execute(
                "SELECT 1 FROM divergence_records WHERE assessment_id = ? AND exceeds_threshold = 1 LIMIT 1",
                (latest["id"],),
            ).fetchone() is not None
            high_spread = conn.execute(
                "SELECT 1 FROM score_aggregates WHERE assessment_id = ? AND high_spread = 1 LIMIT 1",
                (latest["id"],),
            ).fetchone() is not None
            # Cheap EXISTS-style approximation of _criterion_output's
            # needs_review (B3) — this endpoint is polled every 2s while
            # grading is active, so it deliberately avoids the full
            # per-criterion loop the breakdown/assessment endpoints use.
            weak_ref_present = conn.execute(
                """SELECT 1 FROM score_aggregates sa
                   JOIN criteria c ON c.rubric_id = ? AND c.rubric_version = ? AND c.criterion_id = sa.criterion_id
                   WHERE sa.assessment_id = ? AND sa.path = 'personalized' AND c.referenceability = 'weak' LIMIT 1""",
                (assignment["rubric_id"], assignment["rubric_version"], latest["id"]),
            ).fetchone() is not None
            unsupported_evidence_present = conn.execute(
                """SELECT 1 FROM score_aggregates WHERE assessment_id = ? AND path = 'personalized'
                   AND is_no_evidence = 0 AND json_array_length(evidence_json) = 0 LIMIT 1""",
                (latest["id"],),
            ).fetchone() is not None
            entries.append({
                "essay_id": essay["id"], "student_id": essay["student_id"],
                "latest_assessment_id": latest["id"], "status": latest["status"],
                "exceeds_threshold": exceeds, "high_spread": high_spread,
                "needs_review": exceeds or high_spread or weak_ref_present or unsupported_evidence_present,
            })
    return entries


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
        n_graded_essays = 0
        criterion_stats: dict[str, dict] = {}

        for essay in essays:
            latest = conn.execute(
                "SELECT * FROM assessments WHERE essay_id = ? ORDER BY created_at DESC LIMIT 1",
                (essay["id"],),
            ).fetchone()
            if latest is None or latest["status"] != "complete":
                continue
            n_graded_essays += 1
            criteria_ids = [
                r["criterion_id"] for r in conn.execute(
                    "SELECT DISTINCT criterion_id FROM score_aggregates WHERE assessment_id = ?", (latest["id"],)
                ).fetchall()
            ]
            for cid in criteria_ids:
                out = _criterion_output(conn, latest["id"], cid)
                if out["output_score"] is None:
                    continue
                stats = criterion_stats.setdefault(
                    cid, {
                        "scores": [], "n_divergent": 0, "n_high_spread": 0,
                        "n_weak_referenceability": 0, "n_unsupported_evidence": 0, "flagged": [],
                    }
                )
                stats["scores"].append(out["output_score"])
                if out["needs_review"]:
                    stats["flagged"].append({
                        "essay_id": essay["id"], "assessment_id": latest["id"], "student_id": essay["student_id"],
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


def _csv_response(rows: list[dict], fieldnames: list[str], filename: str) -> Response:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _essay_csv_row(conn, essay, students_by_id: dict) -> dict:
    summary = _essay_grade_summary(conn, essay["id"])
    student = students_by_id.get(essay["student_id"])
    return {
        "student_name": student["display_name"] if student else "",
        "external_ref": (student["external_ref"] if student else "") or "",
        "status": summary["status"] or "ungraded",
        "avg_score": f"{summary['avg_score']:.2f}" if summary["avg_score"] is not None else "",
        "n_criteria": summary["n_criteria"],
        "n_divergent": summary["n_divergent"],
        "n_high_spread": summary["n_high_spread"],
    }


@router.get("/assignments/{assignment_id}/export.csv")
def export_assignment_csv(assignment_id: str, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if assignment is None:
            raise HTTPException(404, "Assignment not found")
        _assert_course_owned(conn, assignment["course_id"], instructor_id)
        essays = conn.execute("SELECT * FROM essays WHERE assignment_id = ?", (assignment_id,)).fetchall()
        students_by_id = {
            s["id"]: s for s in conn.execute(
                "SELECT * FROM students WHERE course_id = ?", (assignment["course_id"],)
            ).fetchall()
        }
        rows = [_essay_csv_row(conn, e, students_by_id) for e in essays]
    fieldnames = ["student_name", "external_ref", "status", "avg_score", "n_criteria", "n_divergent", "n_high_spread"]
    return _csv_response(rows, fieldnames, f"{assignment['name']}_scores.csv")


@router.get("/courses/{course_id}/export.csv")
def export_course_csv(course_id: str, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        _assert_course_owned(conn, course_id, instructor_id)
        assignments = conn.execute("SELECT * FROM assignments WHERE course_id = ?", (course_id,)).fetchall()
        students_by_id = {
            s["id"]: s for s in conn.execute("SELECT * FROM students WHERE course_id = ?", (course_id,)).fetchall()
        }
        rows = []
        for a in assignments:
            essays = conn.execute("SELECT * FROM essays WHERE assignment_id = ?", (a["id"],)).fetchall()
            for e in essays:
                row = _essay_csv_row(conn, e, students_by_id)
                row["assignment_name"] = a["name"]
                rows.append(row)
    fieldnames = [
        "assignment_name", "student_name", "external_ref", "status",
        "avg_score", "n_criteria", "n_divergent", "n_high_spread",
    ]
    return _csv_response(rows, fieldnames, "course_scores.csv")
