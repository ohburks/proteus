"""Professor calibration examples: SQLite source of truth + Chroma mirror."""
import sqlite3
import uuid
from datetime import UTC, datetime

from app import chroma_store


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _vector_id(example_id: str, criterion_id: str) -> str:
    return f"calibration:{example_id}:{criterion_id}"


def _mirror_score(
    conn: sqlite3.Connection,
    *,
    example_id: str,
    criterion_id: str,
) -> None:
    row = conn.execute(
        """SELECT e.*, s.criterion_id, s.score, s.rationale,
                  a.course_id, a.rubric_id, a.rubric_version
           FROM calibration_examples e
           JOIN calibration_example_scores s ON s.example_id = e.id
           JOIN assignments a ON a.id = e.assignment_id
           WHERE e.id = ? AND s.criterion_id = ?""",
        (example_id, criterion_id),
    ).fetchone()
    if row is None:
        return
    chroma_store.upsert(
        chroma_store.CALIBRATION_COLLECTION,
        _vector_id(example_id, criterion_id),
        row["essay_text"],
        {
            "example_id": example_id,
            "example_name": row["name"],
            "assignment_id": row["assignment_id"],
            "course_id": row["course_id"],
            "instructor_id": row["instructor_id"],
            "rubric_id": row["rubric_id"],
            "rubric_version": row["rubric_version"],
            "criterion_id": criterion_id,
            "score": row["score"],
            "rationale": row["rationale"],
            "source": row["source"],
            "updated_at": row["updated_at"],
        },
    )


def insert_calibration_example(
    conn: sqlite3.Connection,
    *,
    assignment_id: str,
    instructor_id: str,
    name: str,
    essay_text: str,
    scores: list[dict],
    source: str = "uploaded",
    source_assessment_id: str | None = None,
) -> str:
    example_id = str(uuid.uuid4())
    now = _now()
    conn.execute(
        """INSERT INTO calibration_examples
           (id, assignment_id, instructor_id, name, essay_text, source,
            source_assessment_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            example_id,
            assignment_id,
            instructor_id,
            name,
            essay_text,
            source,
            source_assessment_id,
            now,
            now,
        ),
    )
    for item in scores:
        conn.execute(
            """INSERT INTO calibration_example_scores
               (example_id, criterion_id, score, rationale, created_at, updated_at)
               VALUES (?,?,?,?,?,?)""",
            (
                example_id,
                item["criterion_id"],
                item["score"],
                item["rationale"],
                now,
                now,
            ),
        )
        _mirror_score(conn, example_id=example_id, criterion_id=item["criterion_id"])
    return example_id


def upsert_review_calibration_score(
    conn: sqlite3.Connection,
    *,
    assessment,
    essay,
    instructor_id: str,
    criterion_id: str,
    score: int,
    rationale: str,
    source: str,
) -> str:
    """Add or update one reviewed criterion on a full assessment example."""
    now = _now()
    row = conn.execute(
        """SELECT id FROM calibration_examples
           WHERE assignment_id = ? AND source_assessment_id = ?""",
        (essay["assignment_id"], assessment["id"]),
    ).fetchone()
    if row is None:
        example_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO calibration_examples
               (id, assignment_id, instructor_id, name, essay_text, source,
                source_assessment_id, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                example_id,
                essay["assignment_id"],
                instructor_id,
                f"Reviewed submission {assessment['id'][:8]}",
                essay["text"],
                source,
                assessment["id"],
                now,
                now,
            ),
        )
    else:
        example_id = row["id"]
        conn.execute(
            """UPDATE calibration_examples
               SET source = ?, essay_text = ?, updated_at = ?
               WHERE id = ?""",
            (source, essay["text"], now, example_id),
        )
    conn.execute(
        """INSERT INTO calibration_example_scores
           (example_id, criterion_id, score, rationale, created_at, updated_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT (example_id, criterion_id) DO UPDATE SET
             score = excluded.score,
             rationale = excluded.rationale,
             updated_at = excluded.updated_at""",
        (example_id, criterion_id, score, rationale, now, now),
    )
    _mirror_score(conn, example_id=example_id, criterion_id=criterion_id)
    return example_id


def delete_calibration_example(conn: sqlite3.Connection, example_id: str) -> None:
    ids = [
        _vector_id(example_id, row["criterion_id"])
        for row in conn.execute(
            "SELECT criterion_id FROM calibration_example_scores WHERE example_id = ?",
            (example_id,),
        ).fetchall()
    ]
    chroma_store.delete(chroma_store.CALIBRATION_COLLECTION, ids)
    conn.execute("DELETE FROM calibration_example_scores WHERE example_id = ?", (example_id,))
    conn.execute("DELETE FROM calibration_examples WHERE id = ?", (example_id,))


def delete_assignment_calibration_examples(
    conn: sqlite3.Connection,
    assignment_id: str,
) -> None:
    rows = conn.execute(
        "SELECT id FROM calibration_examples WHERE assignment_id = ?",
        (assignment_id,),
    ).fetchall()
    for row in rows:
        delete_calibration_example(conn, row["id"])


def rebuild_calibration_chroma_collection(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """SELECT e.*, s.criterion_id, s.score, s.rationale,
                  a.course_id, a.rubric_id, a.rubric_version
           FROM calibration_examples e
           JOIN calibration_example_scores s ON s.example_id = e.id
           JOIN assignments a ON a.id = e.assignment_id"""
    ).fetchall()
    chroma_store.rebuild_collection(
        chroma_store.CALIBRATION_COLLECTION,
        [
            {
                "id": _vector_id(row["id"], row["criterion_id"]),
                "document": row["essay_text"],
                "metadata": {
                    "example_id": row["id"],
                    "example_name": row["name"],
                    "assignment_id": row["assignment_id"],
                    "course_id": row["course_id"],
                    "instructor_id": row["instructor_id"],
                    "rubric_id": row["rubric_id"],
                    "rubric_version": row["rubric_version"],
                    "criterion_id": row["criterion_id"],
                    "score": row["score"],
                    "rationale": row["rationale"],
                    "source": row["source"],
                    "updated_at": row["updated_at"],
                },
            }
            for row in rows
        ],
    )
