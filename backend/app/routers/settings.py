"""Settings surfaces (design doc §10) + profile CRUD (§6.2, §6.3)."""
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from app.auth import CurrentUser, get_current_user
from app.db import get_connection
from app.repositories.settings import (
    lookup_divergence_threshold,
    lookup_pool_threshold,
    lookup_spread_threshold,
    set_divergence_threshold,
    set_pool_threshold,
    set_spread_threshold,
)
from app.schemas import (
    AssignmentProfileUpdate,
    CourseProfileUpdate,
    DivergenceThresholdUpdate,
    InstructorProfileUpdate,
    PoolThresholdUpdate,
    SpreadThresholdUpdate,
    ThemeUpdate,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _now() -> str:
    return datetime.now(UTC).isoformat()


@router.get("/instructor-profile")
def get_instructor_profile(user: CurrentUser = Depends(get_current_user)):
    """Current instructor profile, with nulls when unset. The Settings form
    must load this before saving: the PUT below upserts ALL profile columns,
    so a save built from an unloaded (empty) form would silently wipe
    whatever was stored — see §6.2."""
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM instructor_profile WHERE instructor_id = ?", (instructor_id,)
        ).fetchone()
    return {
        "grading_philosophy": row["grading_philosophy"] if row else None,
        "deprioritized_criteria": (
            json.loads(row["deprioritized_criteria_json"])
            if row and row["deprioritized_criteria_json"] else None
        ),
        "rationale_tone": row["rationale_tone"] if row else None,
        "default_llm_provider": row["default_llm_provider"] if row else None,
        "default_llm_model": row["default_llm_model"] if row else None,
    }


@router.get("/thresholds")
def get_thresholds(rubric_id: str, criterion_id: str, user: CurrentUser = Depends(get_current_user)):
    """Effective per-criterion thresholds (stored value or default), so the
    Settings form can display what is actually in force instead of hardcoded
    placeholder defaults."""
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        return {
            "divergence_threshold": lookup_divergence_threshold(conn, instructor_id, rubric_id, criterion_id),
            "spread_threshold": lookup_spread_threshold(conn, instructor_id, rubric_id, criterion_id),
            "min_scoped_pool_size": lookup_pool_threshold(conn, instructor_id, rubric_id, criterion_id),
        }


