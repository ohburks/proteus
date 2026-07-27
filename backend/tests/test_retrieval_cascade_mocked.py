from app import chroma_store
from app.grading.retrieval import DEFAULT_K, Scope, assemble_personalized_pool, query_exemplar_pool


class RecordingChromaQuery:
    """Fake for chroma_store.query: returns queued per-call results and
    records every call's arguments, so cascade tier order/count/filters can
    be asserted without touching a real Chroma instance."""

    def __init__(self, tier_results):
        self._tier_results = list(tier_results)
        self.calls: list[dict] = []

    def __call__(self, collection_name, query_text, where, n, exclude_ids=None, query_embedding=None):
        index = len(self.calls)
        self.calls.append({
            "collection_name": collection_name,
            "where": where,
            "n": n,
            "exclude_ids": exclude_ids,
        })
        return self._tier_results[index] if index < len(self._tier_results) else []


def _where_value(where: dict, key: str):
    for clause in where["$and"]:
        if key in clause:
            return clause[key]
    raise KeyError(key)


def _ids(n: int, prefix: str) -> list[dict]:
    return [{"id": f"{prefix}{i}"} for i in range(n)]


def test_tier1_alone_sufficient_never_touches_tier2_or_tier3(monkeypatch):
    recorder = RecordingChromaQuery([_ids(DEFAULT_K, "a")])
    monkeypatch.setattr(chroma_store, "query", recorder)
    scope = Scope(instructor_id="i1", course_id="c1", assignment_id="a1")

    pool = assemble_personalized_pool("essay", scope, "C1", "r1")

    assert len(recorder.calls) == 1
    assert len(pool) == DEFAULT_K
    assert _where_value(recorder.calls[0]["where"], "assignment_id") == "a1"
    assert _where_value(recorder.calls[0]["where"], "course_id") == "c1"


def test_tier1_empty_falls_back_to_tier2(monkeypatch):
    recorder = RecordingChromaQuery([[], _ids(DEFAULT_K, "b")])
    monkeypatch.setattr(chroma_store, "query", recorder)
    scope = Scope(instructor_id="i1", course_id="c1", assignment_id="a1")

    pool = assemble_personalized_pool("essay", scope, "C1", "r1")

    assert len(recorder.calls) == 2
    assert recorder.calls[1]["n"] == DEFAULT_K
    assert _where_value(recorder.calls[1]["where"], "assignment_id") == ""
    assert _where_value(recorder.calls[1]["where"], "course_id") == "c1"
    assert len(pool) == DEFAULT_K


def test_tier1_and_tier2_partial_fill_falls_back_to_tier3(monkeypatch):
    recorder = RecordingChromaQuery([_ids(2, "a"), _ids(2, "b"), _ids(1, "c")])
    monkeypatch.setattr(chroma_store, "query", recorder)
    scope = Scope(instructor_id="i1", course_id="c1", assignment_id="a1")

    pool = assemble_personalized_pool("essay", scope, "C1", "r1")

    assert len(recorder.calls) == 3
    assert recorder.calls[1]["n"] == 3
    assert recorder.calls[1]["exclude_ids"] == ["a0", "a1"]
    assert recorder.calls[2]["n"] == 1
    assert recorder.calls[2]["exclude_ids"] == ["a0", "a1", "b0", "b1"]
    assert _where_value(recorder.calls[2]["where"], "course_id") == ""
    assert _where_value(recorder.calls[2]["where"], "assignment_id") == ""
    assert [p["id"] for p in pool] == ["a0", "a1", "b0", "b1", "c0"]


def test_no_assignment_id_skips_tier1_entirely(monkeypatch):
    recorder = RecordingChromaQuery([_ids(DEFAULT_K, "b")])
    monkeypatch.setattr(chroma_store, "query", recorder)
    scope = Scope(instructor_id="i1", course_id="c1", assignment_id=None)

    pool = assemble_personalized_pool("essay", scope, "C1", "r1")

    assert len(recorder.calls) == 1
    assert _where_value(recorder.calls[0]["where"], "assignment_id") == ""
    assert _where_value(recorder.calls[0]["where"], "course_id") == "c1"
    assert len(pool) == DEFAULT_K


def test_no_course_or_assignment_id_goes_straight_to_tier3(monkeypatch):
    recorder = RecordingChromaQuery([_ids(DEFAULT_K, "c")])
    monkeypatch.setattr(chroma_store, "query", recorder)
    scope = Scope(instructor_id="i1", course_id=None, assignment_id=None)

    pool = assemble_personalized_pool("essay", scope, "C1", "r1")

    assert len(recorder.calls) == 1
    assert _where_value(recorder.calls[0]["where"], "course_id") == ""
    assert _where_value(recorder.calls[0]["where"], "assignment_id") == ""
    assert len(pool) == DEFAULT_K


def test_assignment_id_without_course_id_uses_empty_string_sentinel(monkeypatch):
    # Tier 1's filter is `course_id: scope.course_id or ""` - a scope that
    # has an assignment_id but no course_id must still query with "", not
    # None (Chroma's where filter can't match a bare None - see
    # retrieval.py's module docstring).
    recorder = RecordingChromaQuery([_ids(DEFAULT_K, "a")])
    monkeypatch.setattr(chroma_store, "query", recorder)
    scope = Scope(instructor_id="i1", course_id=None, assignment_id="a1")

    assemble_personalized_pool("essay", scope, "C1", "r1")

    assert _where_value(recorder.calls[0]["where"], "course_id") == ""


def test_final_pool_is_capped_at_k_even_if_a_tier_over_returns(monkeypatch):
    recorder = RecordingChromaQuery([_ids(DEFAULT_K + 3, "a")])
    monkeypatch.setattr(chroma_store, "query", recorder)
    scope = Scope(instructor_id="i1", course_id="c1", assignment_id="a1")

    pool = assemble_personalized_pool("essay", scope, "C1", "r1")

    assert len(pool) == DEFAULT_K


def test_custom_k_is_honored_throughout_the_cascade(monkeypatch):
    recorder = RecordingChromaQuery([_ids(1, "a"), _ids(1, "b")])
    monkeypatch.setattr(chroma_store, "query", recorder)
    scope = Scope(instructor_id="i1", course_id="c1", assignment_id="a1")

    pool = assemble_personalized_pool("essay", scope, "C1", "r1", k=2)

    assert recorder.calls[0]["n"] == 2
    assert recorder.calls[1]["n"] == 1
    assert len(pool) == 2


def test_exemplar_pool_is_a_single_unscoped_query(monkeypatch):
    recorder = RecordingChromaQuery([_ids(3, "e")])
    monkeypatch.setattr(chroma_store, "query", recorder)

    pool = query_exemplar_pool("essay", "C1", "r1", "v1")

    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["collection_name"] == chroma_store.EXEMPLAR_COLLECTION
    assert _where_value(call["where"], "rubric_id") == "r1"
    assert _where_value(call["where"], "rubric_version") == "v1"
    assert _where_value(call["where"], "criterion_id") == "C1"
    assert len(pool) == 3
