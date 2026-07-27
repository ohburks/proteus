"""Output-selection precedence: override > personalized > incomplete, and
divergence never changes which score is output - only whether it's flagged
for review (T13).
"""
from datetime import UTC, datetime

from app.routers.assessments import _criterion_outputs


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _seed_assessment(isolated_db, assessment_id="as1"):
    now = _now()
    isolated_db.execute(
        "INSERT INTO courses (id, instructor_id, name, created_at) VALUES (?,?,?,?)",
        ("c1", "i1", "Course", now),
    )
    isolated_db.execute(
        """INSERT INTO assignments (id, course_id, name, rubric_id, rubric_version, created_at)
           VALUES (?,?,?,?,?,?)""",
        ("a1", "c1", "Assignment", "r1", "v1", now),
    )
    isolated_db.execute(
        "INSERT INTO essays (id, assignment_id, student_id, text, created_at) VALUES (?,?,?,?,?)",
        ("e1", "a1", None, "An essay.", now),
    )
    isolated_db.execute(
        """INSERT INTO assessments
           (id, essay_id, instructor_id, student_id, rubric_id, rubric_version, provider, model, status, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (assessment_id, "e1", "i1", None, "r1", "v1", "openai", "gpt-4o-mini", "complete", now),
    )
    isolated_db.commit()
    return isolated_db.execute("SELECT * FROM assessments WHERE id = ?", (assessment_id,)).fetchone()


def _seed_aggregate(isolated_db, assessment_id, criterion_id, path, score, high_spread=0):
    isolated_db.execute(
        """INSERT INTO score_aggregates
           (assessment_id, criterion_id, path, score, is_no_evidence, anchor_matched,
            evidence_json, precedent_ids_json, rationale, spread, confidence, high_spread,
            n_passes, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (assessment_id, criterion_id, path, score, 0, score, "[]", "[]", "r", 0.0, 0.9, high_spread, 1, _now()),
    )
    isolated_db.commit()


def _seed_divergence(isolated_db, assessment_id, criterion_id, score_diff, exceeds_threshold):
    isolated_db.execute(
        """INSERT INTO divergence_records
           (assessment_id, criterion_id, score_diff, anchor_mismatch, no_evidence_asymmetry,
            exceeds_threshold, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (assessment_id, criterion_id, score_diff, 0, 0, int(exceeds_threshold), _now()),
    )
    isolated_db.commit()


def _seed_override(isolated_db, assessment_id, criterion_id, new_score):
    isolated_db.execute(
        """INSERT INTO score_overrides (assessment_id, criterion_id, new_score, new_rationale, overridden_by, created_at)
           VALUES (?,?,?,?,?,?)""",
        (assessment_id, criterion_id, new_score, "instructor correction", "instructor-user", _now()),
    )
    isolated_db.commit()


def _output_for(isolated_db, assessment, criterion_id: str) -> dict:
    outputs = {o["criterion_id"]: o for o in _criterion_outputs(isolated_db, assessment)}
    return outputs[criterion_id]


def test_personalized_score_is_output_even_with_high_divergence(isolated_db):
    assessment = _seed_assessment(isolated_db)
    _seed_aggregate(isolated_db, "as1", "W1d-1", "exemplar", score=1)
    _seed_aggregate(isolated_db, "as1", "W1d-1", "personalized", score=5)
    _seed_divergence(isolated_db, "as1", "W1d-1", score_diff=4, exceeds_threshold=True)

    out = _output_for(isolated_db, assessment, "W1d-1")

    assert out["output_score"] == 5
    assert out["output_source"] == "personalized"
    assert out["exceeds_threshold"] is True
    assert "divergent" in out["review_reasons"]


def test_override_wins_over_personalized_even_with_high_divergence(isolated_db):
    assessment = _seed_assessment(isolated_db)
    _seed_aggregate(isolated_db, "as1", "W1d-1", "exemplar", score=1)
    _seed_aggregate(isolated_db, "as1", "W1d-1", "personalized", score=5)
    _seed_divergence(isolated_db, "as1", "W1d-1", score_diff=4, exceeds_threshold=True)
    _seed_override(isolated_db, "as1", "W1d-1", new_score=2)

    out = _output_for(isolated_db, assessment, "W1d-1")

    assert out["output_score"] == 2
    assert out["output_source"] == "override"
    # Divergence is still surfaced as a reason even though it's overridden -
    # the override doesn't erase the fact that the two paths disagreed.
    assert out["exceeds_threshold"] is True
    assert "divergent" in out["review_reasons"]


def test_low_divergence_does_not_get_flagged(isolated_db):
    assessment = _seed_assessment(isolated_db)
    _seed_aggregate(isolated_db, "as1", "W1d-1", "exemplar", score=4)
    _seed_aggregate(isolated_db, "as1", "W1d-1", "personalized", score=4)
    _seed_divergence(isolated_db, "as1", "W1d-1", score_diff=0, exceeds_threshold=False)

    out = _output_for(isolated_db, assessment, "W1d-1")

    assert out["output_score"] == 4
    assert out["output_source"] == "personalized"
    assert out["exceeds_threshold"] is False
    assert "divergent" not in out["review_reasons"]


def test_incomplete_when_personalized_has_not_finished_and_no_override(isolated_db):
    assessment = _seed_assessment(isolated_db)
    # Only the exemplar path has a row - personalized hasn't finished, and
    # there's no override, so nothing can be output yet.
    _seed_aggregate(isolated_db, "as1", "W1d-1", "exemplar", score=4)

    out = _output_for(isolated_db, assessment, "W1d-1")

    assert out["output_score"] is None
    assert out["output_source"] == "incomplete"
