"""Loads committed exemplar/personalized excerpt corpora from content/ into
the DB + Chroma (design doc §3.5, §13). Mirrors seed.py's idempotent,
skip-if-already-present style so repeated startups don't duplicate rows.

Must run after seed_default_accounts(): the personalized seed's
`instructor_id` field is a *username* placeholder (e.g. "instructor"), not
the real scoping id — it's resolved against `users.username` here, so the
matching user row has to exist first.
"""
import json
from datetime import UTC, datetime

from app.db import get_connection
from app.grading.evidence import EvidenceVerificationError
from app.repositories.excerpts import insert_exemplar_excerpt, insert_personalized_excerpt
from app.seed import CONTENT_DIR

EXEMPLARS_DIR = CONTENT_DIR / "exemplars"
PERSONALIZED_SEEDS_DIR = CONTENT_DIR / "personalized-seeds"


def seed_exemplar_excerpts() -> None:
    if not EXEMPLARS_DIR.exists():
        return
    with get_connection() as conn:
        for path in EXEMPLARS_DIR.glob("*.json"):
            data = json.loads(path.read_text())
            rubric_id = data["rubric_id"]
            rubric_version = data["rubric_version"]
            is_preseeded = data["is_preseeded"]

            existing = conn.execute(
                "SELECT 1 FROM exemplar_excerpts_src WHERE rubric_id = ? AND rubric_version = ? LIMIT 1",
                (rubric_id, rubric_version),
            ).fetchone()
            if existing:
                continue

            for essay in data["source_essays"]:
                already = conn.execute(
                    "SELECT 1 FROM exemplar_source_essays WHERE source_essay_id = ?",
                    (essay["source_essay_id"],),
                ).fetchone()
                if already:
                    continue
                conn.execute(
                    "INSERT INTO exemplar_source_essays (source_essay_id, text) VALUES (?,?)",
                    (essay["source_essay_id"], essay["text"]),
                )

            for ex in data["excerpts"]:
                try:
                    insert_exemplar_excerpt(
                        conn,
                        rubric_id=rubric_id,
                        rubric_version=rubric_version,
                        criterion_id=ex["criterion_id"],
                        excerpt_text=ex["excerpt_text"],
                        score=ex["score"],
                        anchor_matched=ex["anchor_matched"],
                        rationale=ex["rationale"],
                        source_essay_id=ex["source_essay_id"],
                        is_preseeded=is_preseeded,
                    )
                except EvidenceVerificationError as e:
                    print(f"seed_exemplar_excerpts: skipping {path.name} excerpt "
                          f"(criterion={ex['criterion_id']!r}, source={ex['source_essay_id']!r}): {e}")
        conn.commit()


def seed_personalized_excerpts() -> None:
    if not PERSONALIZED_SEEDS_DIR.exists():
        return
    with get_connection() as conn:
        for path in PERSONALIZED_SEEDS_DIR.glob("*.json"):
            data = json.loads(path.read_text())
            rubric_id = data["rubric_id"]
            course_id = data["course_id"]
            assignment_id = data["assignment_id"]
            placeholder_instructor_id = data["instructor_id"]

            user_row = conn.execute(
                "SELECT id, instructor_id FROM users WHERE username = ? AND role = 'instructor'",
                (placeholder_instructor_id,),
            ).fetchone()
            if user_row is None:
                print(f"seed_personalized_excerpts: skipping {path.name} — no instructor user "
                      f"with username={placeholder_instructor_id!r} (instructor_id is a username "
                      f"placeholder, resolved against users.username)")
                continue
            real_instructor_id = user_row["instructor_id"]
            added_by = user_row["id"]

            existing = conn.execute(
                "SELECT 1 FROM personalized_excerpts_src WHERE instructor_id = ? AND rubric_id = ? LIMIT 1",
                (real_instructor_id, rubric_id),
            ).fetchone()
            if existing:
                continue

            source_essay_text = {e["source_essay_id"]: e["text"] for e in data["source_essays"]}

            for ex in data["excerpts"]:
                try:
                    insert_personalized_excerpt(
                        conn,
                        rubric_id=rubric_id,
                        criterion_id=ex["criterion_id"],
                        instructor_id=real_instructor_id,
                        course_id=course_id,
                        assignment_id=assignment_id,
                        excerpt_text=ex["excerpt_text"],
                        score=ex["score"],
                        anchor_matched=ex["anchor_matched"],
                        rationale=ex["rationale"],
                        source=ex["source"],
                        added_by=added_by,
                        source_essay_text=source_essay_text[ex["source_essay_id"]],
                    )
                except EvidenceVerificationError as e:
                    print(f"seed_personalized_excerpts: skipping {path.name} excerpt "
                          f"(id={ex['excerpt_id']!r}, criterion={ex['criterion_id']!r}): {e}")

            profile = data.get("instructor_profile")
            if profile:
                now = datetime.now(UTC).isoformat()
                conn.execute(
                    """INSERT INTO instructor_profile
                       (instructor_id, grading_philosophy, deprioritized_criteria_json, rationale_tone, updated_at)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT (instructor_id) DO UPDATE SET
                         grading_philosophy=excluded.grading_philosophy,
                         deprioritized_criteria_json=excluded.deprioritized_criteria_json,
                         rationale_tone=excluded.rationale_tone, updated_at=excluded.updated_at""",
                    (
                        real_instructor_id,
                        profile.get("grading_philosophy"),
                        json.dumps(profile["deprioritized_criteria"]) if profile.get("deprioritized_criteria") is not None else None,
                        profile.get("rationale_tone"),
                        now,
                    ),
                )
        conn.commit()
