"""Path separation and provider/model consistency (T12).

Exercises the real run_dual_path_for_criteria_batch() with a mocked
chroma_store.query (distinctly-tagged precedent per collection) and a
recording LLM client, to prove: the Exemplar and Personalized paths never
see each other's retrieved precedent or prompt context, and provider/model
stays fixed across both paths within one run.
"""
import inspect
from datetime import UTC, datetime

from app import chroma_store
from app.grading.engine import run_dual_path_for_criteria_batch

CRITERION = {
    "criterionId": "W1d-1",
    "statement": "Uses precise, purposeful language.",
    "anchors": {"0": "no evidence", "5": "consistently precise"},
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _seed_assignment_essay_assessment(isolated_db):
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
        ("e1", "a1", None, "A grounded sentence.", now),
    )
    isolated_db.execute(
        """INSERT INTO assessments
           (id, essay_id, instructor_id, student_id, rubric_id, rubric_version, provider, model, status, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        ("as1", "e1", "i1", None, "r1", "v1", "openai", "gpt-4o-mini", "running", now),
    )
    isolated_db.commit()


def _fake_query(collection_name, query_text, where, n, exclude_ids=None, query_embedding=None):
    if collection_name == chroma_store.EXEMPLAR_COLLECTION:
        return [{
            "id": "exemplar-precedent-1",
            "document": "An exemplar-only precedent quote.",
            "metadata": {"score": 4, "anchor_matched": 4, "rationale": "exemplar rationale"},
            "distance": 0.1,
        }]
    return [{
        "id": "personalized-precedent-1",
        "document": "A personalized-only precedent quote.",
        "metadata": {"score": 3, "anchor_matched": 3, "rationale": "personalized rationale"},
        "distance": 0.1,
    }]


def _batch_response(criterion_id: str, score: int) -> dict:
    return {"results": [{
        "criterionId": criterion_id,
        "evidence": [{"quote": "A grounded sentence.", "reasoning": "ok"}],
        "anchorMatched": score,
        "score": score,
        "rationale": "ok",
        "selfConfidence": 0.9,
        "precedent_referenced": [],
    }]}


def test_paths_never_share_retrieved_precedent_or_prompt_context(monkeypatch, isolated_db, llm_client_factory):
    monkeypatch.setattr(chroma_store, "query", _fake_query)
    monkeypatch.setattr(chroma_store, "embed_text", lambda text: [0.0])
    _seed_assignment_essay_assessment(isolated_db)
    client = llm_client_factory([_batch_response("W1d-1", 4), _batch_response("W1d-1", 3)])

    run_dual_path_for_criteria_batch(
        isolated_db, client,
        assessment_id="as1", criteria=[CRITERION], rubric_id="r1", rubric_version="v1",
        essay_text="A grounded sentence.", assignment_id="a1", instructor_id="i1", course_id="c1",
    )

    assert len(client.calls) == 2
    exemplar_call, personalized_call = client.calls

    assert "exemplar-precedent-1" in exemplar_call["system_prompt"]
    assert "personalized-precedent-1" not in exemplar_call["system_prompt"]

    assert "personalized-precedent-1" in personalized_call["system_prompt"]
    assert "exemplar-precedent-1" not in personalized_call["system_prompt"]


def test_instructor_guidance_is_structurally_absent_from_the_exemplar_prompt(
    monkeypatch, isolated_db, llm_client_factory
):
    monkeypatch.setattr(chroma_store, "query", _fake_query)
    monkeypatch.setattr(chroma_store, "embed_text", lambda text: [0.0])
    _seed_assignment_essay_assessment(isolated_db)
    client = llm_client_factory([_batch_response("W1d-1", 4), _batch_response("W1d-1", 3)])

    run_dual_path_for_criteria_batch(
        isolated_db, client,
        assessment_id="as1", criteria=[CRITERION], rubric_id="r1", rubric_version="v1",
        essay_text="A grounded sentence.", assignment_id="a1", instructor_id="i1", course_id="c1",
    )

    exemplar_call, personalized_call = client.calls
    assert "[INSTRUCTOR GUIDANCE]" not in exemplar_call["system_prompt"]
    assert "[INSTRUCTOR GUIDANCE]" in personalized_call["system_prompt"]


def test_both_paths_are_graded_through_the_same_client_instance(monkeypatch, isolated_db, llm_client_factory):
    # There is exactly one `client` argument threaded through both the
    # exemplar and personalized batch calls (not two, one per path) - this
    # is what structurally guarantees provider/model can never drift
    # between the two paths within a single run.
    monkeypatch.setattr(chroma_store, "query", _fake_query)
    monkeypatch.setattr(chroma_store, "embed_text", lambda text: [0.0])
    _seed_assignment_essay_assessment(isolated_db)
    client = llm_client_factory([_batch_response("W1d-1", 4), _batch_response("W1d-1", 3)])

    run_dual_path_for_criteria_batch(
        isolated_db, client,
        assessment_id="as1", criteria=[CRITERION], rubric_id="r1", rubric_version="v1",
        essay_text="A grounded sentence.", assignment_id="a1", instructor_id="i1", course_id="c1",
    )

    # Both calls landed on this one recorder - if the code ever built a
    # second client for one of the paths, this count (or the prompts
    # above) would be the first thing to break.
    assert len(client.calls) == 2

    aggregates = isolated_db.execute(
        "SELECT path FROM score_aggregates WHERE assessment_id = ? ORDER BY path", ("as1",)
    ).fetchall()
    assert [row["path"] for row in aggregates] == ["exemplar", "personalized"]


def test_run_dual_path_signature_has_only_one_client_parameter():
    # Structural guardrail: if a future refactor ever split this into two
    # client parameters (one per path), that would reopen the possibility
    # of provider/model drift between paths - fail loudly if it happens.
    params = list(inspect.signature(run_dual_path_for_criteria_batch).parameters)
    client_params = [name for name in params if "client" in name.lower()]
    assert client_params == ["client"]
