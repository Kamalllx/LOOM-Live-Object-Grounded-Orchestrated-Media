import json
from pathlib import Path

import httpx

from app.orchestrator import AgentMeshOrchestrator
from app.registry import default_registry


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPOSITORY_ROOT / "fixtures"


def load_fixture(filename: str) -> dict:
    with (FIXTURES_DIR / filename).open(encoding="utf-8-sig") as fixture_file:
        return json.load(fixture_file)


def fake_agent_transport(request: httpx.Request) -> httpx.Response:
    responses = {
        "/run": {
            "agent": "unknown",
            "version": "1.0",
            "status": "ok",
            "result": {},
        }
    }

    if request.url.port == 8101:
        responses["/run"] = {
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
        }
    elif request.url.port == 8102:
        responses["/run"] = {
            "agent": "pedagogy",
            "version": "1.0",
            "status": "ok",
            "result": {"actions": {"c_01": "review"}},
        }
    elif request.url.port == 8103:
        responses["/run"] = {
            "agent": "personalizer",
            "version": "1.0",
            "status": "ok",
            "result": {
                "threads": [
                    {
                        "thread_id": "t1",
                        "concept_node_ids": ["c_01"],
                        "action": "review",
                        "start": 12.0,
                        "end": 25.0,
                    }
                ]
            },
        }
    elif request.url.port == 8104:
        responses["/run"] = {
            "agent": "assessment",
            "version": "1.0",
            "status": "ok",
            "result": {
                "quiz": [
                    {
                        "question": "What is the main idea of acid-base neutralization?",
                        "concept_node_id": "c_01",
                    }
                ]
            },
        }

    return httpx.Response(200, json=responses["/run"], request=request)


def test_orchestrator_builds_candidate_cut():
    client = httpx.Client(transport=httpx.MockTransport(fake_agent_transport))
    service = AgentMeshOrchestrator(
        registry=default_registry(),
        http_client=client,
    )

    result = service.run(
        load_fixture("concept-graph.sample.json"),
        load_fixture("learner-profile.sample.json"),
        session_id="sess_test01",
    )

    assert result["session_id"] == "sess_test01"
    assert result["video_id"] == "vid_00123"
    assert result["learner_id"] == "learner_al91"
    assert result["threads"][0]["action"] == "review"
    assert result["quiz"][0]["concept_node_id"] == "c_01"
    assert len(result["agent_trace"]) == 4
