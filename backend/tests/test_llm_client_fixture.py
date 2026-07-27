import json

from app.grading.engine import _run_graded_batch_pass, _run_multi_pass


def _single_response(score: int = 4) -> dict:
    return {
        "evidence": [{"quote": "A grounded sentence.", "reasoning": "Direct support."}],
        "anchorMatched": score,
        "score": score,
        "rationale": "The cited sentence supports the score.",
        "selfConfidence": 0.9,
        "precedent_referenced": [],
    }


def test_records_each_call_in_order(llm_client_factory):
    client = llm_client_factory([_single_response(3), _single_response(4)])

    client.complete("system-1", "user-1")
    client.complete("system-2", "user-2")

    assert len(client.calls) == 2
    assert client.calls[0] == {"system_prompt": "system-1", "user_prompt": "user-1"}
    assert client.calls[1] == {"system_prompt": "system-2", "user_prompt": "user-2"}


def test_returns_the_queued_response_as_json_in_order(llm_client_factory):
    client = llm_client_factory([_single_response(2), _single_response(5)])

    first = json.loads(client.complete("system", "user"))
    second = json.loads(client.complete("system", "user"))

    assert first["score"] == 2
    assert second["score"] == 5


def test_two_factory_built_clients_are_independent(llm_client_factory):
    client_a = llm_client_factory([_single_response(1)])
    client_b = llm_client_factory([_single_response(1)])

    client_a.complete("system", "user")

    assert len(client_a.calls) == 1
    assert len(client_b.calls) == 0


def test_records_every_pass_across_a_real_multi_pass_run(llm_client_factory):
    # _run_multi_pass is what grade_criterion_exemplar/personalized call —
    # confirms the fixture works as a drop-in LLMClient for that real code
    # path, not just for hand-written complete() calls above.
    client = llm_client_factory([_single_response(4), _single_response(4), _single_response(4)])

    passes = _run_multi_pass(client, "system-prompt", "A grounded sentence.", [], n=3)

    assert len(passes) == 3
    assert len(client.calls) == 3
    assert all(call["system_prompt"] == "system-prompt" for call in client.calls)


def test_one_client_instance_can_record_two_distinctly_tagged_batches(llm_client_factory):
    # Mirrors how run_dual_path_for_criteria_batch threads a single client
    # through an exemplar batch call and then a personalized batch call —
    # the fixture must let a test tell the two apart afterward by prompt
    # content, not just by call count.
    exemplar_batch = {"results": [{
        "criterionId": "C1",
        "evidence": [{"quote": "A grounded sentence.", "reasoning": "ok"}],
        "anchorMatched": 4, "score": 4, "rationale": "ok",
        "selfConfidence": 0.9, "precedent_referenced": [],
    }]}
    personalized_batch = {"results": [{
        "criterionId": "C1",
        "evidence": [{"quote": "A grounded sentence.", "reasoning": "ok"}],
        "anchorMatched": 3, "score": 3, "rationale": "ok",
        "selfConfidence": 0.9, "precedent_referenced": [],
    }]}
    client = llm_client_factory([exemplar_batch, personalized_batch])

    _run_graded_batch_pass(client, "EXEMPLAR PROMPT", "A grounded sentence.", {"C1": []})
    _run_graded_batch_pass(client, "PERSONALIZED PROMPT", "A grounded sentence.", {"C1": []})

    assert len(client.calls) == 2
    assert client.calls[0]["system_prompt"] == "EXEMPLAR PROMPT"
    assert client.calls[1]["system_prompt"] == "PERSONALIZED PROMPT"
