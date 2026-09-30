from fastapi import FastAPI

from ..agent_protocol import AgentTaskRequest, AgentTaskResponse, success_response


AGENT_NAME = "pedagogy"
AGENT_VERSION = "1.0"

app = FastAPI(
    title="LOOM Pedagogy Agent",
    version=AGENT_VERSION,
)


def _action_for_mastery(level: float) -> str:
    """Map normalized mastery to a simple teaching action."""

    if level < 0.40:
        return "expand"
    if level < 0.75:
        return "review"
    return "concise"


def choose_actions(request: AgentTaskRequest) -> dict:
    mastery_by_concept = {
        item.concept_id: item.level
        for item in request.learner_profile.mastery_graph
    }

    actions = {}
    for node in request.concept_graph.concept_nodes:
        level = mastery_by_concept.get(node.node_id, 0.0)
        actions[node.node_id] = _action_for_mastery(level)

    return {"actions": actions}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": AGENT_NAME}


@app.get("/.well-known/agent-card.json")
def agent_card() -> dict:
    return {
        "name": AGENT_NAME,
        "version": AGENT_VERSION,
        "url": "http://127.0.0.1:8102",
        "capabilities": ["choose_learning_action"],
    }


@app.post("/run", response_model=AgentTaskResponse)
def run(request: AgentTaskRequest) -> AgentTaskResponse:
    return success_response(
        agent=AGENT_NAME,
        version=AGENT_VERSION,
        result=choose_actions(request),
    )
