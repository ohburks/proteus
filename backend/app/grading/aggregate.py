"""Multi-pass aggregation: median score + spread/confidence over N independent
passes of the *same* path (design doc §7 multi-pass extension).

`spread` (within-path disagreement across repeated passes) is a distinct
concept from `Divergence` (grading/divergence.py, between-path disagreement)
and must never share a name, column, or UI badge with it — see engine_types.py.
"""
import statistics

from app.grading.engine_types import AggregateResult, PassResult

# Score scale is 0-5 (schema.sql score_records_v2 CHECK), so 5 is the
# maximum possible spread; used only to normalize the confidence heuristic.
SCORE_SCALE = 5


def _spread_to_confidence(spread: float) -> float:
    """Lower spread -> higher confidence. Linear falloff over the full scale,
    clamped to [0, 1]."""
    return max(0.0, min(1.0, 1.0 - (spread / SCORE_SCALE)))


def aggregate_passes(passes: list[PassResult]) -> AggregateResult:
    if not passes:
        raise ValueError("aggregate_passes requires at least one pass")

    scored = [p for p in passes if p.score is not None]

    if not scored:
        # Every pass came back no-evidence — the path's aggregate result for
        # this criterion is no-evidence too, same as today's single-pass case.
        rep = passes[0]
        return AggregateResult(
            score=None,
            anchor_matched=0,
            evidence=[],
            rationale=rep.rationale,
            confidence=0.0,
            precedent_referenced=[],
            precedent_ids=rep.precedent_ids,
            spread=None,
            n_passes=len(passes),
            passes=passes,
        )

    scores = [p.score for p in scored]
    median_score = statistics.median(scores)
    spread = max(scores) - min(scores)

    # The representative pass backs the aggregate's evidence/rationale/anchor:
    # the pass whose own score is closest to the median (ties broken by
    # earliest pass), so the median always corresponds to an actual, verified
    # LLM output rather than a synthetic blend.
    representative = min(scored, key=lambda p: (abs(p.score - median_score), scored.index(p)))

    return AggregateResult(
        score=float(median_score),
        anchor_matched=representative.anchor_matched,
        evidence=representative.evidence,
        rationale=representative.rationale,
        confidence=_spread_to_confidence(spread),
        precedent_referenced=representative.precedent_referenced,
        precedent_ids=representative.precedent_ids,
        spread=float(spread),
        n_passes=len(passes),
        passes=passes,
    )
