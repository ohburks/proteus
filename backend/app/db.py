import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "app.sqlite3"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate_score_records_v2_pass_index(conn: sqlite3.Connection) -> None:
    # CREATE TABLE IF NOT EXISTS in schema.sql is a no-op against a DB that
    # already has this table from before pass_index was added, so existing
    # DBs get rebuilt here. Guarded on the column check (not just the
    # migrations log) so it's a no-op if the table is already current.
    if "pass_index" in _table_columns(conn, "score_records_v2"):
        return
    conn.executescript(
        """
        CREATE TABLE score_records_v2_new (
          id TEXT PRIMARY KEY,
          assessment_id TEXT NOT NULL REFERENCES assessments(id),
          criterion_id TEXT NOT NULL,
          path TEXT NOT NULL CHECK (path IN ('exemplar','personalized')),
          pass_index INTEGER NOT NULL DEFAULT 0,
          score INTEGER,
          is_no_evidence INTEGER NOT NULL DEFAULT 0,
          anchor_matched INTEGER,
          evidence_json TEXT NOT NULL,
          precedent_ids_json TEXT NOT NULL,
          confidence REAL,
          rationale TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE (assessment_id, criterion_id, path, pass_index)
        );
        INSERT INTO score_records_v2_new (
          id, assessment_id, criterion_id, path, pass_index, score,
          is_no_evidence, anchor_matched, evidence_json, precedent_ids_json,
          confidence, rationale, created_at
        )
        SELECT
          id, assessment_id, criterion_id, path, 0, score,
          is_no_evidence, anchor_matched, evidence_json, precedent_ids_json,
          confidence, rationale, created_at
        FROM score_records_v2;
        DROP TABLE score_records_v2;
        ALTER TABLE score_records_v2_new RENAME TO score_records_v2;
        """
    )


# Ordered, idempotent schema migrations for DBs created under an older
# schema.sql. Each entry runs at most once per id (tracked in
# schema_migrations) and also self-guards so re-running is always safe.
MIGRATIONS: list[tuple[str, Callable[[sqlite3.Connection], None]]] = [
    ("0001_score_records_v2_pass_index", _migrate_score_records_v2_pass_index),
]


def _run_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  id TEXT PRIMARY KEY,"
        "  applied_at TEXT NOT NULL"
        ")"
    )
    applied = {row["id"] for row in conn.execute("SELECT id FROM schema_migrations")}
    for migration_id, migrate in MIGRATIONS:
        if migration_id in applied:
            continue
        migrate(conn)
        conn.execute(
            "INSERT INTO schema_migrations (id, applied_at) VALUES (?, datetime('now'))",
            (migration_id,),
        )


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA_PATH.read_text())
        _run_migrations(conn)


@contextmanager
def transaction():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
