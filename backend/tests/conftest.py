import json
import sqlite3
from collections.abc import Callable, Iterator
from typing import Any

import pytest

import app.chroma_store as chroma_store
import app.db as db


@pytest.fixture
def isolated_db(monkeypatch, tmp_path) -> Iterator[sqlite3.Connection]:
    """A fresh, disposable SQLite DB for a single test.

    Points app.db at a throwaway file under tmp_path and applies
    schema.sql via init_db(), so any code under test that calls
    app.db.get_connection() — production code paths included, not just
    the test itself — reads/writes this DB instead of the shared dev
    database (backend/data/app.sqlite3).
    """
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.sqlite3")
    db.init_db()
    conn = db.get_connection()
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def isolated_chroma(monkeypatch, tmp_path) -> Iterator[None]:
    """A fresh, disposable Chroma instance for a single test.

    app.chroma_store keeps a module-level cached client (`_client`) pointed
    at a hardcoded directory (`CHROMA_DIR`); monkeypatching both for the
    duration of a test lets insert_personalized_excerpt()/
    insert_exemplar_excerpt()/assemble_personalized_pool()/
    query_exemplar_pool() exercise a real Chroma round-trip — filter
    correctness, the None->"" scope-sentinel convention — against a
    throwaway directory instead of the shared dev collections under
    backend/data/chroma/. Resetting `_client` to None (not just CHROMA_DIR)
    is required: get_client() only builds a new PersistentClient when
    `_client` is None, so a client already cached from an earlier test
    would otherwise keep pointing at that test's directory.
    """
    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(chroma_store, "CHROMA_DIR", chroma_dir)
    monkeypatch.setattr(chroma_store, "_client", None)
    yield


class RecordingLLMClient:
    """Fake `app.llm.base.LLMClient` that returns queued canned responses and
    records every call's prompts, in order.

    Generalizes test_performance.py's old private `FakeBatchClient`: that
    class only tracked a call *count*, which was enough to check retry
    behavior but not enough to check what a call actually contained. Path
    separation (exemplar vs. personalized never sharing prompt content) and
    provider/model consistency both require inspecting the prompts a real
    call received, not just how many calls happened — so this records each
    call as a dict with `system_prompt`/`user_prompt` instead of just
    incrementing a counter.

    One instance handles both the single-criterion response shape
    (`_run_graded_pass`, a bare LLMGradingResponse dict) and the batch shape
    (`_run_graded_batch_pass`, a `{"results": [...]}` dict) — it's the
    caller's job to queue whichever shape the code path under test expects;
    this client just serializes whatever dict it's given to JSON.
    """

    def __init__(self, responses: list[dict[str, Any]]):
        self._responses = list(responses)
        self.calls: list[dict[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str, emit: Callable[[str], None] | None = None) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        response = self._responses[len(self.calls) - 1]
        return json.dumps(response)


@pytest.fixture
def llm_client_factory() -> Callable[[list[dict[str, Any]]], RecordingLLMClient]:
    """Factory fixture: `llm_client_factory([...responses])` -> RecordingLLMClient.

    A factory rather than a ready-made client because each test needs a
    different queue of canned responses (and, for multi-call tests, may
    build several independent clients to compare against each other).
    """
    return RecordingLLMClient
