"""Review UI data contract + override / adopt-exemplar actions (design doc §9)."""
import json

from fastapi import APIRouter, Depends, HTTPException

from app.auth import CurrentUser, get_current_user
from app.db import get_connection
from app.repositories.excerpts import insert_personalized_excerpt
from app.schemas import OverrideRequest

router = APIRouter(prefix="/api/assessments/{assessment_id}/criteria/{criterion_id}", tags=["review"])


def _raw_pass_out(row) -> dict:
    return {
        "pass_index": row["pass_index"],
        "score": row["score"] if not row["is_no_evidence"] else "no-evidence",
        "anchor_matched": row["anchor_matched"],
        "evidence": json.loads(row["evidence_json"]),
        "rationale": row["rationale"],
        "confidence": row["confidence"],
    }


def _aggregate_out(row, raw_passes: list) -> dict | None:
    if row is None:
        return None
    return {
        "score": row["score"] if not row["is_no_evidence"] else "no-evidence",
        "anchor_matched": row["anchor_matched"],
        "evidence": json.loads(row["evidence_json"]),
        "rationale": row["rationale"],
        "precedent_ids": json.loads(row["precedent_ids_json"]),
        "spread": row["spread"],
        # Renamed from "confidence" (B2): this is 1 - spread/5 over N repeated
        # sampling passes, not a probability the score is correct — the old
        # name overstated it, especially now that N defaults to 1 (engine.py).
        "pass_stability": row["confidence"],
        "high_spread": bool(row["high_spread"]),
        "n_passes": row["n_passes"],
        "passes": [_raw_pass_out(p) for p in raw_passes],
    }


def _load_context(conn, assessment_id: str, criterion_id: str, instructor_id: str):
    assessment = conn.execute("SELECT * FROM assessments WHERE id = ?", (assessment_id,)).fetchone()
    if assessment is None or assessment["instructor_id"] != instructor_id:
        raise HTTPException(404, "Assessment not found")
    personalized = conn.execute(
        "SELECT * FROM score_aggregates WHERE assessment_id=? AND criterion_id=? AND path='personalized'",
        (assessment_id, criterion_id),
    ).fetchone()
    exemplar = conn.execute(
        "SELECT * FROM score_aggregates WHERE assessment_id=? AND criterion_id=? AND path='exemplar'",
        (assessment_id, criterion_id),
    ).fetchone()
    personalized_passes = conn.execute(
        "SELECT * FROM score_records_v2 WHERE assessment_id=? AND criterion_id=? AND path='personalized' ORDER BY pass_index",
        (assessment_id, criterion_id),
    ).fetchall()
    exemplar_passes = conn.execute(
        "SELECT * FROM score_records_v2 WHERE assessment_id=? AND criterion_id=? AND path='exemplar' ORDER BY pass_index",
        (assessment_id, criterion_id),
    ).fetchall()
    divergence = conn.execute(
        "SELECT * FROM divergence_records WHERE assessment_id=? AND criterion_id=?", (assessment_id, criterion_id)
    ).fetchone()
    override = conn.execute(
        "SELECT * FROM score_overrides WHERE assessment_id=? AND criterion_id=?", (assessment_id, criterion_id)
    ).fetchone()
    essay = conn.execute("SELECT * FROM essays WHERE id = ?", (assessment["essay_id"],)).fetchone()
    return (
        assessment, personalized, exemplar, personalized_passes, exemplar_passes,
        divergence, override, essay,
    )


