"""Dual-path grading flow (design doc §7).

Both paths reuse the same per-criterion, multi-pass, evidence-provenance-
guarded grading logic — only the retrieval source differs (§7). No prompt
ever mixes exemplar and personalized precedent (§15).

Grading-time evidence check (§3.5): every cited quote in a freshly produced
score is verified against the essay currently being graded, every call,
regardless of retrieval. A quote that fails is not silently dropped — the
model gets one corrective pass naming the failed quote(s); if evidence still
fails to verify after MAX_EVIDENCE_CORRECTION_ATTEMPTS, the pass falls back to
"no-evidence" rather than persisting an ungrounded claim. This per-pass
verification runs independently for every one of the N sampling passes below,
not just once on an aggregate.

Multi-pass sampling (design doc §7 extension): each path runs N independent,
identically-prompted passes per criterion — same retrieved precedent, same
prompt, only sampling varies — and the path's result is the median of those N
scores (grading/aggregate.py), plus a spread/confidence summary. N is shared
by both paths within a single run (GRADING_N_PASSES): letting the paths use
different pass counts would make any difference in how "settled" one path's
output looks an artifact of sample size, not a real stability difference —
the same reason provider/model is a run-level, not per-path, setting
(llm/key_resolution.py §14.3).
"""
import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime

from app.db import write_with_retry
from app.grading.aggregate import aggregate_passes
from app.grading.divergence import compute_divergence
from app.grading.engine_types import AggregateResult, Evidence, PassResult
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
from app.repositories.settings import (
    lookup_divergence_threshold,
    lookup_pool_threshold,
    lookup_spread_threshold,
)

# Evidence-correction retries within a single sampling pass (§3.5) — unrelated
# to N below, which controls how many independent sampling passes are taken.
MAX_EVIDENCE_CORRECTION_ATTEMPTS = 2

# Default to a single pass: at temperature=0 (providers.py) repeated passes
# are near-deterministic and the resulting "confidence" is a stability
# artifact, not evidence of correctness (see review.py's pass_stability
# rename). Override via GRADING_N_PASSES below for real repeated-pass
# stability checking when that's actually being evaluated.
DEFAULT_N_GRADING_PASSES = 1


def _n_grading_passes() -> int:
    # Tunable without a code change (design doc §7 multi-pass): override via
    # GRADING_N_PASSES in the server environment.
    return int(os.environ.get("GRADING_N_PASSES", str(DEFAULT_N_GRADING_PASSES)))


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
    """One independent sampling pass, with its own evidence-correction retries."""
    precedent_ids = [p["id"] for p in precedent_pool]
    user_prompt = build_user_prompt(essay_text)
    failed_quotes: list[str] = []
    # D1: a real numeric score with zero cited evidence used to sail straight
    # through here (an empty evidence list has no bad quotes to catch), so it
    # never got a correction retry the way an unverifiable quote does. Route
    # it through the same retry mechanism instead of accepting it silently.
    needs_evidence = False

    for attempt in range(MAX_EVIDENCE_CORRECTION_ATTEMPTS):
        prompt = user_prompt
        if failed_quotes:
            if emit:
                emit(f"correcting {len(failed_quotes)} unverifiable quote(s)…")
            prompt += (
                "\n\n[CORRECTION REQUIRED]\nThe following quoted evidence did not appear "
                "verbatim in the essay text above and must be replaced with a real quote "
                "from the essay, or dropped if no such quote exists:\n"
                + "\n".join(f"- {q!r}" for q in failed_quotes)
            )
        elif needs_evidence:
            if emit:
                emit("correcting: score given with no cited evidence…")
            prompt += (
                "\n\n[CORRECTION REQUIRED]\nYou gave a numeric score with no cited "
                "evidence. Either cite at least one verbatim quote from the essay that "
                "supports this score, or change the score to \"no-evidence\" if none "
                "exists."
            )
        raw = client.complete(system_prompt, prompt, emit=emit)
        parsed = _parse_response(raw)

        evidence_items = [Evidence(quote=e["quote"], reasoning=e["reasoning"]) for e in parsed.get("evidence", [])]
        bad = [e.quote for e in evidence_items if not verify_quote(e.quote, essay_text)]
        raw_score = parsed.get("score")
        score = None if raw_score == "no-evidence" else int(raw_score)
        unsupported = score is not None and not evidence_items

        if not bad and not unsupported:
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
        needs_evidence = unsupported and not bad

    # Every pass either had an unverifiable quote or an unsupported score
    # after all correction attempts — fall back to no-evidence rather than
    # persist an ungrounded claim (§3.5).
    return PassResult(
        score=None,
        anchor_matched=0,
        evidence=[],
        rationale="No verifiable evidence could be produced after correction passes.",
        confidence=0.0,
        precedent_referenced=[],
        precedent_ids=precedent_ids,
    )


