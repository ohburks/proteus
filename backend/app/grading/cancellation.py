"""In-process cancellation signals for running assessments.

A grading run executes in a background thread (routers.assessments._run_assessment)
and works through the rubric's criteria one at a time. An in-flight LLM call can't
be interrupted mid-request, but between criteria the loop can check a shared flag
and stop early. This module is that flag: request() marks an assessment for
cancellation and is_cancelled() lets the grading loop poll it before starting the
next criterion.

In-memory and single-process, exactly like app.grading.progress — a cancel only
reaches a run in the same process. That matches the single-worker dev/demo
deployment this targets; it is not a distributed control plane. The registry only
ever holds ids that were explicitly cancelled and clears them when the run ends
(see _run_assessment's finally), so it stays small on its own.
"""
import threading

_cancelled: set[str] = set()
_lock = threading.Lock()


def request(assessment_id: str) -> None:
    """Signal that the given assessment's grading run should stop."""
    with _lock:
        _cancelled.add(assessment_id)


def is_cancelled(assessment_id: str) -> bool:
    """True if a cancel has been requested for this assessment and not yet cleared."""
    with _lock:
        return assessment_id in _cancelled


def clear(assessment_id: str) -> None:
    """Drop any cancel signal for this assessment (called once its run ends)."""
    with _lock:
        _cancelled.discard(assessment_id)
