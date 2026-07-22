"""Divergence computation (design doc §8).

Drives surfacing only — badges, sort order, review queue inclusion — never
gates whether the personalized score is output (§2, §8, §15).
"""
from dataclasses import dataclass

from app.grading.engine_types import AggregateResult


@dataclass
class Divergence:
    score_diff: float | None
    anchor_mismatch: bool
    no_evidence_asymmetry: bool
    exceeds_threshold: bool


def compute_divergence(result_e: AggregateResult, result_p: AggregateResult, threshold: int) -> Divergence:
    e_no_evidence = result_e.score is None
    p_no_evidence = result_p.score is None
    no_evidence_asymmetry = e_no_evidence != p_no_evidence

    score_diff = None if (e_no_evidence or p_no_evidence) else abs(result_e.score - result_p.score)
    anchor_mismatch = result_e.anchor_matched != result_p.anchor_matched
    exceeds_threshold = (score_diff is not None and score_diff >= threshold) or no_evidence_asymmetry

    return Divergence(
        score_diff=score_diff,
        anchor_mismatch=anchor_mismatch,
        no_evidence_asymmetry=no_evidence_asymmetry,
        exceeds_threshold=exceeds_threshold,
    )
