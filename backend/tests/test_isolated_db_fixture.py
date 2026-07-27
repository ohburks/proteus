import app.db as db


def test_isolated_db_points_at_a_throwaway_file(isolated_db, tmp_path):
    assert db.DB_PATH == tmp_path / "test.sqlite3"
    assert db.DB_PATH.exists()


def test_isolated_db_has_schema_applied(isolated_db):
    tables = {
        row["name"]
        for row in isolated_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"assessments", "score_records_v2", "divergence_records", "personalized_excerpts_src"} <= tables


def test_isolated_db_starts_empty(isolated_db):
    row = isolated_db.execute("SELECT COUNT(*) AS n FROM personalized_excerpts_src").fetchone()
    assert row["n"] == 0


def test_isolated_db_is_fresh_per_test(isolated_db):
    # If a previous test's data leaked in, this would be nonzero.
    row = isolated_db.execute("SELECT COUNT(*) AS n FROM users").fetchone()
    assert row["n"] == 0
    isolated_db.execute(
        """INSERT INTO users (id, username, password_hash, role, is_active, created_at)
           VALUES ('u1','someone','hash','admin',1,'2026-01-01T00:00:00+00:00')""",
    )
    isolated_db.commit()


def test_isolated_db_does_not_leak_across_tests(isolated_db):
    row = isolated_db.execute("SELECT COUNT(*) AS n FROM users").fetchone()
    assert row["n"] == 0


def test_production_code_reads_the_same_isolated_db(isolated_db):
    # Production code calls db.get_connection() itself rather than reusing
    # the fixture's connection object — confirm both point at the same file.
    isolated_db.execute(
        """INSERT INTO users (id, username, password_hash, role, is_active, created_at)
           VALUES ('u2','someone-else','hash','admin',1,'2026-01-01T00:00:00+00:00')""",
    )
    isolated_db.commit()

    with db.get_connection() as fresh_conn:
        row = fresh_conn.execute("SELECT username FROM users WHERE id = 'u2'").fetchone()
    assert row["username"] == "someone-else"
