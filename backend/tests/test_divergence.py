from app.grading.divergence import compute_divergence
from app.grading.engine_types import AggregateResult


def _agg(score, anchor_matched=0):
    return AggregateResult(
        score=score,
        anchor_matched=anchor_matched,
        evidence=[],
        rationale="r",
        confidence=0.9,
        precedent_referenced=[],
        precedent_ids=[],
        spread=0.0 if score is not None else None,
        n_passes=1,
        passes=[],
    )


def test_identical_scores_and_anchors_diverge_on_nothing():
    divergence = compute_divergence(_agg(4, anchor_matched=4), _agg(4, anchor_matched=4), threshold=2)

    assert divergence.score_diff == 0
    assert divergence.anchor_mismatch is False
    assert divergence.no_evidence_asymmetry is False
    assert divergence.exceeds_threshold is False


def test_score_diff_exactly_at_threshold_exceeds():
    divergence = compute_divergence(_agg(4), _agg(2), threshold=2)

    assert divergence.score_diff == 2
    assert divergence.exceeds_threshold is True


def test_score_diff_just_below_threshold_does_not_exceed():
    divergence = compute_divergence(_agg(4), _agg(3), threshold=2)

    assert divergence.score_diff == 1
    assert divergence.exceeds_threshold is False


def test_anchor_mismatch_alone_does_not_trigger_exceeds_threshold():
    # Same score, different anchor fit: anchor_mismatch is reported, but it
    # is not one of the inputs to exceeds_threshold - only score_diff and
    # no_evidence_asymmetry are (design doc: surfacing only, no gating).
    divergence = compute_divergence(_agg(4, anchor_matched=4), _agg(4, anchor_matched=2), threshold=2)

    assert divergence.score_diff == 0
    assert divergence.anchor_mismatch is True
    assert divergence.exceeds_threshold is False


def test_no_evidence_asymmetry_when_only_one_path_has_a_score():
    divergence = compute_divergence(_agg(4, anchor_matched=4), _agg(None), threshold=2)

    assert divergence.score_diff is None
    assert divergence.no_evidence_asymmetry is True
    assert divergence.exceeds_threshold is True


def test_no_evidence_asymmetry_is_direction_independent():
    divergence = compute_divergence(_agg(None), _agg(4, anchor_matched=4), threshold=2)

    assert divergence.no_evidence_asymmetry is True
    assert divergence.exceeds_threshold is True


def test_both_paths_no_evidence_is_not_an_asymmetry():
    divergence = compute_divergence(_agg(None), _agg(None), threshold=2)

    assert divergence.score_diff is None
    assert divergence.no_evidence_asymmetry is False
    assert divergence.anchor_mismatch is False
    assert divergence.exceeds_threshold is False


def test_zero_threshold_means_any_nonzero_diff_exceeds():
    divergence = compute_divergence(_agg(4), _agg(3), threshold=0)

    assert divergence.score_diff == 1
    assert divergence.exceeds_threshold is True


def test_zero_threshold_exceeds_even_on_zero_diff():
    # >= is inclusive, so threshold=0 means every score_diff, including an
    # exact match, counts as "exceeding" - a threshold of 0 effectively
    # always surfaces. Worth asserting explicitly since it is easy to
    # assume threshold=0 means "off".
    divergence = compute_divergence(_agg(4), _agg(4), threshold=0)

    assert divergence.score_diff == 0
    assert divergence.exceeds_threshold is True
