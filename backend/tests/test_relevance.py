import json

from app.grading import progress
from app.grading.relevance import run_relevance_check
from app.routers import assessments


ASSIGNMENT = {
    "id": "assignment-1",
    "course_id": "course-1",
    "rubric_id": "rubric-1",
    "rubric_version": "1",
}
ESSAY_TEXT = "Hospital systems must isolate clinical networks from public Wi-Fi."


def _seed_assessment(conn, *, prompt: str | None = "Explain the causes and effects of climate change.") -> None:
    now = "2026-07-27T12:00:00+00:00"
    conn.execute(
        """INSERT INTO rubrics
           (rubric_id, version, genre, notes, assignment_guidance, raw_json, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        ("rubric-1", "1", "essay", "", "", "{}", now),
    )
    conn.execute(
        "INSERT INTO courses (id, instructor_id, name, created_at) VALUES (?,?,?,?)",
        ("course-1", "instructor-1", "Course", now),
    )
    conn.execute(
        """INSERT INTO assignments
           (id, course_id, name, rubric_id, rubric_version, created_at)
           VALUES (?,?,?,?,?,?)""",
        ("assignment-1", "course-1", "Climate essay", "rubric-1", "1", now),
    )
    conn.execute(
        """INSERT INTO assignment_profile
           (assignment_id, course_id, prompt_text, format_expectations,
            criterion_emphasis_notes, common_pitfalls, updated_at)
           VALUES (?,?,?,?,?,?,?)""",
        ("assignment-1", "course-1", prompt, "A complete essay", None, None, now),
    )
    conn.execute(
        "INSERT INTO essays (id, assignment_id, student_id, text, created_at) VALUES (?,?,?,?,?)",
        ("essay-1", "assignment-1", None, ESSAY_TEXT, now),
    )
    conn.execute(
        """INSERT INTO assessments
           (id, essay_id, instructor_id, student_id, rubric_id, rubric_version,
            provider, model, status, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            "assessment-1",
            "essay-1",
            "instructor-1",
            None,
            "rubric-1",
            "1",
            "test",
            "test-model",
            "running",
            now,
        ),
    )
    conn.commit()


def _relevance_response(
    *,
    decision: str,
    submission_type: str,
    responds: bool,
    sufficient: bool,
    quote: str = ESSAY_TEXT,
) -> dict:
    return {
        "submissionType": submission_type,
        "respondsToPrompt": responds,
        "hasSufficientContent": sufficient,
        "decision": decision,
        "rationale": "The document discusses hospital networks, not climate change.",
        "evidence": [{"quote": quote, "reasoning": "This is the document's actual subject."}],
    }


def test_relevance_is_one_standalone_call_with_untrusted_submission_boundary(
    isolated_db, llm_client_factory
):
    _seed_assessment(isolated_db)
    client = llm_client_factory(
        [
            _relevance_response(
                decision="reject",
                submission_type="source_material",
                responds=False,
                sufficient=True,
            )
        ]
    )

    result = run_relevance_check(
        isolated_db,
        client,
        assessment_id="assessment-1",
        assignment_id="assignment-1",
        essay_text=ESSAY_TEXT,
    )

    assert result.decision == "reject"
    assert len(client.calls) == 1
    assert "[SECURITY BOUNDARY]" in client.calls[0]["system_prompt"]
    assert "Explain the causes and effects of climate change." in client.calls[0]["system_prompt"]
    assert client.calls[0]["user_prompt"].startswith("[UNTRUSTED SUBMISSION]")
    stored = isolated_db.execute(
        "SELECT * FROM relevance_checks WHERE assessment_id = 'assessment-1'"
    ).fetchone()
    assert stored["decision"] == "reject"
    assert json.loads(stored["evidence_json"])[0]["quote"] == ESSAY_TEXT


def test_unverifiable_rejection_evidence_falls_back_to_manual_review(
    isolated_db, llm_client_factory
):
    _seed_assessment(isolated_db)
    client = llm_client_factory(
        [
            _relevance_response(
                decision="reject",
                submission_type="source_material",
                responds=False,
                sufficient=True,
                quote="This quote is not in the submission.",
            )
        ]
    )

    result = run_relevance_check(
        isolated_db,
        client,
        assessment_id="assessment-1",
        assignment_id="assignment-1",
        essay_text=ESSAY_TEXT,
    )

    assert result.decision == "manual_review"
    assert result.evidence == []
    assert len(client.calls) == 1


