"""Dual-path grading flow (design doc §7).

Both paths reuse the same per-criterion, multi-pass, evidence-provenance-
guarded grading logic — only the retrieval source differs (§7). No prompt
ever mixes exemplar and personalized precedent (§15).

Grading-time evidence check (§3.5): every cited quote in a freshly produced
score is verified against the essay currently being graded, every call,
regardless of retrieval. A quote that fails is not silently dropped — the
model gets one corrective pass naming the failed quote(s); if evidence still
fails to verify after MAX_PASSES, the pass falls back to "no-evidence" rather
than persisting an ungrounded claim.
"""
import json
import sqlite3
import uuid
from datetime import UTC, datetime

from app.grading.divergence import compute_divergence
from app.grading.engine_types import Evidence, PassResult
from app.grading.evidence import verify_quote
from app.grading.profiles import (
    BothPathsContext,
    PersonalizedOnlyContext,
    resolve_both_paths_context,
    resolve_personalized_only_context,
)
from app.grading.prompt import build_system_prompt, build_user_prompt
from app.grading.retrieval import Scope, assemble_personalized_pool, query_exemplar_pool
from app.llm.base import EmitFn, LLMClient
from app.repositories.settings import lookup_divergence_threshold, lookup_pool_threshold

MAX_PASSES = 2


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_response(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM response was not valid JSON: {raw!r}") from e


def _run_graded_pass(
    client: LLMClient, system_prompt: str, essay_text: str, precedent_pool: list[dict],
    emit: EmitFn | None = None,
) -> PassResult:
    precedent_ids = [p["id"] for p in precedent_pool]
    user_prompt = build_user_prompt(essay_text)
    failed_quotes: list[str] = []

    for attempt in range(MAX_PASSES):
        prompt = user_prompt
        if failed_quotes:
            if emit:
                emit(f"Pass {attempt + 1}/{MAX_PASSES}: correcting {len(failed_quotes)} unverifiable quote(s)…")
            prompt += (
                "\n\n[CORRECTION REQUIRED]\nThe following quoted evidence did not appear "
                "verbatim in the essay text above and must be replaced with a real quote "
                "from the essay, or dropped if no such quote exists:\n"
                + "\n".join(f"- {q!r}" for q in failed_quotes)
            )
        raw = client.complete(system_prompt, prompt, emit=emit)
        parsed = _parse_response(raw)

        evidence_items = [Evidence(quote=e["quote"], reasoning=e["reasoning"]) for e in parsed.get("evidence", [])]
        bad = [e.quote for e in evidence_items if not verify_quote(e.quote, essay_text)]

        if not bad:
            raw_score = parsed.get("score")
            score = None if raw_score == "no-evidence" else int(raw_score)
            return PassResult(
                score=score,
                anchor_matched=int(parsed["anchorMatched"]),
                evidence=evidence_items,
                rationale=parsed.get("rationale", ""),
                confidence=float(parsed.get("selfConfidence", 0.0)),
                precedent_referenced=list(parsed.get("precedent_referenced", [])),
                precedent_ids=precedent_ids,
            )
        failed_quotes = bad

    # Every pass produced at least one unverifiable quote — fall back to
    # no-evidence rather than persist an ungrounded claim (§3.5).
    return PassResult(
        score=None,
        anchor_matched=0,
        evidence=[],
        rationale="No verifiable evidence could be produced after correction passes.",
        confidence=0.0,
        precedent_referenced=[],
        precedent_ids=precedent_ids,
    )


def grade_criterion_exemplar(
    client: LLMClient, criterion: dict, rubric_id: str, rubric_version: str,
    essay_text: str, both_paths_ctx: BothPathsContext, emit: EmitFn | None = None,
) -> PassResult:
    pool = query_exemplar_pool(essay_text, criterion["criterionId"], rubric_id, rubric_version)
    if emit:
        emit(f"Exemplar pool: {len(pool)} precedent(s) retrieved")
    system_prompt = build_system_prompt(
        path="exemplar", criterion=criterion, rubric_id=rubric_id,
        both_paths_ctx=both_paths_ctx, personalized_only_ctx=None, precedent_pool=pool,
    )
    return _run_graded_pass(client, system_prompt, essay_text, pool, emit=emit)


def grade_criterion_personalized(
    conn: sqlite3.Connection, client: LLMClient, criterion: dict, rubric_id: str,
    essay_text: str, both_paths_ctx: BothPathsContext, scope: Scope, emit: EmitFn | None = None,
) -> PassResult:
    k = lookup_pool_threshold(conn, scope.instructor_id, rubric_id, criterion["criterionId"])
    pool = assemble_personalized_pool(essay_text, scope, criterion["criterionId"], rubric_id, k=k)
    if emit:
        emit(f"Personalized pool: {len(pool)} precedent(s) retrieved")
    personalized_ctx = resolve_personalized_only_context(conn, scope.instructor_id)
    system_prompt = build_system_prompt(
        path="personalized", criterion=criterion, rubric_id=rubric_id,
        both_paths_ctx=both_paths_ctx, personalized_only_ctx=personalized_ctx, precedent_pool=pool,
    )
    return _run_graded_pass(client, system_prompt, essay_text, pool, emit=emit)


def _persist_score_record(conn: sqlite3.Connection, assessment_id: str, criterion_id: str, path: str, result: PassResult) -> None:
    conn.execute(
        """INSERT INTO score_records_v2
           (id, assessment_id, criterion_id, path, score, is_no_evidence, anchor_matched,
            evidence_json, precedent_ids_json, confidence, rationale, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            str(uuid.uuid4()), assessment_id, criterion_id, path,
            result.score, int(result.score is None), result.anchor_matched,
            json.dumps([{"quote": e.quote, "reasoning": e.reasoning} for e in result.evidence]),
            json.dumps(result.precedent_referenced), result.confidence, result.rationale, _now(),
        ),
    )


def run_dual_path_for_criterion(
    conn: sqlite3.Connection, client: LLMClient, *, assessment_id: str, criterion: dict,
    rubric_id: str, rubric_version: str, essay_text: str, assignment_id: str,
    instructor_id: str, course_id: str | None, emit: EmitFn | None = None,
) -> None:
    """Design doc §7, steps 1-5, for a single criterion."""
    both_paths_ctx = resolve_both_paths_context(conn, assignment_id)
    scope = Scope(instructor_id=instructor_id, course_id=course_id, assignment_id=assignment_id)

    if emit:
        emit(f"Criterion {criterion['criterionId']}: grading exemplar path…")
    result_e = grade_criterion_exemplar(
        client, criterion, rubric_id, rubric_version, essay_text, both_paths_ctx, emit=emit
    )
    _persist_score_record(conn, assessment_id, criterion["criterionId"], "exemplar", result_e)
    if emit:
        score_str = result_e.score if result_e.score is not None else "no-evidence"
        emit(f"Criterion {criterion['criterionId']}: exemplar path done — score={score_str}, anchor={result_e.anchor_matched}")

    if emit:
        emit(f"Criterion {criterion['criterionId']}: grading personalized path…")
    result_p = grade_criterion_personalized(
        conn, client, criterion, rubric_id, essay_text, both_paths_ctx, scope, emit=emit
    )
    _persist_score_record(conn, assessment_id, criterion["criterionId"], "personalized", result_p)
    if emit:
        score_str = result_p.score if result_p.score is not None else "no-evidence"
        emit(f"Criterion {criterion['criterionId']}: personalized path done — score={score_str}, anchor={result_p.anchor_matched}")

    threshold = lookup_divergence_threshold(conn, instructor_id, rubric_id, criterion["criterionId"])
    divergence = compute_divergence(result_e, result_p, threshold)
    conn.execute(
        """INSERT INTO divergence_records
           (assessment_id, criterion_id, score_diff, anchor_mismatch, no_evidence_asymmetry, exceeds_threshold, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (
            assessment_id, criterion["criterionId"], divergence.score_diff,
            int(divergence.anchor_mismatch), int(divergence.no_evidence_asymmetry),
            int(divergence.exceeds_threshold), _now(),
        ),
    )
    if emit:
        if divergence.exceeds_threshold:
            emit(f"Criterion {criterion['criterionId']}: divergence EXCEEDS threshold (diff={divergence.score_diff})")
        else:
            emit(f"Criterion {criterion['criterionId']}: divergence within threshold (diff={divergence.score_diff})")
    # Output grade for this criterion = result_p.score, always (§7 step 5).
    # No separate "output" column is stored: consumers read score_records_v2
    # where path='personalized', optionally overridden by score_overrides (§9).
