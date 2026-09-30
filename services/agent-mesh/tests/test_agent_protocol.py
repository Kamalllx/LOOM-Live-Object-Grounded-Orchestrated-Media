import pytest
from pydantic import ValidationError

from app.agent_protocol import (
    AgentTaskRequest,
    error_response,
    success_response,
)


CONCEPT_GRAPH = {
    "schema_version": "1.0",
    "video_id": "vid_test",
    "objects": [],
    "transcript": [],
    "concept_nodes": [],
}

LEARNER_PROFILE = {
    "schema_version": "1.0",
    "learner_id": "learner_test",
    "mastery_graph": [],
}


def test_agent_request_accepts_shared_inputs():
    request = AgentTaskRequest(
        task_id="task_001",
        concept_graph=CONCEPT_GRAPH,
        learner_profile=LEARNER_PROFILE,
        context={"requested_action": "review"},
    )

    assert request.task_id == "task_001"
    assert request.concept_graph.video_id == "vid_test"
    assert request.learner_profile.learner_id == "learner_test"


def test_agent_request_rejects_invalid_mastery_level():
    invalid_profile = {
        **LEARNER_PROFILE,
        "mastery_graph": [{"concept_id": "c_01", "level": 1.5}],
    }

    with pytest.raises(ValidationError):
        AgentTaskRequest(
            task_id="task_001",
            concept_graph=CONCEPT_GRAPH,
            learner_profile=invalid_profile,
        )


def test_success_response_has_standard_shape():
    response = success_response("curator", {"threads": []})

    assert response.status == "ok"
    assert response.agent == "curator"
    assert response.result == {"threads": []}
    assert response.error is None


def test_error_response_has_standard_shape():
    response = error_response("curator", "Unable to select threads")

    assert response.status == "error"
    assert response.error == "Unable to select threads"
    assert response.result == {}
