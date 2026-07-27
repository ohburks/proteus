from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app import chroma_store
from app.auth import CurrentUser, get_current_user
from app.grading.engine import run_calibrated_for_criteria_batch
from app.grading.retrieval import (
    Scope,
    assemble_calibration_pool,
    limit_calibration_examples_for_batch,
)
from app.main import app


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _seed_assignment(
    conn,
    *,
    instructor_id: str = "i1",
    rubric_id: str = "r1",
    version: str = "v1",
):
    now = _now()
    conn.execute(
        """INSERT INTO rubrics
           (rubric_id, version, owner_instructor_id, genre, notes,
            assignment_guidance, raw_json, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            rubric_id,
            version,
            instructor_id,
            "essay",
            "",
            "Reward locally feasible proposals.",
            "{}",
            now,
        ),
    )
    conn.execute(
        """INSERT INTO criteria
           (rubric_id, rubric_version, criterion_id, standard, dimension,
            statement, scale, referenceability, source, anchors_json)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            rubric_id,
            version,
            "C1",
            "",
            "Claims",
            "States a defensible claim.",
            "0-5",
            "strong",
            "",
            '{"0":"none","1":"minimal","2":"weak","3":"adequate","4":"strong","5":"excellent"}',
        ),
    )
    conn.execute(
        "INSERT INTO courses (id, instructor_id, name, created_at) VALUES (?,?,?,?)",
        ("course-1", instructor_id, "Course", now),
    )
    conn.execute(
        """INSERT INTO assignments
           (id, course_id, name, rubric_id, rubric_version, created_at)
           VALUES (?,?,?,?,?,?)""",
        ("assignment-1", "course-1", "Assignment", rubric_id, version, now),
    )
    conn.execute(
        """INSERT INTO assignment_profile
           (assignment_id, course_id, prompt_text, format_expectations,
            criterion_emphasis_notes, common_pitfalls, updated_at)
           VALUES (?,?,?,?,?,?,?)""",
        (
            "assignment-1",
            "course-1",
            "Argue for a local climate policy.",
            "Use evidence.",
            None,
            None,
            now,
        ),
    )
    conn.commit()


def _grading_response() -> dict:
    return {
        "results": [
            {
                "criterionId": "C1",
                "evidence": [
                    {
                        "quote": "The city should electrify its bus fleet.",
                        "reasoning": "This is a direct policy claim.",
                    }
                ],
                "anchorMatched": 4,
                "score": 4,
                "rationale": "This matches the professor's strong examples.",
                "selfConfidence": 0.9,
                "precedent_referenced": ["calibration:example-1:C1"],
            }
        ]
    }


