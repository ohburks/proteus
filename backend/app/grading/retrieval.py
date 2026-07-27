"""Retrieval: cascading pool assembly (design doc §5).

Chroma's `where` filter can't match a bare Python None, so the "unset tier"
sentinel used when mirroring rows into Chroma (app.repositories.excerpts) is
the empty string "" for course_id/assignment_id — that convention is applied
here too when building tier filters.

Default k = 5, MMR re-ranking deferred (§16.1, resolved with the user).
"""
from dataclasses import dataclass

from app import chroma_store

DEFAULT_K = 5
MAX_POOL_SIZE = 20
MAX_CALIBRATION_EXAMPLES_PER_BATCH = 10


@dataclass
class Scope:
    instructor_id: str
    course_id: str | None
    assignment_id: str | None


def _balance_by_professor_score(candidates: list[dict], k: int) -> list[dict]:
    """Preserve semantic order while preventing one score band dominating."""
    buckets: dict[int, list[dict]] = {}
    for item in candidates:
        buckets.setdefault(int(item["metadata"]["score"]), []).append(item)
    ordered_scores = sorted(
        buckets,
        key=lambda score: buckets[score][0].get("distance", float("inf")),
    )
    selected: list[dict] = []
    while ordered_scores and len(selected) < k:
        remaining_scores = []
        for score in ordered_scores:
            bucket = buckets[score]
            if bucket and len(selected) < k:
                selected.append(bucket.pop(0))
            if bucket:
                remaining_scores.append(score)
        ordered_scores = remaining_scores
    return selected


def assemble_calibration_pool(
    query_text: str,
    scope: Scope,
    criterion_id: str,
    rubric_id: str,
    rubric_version: str,
    k: int = DEFAULT_K,
    query_embedding: list[float] | None = None,
) -> list[dict]:
    """Retrieve only professor-labelled examples for the current assignment.

    We over-fetch semantically, then round-robin across the professor's score
    bands. This keeps the most similar work while avoiding a prompt containing
    only high-scoring or only low-scoring precedents.
    """
    if not scope.assignment_id or k <= 0:
        return []
    k = min(k, MAX_POOL_SIZE)
    candidates = chroma_store.query(
        chroma_store.CALIBRATION_COLLECTION,
        query_text,
        where={
            "$and": [
                {"instructor_id": scope.instructor_id},
                {"assignment_id": scope.assignment_id},
                {"criterion_id": criterion_id},
                {"rubric_id": rubric_id},
                {"rubric_version": rubric_version},
            ]
        },
        n=max(k * 6, 30),
        query_embedding=query_embedding,
    )
    return _balance_by_professor_score(candidates, k)


def limit_calibration_examples_for_batch(
    pools: dict[str, list[dict]],
    max_examples: int = MAX_CALIBRATION_EXAMPLES_PER_BATCH,
) -> dict[str, list[dict]]:
    """Bound unique full submissions included in one provider request.

    Criterion pools are interleaved by semantic rank so every criterion gets
    its nearest example before any criterion receives a second unique one.
    This prevents a large rubric from creating an unbounded prompt while
    preserving the score-band ordering already established inside each pool.
    """
    if max_examples <= 0:
        return {criterion_id: [] for criterion_id in pools}
    selected: set[str] = set()
    max_rank = max((len(pool) for pool in pools.values()), default=0)
    for rank in range(max_rank):
        for pool in pools.values():
            if rank >= len(pool):
                continue
            item = pool[rank]
            example_id = str(item["metadata"].get("example_id") or item["id"])
            selected.add(example_id)
            if len(selected) >= max_examples:
                break
        if len(selected) >= max_examples:
            break
    return {
        criterion_id: [
            item
            for item in pool
            if str(item["metadata"].get("example_id") or item["id"]) in selected
        ]
        for criterion_id, pool in pools.items()
    }


def assemble_personalized_pool(
    query_text: str,
    scope: Scope,
    criterion_id: str,
    rubric_id: str,
    k: int = DEFAULT_K,
    query_embedding: list[float] | None = None,
) -> list[dict]:
    pool: list[dict] = []

    # Tier 1: assignment-scoped
    if scope.assignment_id:
        pool += chroma_store.query(
            chroma_store.PERSONALIZED_COLLECTION,
            query_text,
            where={
                "$and": [
                    {"instructor_id": scope.instructor_id},
                    {"course_id": scope.course_id or ""},
                    {"assignment_id": scope.assignment_id},
                    {"criterion_id": criterion_id},
                    {"rubric_id": rubric_id},
                ]
            },
            n=k,
            query_embedding=query_embedding,
        )

    # Tier 2: course-scoped, course-default tier only (fills remaining slots)
    if len(pool) < k and scope.course_id:
        remaining = k - len(pool)
        pool += chroma_store.query(
            chroma_store.PERSONALIZED_COLLECTION,
            query_text,
            where={
                "$and": [
                    {"instructor_id": scope.instructor_id},
                    {"course_id": scope.course_id},
                    {"assignment_id": ""},
                    {"criterion_id": criterion_id},
                    {"rubric_id": rubric_id},
                ]
            },
            n=remaining,
            exclude_ids=[p["id"] for p in pool],
            query_embedding=query_embedding,
        )

    # Tier 3: instructor-default tier (fills remaining slots)
    if len(pool) < k:
        remaining = k - len(pool)
        pool += chroma_store.query(
            chroma_store.PERSONALIZED_COLLECTION,
            query_text,
            where={
                "$and": [
                    {"instructor_id": scope.instructor_id},
                    {"course_id": ""},
                    {"assignment_id": ""},
                    {"criterion_id": criterion_id},
                    {"rubric_id": rubric_id},
                ]
            },
            n=remaining,
            exclude_ids=[p["id"] for p in pool],
            query_embedding=query_embedding,
        )

    return pool[:k]


def query_exemplar_pool(
    query_text: str,
    criterion_id: str,
    rubric_id: str,
    rubric_version: str,
    k: int = DEFAULT_K,
    query_embedding: list[float] | None = None,
) -> list[dict]:
    # Unscoped, no tier cascade, never blended with personalized data (§5, §15).
    return chroma_store.query(
        chroma_store.EXEMPLAR_COLLECTION,
        query_text,
        where={
            "$and": [
                {"rubric_id": rubric_id},
                {"rubric_version": rubric_version},
                {"criterion_id": criterion_id},
            ]
        },
        n=k,
        query_embedding=query_embedding,
    )
