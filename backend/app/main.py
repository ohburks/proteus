from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.routers import assessments, auth, excerpts, review, roster, rubrics, settings

app = FastAPI(title="Proteus (Dual RAG Grading)")

app.include_router(auth.router)
app.include_router(rubrics.router)
app.include_router(roster.router)
app.include_router(assessments.router)
app.include_router(review.router)
app.include_router(settings.router)
app.include_router(excerpts.router)


@app.on_event("startup")
def startup() -> None:
    # Schema only — no data seeding here. Rubrics/accounts/excerpt corpora
    # are seeded explicitly via `make seed` (app.seed_all), a one-time step
    # before `make dev`, not on every server startup.
    init_db()


SPA_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if SPA_DIST.exists():
    app.mount("/", StaticFiles(directory=str(SPA_DIST), html=True), name="spa")
