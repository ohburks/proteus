"""Divergence / pool threshold lookups (design doc §4, §8, §10)."""
import sqlite3
from datetime import UTC, datetime

from app.grading.retrieval import DEFAULT_K

DEFAULT_DIVERGENCE_THRESHOLD = 2

# Spread threshold gates the within-path "high spread" signal (score_aggregates
# .high_spread) — distinct from DEFAULT_DIVERGENCE_THRESHOLD above, which gates
# between-path disagreement. Same 0-5 score scale, so the same default value
# is a reasonable starting point, but the two are tuned independently.
DEFAULT_SPREAD_THRESHOLD = 2


def _now() -> str:
    return datetime.now(UTC).isoformat()


def lookup_pool_threshold(
    conn: sqlite3.Connection, instructor_id: str, rubric_id: str, criterion_id: str
) -> int:
    row = conn.execute(
        """SELECT min_scoped_pool_size FROM pool_thresholds
           WHERE instructor_id = ? AND rubric_id = ? AND criterion_id = ?""",
        (instructor_id, rubric_id, criterion_id),
    ).fetchone()
    if row is not None:
        return row["min_scoped_pool_size"]
    row = conn.execute(
        """SELECT min_scoped_pool_size FROM pool_thresholds
           WHERE instructor_id = ? AND rubric_id = ? AND criterion_id IS NULL""",
        (instructor_id, rubric_id),
    ).fetchone()
    if row is not None:
        return row["min_scoped_pool_size"]
    return DEFAULT_K


def lookup_divergence_threshold(
    conn: sqlite3.Connection, instructor_id: str, rubric_id: str, criterion_id: str
) -> int:
    row = conn.execute(
        """SELECT threshold FROM divergence_thresholds
           WHERE instructor_id = ? AND rubric_id = ? AND criterion_id = ?""",
        (instructor_id, rubric_id, criterion_id),
    ).fetchone()
    return row["threshold"] if row is not None else DEFAULT_DIVERGENCE_THRESHOLD


def lookup_spread_threshold(
    conn: sqlite3.Connection, instructor_id: str, rubric_id: str, criterion_id: str
) -> float:
    row = conn.execute(
        """SELECT threshold FROM spread_thresholds
           WHERE instructor_id = ? AND rubric_id = ? AND criterion_id = ?""",
        (instructor_id, rubric_id, criterion_id),
    ).fetchone()
    return row["threshold"] if row is not None else DEFAULT_SPREAD_THRESHOLD


def set_spread_threshold(
    conn: sqlite3.Connection, instructor_id: str, rubric_id: str, criterion_id: str, threshold: float,
) -> None:
    conn.execute(
        """INSERT INTO spread_thresholds (instructor_id, rubric_id, criterion_id, threshold, updated_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT (instructor_id, rubric_id, criterion_id)
           DO UPDATE SET threshold = excluded.threshold, updated_at = excluded.updated_at""",
        (instructor_id, rubric_id, criterion_id, threshold, _now()),
    )


def set_pool_threshold(
    conn: sqlite3.Connection, instructor_id: str, rubric_id: str,
    criterion_id: str | None, min_scoped_pool_size: int,
) -> None:
    # SQLite treats NULL as distinct in every row for UNIQUE/PK purposes, so
    # ON CONFLICT can't dedupe the criterion_id IS NULL (instructor-wide
    # default) row the way it does for non-NULL criterion_id — handled
    # explicitly instead.
    if criterion_id is None:
        existing = conn.execute(
            """SELECT 1 FROM pool_thresholds
               WHERE instructor_id = ? AND rubric_id = ? AND criterion_id IS NULL""",
            (instructor_id, rubric_id),
        ).fetchone()
        if existing is not None:
            conn.execute(
                """UPDATE pool_thresholds SET min_scoped_pool_size = ?, updated_at = ?
                   WHERE instructor_id = ? AND rubric_id = ? AND criterion_id IS NULL""",
                (min_scoped_pool_size, _now(), instructor_id, rubric_id),
            )
            return
        conn.execute(
            """INSERT INTO pool_thresholds (instructor_id, rubric_id, criterion_id, min_scoped_pool_size, updated_at)
               VALUES (?,?,NULL,?,?)""",
            (instructor_id, rubric_id, min_scoped_pool_size, _now()),
        )
        return
    conn.execute(
        """INSERT INTO pool_thresholds (instructor_id, rubric_id, criterion_id, min_scoped_pool_size, updated_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT (instructor_id, rubric_id, criterion_id)
           DO UPDATE SET min_scoped_pool_size = excluded.min_scoped_pool_size, updated_at = excluded.updated_at""",
        (instructor_id, rubric_id, criterion_id, min_scoped_pool_size, _now()),
    )


def set_divergence_threshold(
    conn: sqlite3.Connection, instructor_id: str, rubric_id: str, criterion_id: str, threshold: int,
) -> None:
    conn.execute(
        """INSERT INTO divergence_thresholds (instructor_id, rubric_id, criterion_id, threshold, updated_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT (instructor_id, rubric_id, criterion_id)
           DO UPDATE SET threshold = excluded.threshold, updated_at = excluded.updated_at""",
        (instructor_id, rubric_id, criterion_id, threshold, _now()),
    )
