"""Override write-back creates a retrievable personalized precedent (T11).

Calls the real _write_override_and_precedent() (not the HTTP endpoint, to
avoid standing up auth) against T1+T2's isolated DB/Chroma, then confirms
the new excerpt actually surfaces in a subsequent assemble_personalized_pool
call at the assignment it was written for - proving the write-back isn't
just "a row exists somewhere" but genuinely closes the loop back into
retrieval.
"""
from datetime import UTC, datetime

from app.grading.retrieval import Scope, assemble_personalized_pool
from app.routers.review import _write_override_and_precedent


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _seed_assignment_essay_assessment(isolated_db, *, instructor_id, course_id, assignment_id, essay_id,
                                       assessment_id, essay_text, rubric_id="r1", rubric_version="v1"):
    now = _now()
    isolated_db.execute(
        "INSERT INTO courses (id, instructor_id, name, created_at) VALUES (?,?,?,?)",
        (course_id, instructor_id, "Course", now),
    )
    isolated_db.execute(
        """INSERT INTO assignments (id, course_id, name, rubric_id, rubric_version, created_at)
           VALUES (?,?,?,?,?,?)""",
        (assignment_id, course_id, "Assignment", rubric_id, rubric_version, now),
    )
    isolated_db.execute(
        "INSERT INTO essays (id, assignment_id, student_id, text, created_at) VALUES (?,?,?,?,?)",
        (essay_id, assignment_id, None, essay_text, now),
    )
    isolated_db.execute(
        """INSERT INTO assessments
           (id, essay_id, instructor_id, student_id, rubric_id, rubric_version, provider, model, status, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (assessment_id, essay_id, instructor_id, None, rubric_id, rubric_version, "openai", "gpt-4o-mini",
         "complete", now),
    )
    isolated_db.commit()

    assessment = isolated_db.execute("SELECT * FROM assessments WHERE id = ?", (assessment_id,)).fetchone()
    essay = isolated_db.execute("SELECT * FROM essays WHERE id = ?", (essay_id,)).fetchone()
    return assessment, essay


def test_override_writeback_creates_a_precedent_retrievable_at_the_same_assignment(isolated_db, isolated_chroma):
    essay_text = "Climate change requires urgent, coordinated global action from every nation."
    assessment, essay = _seed_assignment_essay_assessment(
        isolated_db, instructor_id="i1", course_id="c1", assignment_id="a1",
        essay_id="e1", assessment_id="as1", essay_text=essay_text,
    )

    _write_override_and_precedent(
        isolated_db, assessment, essay, instructor_id="i1", criterion_id="W1d-1",
        new_score=4, new_rationale="Strong, specific call to action.",
        overridden_by="instructor-user",
        from_evidence=[{"quote": "Climate change requires urgent, coordinated global action from every nation."}],
        original_anchor_matched=3,
    )
    isolated_db.commit()

    pool = assemble_personalized_pool(
        "urgent coordinated global action",
        Scope(instructor_id="i1", course_id="c1", assignment_id="a1"),
        "W1d-1", "r1",
    )

    assert len(pool) == 1
    assert pool[0]["metadata"]["source"] == "review_writeback"
    assert pool[0]["metadata"]["assignment_id"] == "a1"
    assert pool[0]["metadata"]["score"] == 4


def test_override_writeback_uses_original_pass_anchor_not_new_score(isolated_db, isolated_chroma):
    essay_text = "The argument lacked sufficient supporting detail throughout."
    assessment, essay = _seed_assignment_essay_assessment(
        isolated_db, instructor_id="i1", course_id="c1", assignment_id="a1",
        essay_id="e1", assessment_id="as1", essay_text=essay_text,
    )

    _write_override_and_precedent(
        isolated_db, assessment, essay, instructor_id="i1", criterion_id="W1d-1",
        new_score=5, new_rationale="Actually much stronger than originally scored.",
        overridden_by="instructor-user",
        from_evidence=[{"quote": "The argument lacked sufficient supporting detail throughout."}],
        original_anchor_matched=2,
    )
    isolated_db.commit()

    pool = assemble_personalized_pool(
        "argument lacked supporting detail",
        Scope(instructor_id="i1", course_id="c1", assignment_id="a1"),
        "W1d-1", "r1",
    )

    assert pool[0]["metadata"]["score"] == 5
    assert pool[0]["metadata"]["anchor_matched"] == 2


def test_override_still_stands_when_no_evidence_quote_is_grounded(isolated_db, isolated_chroma):
    essay_text = "A short essay about municipal budgeting decisions."
    assessment, essay = _seed_assignment_essay_assessment(
        isolated_db, instructor_id="i1", course_id="c1", assignment_id="a1",
        essay_id="e1", assessment_id="as1", essay_text=essay_text,
    )

    _write_override_and_precedent(
        isolated_db, assessment, essay, instructor_id="i1", criterion_id="W1d-1",
        new_score=4, new_rationale="Overridden on instructor judgment alone.",
        overridden_by="instructor-user",
        from_evidence=[{"quote": "This quote does not appear anywhere in the essay."}],
        original_anchor_matched=3,
    )
    isolated_db.commit()

    override_row = isolated_db.execute(
        "SELECT * FROM score_overrides WHERE assessment_id=? AND criterion_id=?", ("as1", "W1d-1")
    ).fetchone()
    assert override_row["new_score"] == 4

    pool = assemble_personalized_pool(
        "municipal budgeting", Scope(instructor_id="i1", course_id="c1", assignment_id="a1"), "W1d-1", "r1",
    )
    assert pool == []


def test_override_upsert_replaces_the_previous_override(isolated_db, isolated_chroma):
    essay_text = "An essay about renewable energy policy."
    assessment, essay = _seed_assignment_essay_assessment(
        isolated_db, instructor_id="i1", course_id="c1", assignment_id="a1",
        essay_id="e1", assessment_id="as1", essay_text=essay_text,
    )

    _write_override_and_precedent(
        isolated_db, assessment, essay, instructor_id="i1", criterion_id="W1d-1",
        new_score=2, new_rationale="First override.",
        overridden_by="instructor-user", from_evidence=None,
    )
    isolated_db.commit()
    _write_override_and_precedent(
        isolated_db, assessment, essay, instructor_id="i1", criterion_id="W1d-1",
        new_score=5, new_rationale="Corrected override.",
        overridden_by="instructor-user", from_evidence=None,
    )
    isolated_db.commit()

    rows = isolated_db.execute(
        "SELECT * FROM score_overrides WHERE assessment_id=? AND criterion_id=?", ("as1", "W1d-1")
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["new_score"] == 5
    assert rows[0]["new_rationale"] == "Corrected override."
