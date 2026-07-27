from app.grading.engine import _run_graded_batch_pass, criteria_batch_size


def _result(criterion_id: str, quote: str) -> dict:
    return {
        "criterionId": criterion_id,
        "evidence": [{"quote": quote, "reasoning": "Direct support."}],
        "anchorMatched": 4,
        "score": 4,
        "rationale": "The cited sentence supports the score.",
        "selfConfidence": 0.9,
        "precedent_referenced": [],
    }


def test_batch_pass_grades_multiple_criteria_in_one_provider_call(llm_client_factory):
    client = llm_client_factory([
        {"results": [_result("C1", "A grounded sentence."), _result("C2", "A grounded sentence.")]}
    ])

    results = _run_graded_batch_pass(
        client,
        "system",
        "A grounded sentence.",
        {"C1": [], "C2": []},
    )

    assert len(client.calls) == 1
    assert set(results) == {"C1", "C2"}
    assert results["C1"].score == 4
    assert results["C2"].score == 4


def test_batch_retry_preserves_valid_results_and_repairs_only_bad_ones(llm_client_factory):
    client = llm_client_factory([
        {
            "results": [
                _result("C1", "A grounded sentence."),
                _result("C2", "This quote is fabricated."),
            ]
        },
        {"results": [_result("C2", "A grounded sentence.")]},
    ])

    results = _run_graded_batch_pass(
        client,
        "system",
        "A grounded sentence.",
        {"C1": [], "C2": []},
    )

    assert len(client.calls) == 2
    assert results["C1"].score == 4
    assert results["C2"].score == 4


def test_criteria_batch_size_is_bounded(monkeypatch):
    monkeypatch.setenv("GRADING_CRITERIA_BATCH_SIZE", "999")
    assert criteria_batch_size() == 10
    monkeypatch.setenv("GRADING_CRITERIA_BATCH_SIZE", "0")
    assert criteria_batch_size() == 1
    monkeypatch.setenv("GRADING_CRITERIA_BATCH_SIZE", "not-a-number")
    assert criteria_batch_size() == 5
