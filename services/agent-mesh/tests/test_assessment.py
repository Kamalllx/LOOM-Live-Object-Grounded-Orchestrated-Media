import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.agent_protocol import AgentTaskRequest
from app.agents.assessment import app, create_quiz


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPOSITORY_ROOT / "fixtures"


def load_fixture(filename: str) -> dict:
    with (FIXTURES_DIR / filename).open(encoding="utf-8-sig") as fixture_file:
        return json.load(fixture_file)


def make_request() -> AgentTaskRequest:
    return AgentTaskRequest(
        task_id="task_assessment_001",
        concept_graph=load_fixture("concept-graph.sample.json"),
        learner_profile=load_fixture("learner-profile.sample.json"),
    )


def test_assessment_creates_concept_linked_quiz():
    result = create_quiz(make_request())

    assert result == {
        "quiz": [
            {
                "question": "What is the main idea of acid-base neutralization?",
                "concept_node_id": "c_01",
            }
        ]
    }


def test_assessment_http_run_endpoint():
    response = TestClient(app).post(
        "/run",
        json=make_request().model_dump(),
    )

    assert response.status_code == 200
    assert response.json()["agent"] == "assessment"
    assert response.json()["result"]["quiz"][0]["concept_node_id"] == "c_01"
