import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.auth import assert_secure_jwt_secret
from app.db import init_db, reconcile_interrupted_assessments
from app.routers import accounts, assessments, auth, excerpts, review, roster, rubrics, settings

app = FastAPI(title="Proteus (Dual RAG Grading)")

app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(rubrics.router)
app.include_router(roster.router)
app.include_router(assessments.router)
app.include_router(review.router)
app.include_router(settings.router)
app.include_router(excerpts.router)


@app.on_event("startup")
def startup() -> None:
    # Refuse to boot in production on the built-in dev JWT secret (D9); warn in
    # dev. Runs first so a misconfigured production deploy fails before it opens
    # a port.
    assert_secure_jwt_secret()
    # Schema only — no data seeding here. Rubrics/accounts/excerpt corpora
    # are seeded explicitly via `make seed` (app.seed_all), a one-time step
    # before `make dev`, not on every server startup.
    init_db()
    # Fail any assessment orphaned in running/pending by a process that died
    # mid-grade (D7) — otherwise it shows as perpetually grading and blocks the
    # delete endpoints' active-assessment guard.
    reconciled = reconcile_interrupted_assessments()
    if reconciled:
        logging.getLogger("proteus").warning(
            "Reconciled %d assessment(s) stuck in running/pending at startup -> failed",
            reconciled,
        )


SPA_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if SPA_DIST.exists():
    app.mount("/", StaticFiles(directory=str(SPA_DIST), html=True), name="spa")
