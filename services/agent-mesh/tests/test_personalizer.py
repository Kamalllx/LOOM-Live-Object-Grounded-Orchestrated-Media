import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.agent_protocol import AgentTaskRequest
from app.agents.personalizer import app, personalize


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPOSITORY_ROOT / "fixtures"


def load_fixture(filename: str) -> dict:
    with (FIXTURES_DIR / filename).open(encoding="utf-8-sig") as fixture_file:
        return json.load(fixture_file)


def make_request() -> AgentTaskRequest:
    return AgentTaskRequest(
        task_id="task_personalizer_001",
        concept_graph=load_fixture("concept-graph.sample.json"),
        learner_profile=load_fixture("learner-profile.sample.json"),
        context={
            "curator": {
                "agent": "curator",
                "version": "1.0",
                "status": "ok",
                "result": {
                    "threads": [
                        {
                            "thread_id": "t1",
                            "concept_node_ids": ["c_01"],
                            "start": 12.0,
                            "end": 25.0,
                        }
                    ]
                },
            },
            "pedagogy": {
                "agent": "pedagogy",
                "version": "1.0",
                "status": "ok",
                "result": {"actions": {"c_01": "review"}},
            },
        },
    )


def test_personalizer_adds_pedagogy_action_to_thread():
    result = personalize(make_request())

    assert result["threads"] == [
        {
            "thread_id": "t1",
            "concept_node_ids": ["c_01"],
            "action": "review",
            "start": 12.0,
            "end": 25.0,
        }
    ]
    assert result["pace"] == "standard"
    assert result["language"] == "en"


def test_personalizer_defaults_missing_action_to_review():
    request = make_request()
    request.context["pedagogy"]["result"]["actions"] = {}

    result = personalize(request)

    assert result["threads"][0]["action"] == "review"


def test_personalizer_http_run_endpoint():
    response = TestClient(app).post(
        "/run",
        json=make_request().model_dump(),
    )

    assert response.status_code == 200
    assert response.json()["agent"] == "personalizer"
    assert response.json()["result"]["threads"][0]["action"] == "review"