@router.get("/review")
def get_review(assessment_id: str, criterion_id: str, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        (
            assessment, personalized, exemplar, personalized_passes, exemplar_passes,
            divergence, override, _,
        ) = _load_context(conn, assessment_id, criterion_id, instructor_id)
        criterion_row = conn.execute(
            "SELECT statement, anchors_json FROM criteria WHERE rubric_id = ? AND rubric_version = ? AND criterion_id = ?",
            (assessment["rubric_id"], assessment["rubric_version"], criterion_id),
        ).fetchone()
    return {
        "criterion_id": criterion_id,
        "criterion": {
            "statement": criterion_row["statement"],
            "anchors": json.loads(criterion_row["anchors_json"]),
        } if criterion_row else None,
        "personalized": _aggregate_out(personalized, personalized_passes),
        "exemplar": _aggregate_out(exemplar, exemplar_passes),
        "divergence": {
            "score_diff": divergence["score_diff"],
            "anchor_mismatch": bool(divergence["anchor_mismatch"]),
            "no_evidence_asymmetry": bool(divergence["no_evidence_asymmetry"]),
            "exceeds_threshold": bool(divergence["exceeds_threshold"]),
        } if divergence else None,
        "current_override": {
            "new_score": override["new_score"],
            "new_rationale": override["new_rationale"],
            "overridden_by": override["overridden_by"],
            "created_at": override["created_at"],
        } if override else None,
    }


def _write_override_and_precedent(
    conn, assessment, essay, instructor_id: str, criterion_id: str, new_score: int, new_rationale: str,
    overridden_by: str, from_evidence: list[dict] | None,
):
    from datetime import UTC, datetime
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """INSERT INTO score_overrides (assessment_id, criterion_id, new_score, new_rationale, overridden_by, created_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT (assessment_id, criterion_id)
           DO UPDATE SET new_score=excluded.new_score, new_rationale=excluded.new_rationale,
                         overridden_by=excluded.overridden_by, created_at=excluded.created_at""",
        (assessment["id"], criterion_id, new_score, new_rationale, overridden_by, now),
    )

    # Write-back into personalized corpus regardless of override direction (§9),
    # scoped to the same instructor/course/assignment/criterion. The excerpt
    # text is a quote already grounded in this essay (from the pass whose
    # score/evidence the override is based on) — an override's free-text
    # rationale isn't itself essay text, so it can't stand in as the excerpt.
    from app.grading.evidence import verify_quote
    assignment = conn.execute(
        "SELECT * FROM assignments WHERE id = (SELECT assignment_id FROM essays WHERE id = ?)", (essay["id"],)
    ).fetchone()
    grounded_quote = next(
        (e["quote"] for e in (from_evidence or []) if verify_quote(e["quote"], essay["text"])), None
    )
    if grounded_quote:
        try:
            insert_personalized_excerpt(
                conn,
                rubric_id=assessment["rubric_id"], criterion_id=criterion_id, instructor_id=instructor_id,
                course_id=assignment["course_id"] if assignment else None,
                assignment_id=assignment["id"] if assignment else None,
                excerpt_text=grounded_quote, score=new_score, anchor_matched=new_score,
                rationale=new_rationale, source="review_writeback", added_by=overridden_by,
                source_essay_text=essay["text"],
            )
        except Exception:
            pass  # not essay-grounded enough to become precedent; override itself still stands


@router.post("/override")
def override_score(
    assessment_id: str, criterion_id: str, body: OverrideRequest, user: CurrentUser = Depends(get_current_user)
):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        assessment, personalized, _, _, _, _, _, essay = _load_context(conn, assessment_id, criterion_id, instructor_id)
        evidence = json.loads(personalized["evidence_json"]) if personalized else None
        _write_override_and_precedent(
            conn, assessment, essay, instructor_id, criterion_id, body.new_score, body.new_rationale,
            user.user_id, evidence,
        )
        conn.commit()
    return {"status": "ok"}


@router.post("/adopt-exemplar")
def adopt_exemplar(assessment_id: str, criterion_id: str, user: CurrentUser = Depends(get_current_user)):
    instructor_id = user.scoped_instructor_id()
    with get_connection() as conn:
        assessment, _, exemplar, _, _, _, _, essay = _load_context(conn, assessment_id, criterion_id, instructor_id)
        if exemplar is None or exemplar["is_no_evidence"]:
            raise HTTPException(400, "Exemplar path has no score to adopt")
        evidence = json.loads(exemplar["evidence_json"])
        # exemplar["score"] is the multi-pass median (score_aggregates.score,
        # REAL) — round to the nearest whole point for the override/precedent
        # columns, which store a single discrete 0-5 score. Round half UP so
        # a 2.5 median -> 3, matching the frontend's Math.round of the same
        # value (Python's round() is banker's rounding: 2.5 -> 2, inconsistent).
        adopted_score = int(exemplar["score"] + 0.5)
        _write_override_and_precedent(
            conn, assessment, essay, instructor_id, criterion_id, adopted_score, exemplar["rationale"],
            user.user_id, evidence,
        )
        conn.commit()
    return {"status": "ok"}