def test_internally_inconsistent_rejection_falls_back_to_manual_review(
    isolated_db, llm_client_factory
):
    _seed_assessment(isolated_db)
    client = llm_client_factory(
        [
            _relevance_response(
                decision="reject",
                submission_type="student_response",
                responds=True,
                sufficient=True,
            )
        ]
    )

    result = run_relevance_check(
        isolated_db,
        client,
        assessment_id="assessment-1",
        assignment_id="assignment-1",
        essay_text=ESSAY_TEXT,
    )

    assert result.decision == "manual_review"
    assert "internally inconsistent" in result.rationale


def test_malformed_relevance_response_falls_back_to_manual_review(isolated_db):
    _seed_assessment(isolated_db)

    class MalformedClient:
        calls = 0

        def complete(self, system_prompt, user_prompt, emit=None):
            self.calls += 1
            return "not JSON"

    client = MalformedClient()
    result = run_relevance_check(
        isolated_db,
        client,
        assessment_id="assessment-1",
        assignment_id="assignment-1",
        essay_text=ESSAY_TEXT,
    )

    assert result.decision == "manual_review"
    assert client.calls == 1


def test_rejection_still_runs_retrieval_and_rubric_grading(
    isolated_db, llm_client_factory, monkeypatch
):
    _seed_assessment(isolated_db)
    client = llm_client_factory(
        [
            _relevance_response(
                decision="reject",
                submission_type="source_material",
                responds=False,
                sufficient=True,
            )
        ]
    )

    pipeline_calls: list[tuple[str, object]] = []

    def fake_embed(text):
        pipeline_calls.append(("retrieval", text))
        return [0.1, 0.2]

    def fake_grade(*_args, **kwargs):
        pipeline_calls.append(("grading", kwargs["query_embedding"]))

    monkeypatch.setattr(assessments.chroma_store, "embed_text", fake_embed)
    monkeypatch.setattr(assessments, "run_dual_path_for_criteria_batch", fake_grade)
    progress.start("assessment-1")

    assessments._run_assessment(
        "assessment-1",
        client,
        [{"criterion_id": "C1", "statement": "Claim", "anchors_json": "{}"}],
        ASSIGNMENT,
        ESSAY_TEXT,
        "instructor-1",
    )

    row = isolated_db.execute(
        "SELECT status FROM assessments WHERE id = 'assessment-1'"
    ).fetchone()
    assert row["status"] == "complete"
    assert len(client.calls) == 1
    assert pipeline_calls == [("retrieval", ESSAY_TEXT), ("grading", [0.1, 0.2])]


def test_passing_relevance_then_enters_rubric_pipeline(
    isolated_db, llm_client_factory, monkeypatch
):
    _seed_assessment(
        isolated_db,
        prompt="Explain how hospital network segmentation reduces cybersecurity risk.",
    )
    client = llm_client_factory(
        [
            _relevance_response(
                decision="grade",
                submission_type="student_response",
                responds=True,
                sufficient=True,
            )
        ]
    )
    pipeline_calls: list[tuple[str, object]] = []

    def fake_embed(text):
        pipeline_calls.append(("retrieval", text))
        return [0.1, 0.2]

    def fake_grade(*_args, **kwargs):
        pipeline_calls.append(("grading", kwargs["query_embedding"]))

    monkeypatch.setattr(assessments.chroma_store, "embed_text", fake_embed)
    monkeypatch.setattr(assessments, "run_dual_path_for_criteria_batch", fake_grade)
    progress.start("assessment-1")

    assessments._run_assessment(
        "assessment-1",
        client,
        [{"criterion_id": "C1", "statement": "Claim", "anchors_json": "{}"}],
        ASSIGNMENT,
        ESSAY_TEXT,
        "instructor-1",
    )

    assert len(client.calls) == 1
    assert pipeline_calls == [("retrieval", ESSAY_TEXT), ("grading", [0.1, 0.2])]
    row = isolated_db.execute(
        "SELECT status FROM assessments WHERE id = 'assessment-1'"
    ).fetchone()
    assert row["status"] == "complete"
