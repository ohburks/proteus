"""Profile layers and cascading field resolution (design doc §6).

§6.1: the field split that governs everything here — factual/contextual
fields feed BOTH grading paths; stylistic/instructor-specific fields feed
the Personalized path only and are structurally absent from the Exemplar
path's prompt (not null/empty — omitted).

§6.4 judgment call (resolved with the user): criterion_emphasis_notes is
treated as assignment pedagogy, fed to BOTH paths, alongside prompt_text /
format_expectations.
"""
import json
import sqlite3
from dataclasses import dataclass


@dataclass
class BothPathsContext:
    """§6.6 [ASSIGNMENT CONTEXT] — factual, resolved via §6.5, both paths."""
    prompt_text: str | None
    format_expectations: str | None
    criterion_emphasis_notes: str | None
    curriculum_texts: list[str] | None
    cohort_level: str | None


@dataclass
class PersonalizedOnlyContext:
    """§6.6 [INSTRUCTOR GUIDANCE] — personalized path only."""
    grading_philosophy: str | None
    deprioritized_criteria: list[str] | None
    rationale_tone: str | None


def resolve_both_paths_context(conn: sqlite3.Connection, assignment_id: str) -> BothPathsContext:
    a = conn.execute(
        "SELECT * FROM assignment_profile WHERE assignment_id = ?", (assignment_id,)
    ).fetchone()
    course_id = a["course_id"] if a else None
    c = (
        conn.execute("SELECT * FROM course_profile WHERE course_id = ?", (course_id,)).fetchone()
        if course_id else None
    )
    return BothPathsContext(
        prompt_text=a["prompt_text"] if a else None,
        format_expectations=a["format_expectations"] if a else None,
        criterion_emphasis_notes=a["criterion_emphasis_notes"] if a else None,
        curriculum_texts=json.loads(c["curriculum_texts_json"]) if c and c["curriculum_texts_json"] else None,
        cohort_level=c["cohort_level"] if c else None,
    )


def resolve_personalized_only_context(conn: sqlite3.Connection, instructor_id: str) -> PersonalizedOnlyContext:
    i = conn.execute(
        "SELECT * FROM instructor_profile WHERE instructor_id = ?", (instructor_id,)
    ).fetchone()
    if not i:
        return PersonalizedOnlyContext(None, None, None)
    return PersonalizedOnlyContext(
        grading_philosophy=i["grading_philosophy"],
        deprioritized_criteria=json.loads(i["deprioritized_criteria_json"]) if i["deprioritized_criteria_json"] else None,
        rationale_tone=i["rationale_tone"],
    )
