"""Manual curation of the personalized corpus (design doc §3.5 entry path)."""
from fastapi import APIRouter, Depends, HTTPException

from app.auth import CurrentUser, get_current_user
from app.db import get_connection
from app.grading.evidence import EvidenceVerificationError
from app.repositories.excerpts import delete_personalized_excerpt, insert_personalized_excerpt
from app.schemas import PersonalizedExcerptCreate

router = APIRouter(prefix="/api/personalized-excerpts", tags=["excerpts"])


@router.post("")
def create_personalized_excerpt(body: PersonalizedExcerptCreate, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        if body.assignment_id:
            assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (body.assignment_id,)).fetchone()
            if assignment is None:
                raise HTTPException(404, "Assignment not found")
            course = conn.execute("SELECT * FROM courses WHERE id = ?", (assignment["course_id"],)).fetchone()
            if course["instructor_id"] != instructor_id:
                raise HTTPException(403, "Not your assignment")
        try:
            excerpt_id = insert_personalized_excerpt(
                conn,
                rubric_id=body.rubric_id, criterion_id=body.criterion_id, instructor_id=instructor_id,
                course_id=body.course_id, assignment_id=body.assignment_id,
                excerpt_text=body.excerpt_text, score=body.score, anchor_matched=body.anchor_matched,
                rationale=body.rationale, source="manual", added_by=user.user_id,
                source_essay_text=body.source_essay_text,
            )
        except EvidenceVerificationError as e:
            raise HTTPException(422, str(e)) from e
        conn.commit()
    return {"id": excerpt_id}


@router.get("")
def list_personalized_excerpts(
    rubric_id: str, criterion_id: str, user: CurrentUser = Depends(get_current_user)
):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM personalized_excerpts_src
               WHERE instructor_id = ? AND rubric_id = ? AND criterion_id = ?
               ORDER BY updated_at DESC""",
            (instructor_id, rubric_id, criterion_id),
        ).fetchall()
    return [dict(r) for r in rows]


@router.delete("/{excerpt_id}")
def delete_excerpt(excerpt_id: str, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM personalized_excerpts_src WHERE id = ?", (excerpt_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Excerpt not found")
        if row["instructor_id"] != instructor_id:
            raise HTTPException(403, "Not your excerpt")
        delete_personalized_excerpt(conn, excerpt_id)
        conn.commit()
    return {"status": "ok"}
