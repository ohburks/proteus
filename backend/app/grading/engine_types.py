from dataclasses import dataclass


@dataclass
class Evidence:
    quote: str
    reasoning: str


@dataclass
class PassResult:
    score: int | None  # None means "no-evidence"
    anchor_matched: int
    evidence: list[Evidence]
    rationale: str
    confidence: float  # this pass's own self-reported confidence (raw LLM output)
    precedent_referenced: list[str]
    precedent_ids: list[str]  # all precedent ids offered to the model this pass


@dataclass
class AggregateResult:
    """One path's multi-pass result for one criterion: median of N independent
    passes plus a spread/confidence summary over them (design doc §7 multi-pass).

    `spread` measures disagreement *within* this path's own repeated passes —
    not to be confused with `Divergence` (grading/divergence.py), which measures
    disagreement *between* the exemplar and personalized paths. The two must
    never be conflated: this is "is this path stable with itself?", divergence
    is "do the two paths agree with each other?".
    """
    score: float | None  # median across evidence-bearing passes; None if every pass was no-evidence
    anchor_matched: int
    evidence: list[Evidence]  # from the representative pass (closest to the median score)
    rationale: str  # from the representative pass
    confidence: float  # spread-derived heuristic — NOT a raw per-pass selfConfidence
    precedent_referenced: list[str]
    precedent_ids: list[str]
    spread: float | None  # max - min across evidence-bearing passes' scores; None if no-evidence
    n_passes: int
    passes: list[PassResult]  # every raw pass, kept for audit (score/evidence/rationale/confidence each)
