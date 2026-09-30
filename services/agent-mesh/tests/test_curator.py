import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.agents.curator import app, curate
from app.agent_protocol import AgentTaskRequest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPOSITORY_ROOT / "fixtures"


def load_fixture(filename: str) -> dict:
    with (FIXTURES_DIR / filename).open(encoding="utf-8-sig") as fixture_file:
        return json.load(fixture_file)


def make_request() -> AgentTaskRequest:
    return AgentTaskRequest(
        task_id="task_curator_001",
        concept_graph=load_fixture("concept-graph.sample.json"),
        learner_profile=load_fixture("learner-profile.sample.json"),
    )


def test_curator_selects_fixture_time_range():
    result = curate(make_request())

    assert result == {
        "threads": [
            {
                "thread_id": "t1",
                "concept_node_ids": ["c_01"],
                "start": 12.0,
                "end": 25.0,
            }
        ]
    }


def test_curator_http_run_endpoint():
    client = TestClient(app)

    response = client.post(
        "/run",
        json={
            "task_id": "task_curator_001",
            "concept_graph": load_fixture("concept-graph.sample.json"),
            "learner_profile": load_fixture("learner-profile.sample.json"),
        },
    )

    assert response.status_code == 200
    assert response.json()["agent"] == "curator"
    assert response.json()["status"] == "ok"
    assert response.json()["result"]["threads"][0]["start"] == 12.0


def test_curator_agent_card():
    response = TestClient(app).get("/.well-known/agent-card.json")

    assert response.status_code == 200
    assert response.json()["name"] == "curator"
    assert response.json()["capabilities"] == ["select_threads"]
