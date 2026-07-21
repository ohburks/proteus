"""Structured system prompt builder (design doc §6.6).

The [INSTRUCTOR GUIDANCE] section is the actual path-separation enforcement
mechanism: it is omitted entirely (not rendered empty) for the Exemplar
path, never just left blank — §6.1, §6.6.
"""
import json

from app.grading.profiles import BothPathsContext, PersonalizedOnlyContext


def _criterion_block(criterion: dict) -> str:
    anchors = "\n".join(f"  {k}: {v}" for k, v in criterion["anchors"].items())
    return f"{criterion['statement']}\nAnchors:\n{anchors}"


def _assignment_context_block(ctx: BothPathsContext) -> str:
    lines = []
    if ctx.prompt_text:
        lines.append(f"Assignment prompt: {ctx.prompt_text}")
    if ctx.format_expectations:
        lines.append(f"Format expectations: {ctx.format_expectations}")
    if ctx.criterion_emphasis_notes:
        lines.append(f"Criterion emphasis notes: {ctx.criterion_emphasis_notes}")
    if ctx.cohort_level:
        lines.append(f"Cohort level: {ctx.cohort_level}")
    if ctx.curriculum_texts:
        lines.append(f"Curriculum texts referenced by this course: {', '.join(ctx.curriculum_texts)}")
    return "\n".join(lines) if lines else "(none provided)"


def _instructor_guidance_block(ctx: PersonalizedOnlyContext) -> str:
    lines = []
    if ctx.grading_philosophy:
        lines.append(f"Grading philosophy: {ctx.grading_philosophy}")
    if ctx.deprioritized_criteria:
        lines.append(f"Deprioritized criteria (do not strictly enforce): {', '.join(ctx.deprioritized_criteria)}")
    if ctx.rationale_tone:
        lines.append(f"Rationale tone: {ctx.rationale_tone}")
    return "\n".join(lines) if lines else "(none provided)"


def _precedent_block(pool: list[dict]) -> str:
    if not pool:
        return "(no precedent retrieved)"
    parts = []
    for item in pool:
        meta = item["metadata"]
        parts.append(
            f"- id: {item['id']}\n"
            f"  quote: {item['document']!r}\n"
            f"  score: {meta['score']}\n"
            f"  anchor_matched: {meta['anchor_matched']}\n"
            f"  rationale: {meta['rationale']}"
        )
    return "\n".join(parts)


OUTPUT_SCHEMA = """{
  "evidence": [{"quote": string, "reasoning": string}],
  "anchorMatched": int (0-5),
  "score": int (0-5) | "no-evidence",
  "selfConfidence": float (0-1),
  "precedent_referenced": [excerpt_id, ...]
}"""


def build_system_prompt(
    *,
    path: str,  # "exemplar" | "personalized"
    criterion: dict,
    rubric_id: str,
    both_paths_ctx: BothPathsContext,
    personalized_only_ctx: PersonalizedOnlyContext | None,
    precedent_pool: list[dict],
) -> str:
    sections = [
        "[ROLE/TASK]",
        f"Grade the following essay excerpt against criterion {criterion['criterionId']} "
        f"of the {rubric_id} rubric. Output must follow the schema below.",
        "",
        "[RUBRIC CRITERION]",
        _criterion_block(criterion),
        "",
        "[ASSIGNMENT CONTEXT]",
        _assignment_context_block(both_paths_ctx),
        "",
    ]
    if path == "personalized":
        sections += [
            "[INSTRUCTOR GUIDANCE]",
            _instructor_guidance_block(personalized_only_ctx or PersonalizedOnlyContext(None, None, None)),
            "",
        ]
    sections += [
        "[PRECEDENT]",
        _precedent_block(precedent_pool),
        "",
        "[OUTPUT SCHEMA]",
        "Respond with a single JSON object matching exactly:",
        OUTPUT_SCHEMA,
    ]
    return "\n".join(sections)


def build_user_prompt(essay_text: str) -> str:
    return f"[ESSAY TEXT]\n{essay_text}"
