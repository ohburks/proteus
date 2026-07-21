"""Excerpt corpus writes: SQLite (source of truth) + Chroma mirror, together.

Design doc §13: every write to `*_excerpts_src` must mirror into the
corresponding Chroma collection in the same request path. This module is the
only place that's allowed to write to `exemplar_excerpts_src` /
`personalized_excerpts_src` for that reason — callers (manual curation,
review write-back §9, bulk import) go through here so the dual-write and the
§3.5 ingestion-time evidence check can't be bypassed.
"""
import json
import sqlite3
import uuid
from datetime import UTC, datetime

from app import chroma_store
from app.grading.evidence import EvidenceVerificationError, verify_quote


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Exemplar corpus
# ---------------------------------------------------------------------------

def insert_exemplar_excerpt(
    conn: sqlite3.Connection,
    *,
    rubric_id: str,
    rubric_version: str,
    criterion_id: str,
    excerpt_text: str,
    score: int,
    anchor_matched: int,
    rationale: str,
    source_essay_id: str,
    is_preseeded: bool,
) -> str:
    row = conn.execute(
        "SELECT text FROM exemplar_source_essays WHERE source_essay_id = ?",
        (source_essay_id,),
    ).fetchone()
    if row is None:
        raise EvidenceVerificationError(
            excerpt_text, f"no source essay on file for source_essay_id={source_essay_id!r}"
        )
    if not verify_quote(excerpt_text, row["text"]):
        raise EvidenceVerificationError(excerpt_text, f"ingestion, source_essay_id={source_essay_id!r}")

    excerpt_id = f"exemplar_excerpts:{uuid.uuid4()}"
    created_at = _now()
    conn.execute(
        """INSERT INTO exemplar_excerpts_src
           (id, rubric_id, rubric_version, criterion_id, excerpt_text, score,
            anchor_matched, rationale, source_essay_id, is_preseeded, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            excerpt_id, rubric_id, rubric_version, criterion_id, excerpt_text, score,
            anchor_matched, rationale, source_essay_id, int(is_preseeded), created_at,
        ),
    )
    chroma_store.upsert(
        chroma_store.EXEMPLAR_COLLECTION,
        excerpt_id,
        excerpt_text,
        {
            "rubric_id": rubric_id,
            "rubric_version": rubric_version,
            "criterion_id": criterion_id,
            "score": score,
            "anchor_matched": anchor_matched,
            "rationale": rationale,
            "source_essay_id": source_essay_id,
            "is_preseeded": bool(is_preseeded),
        },
    )
    return excerpt_id


def rebuild_exemplar_chroma_collection(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT * FROM exemplar_excerpts_src").fetchall()
    chroma_store.rebuild_collection(
        chroma_store.EXEMPLAR_COLLECTION,
        [
            {
                "id": r["id"],
                "document": r["excerpt_text"],
                "metadata": {
                    "rubric_id": r["rubric_id"],
                    "rubric_version": r["rubric_version"],
                    "criterion_id": r["criterion_id"],
                    "score": r["score"],
                    "anchor_matched": r["anchor_matched"],
                    "rationale": r["rationale"],
                    "source_essay_id": r["source_essay_id"],
                    "is_preseeded": bool(r["is_preseeded"]),
                },
            }
            for r in rows
        ],
    )


# ---------------------------------------------------------------------------
# Personalized corpus
# ---------------------------------------------------------------------------

def insert_personalized_excerpt(
    conn: sqlite3.Connection,
    *,
    rubric_id: str,
    criterion_id: str,
    instructor_id: str,
    course_id: str | None,
    assignment_id: str | None,
    excerpt_text: str,
    score: int,
    anchor_matched: int,
    rationale: str,
    source: str,
    added_by: str,
    source_essay_text: str,
) -> str:
    """`source_essay_text` is the full text of whichever essay this excerpt is
    quoted from — supplied by the caller (the current assessment's essay for
    review write-back, or the essay text accompanying a manual/import entry).
    Verified here, once, per §3.5; never stored, only checked.
    """
    if not verify_quote(excerpt_text, source_essay_text):
        raise EvidenceVerificationError(excerpt_text, f"ingestion, source={source!r}")

    excerpt_id = f"personalized_excerpts:{uuid.uuid4()}"
    now = _now()
    conn.execute(
        """INSERT INTO personalized_excerpts_src
           (id, rubric_id, criterion_id, instructor_id, course_id, assignment_id,
            excerpt_text, score, anchor_matched, rationale, source, added_by,
            created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            excerpt_id, rubric_id, criterion_id, instructor_id, course_id, assignment_id,
            excerpt_text, score, anchor_matched, rationale, source, added_by, now, now,
        ),
    )
    chroma_store.upsert(
        chroma_store.PERSONALIZED_COLLECTION,
        excerpt_id,
        excerpt_text,
        {
            "rubric_id": rubric_id,
            "criterion_id": criterion_id,
            "instructor_id": instructor_id,
            "course_id": course_id or "",
            "assignment_id": assignment_id or "",
            "score": score,
            "anchor_matched": anchor_matched,
            "rationale": rationale,
            "source": source,
            "added_by": added_by,
            "updated_at": now,
        },
    )
    return excerpt_id


def delete_personalized_excerpt(conn: sqlite3.Connection, excerpt_id: str) -> None:
    conn.execute("DELETE FROM personalized_excerpts_src WHERE id = ?", (excerpt_id,))
    chroma_store.delete(chroma_store.PERSONALIZED_COLLECTION, [excerpt_id])


def rebuild_personalized_chroma_collection(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT * FROM personalized_excerpts_src").fetchall()
    chroma_store.rebuild_collection(
        chroma_store.PERSONALIZED_COLLECTION,
        [
            {
                "id": r["id"],
                "document": r["excerpt_text"],
                "metadata": {
                    "rubric_id": r["rubric_id"],
                    "criterion_id": r["criterion_id"],
                    "instructor_id": r["instructor_id"],
                    "course_id": r["course_id"] or "",
                    "assignment_id": r["assignment_id"] or "",
                    "score": r["score"],
                    "anchor_matched": r["anchor_matched"],
                    "rationale": r["rationale"],
                    "source": r["source"],
                    "added_by": r["added_by"],
                    "updated_at": r["updated_at"],
                },
            }
            for r in rows
        ],
    )
