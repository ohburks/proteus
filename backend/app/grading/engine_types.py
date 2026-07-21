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
    confidence: float
    precedent_referenced: list[str]
    precedent_ids: list[str]  # all precedent ids offered to the model this pass
