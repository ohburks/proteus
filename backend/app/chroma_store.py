"""Chroma persistence layer (design doc §3, §13).

Chroma collections are rebuildable from SQLite, not the source of truth —
SQLite holds the canonical excerpt rows, Chroma holds the vector index over
them. Consistency strategy (per §16.2, resolved): rebuild-on-drift — treat
SQLite as authoritative and rebuild the affected collection wholesale on any
detected drift, rather than running a periodic reconciliation/diff job.
"""
from pathlib import Path
from typing import Any

import chromadb

CHROMA_DIR = Path(__file__).resolve().parent.parent / "data" / "chroma"
CHROMA_DIR.mkdir(parents=True, exist_ok=True)

EXEMPLAR_COLLECTION = "exemplar_excerpts"
PERSONALIZED_COLLECTION = "personalized_excerpts"

_client = None


def get_client():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return _client


def get_collection(name: str):
    # Uses Chroma's default embedding function (all-MiniLM-L6-v2, local ONNX,
    # no per-call API key) — design doc §3.3. Not pinned/pre-baked: internet
    # access is guaranteed, so the one-time model fetch on first use is fine.
    return get_client().get_or_create_collection(name=name)


def upsert(collection_name: str, id_: str, document: str, metadata: dict[str, Any]) -> None:
    get_collection(collection_name).upsert(ids=[id_], documents=[document], metadatas=[metadata])


def delete(collection_name: str, ids: list[str]) -> None:
    if not ids:
        return
    get_collection(collection_name).delete(ids=ids)


def query(
    collection_name: str,
    query_text: str,
    where: dict[str, Any],
    n: int,
    exclude_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    if n <= 0:
        return []
    coll = get_collection(collection_name)
    # Over-fetch so post-filtering excluded ids doesn't starve the result.
    fetch_n = n + len(exclude_ids or [])
    result = coll.query(
        query_texts=[query_text],
        n_results=min(fetch_n, max(coll.count(), 1)),
        where=where or None,
    )
    ids = result.get("ids", [[]])[0]
    docs = result.get("documents", [[]])[0]
    metas = result.get("metadatas", [[]])[0]
    dists = result.get("distances", [[]])[0]
    exclude = set(exclude_ids or [])
    out = []
    for id_, doc, meta, dist in zip(ids, docs, metas, dists):
        if id_ in exclude:
            continue
        out.append({"id": id_, "document": doc, "metadata": meta, "distance": dist})
        if len(out) >= n:
            break
    return out


def rebuild_collection(collection_name: str, rows: list[dict[str, Any]]) -> None:
    """Rebuild-on-drift: drop and recreate the collection from SQLite rows.

    `rows` items need `id`, `document`, `metadata` keys.
    """
    client = get_client()
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    coll = client.get_or_create_collection(name=collection_name)
    if rows:
        coll.upsert(
            ids=[r["id"] for r in rows],
            documents=[r["document"] for r in rows],
            metadatas=[r["metadata"] for r in rows],
        )
