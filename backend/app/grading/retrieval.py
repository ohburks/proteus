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


@dataclass
class Scope:
    instructor_id: str
    course_id: str | None
    assignment_id: str | None


def assemble_personalized_pool(
    query_text: str, scope: Scope, criterion_id: str, rubric_id: str, k: int = DEFAULT_K
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
        )

    return pool[:k]


def query_exemplar_pool(
    query_text: str, criterion_id: str, rubric_id: str, rubric_version: str, k: int = DEFAULT_K
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
    )
