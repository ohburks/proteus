"""In-memory live-grading progress log — TESTING ONLY.

Backs the dev "live grading terminal" panel so an instructor can watch an
assessment's dual-path grading run as it happens. Single-process, in-memory,
unbounded for the lifetime of the process: it does not survive a restart and
does not work across multiple uvicorn workers, so this is not a durable audit
log or a mechanism to rely on in production — score_records_v2 remains the
source of truth for what actually happened.
"""
import asyncio
import threading
import time
from dataclasses import dataclass, field

from fastapi import Request

_MAX_LINES = 2000


@dataclass
class _Log:
    lines: list[str] = field(default_factory=list)
    done: bool = False
    status: str = "running"
    lock: threading.Lock = field(default_factory=threading.Lock)


_logs: dict[str, _Log] = {}
_registry_lock = threading.Lock()


def start(assessment_id: str) -> None:
    with _registry_lock:
        _logs[assessment_id] = _Log()


def emit(assessment_id: str, message: str) -> None:
    log = _logs.get(assessment_id)
    if log is None:
        return
    ts = time.strftime("%H:%M:%S")
    with log.lock:
        log.lines.append(f"[{ts}] {message}")
        if len(log.lines) > _MAX_LINES:
            log.lines = log.lines[-_MAX_LINES:]


def finish(assessment_id: str, status: str) -> None:
    log = _logs.get(assessment_id)
    if log is None:
        return
    with log.lock:
        log.status = status
        log.done = True


async def stream(assessment_id: str, request: Request | None = None):
    """Yield SSE-formatted chunks of new lines until the run finishes.

    Also breaks if `request` disconnects (browser tab closed/navigated away)
    — without this, an assessment that never finishes (or a client that
    never disconnects) keeps this generator, and the HTTP request behind it,
    alive forever. That in turn can block Uvicorn's graceful shutdown
    indefinitely on `make dev` Ctrl+C, since nothing here previously bounded
    how long the request could stay open.
    """
    log = _logs.get(assessment_id)
    if log is None:
        yield "event: error\ndata: unknown assessment\n\n"
        return
    sent = 0
    while True:
        if request is not None and await request.is_disconnected():
            break
        with log.lock:
            new_lines = log.lines[sent:]
            sent = len(log.lines)
            done = log.done
            status = log.status
        for line in new_lines:
            yield f"data: {line}\n\n"
        if done:
            yield f"event: done\ndata: {status}\n\n"
            break
        await asyncio.sleep(0.3)
