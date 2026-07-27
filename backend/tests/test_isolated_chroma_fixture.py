import pytest

from app import chroma_store
from app.grading.evidence import EvidenceVerificationError
from app.grading.retrieval import Scope, assemble_personalized_pool, query_exemplar_pool
from app.repositories.excerpts import insert_exemplar_excerpt, insert_personalized_excerpt


def _make_source_essay(isolated_db, essay_id: str, text: str) -> None:
    isolated_db.execute(
        "INSERT INTO exemplar_source_essays (source_essay_id, text) VALUES (?, ?)",
        (essay_id, text),
    )
    isolated_db.commit()


def test_isolated_chroma_points_at_a_throwaway_dir(isolated_chroma, tmp_path):
    assert chroma_store.CHROMA_DIR == tmp_path / "chroma"
    assert chroma_store.CHROMA_DIR.exists()


def test_exemplar_excerpt_roundtrips_through_real_chroma(isolated_db, isolated_chroma):
    essay_text = "The rain in Spain falls mainly on the plain."
    _make_source_essay(isolated_db, "essay-1", essay_text)

    insert_exemplar_excerpt(
        isolated_db,
        rubric_id="r1",
        rubric_version="v1",
        criterion_id="C1",
        excerpt_text="The rain in Spain falls mainly on the plain.",
        score=4,
        anchor_matched=4,
        rationale="solid",
        source_essay_id="essay-1",
        is_preseeded=False,
    )
    isolated_db.commit()

    pool = query_exemplar_pool("rain falling in spain", "C1", "r1", "v1")
    assert len(pool) == 1
    assert pool[0]["metadata"]["criterion_id"] == "C1"
    assert pool[0]["document"] == "The rain in Spain falls mainly on the plain."


def test_personalized_excerpt_roundtrips_and_is_retrievable_at_scope(isolated_db, isolated_chroma):
    essay_text = "Climate change requires urgent, coordinated global action."
    insert_personalized_excerpt(
        isolated_db,
        rubric_id="r1",
        criterion_id="W1d-1",
        instructor_id="instr-1",
        course_id="course-1",
        assignment_id="assign-1",
        excerpt_text="Climate change requires urgent, coordinated global action.",
        score=3,
        anchor_matched=3,
        rationale="on topic",
        source="manual",
        added_by="instr-1",
        source_essay_text=essay_text,
    )
    isolated_db.commit()

    pool = assemble_personalized_pool(
        "urgent coordinated global action",
        Scope(instructor_id="instr-1", course_id="course-1", assignment_id="assign-1"),
        "W1d-1",
        "r1",
    )
    assert len(pool) == 1
    assert pool[0]["metadata"]["assignment_id"] == "assign-1"
    assert pool[0]["metadata"]["instructor_id"] == "instr-1"


def test_personalized_excerpt_not_retrievable_for_a_different_instructor(isolated_db, isolated_chroma):
    essay_text = "Climate change requires urgent, coordinated global action."
    insert_personalized_excerpt(
        isolated_db,
        rubric_id="r1",
        criterion_id="W1d-1",
        instructor_id="instr-1",
        course_id="course-1",
        assignment_id="assign-1",
        excerpt_text="Climate change requires urgent, coordinated global action.",
        score=3,
        anchor_matched=3,
        rationale="on topic",
        source="manual",
        added_by="instr-1",
        source_essay_text=essay_text,
    )
    isolated_db.commit()

    pool = assemble_personalized_pool(
        "urgent coordinated global action",
        Scope(instructor_id="instr-2", course_id="course-1", assignment_id="assign-1"),
        "W1d-1",
        "r1",
    )
    assert pool == []


def test_fabricated_quote_is_rejected_even_with_real_chroma(isolated_db, isolated_chroma):
    _make_source_essay(isolated_db, "essay-2", "A short, unrelated essay about trees.")
    with pytest.raises(EvidenceVerificationError):
        insert_exemplar_excerpt(
            isolated_db,
            rubric_id="r1",
            rubric_version="v1",
            criterion_id="C1",
            excerpt_text="This quote does not appear anywhere in the source essay.",
            score=4,
            anchor_matched=4,
            rationale="bad",
            source_essay_id="essay-2",
            is_preseeded=False,
        )
    # Rejected insert must not have reached Chroma either.
    pool = query_exemplar_pool("this quote does not appear", "C1", "r1", "v1")
    assert pool == []


def test_chroma_state_does_not_leak_across_tests(isolated_db, isolated_chroma):
    # If test_exemplar_excerpt_roundtrips_through_real_chroma's data leaked
    # in via a stale cached client, this would find a stray result.
    pool = query_exemplar_pool("rain falling in spain", "C1", "r1", "v1")
    assert pool == []