def test_new_grading_uses_one_professor_calibrated_call_and_no_generic_path(
    isolated_db,
    llm_client_factory,
    monkeypatch,
):
    _seed_assignment(isolated_db)
    now = _now()
    isolated_db.execute(
        "INSERT INTO essays (id, assignment_id, student_id, text, created_at) VALUES (?,?,?,?,?)",
        (
            "essay-1",
            "assignment-1",
            None,
            "The city should electrify its bus fleet.",
            now,
        ),
    )
    isolated_db.execute(
        """INSERT INTO assessments
           (id, essay_id, instructor_id, student_id, rubric_id, rubric_version,
            provider, model, status, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            "assessment-1",
            "essay-1",
            "i1",
            None,
            "r1",
            "v1",
            "test",
            "test",
            "running",
            now,
        ),
    )
    isolated_db.commit()
    queried_collections: list[str] = []

    def fake_query(collection_name, query_text, where, n, exclude_ids=None, query_embedding=None):
        queried_collections.append(collection_name)
        if collection_name == chroma_store.CALIBRATION_COLLECTION:
            return [
                {
                    "id": "calibration:example-1:C1",
                    "document": "The county replaced diesel buses with electric buses.",
                    "metadata": {
                        "example_id": "example-1",
                        "example_name": "Professor score 4",
                        "score": 4,
                        "rationale": "Specific, defensible policy claim.",
                    },
                    "distance": 0.1,
                }
            ]
        return []

    monkeypatch.setattr(chroma_store, "query", fake_query)
    monkeypatch.setenv("GRADING_N_PASSES", "1")
    client = llm_client_factory([_grading_response()])

    run_calibrated_for_criteria_batch(
        isolated_db,
        client,
        assessment_id="assessment-1",
        criteria=[
            {
                "criterionId": "C1",
                "statement": "States a defensible claim.",
                "anchors": {"0": "none", "5": "excellent"},
            }
        ],
        rubric_id="r1",
        rubric_version="v1",
        essay_text="The city should electrify its bus fleet.",
        assignment_id="assignment-1",
        instructor_id="i1",
        course_id="course-1",
        query_embedding=[0.1],
    )

    assert len(client.calls) == 1
    prompt = client.calls[0]["system_prompt"]
    assert "Predict the scores this professor would assign" in prompt
    assert "Reward locally feasible proposals." in prompt
    assert "Professor score 4" in prompt
    assert "The county replaced diesel buses" in prompt
    assert queried_collections == [chroma_store.CALIBRATION_COLLECTION]
    paths = isolated_db.execute(
        "SELECT path FROM score_aggregates WHERE assessment_id = ?",
        ("assessment-1",),
    ).fetchall()
    assert [row["path"] for row in paths] == ["personalized"]
    assert (
        isolated_db.execute(
            "SELECT COUNT(*) AS n FROM divergence_records WHERE assessment_id = ?",
            ("assessment-1",),
        ).fetchone()["n"]
        == 0
    )


def test_calibration_retrieval_balances_professor_score_bands(monkeypatch):
    candidates = [
        {
            "id": f"id-{index}",
            "document": f"example {index}",
            "metadata": {"score": score},
            "distance": distance,
        }
        for index, (score, distance) in enumerate(
            [(5, 0.01), (5, 0.02), (5, 0.03), (0, 0.04), (2, 0.05)]
        )
    ]

    def fake_query(collection_name, query_text, where, n, exclude_ids=None, query_embedding=None):
        if collection_name == chroma_store.CALIBRATION_COLLECTION:
            return candidates
        return []

    monkeypatch.setattr(chroma_store, "query", fake_query)
    pool = assemble_calibration_pool(
        "new submission",
        Scope(instructor_id="i1", course_id="c1", assignment_id="a1"),
        "C1",
        "r1",
        "v1",
        k=3,
    )

    assert [item["metadata"]["score"] for item in pool] == [5, 0, 2]


def test_calibration_batch_limits_unique_full_submissions():
    pools = {
        criterion_id: [
            {
                "id": f"{criterion_id}:{index}",
                "document": f"example {index}",
                "metadata": {"example_id": f"{criterion_id}-example-{index}"},
            }
            for index in range(4)
        ]
        for criterion_id in ("C1", "C2", "C3")
    }

    limited = limit_calibration_examples_for_batch(pools, max_examples=4)
    selected = {
        item["metadata"]["example_id"]
        for pool in limited.values()
        for item in pool
    }

    assert len(selected) == 4
    assert all(limited[criterion_id] for criterion_id in pools)


def test_custom_rubric_is_visible_only_to_its_professor(isolated_db):
    client = TestClient(app)
    rubric = {
        "rubricId": "my-rubric",
        "version": "1",
        "genre": "reflection",
        "notes": "My grading language",
        "criteria": [
            {
                "criterionId": "R1",
                "dimension": "Reflection",
                "statement": "Connects experience to learning.",
                "anchors": {str(score): f"Anchor {score}" for score in range(6)},
            }
        ],
    }
    try:
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            "u1",
            "instructor",
            "i1",
            "professor-one",
        )
        response = client.post("/api/rubrics", json=rubric)
        assert response.status_code == 200
        assert client.get("/api/rubrics/my-rubric/1").status_code == 200
        listed = client.get("/api/rubrics").json()
        assert next(item for item in listed if item["rubric_id"] == "my-rubric")[
            "is_custom"
        ] is True

        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            "u2",
            "instructor",
            "i2",
            "professor-two",
        )
        assert client.get("/api/rubrics/my-rubric/1").status_code == 404
    finally:
        app.dependency_overrides.clear()

    row = isolated_db.execute(
        "SELECT owner_instructor_id FROM rubrics WHERE rubric_id = 'my-rubric'"
    ).fetchone()
    assert row["owner_instructor_id"] == "i1"


def test_uploaded_example_requires_and_persists_every_rubric_score(
    isolated_db,
    isolated_chroma,
):
    _seed_assignment(isolated_db)
    client = TestClient(app)
    try:
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            "u1",
            "instructor",
            "i1",
            "professor-one",
        )
        response = client.post(
            "/api/assignments/assignment-1/calibration-examples",
            json={
                "name": "Prior essay A",
                "essay_text": "A complete professor-graded prior submission.",
                "scores": [
                    {
                        "criterion_id": "C1",
                        "score": 3,
                        "rationale": "Adequate but not yet specific.",
                    }
                ],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["n_examples"] == 1
    assert body["examples"][0]["scores"][0]["score"] == 3
    assert (
        isolated_db.execute("SELECT COUNT(*) AS n FROM calibration_examples").fetchone()["n"]
        == 1
    )


def test_approving_a_grade_records_acceptance_and_teaches_future_grading(
    isolated_db,
    isolated_chroma,
):
    _seed_assignment(isolated_db)
    now = _now()
    isolated_db.execute(
        "INSERT INTO essays (id, assignment_id, student_id, text, created_at) VALUES (?,?,?,?,?)",
        (
            "essay-1",
            "assignment-1",
            None,
            "The city should electrify its bus fleet.",
            now,
        ),
    )
    isolated_db.execute(
        """INSERT INTO assessments
           (id, essay_id, instructor_id, student_id, rubric_id, rubric_version,
            provider, model, status, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            "assessment-1",
            "essay-1",
            "i1",
            None,
            "r1",
            "v1",
            "test",
            "test",
            "complete",
            now,
        ),
    )
    isolated_db.execute(
        """INSERT INTO score_aggregates
           (assessment_id, criterion_id, path, score, is_no_evidence,
            anchor_matched, evidence_json, precedent_ids_json, rationale,
            spread, confidence, high_spread, n_passes, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "assessment-1",
            "C1",
            "personalized",
            4,
            0,
            4,
            '[{"quote":"The city should electrify its bus fleet.","reasoning":"claim"}]',
            "[]",
            "A strong policy claim.",
            0,
            1,
            0,
            1,
            now,
        ),
    )
    isolated_db.commit()

    client = TestClient(app)
    try:
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            "u1",
            "instructor",
            "i1",
            "professor-one",
        )
        response = client.post("/api/assessments/assessment-1/criteria/C1/approve")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    feedback = isolated_db.execute(
        """SELECT * FROM grading_feedback
           WHERE assessment_id = 'assessment-1' AND criterion_id = 'C1'"""
    ).fetchone()
    assert feedback["action"] == "approved"
    assert feedback["professor_score"] == 4
    example = isolated_db.execute(
        """SELECT e.source, s.score
           FROM calibration_examples e
           JOIN calibration_example_scores s ON s.example_id = e.id
           WHERE e.source_assessment_id = 'assessment-1' AND s.criterion_id = 'C1'"""
    ).fetchone()
    assert dict(example) == {"source": "review_approved", "score": 4}

    isolated_db.execute(
        """INSERT INTO score_overrides
           (assessment_id, criterion_id, new_score, new_rationale,
            overridden_by, created_at)
           VALUES (?,?,?,?,?,?)""",
        ("assessment-1", "C1", 2, "Professor correction.", "u1", now),
    )
    isolated_db.commit()
    try:
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            "u1",
            "instructor",
            "i1",
            "professor-one",
        )
        blocked_response = client.post(
            "/api/assessments/assessment-1/criteria/C1/approve"
        )
    finally:
        app.dependency_overrides.clear()
    assert blocked_response.status_code == 409
