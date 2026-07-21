"""Loads versioned rubric JSON from content/ into the DB (design doc §1)."""
import json
from datetime import UTC, datetime
from pathlib import Path

from app.db import get_connection

CONTENT_DIR = Path(__file__).resolve().parent.parent.parent / "content"


def seed_rubrics() -> None:
    rubrics_dir = CONTENT_DIR / "rubrics"
    if not rubrics_dir.exists():
        return
    with get_connection() as conn:
        for path in rubrics_dir.glob("*.json"):
            raw = json.loads(path.read_text())
            rubric_id = raw["rubricId"]
            version = raw["version"]
            existing = conn.execute(
                "SELECT 1 FROM rubrics WHERE rubric_id = ? AND version = ?", (rubric_id, version)
            ).fetchone()
            if existing:
                continue
            now = datetime.now(UTC).isoformat()
            conn.execute(
                """INSERT INTO rubrics (rubric_id, version, genre, notes, assignment_guidance, raw_json, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (rubric_id, version, raw.get("genre"), raw.get("notes"), raw.get("assignmentGuidance"), json.dumps(raw), now),
            )
            for c in raw["criteria"]:
                conn.execute(
                    """INSERT INTO criteria
                       (rubric_id, rubric_version, criterion_id, standard, dimension, statement, scale,
                        referenceability, source, anchors_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        rubric_id, version, c["criterionId"], c.get("standard"), c.get("dimension"),
                        c["statement"], c.get("scale"), c.get("referenceability"), c.get("source"),
                        json.dumps(c["anchors"]),
                    ),
                )
        conn.commit()
