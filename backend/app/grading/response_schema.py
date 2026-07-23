"""Strict schema for the raw LLM grading response (D2).

Previously this was manual json.loads() + dict.get()/dict[...] access
with silent defaults — a malformed or incomplete response degraded
quietly instead of failing loudly. This model makes the contract real:
anything that doesn't match is a validation error, routed through the
same correction-retry loop _run_graded_pass already uses for bad quotes
and unsupported evidence (D1) — same budget, same no-evidence fallback.
"""
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class EvidenceItemSchema(BaseModel):
    quote: str
    reasoning: str


class LLMGradingResponse(BaseModel):
    evidence: list[EvidenceItemSchema] = Field(default_factory=list)
    anchorMatched: int = Field(ge=0, le=5)
    score: int | Literal["no-evidence"]
    rationale: str = Field(min_length=1)
    selfConfidence: float = Field(ge=0, le=1)
    precedent_referenced: list[str] = Field(default_factory=list)

    @field_validator("score")
    @classmethod
    def _score_in_range(cls, v: int | str) -> int | str:
        if isinstance(v, int) and not (0 <= v <= 5):
            raise ValueError('score must be between 0 and 5, or "no-evidence"')
        return v
