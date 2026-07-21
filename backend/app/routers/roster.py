"""Courses, assignments, students, essays — the entities everything else
scopes to (design doc §6, §12)."""
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from app.auth import CurrentUser, get_current_user
from app.db import get_connection
from app.schemas import AssignmentCreate, CourseCreate, EssayCreate, StudentCreate

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


def _assert_course_owned(conn, course_id: str, instructor_id: str):
    row = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Course not found")
    if row["instructor_id"] != instructor_id:
        raise HTTPException(403, "Not your course")
    return row


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


@router.get("/essays")
def list_essays(assignment_id: str, user: CurrentUser = Depends(get_current_user)):
    with get_connection() as conn:
        assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if assignment is None:
            raise HTTPException(404, "Assignment not found")
        _assert_course_owned(conn, assignment["course_id"], user.scoped_instructor_id())
        rows = conn.execute("SELECT * FROM essays WHERE assignment_id = ?", (assignment_id,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/essays")
def create_essay(body: EssayCreate, user: CurrentUser = Depends(get_current_user)):
    essay_id = str(uuid.uuid4())
    with get_connection() as conn:
        assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (body.assignment_id,)).fetchone()
        if assignment is None:
            raise HTTPException(404, "Assignment not found")
        _assert_course_owned(conn, assignment["course_id"], user.scoped_instructor_id())
        conn.execute(
            "INSERT INTO essays (id, assignment_id, student_id, text, created_at) VALUES (?,?,?,?,?)",
            (essay_id, body.assignment_id, body.student_id, body.text, _now()),
        )
        conn.commit()
    return {"id": essay_id, "assignment_id": body.assignment_id, "student_id": body.student_id, "text": body.text}
