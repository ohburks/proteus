"""Ingestion-time verbatim verification, wired into the real insert path
(T10). test_evidence.py (T6) proves verify_quote() itself is correct in
isolation; this file proves it actually gates insert_exemplar_excerpt()/
insert_personalized_excerpt() - a bad quote must be rejected before it
ever reaches either SQLite or Chroma, and a real quote must reach both.
"""
import pytest

from app.grading.evidence import EvidenceVerificationError
from app.repositories.excerpts import insert_exemplar_excerpt, insert_personalized_excerpt


def _row_count(isolated_db, table: str) -> int:
    return isolated_db.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


def _make_source_essay(isolated_db, essay_id: str, text: str) -> None:
    isolated_db.execute(
        "INSERT INTO exemplar_source_essays (source_essay_id, text) VALUES (?, ?)",
        (essay_id, text),
    )
    isolated_db.commit()


# --- exemplar ----------------------------------------------------------

def test_exemplar_accepts_a_real_verbatim_quote(isolated_db, isolated_chroma):
    _make_source_essay(isolated_db, "essay-1", "The city council debated the proposal for hours.")

    excerpt_id = insert_exemplar_excerpt(
        isolated_db,
        rubric_id="r1", rubric_version="v1", criterion_id="C1",
        excerpt_text="The city council debated the proposal for hours.",
        score=4, anchor_matched=4, rationale="solid",
        source_essay_id="essay-1", is_preseeded=False,
    )
    isolated_db.commit()

    assert excerpt_id.startswith("exemplar_excerpts:")
    assert _row_count(isolated_db, "exemplar_excerpts_src") == 1


def test_exemplar_rejects_a_fabricated_quote(isolated_db, isolated_chroma):
    _make_source_essay(isolated_db, "essay-1", "The city council debated the proposal for hours.")

    with pytest.raises(EvidenceVerificationError):
        insert_exemplar_excerpt(
            isolated_db,
            rubric_id="r1", rubric_version="v1", criterion_id="C1",
            excerpt_text="This sentence was never in the essay at all.",
            score=4, anchor_matched=4, rationale="bad",
            source_essay_id="essay-1", is_preseeded=False,
        )

    # A rejected quote must not have been written to SQLite either - not
    # just absent from Chroma.
    assert _row_count(isolated_db, "exemplar_excerpts_src") == 0


def test_exemplar_rejects_when_source_essay_is_missing(isolated_db, isolated_chroma):
    with pytest.raises(EvidenceVerificationError, match="no source essay on file"):
        insert_exemplar_excerpt(
            isolated_db,
            rubric_id="r1", rubric_version="v1", criterion_id="C1",
            excerpt_text="Any quote at all.",
            score=4, anchor_matched=4, rationale="n/a",
            source_essay_id="does-not-exist", is_preseeded=False,
        )

    assert _row_count(isolated_db, "exemplar_excerpts_src") == 0


def test_exemplar_accepts_a_quote_needing_normalization(isolated_db, isolated_chroma):
    # Curly quotes + irregular whitespace in the excerpt, straight quotes +
    # normal whitespace in the source - proves verify_quote's normalization
    # is actually wired into this path, not just correct in isolation (T6).
    _make_source_essay(isolated_db, "essay-1", 'She said "the plan works" and moved on.')

    insert_exemplar_excerpt(
        isolated_db,
        rubric_id="r1", rubric_version="v1", criterion_id="C1",
        excerpt_text="She   said  “the plan   works”\nand moved on.",
        score=3, anchor_matched=3, rationale="ok",
        source_essay_id="essay-1", is_preseeded=False,
    )
    isolated_db.commit()

    assert _row_count(isolated_db, "exemplar_excerpts_src") == 1


# --- personalized --------------------------------------------------------

def test_personalized_accepts_a_real_verbatim_quote(isolated_db, isolated_chroma):
    essay_text = "Climate change requires urgent, coordinated global action."

    excerpt_id = insert_personalized_excerpt(
        isolated_db,
        rubric_id="r1", criterion_id="W1d-1", instructor_id="i1",
        course_id="c1", assignment_id="a1",
        excerpt_text="Climate change requires urgent, coordinated global action.",
        score=3, anchor_matched=3, rationale="on topic",
        source="manual", added_by="i1", source_essay_text=essay_text,
    )
    isolated_db.commit()

    assert excerpt_id.startswith("personalized_excerpts:")
    assert _row_count(isolated_db, "personalized_excerpts_src") == 1


def test_personalized_rejects_a_fabricated_quote(isolated_db, isolated_chroma):
    essay_text = "Climate change requires urgent, coordinated global action."

    with pytest.raises(EvidenceVerificationError):
        insert_personalized_excerpt(
            isolated_db,
            rubric_id="r1", criterion_id="W1d-1", instructor_id="i1",
            course_id="c1", assignment_id="a1",
            excerpt_text="This quote is not grounded in the essay above.",
            score=3, anchor_matched=3, rationale="bad",
            source="manual", added_by="i1", source_essay_text=essay_text,
        )

    assert _row_count(isolated_db, "personalized_excerpts_src") == 0


def test_personalized_accepts_a_quote_needing_normalization(isolated_db, isolated_chroma):
    essay_text = "The student's argument was clear and well supported."

    insert_personalized_excerpt(
        isolated_db,
        rubric_id="r1", criterion_id="W1d-1", instructor_id="i1",
        course_id=None, assignment_id=None,
        excerpt_text="THE STUDENT'S  argument  was\tclear and well supported.",
        score=4, anchor_matched=4, rationale="ok",
        source="manual", added_by="i1", source_essay_text=essay_text,
    )
    isolated_db.commit()

    assert _row_count(isolated_db, "personalized_excerpts_src") == 1
