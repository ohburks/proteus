import pytest

from app.grading.aggregate import aggregate_passes
from app.grading.engine_types import PassResult


def _pass(score, rationale="r", precedent_ids=None):
    return PassResult(
        score=score,
        anchor_matched=score if score is not None else 0,
        evidence=[],
        rationale=rationale,
        confidence=0.9,
        precedent_referenced=[],
        precedent_ids=precedent_ids or [],
    )


def test_odd_count_median_and_spread():
    result = aggregate_passes([_pass(3), _pass(4), _pass(5)])

    assert result.score == 4
    assert result.spread == 2
    assert result.confidence == pytest.approx(0.6)
    assert result.anchor_matched == 4
    assert result.n_passes == 3


def test_even_count_median_is_the_midpoint():
    result = aggregate_passes([_pass(2), _pass(4)])

    assert result.score == 3.0
    assert result.spread == 2
    assert result.confidence == pytest.approx(0.6)


def test_even_count_tie_breaks_to_earliest_pass():
    # Both scores are equally close to the median (3) - the earlier one
    # (score=2, rationale="first") must win, not the later one.
    result = aggregate_passes([_pass(2, rationale="first"), _pass(4, rationale="second")])

    assert result.rationale == "first"
    assert result.anchor_matched == 2


def test_exact_median_match_wins_representative_over_a_tie():
    # 3 is the median and an exact match (diff 0); the other pass at 3 is
    # also an exact match, so the earliest of the two wins.
    result = aggregate_passes([_pass(3, rationale="first"), _pass(3, rationale="second"), _pass(5)])

    assert result.score == 3
    assert result.rationale == "first"


def test_all_no_evidence_passes_aggregate_to_no_evidence():
    passes = [_pass(None, rationale="no evidence here"), _pass(None)]

    result = aggregate_passes(passes)

    assert result.score is None
    assert result.spread is None
    assert result.confidence == 0.0
    assert result.anchor_matched == 0
    assert result.evidence == []
    assert result.rationale == "no evidence here"
    assert result.n_passes == 2


def test_no_evidence_passes_are_excluded_from_the_median():
    passes = [_pass(None), _pass(4, rationale="the only scored pass"), _pass(None)]

    result = aggregate_passes(passes)

    assert result.score == 4
    assert result.spread == 0
    assert result.confidence == pytest.approx(1.0)
    assert result.rationale == "the only scored pass"
    assert result.n_passes == 3


def test_zero_spread_gives_full_confidence():
    result = aggregate_passes([_pass(3), _pass(3), _pass(3)])

    assert result.spread == 0
    assert result.confidence == pytest.approx(1.0)


def test_maximum_spread_gives_zero_confidence():
    # Score scale is 0-5, so a 5-point spread is the worst case.
    result = aggregate_passes([_pass(0), _pass(5)])

    assert result.spread == 5
    assert result.confidence == pytest.approx(0.0)


def test_empty_pass_list_is_rejected():
    with pytest.raises(ValueError):
        aggregate_passes([])