def _run_multi_pass(
    client: LLMClient, system_prompt: str, essay_text: str, precedent_pool: list[dict],
    n: int, emit: EmitFn | None = None,
) -> list[PassResult]:
    """N fully independent sampling passes against identical inputs (same
    precedent, same prompt) — only sampling varies between them, never the
    retrieval or prompt content."""
    passes = []
    for i in range(n):
        if emit:
            emit(f"sampling pass {i + 1}/{n}…")
        passes.append(_run_graded_pass(client, system_prompt, essay_text, precedent_pool, emit=emit))
    return passes


def grade_criterion_exemplar(
    client: LLMClient, criterion: dict, rubric_id: str, rubric_version: str,
    essay_text: str, both_paths_ctx: BothPathsContext, n_passes: int, emit: EmitFn | None = None,
) -> AggregateResult:
    pool = query_exemplar_pool(essay_text, criterion["criterionId"], rubric_id, rubric_version)
    if emit:
        emit(f"Exemplar pool: {len(pool)} precedent(s) retrieved")
    system_prompt = build_system_prompt(
        path="exemplar", criterion=criterion, rubric_id=rubric_id,
        both_paths_ctx=both_paths_ctx, personalized_only_ctx=None, precedent_pool=pool,
    )
    passes = _run_multi_pass(client, system_prompt, essay_text, pool, n_passes, emit=emit)
    return aggregate_passes(passes)


def grade_criterion_personalized(
    conn: sqlite3.Connection, client: LLMClient, criterion: dict, rubric_id: str,
    essay_text: str, both_paths_ctx: BothPathsContext, scope: Scope, n_passes: int, emit: EmitFn | None = None,
) -> AggregateResult:
    k = lookup_pool_threshold(conn, scope.instructor_id, rubric_id, criterion["criterionId"])
    pool = assemble_personalized_pool(essay_text, scope, criterion["criterionId"], rubric_id, k=k)
    if emit:
        emit(f"Personalized pool: {len(pool)} precedent(s) retrieved")
    personalized_ctx = resolve_personalized_only_context(conn, scope.instructor_id)
    system_prompt = build_system_prompt(
        path="personalized", criterion=criterion, rubric_id=rubric_id,
        both_paths_ctx=both_paths_ctx, personalized_only_ctx=personalized_ctx, precedent_pool=pool,
    )
    passes = _run_multi_pass(client, system_prompt, essay_text, pool, n_passes, emit=emit)
    return aggregate_passes(passes)


def _persist_passes(
    conn: sqlite3.Connection, assessment_id: str, criterion_id: str, path: str, passes: list[PassResult],
) -> None:
    for i, result in enumerate(passes):
        conn.execute(
            """INSERT INTO score_records_v2
               (id, assessment_id, criterion_id, path, pass_index, score, is_no_evidence, anchor_matched,
                evidence_json, precedent_ids_json, confidence, rationale, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()), assessment_id, criterion_id, path, i,
                result.score, int(result.score is None), result.anchor_matched,
                json.dumps([{"quote": e.quote, "reasoning": e.reasoning} for e in result.evidence]),
                json.dumps(result.precedent_referenced), result.confidence, result.rationale, _now(),
            ),
        )


def _persist_aggregate(
    conn: sqlite3.Connection, assessment_id: str, criterion_id: str, path: str,
    aggregate: AggregateResult, spread_threshold: float,
) -> None:
    high_spread = aggregate.spread is not None and aggregate.spread >= spread_threshold
    conn.execute(
        """INSERT INTO score_aggregates
           (assessment_id, criterion_id, path, score, is_no_evidence, anchor_matched,
            evidence_json, precedent_ids_json, rationale, spread, confidence, high_spread,
            n_passes, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            assessment_id, criterion_id, path,
            aggregate.score, int(aggregate.score is None), aggregate.anchor_matched,
            json.dumps([{"quote": e.quote, "reasoning": e.reasoning} for e in aggregate.evidence]),
            json.dumps(aggregate.precedent_referenced), aggregate.rationale,
            aggregate.spread, aggregate.confidence, int(high_spread), aggregate.n_passes, _now(),
        ),
    )


