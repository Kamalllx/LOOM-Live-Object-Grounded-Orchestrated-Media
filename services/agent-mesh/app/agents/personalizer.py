from typing import Any

from fastapi import FastAPI

from ..agent_protocol import AgentTaskRequest, AgentTaskResponse, success_response


AGENT_NAME = "personalizer"
AGENT_VERSION = "1.0"

app = FastAPI(
    title="LOOM Personalizer Agent",
    version=AGENT_VERSION,
)


def _agent_result(context: dict[str, Any], agent_name: str) -> dict[str, Any]:
    """Read an earlier agent result from the shared orchestration context."""

    value = context.get(agent_name, {})
    if isinstance(value, dict) and isinstance(value.get("result"), dict):
        return value["result"]
    return value if isinstance(value, dict) else {}


def personalize(request: AgentTaskRequest) -> dict[str, Any]:
    """Combine selected threads with the teaching action for each concept."""

    curator_result = _agent_result(request.context, "curator")
    pedagogy_result = _agent_result(request.context, "pedagogy")

    actions = pedagogy_result.get("actions", {})
    personalized_threads = []

    for original_thread in curator_result.get("threads", []):
        concept_ids = original_thread.get("concept_node_ids", [])
        action = "review"

        if concept_ids:
            action = actions.get(concept_ids[0], "review")

        personalized_threads.append(
            {
                **original_thread,
                "action": action,
            }
        )

    preferences = request.learner_profile.preferences
    pace = preferences.get("pace", "standard")
    language = preferences.get("language", "en")

    return {
        "threads": personalized_threads,
        "pace": pace,
        "language": language,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": AGENT_NAME}


@app.get("/.well-known/agent-card.json")
def agent_card() -> dict:
    return {
        "name": AGENT_NAME,
        "version": AGENT_VERSION,
        "url": "http://127.0.0.1:8103",
        "capabilities": ["personalize_threads"],
    }


@app.post("/run", response_model=AgentTaskResponse)
def run(request: AgentTaskRequest) -> AgentTaskResponse:
    return success_response(
        agent=AGENT_NAME,
        version=AGENT_VERSION,
        result=personalize(request),
    )
