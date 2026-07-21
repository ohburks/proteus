"""Settings surfaces (design doc §10) + profile CRUD (§6.2, §6.3)."""
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from app.auth import CurrentUser, get_current_user
from app.db import get_connection
from app.repositories.settings import set_divergence_threshold, set_pool_threshold
from app.schemas import CourseProfileUpdate, DivergenceThresholdUpdate, InstructorProfileUpdate, PoolThresholdUpdate, ThemeUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _now() -> str:
    return datetime.now(UTC).isoformat()


@router.put("/divergence-threshold")
def put_divergence_threshold(body: DivergenceThresholdUpdate, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        set_divergence_threshold(conn, instructor_id, body.rubric_id, body.criterion_id, body.threshold)
        conn.commit()
    return {"status": "ok"}


@router.put("/pool-threshold")
def put_pool_threshold(body: PoolThresholdUpdate, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        set_pool_threshold(conn, instructor_id, body.rubric_id, body.criterion_id, body.min_scoped_pool_size)
        conn.commit()
    return {"status": "ok"}


@router.put("/theme")
def put_theme(body: ThemeUpdate, user: CurrentUser = Depends(get_current_user)):
    if body.theme_preference not in ("system", "light", "dark"):
        raise HTTPException(400, "Invalid theme_preference")
    with get_connection() as conn:
        conn.execute("UPDATE users SET theme_preference = ? WHERE id = ?", (body.theme_preference, user.user_id))
        conn.commit()
    return {"status": "ok"}


@router.put("/instructor-profile")
def put_instructor_profile(body: InstructorProfileUpdate, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    now = _now()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO instructor_profile (instructor_id, grading_philosophy, deprioritized_criteria_json, rationale_tone, updated_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT (instructor_id) DO UPDATE SET
                 grading_philosophy=excluded.grading_philosophy,
                 deprioritized_criteria_json=excluded.deprioritized_criteria_json,
                 rationale_tone=excluded.rationale_tone, updated_at=excluded.updated_at""",
            (
                instructor_id, body.grading_philosophy,
                json.dumps(body.deprioritized_criteria) if body.deprioritized_criteria is not None else None,
                body.rationale_tone, now,
            ),
        )
        conn.commit()
    return {"status": "ok"}


@router.put("/course-profile/{course_id}")
def put_course_profile(course_id: str, body: CourseProfileUpdate, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    now = _now()
    with get_connection() as conn:
        course = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
        if course is None or course["instructor_id"] != instructor_id:
            raise HTTPException(404, "Course not found")
        conn.execute(
            """INSERT INTO course_profile (course_id, instructor_id, cohort_level, curriculum_texts_json, rubric_version_pin, updated_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT (course_id) DO UPDATE SET
                 cohort_level=excluded.cohort_level, curriculum_texts_json=excluded.curriculum_texts_json,
                 rubric_version_pin=excluded.rubric_version_pin, updated_at=excluded.updated_at""",
            (
                course_id, instructor_id, body.cohort_level,
                json.dumps(body.curriculum_texts) if body.curriculum_texts is not None else None,
                body.rubric_version_pin, now,
            ),
        )
        conn.commit()
    return {"status": "ok"}