def run_dual_path_for_criterion(
    conn: sqlite3.Connection, client: LLMClient, *, assessment_id: str, criterion: dict,
    rubric_id: str, rubric_version: str, essay_text: str, assignment_id: str,
    instructor_id: str, course_id: str | None, emit: EmitFn | None = None,
) -> None:
    """Design doc §7, steps 1-5, for a single criterion.

    N sampling passes are taken per path (GRADING_N_PASSES, same count for
    both paths within this call — see module docstring) and reduced to a
    median/spread/confidence aggregate; every raw pass is still persisted for
    audit alongside the aggregate.
    """
    both_paths_ctx = resolve_both_paths_context(conn, assignment_id)
    scope = Scope(instructor_id=instructor_id, course_id=course_id, assignment_id=assignment_id)
    n_passes = _n_grading_passes()
    spread_threshold = lookup_spread_threshold(conn, instructor_id, rubric_id, criterion["criterionId"])

    if emit:
        emit(f"Criterion {criterion['criterionId']}: grading exemplar path ({n_passes} passes)…")
    result_e = grade_criterion_exemplar(
        client, criterion, rubric_id, rubric_version, essay_text, both_paths_ctx, n_passes, emit=emit
    )
    if emit:
        score_str = result_e.score if result_e.score is not None else "no-evidence"
        emit(
            f"Criterion {criterion['criterionId']}: exemplar path done — score={score_str}, "
            f"spread={result_e.spread}, confidence={result_e.confidence:.2f}, anchor={result_e.anchor_matched}"
        )

    if emit:
        emit(f"Criterion {criterion['criterionId']}: grading personalized path ({n_passes} passes)…")
    result_p = grade_criterion_personalized(
        conn, client, criterion, rubric_id, essay_text, both_paths_ctx, scope, n_passes, emit=emit
    )
    if emit:
        score_str = result_p.score if result_p.score is not None else "no-evidence"
        emit(
            f"Criterion {criterion['criterionId']}: personalized path done — score={score_str}, "
            f"spread={result_p.spread}, confidence={result_p.confidence:.2f}, anchor={result_p.anchor_matched}"
        )

    threshold = lookup_divergence_threshold(conn, instructor_id, rubric_id, criterion["criterionId"])
    divergence = compute_divergence(result_e, result_p, threshold)

    # Persist this criterion's rows (both paths + divergence) as one unit,
    # committed per criterion rather than once for the whole assessment: the
    # SQLite write lock is held only briefly, so a concurrent grading run or web
    # request isn't blocked for the entire multi-minute run. write_with_retry
    # survives a transient "database is locked" (rolling the partial rows back
    # first), so contention degrades into a short wait instead of a failed
    # assessment; completed criteria stay checkpointed if a later one fails.
    def _persist_criterion() -> None:
        _persist_passes(conn, assessment_id, criterion["criterionId"], "exemplar", result_e.passes)
        _persist_aggregate(conn, assessment_id, criterion["criterionId"], "exemplar", result_e, spread_threshold)
        _persist_passes(conn, assessment_id, criterion["criterionId"], "personalized", result_p.passes)
        _persist_aggregate(conn, assessment_id, criterion["criterionId"], "personalized", result_p, spread_threshold)
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

    write_with_retry(conn, _persist_criterion)

    if emit:
        if divergence.exceeds_threshold:
            emit(f"Criterion {criterion['criterionId']}: divergence EXCEEDS threshold (diff={divergence.score_diff})")
        else:
            emit(f"Criterion {criterion['criterionId']}: divergence within threshold (diff={divergence.score_diff})")
    # Output grade for this criterion = result_p.score (the median aggregate),
    # always (§7 step 5). No separate "output" column is stored: consumers
    # read score_aggregates where path='personalized', optionally overridden
    # by score_overrides (§9). score_records_v2 holds every raw pass, for audit.