@router.put("/divergence-threshold")
def put_divergence_threshold(body: DivergenceThresholdUpdate, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        set_divergence_threshold(conn, instructor_id, body.rubric_id, body.criterion_id, body.threshold)
        conn.commit()
    return {"status": "ok"}


@router.put("/spread-threshold")
def put_spread_threshold(body: SpreadThresholdUpdate, user: CurrentUser = Depends(get_current_user)):
    """Gates the within-path 'high spread' signal — separate from
    /divergence-threshold, which gates between-path disagreement."""
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        set_spread_threshold(conn, instructor_id, body.rubric_id, body.criterion_id, body.threshold)
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
            """INSERT INTO instructor_profile (instructor_id, grading_philosophy, deprioritized_criteria_json, rationale_tone, default_llm_provider, default_llm_model, updated_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT (instructor_id) DO UPDATE SET
                 grading_philosophy=excluded.grading_philosophy,
                 deprioritized_criteria_json=excluded.deprioritized_criteria_json,
                 rationale_tone=excluded.rationale_tone,
                 default_llm_provider=excluded.default_llm_provider,
                 default_llm_model=excluded.default_llm_model, updated_at=excluded.updated_at""",
            (
                instructor_id, body.grading_philosophy,
                json.dumps(body.deprioritized_criteria) if body.deprioritized_criteria is not None else None,
                body.rationale_tone, body.default_llm_provider, body.default_llm_model, now,
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


@router.get("/course-profile/{course_id}")
def get_course_profile(course_id: str, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        course = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
        if course is None or course["instructor_id"] != instructor_id:
            raise HTTPException(404, "Course not found")
        row = conn.execute("SELECT * FROM course_profile WHERE course_id = ?", (course_id,)).fetchone()
    return {
        "cohort_level": row["cohort_level"] if row else None,
        "curriculum_texts": json.loads(row["curriculum_texts_json"]) if row and row["curriculum_texts_json"] else None,
        "rubric_version_pin": row["rubric_version_pin"] if row else None,
    }


@router.get("/assignment-profile/{assignment_id}")
def get_assignment_profile(assignment_id: str, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if assignment is None:
            raise HTTPException(404, "Assignment not found")
        course = conn.execute("SELECT * FROM courses WHERE id = ?", (assignment["course_id"],)).fetchone()
        if course is None or course["instructor_id"] != instructor_id:
            raise HTTPException(404, "Assignment not found")
        row = conn.execute(
            "SELECT * FROM assignment_profile WHERE assignment_id = ?", (assignment_id,)
        ).fetchone()
    return {
        "prompt_text": row["prompt_text"] if row else None,
        "format_expectations": row["format_expectations"] if row else None,
        "criterion_emphasis_notes": row["criterion_emphasis_notes"] if row else None,
        "common_pitfalls": row["common_pitfalls"] if row else None,
    }


@router.put("/assignment-profile/{assignment_id}")
def put_assignment_profile(
    assignment_id: str, body: AssignmentProfileUpdate, user: CurrentUser = Depends(get_current_user)
):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if assignment is None:
            raise HTTPException(404, "Assignment not found")
        course = conn.execute("SELECT * FROM courses WHERE id = ?", (assignment["course_id"],)).fetchone()
        if course is None or course["instructor_id"] != instructor_id:
            raise HTTPException(404, "Assignment not found")
        # create_assignment always inserts a matching assignment_profile row
        # in the same transaction, so a plain UPDATE is safe here (unlike
        # course_profile/instructor_profile, which are optional and need
        # INSERT ... ON CONFLICT).
        conn.execute(
            """UPDATE assignment_profile SET
                 prompt_text = ?, format_expectations = ?,
                 criterion_emphasis_notes = ?, common_pitfalls = ?, updated_at = ?
               WHERE assignment_id = ?""",
            (
                body.prompt_text, body.format_expectations, body.criterion_emphasis_notes,
                body.common_pitfalls, _now(), assignment_id,
            ),
        )
        conn.commit()
    return {"status": "ok"}


@router.get("/override-rate")
def get_override_rate(user: CurrentUser = Depends(get_current_user)):
    """Per-criterion override rate + score drift (I4): how often this
    instructor overrides the personalized path's score, and in which
    direction, so grading_philosophy/deprioritized_criteria_json can be
    revisited against real data instead of guesswork."""
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        totals = conn.execute(
            """SELECT a.rubric_id, a.rubric_version, sa.criterion_id, COUNT(*) AS n_graded
               FROM score_aggregates sa JOIN assessments a ON sa.assessment_id = a.id
               WHERE a.instructor_id = ? AND sa.path = 'personalized' AND sa.is_no_evidence = 0
               GROUP BY a.rubric_id, a.rubric_version, sa.criterion_id""",
            (instructor_id,),
        ).fetchall()
        overrides = conn.execute(
            """SELECT a.rubric_id, a.rubric_version, so.criterion_id, so.new_score, sa.score AS original_score
               FROM score_overrides so
               JOIN assessments a ON so.assessment_id = a.id
               LEFT JOIN score_aggregates sa
                 ON sa.assessment_id = so.assessment_id AND sa.criterion_id = so.criterion_id AND sa.path = 'personalized'
               WHERE a.instructor_id = ?""",
            (instructor_id,),
        ).fetchall()

        meta = {}
        for rid, rver in {(t["rubric_id"], t["rubric_version"]) for t in totals}:
            for c in conn.execute(
                "SELECT criterion_id, dimension, statement FROM criteria WHERE rubric_id=? AND rubric_version=?",
                (rid, rver),
            ).fetchall():
                meta[(rid, rver, c["criterion_id"])] = {"dimension": c["dimension"], "statement": c["statement"]}

    stats: dict = {}
    for o in overrides:
        key = (o["rubric_id"], o["rubric_version"], o["criterion_id"])
        s = stats.setdefault(key, {"n_overrides": 0, "diffs": []})
        s["n_overrides"] += 1
        if o["original_score"] is not None:
            s["diffs"].append(o["new_score"] - o["original_score"])

    criteria = []
    for t in totals:
        key = (t["rubric_id"], t["rubric_version"], t["criterion_id"])
        s = stats.get(key, {"n_overrides": 0, "diffs": []})
        m = meta.get(key, {})
        criteria.append({
            "rubric_id": t["rubric_id"], "rubric_version": t["rubric_version"], "criterion_id": t["criterion_id"],
            "dimension": m.get("dimension"), "statement": m.get("statement"),
            "n_graded": t["n_graded"], "n_overrides": s["n_overrides"],
            "override_rate": s["n_overrides"] / t["n_graded"],
            "avg_score_diff": sum(s["diffs"]) / len(s["diffs"]) if s["diffs"] else None,
        })
    criteria.sort(key=lambda c: c["override_rate"], reverse=True)
    return {"criteria": criteria}
