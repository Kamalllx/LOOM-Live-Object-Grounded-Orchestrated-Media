import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.agent_protocol import AgentTaskRequest
from app.agents.pedagogy import app, choose_actions


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPOSITORY_ROOT / "fixtures"


def load_fixture(filename: str) -> dict:
    with (FIXTURES_DIR / filename).open(encoding="utf-8-sig") as fixture_file:
        return json.load(fixture_file)


def make_request() -> AgentTaskRequest:
    return AgentTaskRequest(
        task_id="task_pedagogy_001",
        concept_graph=load_fixture("concept-graph.sample.json"),
        learner_profile=load_fixture("learner-profile.sample.json"),
    )


def test_pedagogy_uses_normalized_mastery_level():
    result = choose_actions(make_request())

    assert result == {"actions": {"c_01": "review"}}


def test_unknown_concept_defaults_to_expand():
    request = make_request()
    request.concept_graph.concept_nodes[0].node_id = "c_unknown"

    result = choose_actions(request)

    assert result == {"actions": {"c_unknown": "expand"}}


def test_pedagogy_http_run_endpoint():
    response = TestClient(app).post(
        "/run",
        json={
            "task_id": "task_pedagogy_001",
            "concept_graph": load_fixture("concept-graph.sample.json"),
            "learner_profile": load_fixture("learner-profile.sample.json"),
        },
    )

    assert response.status_code == 200
    assert response.json()["agent"] == "pedagogy"
    assert response.json()["result"]["actions"]["c_01"] == "review"
