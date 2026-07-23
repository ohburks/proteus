import sqlite3
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "app.sqlite3"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # A grading run holds a write transaction while it works through a criterion
    # (routers.assessments runs it in a background thread). WAL lets readers keep
    # reading during that write instead of blocking, and busy_timeout makes a
    # concurrent writer wait for the lock rather than failing instantly with
    # "database is locked". Both are per-connection but WAL persists on the file.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
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


def _migrate_users_is_active(conn: sqlite3.Connection) -> None:
    if "is_active" in _table_columns(conn, "users"):
        return
    conn.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")


def _migrate_assessments_cancelled_status(conn: sqlite3.Connection) -> None:
    # Widen the assessments.status CHECK to allow 'cancelled' (added so an
    # in-progress grading run can be halted — see routers.assessments cancel).
    # A CHECK constraint can't be altered in place, so the table is rebuilt.
    # assessments is referenced by several child tables' foreign keys, so follow
    # SQLite's documented table-redefinition procedure: disable FK enforcement,
    # swap the table inside a transaction, verify nothing broke, re-enable.
    # Guarded on the table's own SQL so re-running is a no-op once 'cancelled'
    # is already allowed (and so a fresh DB, created from the updated schema.sql,
    # skips it entirely).
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'assessments'"
    ).fetchone()
    if row is None or "cancelled" in row["sql"]:
        return
    # PRAGMA foreign_keys only takes effect outside a transaction, and the
    # migration runner may hold an open one from a prior migration's bookkeeping
    # insert — commit first so the pragma isn't silently ignored.
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.executescript(
            """
            BEGIN;
            CREATE TABLE assessments_new (
              id TEXT PRIMARY KEY,
              essay_id TEXT NOT NULL REFERENCES essays(id),
              instructor_id TEXT NOT NULL,
              student_id TEXT REFERENCES students(id),
              rubric_id TEXT NOT NULL,
              rubric_version TEXT NOT NULL,
              provider TEXT NOT NULL,
              model TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','running','complete','failed','cancelled')),
              created_at TEXT NOT NULL
            );
            INSERT INTO assessments_new SELECT * FROM assessments;
            DROP TABLE assessments;
            ALTER TABLE assessments_new RENAME TO assessments;
            COMMIT;
            """
        )
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise sqlite3.IntegrityError(
                f"assessments status migration left {len(violations)} foreign-key "
                f"violation(s); aborting"
            )
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


# Ordered, idempotent schema migrations for DBs created under an older
# schema.sql. Each entry runs at most once per id (tracked in
# schema_migrations) and also self-guards so re-running is always safe.
MIGRATIONS: list[tuple[str, Callable[[sqlite3.Connection], None]]] = [
    ("0001_score_records_v2_pass_index", _migrate_score_records_v2_pass_index),
    ("0002_users_is_active", _migrate_users_is_active),
    ("0003_assessments_cancelled_status", _migrate_assessments_cancelled_status),
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


def write_with_retry(
    conn: sqlite3.Connection, write_fn: Callable[[], object], *, retries: int = 5, base_delay: float = 0.25
) -> None:
    """Run write_fn() (which issues writes on `conn`) and commit it, retrying on
    a transient "database is locked". Rolls back before each retry so no partial
    rows persist, then backs off exponentially.

    Grading runs in background threads that share this one SQLite database, and
    SQLite allows a single writer at a time. WAL + busy_timeout already make a
    brief conflict wait rather than fail; this is the belt-and-suspenders on top,
    so heavy contention (or a slow holder) degrades into a short wait instead of
    a failed assessment, and the failure-status update in routers.assessments
    can't itself die on a lock."""
    for attempt in range(retries):
        try:
            write_fn()
            conn.commit()
            return
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < retries - 1:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                time.sleep(base_delay * (2 ** attempt))
                continue
            raise


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
