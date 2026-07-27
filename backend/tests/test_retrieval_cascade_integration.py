"""Real Chroma+SQLite roundtrip for the personalized retrieval cascade (T9).

test_retrieval_cascade_mocked.py (T8) proves the cascade's control flow
against a mocked chroma_store.query. This file proves the same tiers work
against a REAL Chroma query - catching filter-syntax bugs (the actual
`where` clause, the None->"" scope-sentinel convention) that a mock
structurally cannot catch. It also supplies the two data shapes the
strategy doc identified as missing from the existing dev corpus: a Tier 1
hit and a Tier 1+2 partial fill. Both existing shapes (fully empty, and
Tier-3-only) are covered too, so the whole cascade is exercised for real.
"""
from app.grading.retrieval import Scope, assemble_personalized_pool, query_exemplar_pool
from app.repositories.excerpts import insert_exemplar_excerpt, insert_personalized_excerpt


def _insert_personalized(isolated_db, *, instructor_id, course_id, assignment_id, criterion_id, text, score=3):
    return insert_personalized_excerpt(
        isolated_db,
        rubric_id="r1",
        criterion_id=criterion_id,
        instructor_id=instructor_id,
        course_id=course_id,
        assignment_id=assignment_id,
        excerpt_text=text,
        score=score,
        anchor_matched=score,
        rationale="rationale",
        source="manual",
        added_by=instructor_id,
        source_essay_text=text,
    )


def test_tier1_real_data_fills_the_pool_without_touching_tier2_or_tier3(isolated_db, isolated_chroma):
    for i in range(5):
        _insert_personalized(
            isolated_db,
            instructor_id="i1", course_id="c1", assignment_id="a1", criterion_id="W1d-1",
            text=f"Assignment-scoped excerpt number {i} about the thesis statement.",
        )
    isolated_db.commit()

    pool = assemble_personalized_pool(
        "the thesis statement", Scope(instructor_id="i1", course_id="c1", assignment_id="a1"), "W1d-1", "r1",
    )

    assert len(pool) == 5
    assert all(p["metadata"]["assignment_id"] == "a1" for p in pool)


def test_tier1_and_tier2_partial_fill_with_real_data(isolated_db, isolated_chroma):
    for i in range(2):
        _insert_personalized(
            isolated_db,
            instructor_id="i1", course_id="c1", assignment_id="a1", criterion_id="W1d-1",
            text=f"Assignment-scoped excerpt {i} discussing evidence use.",
        )
    for i in range(3):
        _insert_personalized(
            isolated_db,
            instructor_id="i1", course_id="c1", assignment_id=None, criterion_id="W1d-1",
            text=f"Course-scoped excerpt {i} discussing evidence use.",
        )
    isolated_db.commit()

    pool = assemble_personalized_pool(
        "discussing evidence use", Scope(instructor_id="i1", course_id="c1", assignment_id="a1"), "W1d-1", "r1",
    )

    assert len(pool) == 5
    assignment_scoped = [p for p in pool if p["metadata"]["assignment_id"] == "a1"]
    course_scoped = [p for p in pool if p["metadata"]["assignment_id"] == ""]
    assert len(assignment_scoped) == 2
    assert len(course_scoped) == 3
    assert all(p["metadata"]["course_id"] == "c1" for p in course_scoped)


def test_tier3_fallback_with_only_instructor_default_data(isolated_db, isolated_chroma):
    for i in range(3):
        _insert_personalized(
            isolated_db,
            instructor_id="i1", course_id=None, assignment_id=None, criterion_id="W1d-1",
            text=f"Instructor-default excerpt {i} about topic sentences.",
        )
    isolated_db.commit()

    pool = assemble_personalized_pool(
        "topic sentences", Scope(instructor_id="i1", course_id="c1", assignment_id="a1"), "W1d-1", "r1",
    )

    assert len(pool) == 3
    assert all(p["metadata"]["course_id"] == "" for p in pool)
    assert all(p["metadata"]["assignment_id"] == "" for p in pool)


def test_empty_pool_when_no_excerpts_exist_for_the_criterion(isolated_db, isolated_chroma):
    _insert_personalized(
        isolated_db,
        instructor_id="i1", course_id=None, assignment_id=None, criterion_id="L1-1",
        text="An excerpt for a completely different criterion.",
    )
    isolated_db.commit()

    pool = assemble_personalized_pool(
        "anything", Scope(instructor_id="i1", course_id="c1", assignment_id="a1"), "W1d-1", "r1",
    )

    assert pool == []


def test_exemplar_retrieval_is_scoped_to_its_own_criterion(isolated_db, isolated_chroma):
    isolated_db.execute(
        "INSERT INTO exemplar_source_essays (source_essay_id, text) VALUES (?, ?)",
        ("essay-1", "Sentence for criterion one. Sentence for criterion two."),
    )
    isolated_db.commit()

    insert_exemplar_excerpt(
        isolated_db,
        rubric_id="r1", rubric_version="v1", criterion_id="C1",
        excerpt_text="Sentence for criterion one.", score=4, anchor_matched=4,
        rationale="r", source_essay_id="essay-1", is_preseeded=False,
    )
    insert_exemplar_excerpt(
        isolated_db,
        rubric_id="r1", rubric_version="v1", criterion_id="C2",
        excerpt_text="Sentence for criterion two.", score=3, anchor_matched=3,
        rationale="r", source_essay_id="essay-1", is_preseeded=False,
    )
    isolated_db.commit()

    pool_c1 = query_exemplar_pool("criterion one", "C1", "r1", "v1")
    pool_c2 = query_exemplar_pool("criterion two", "C2", "r1", "v1")

    assert len(pool_c1) == 1
    assert pool_c1[0]["metadata"]["criterion_id"] == "C1"
    assert len(pool_c2) == 1
    assert pool_c2[0]["metadata"]["criterion_id"] == "C2"
