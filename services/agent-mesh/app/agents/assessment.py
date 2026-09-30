from fastapi import FastAPI

from ..agent_protocol import AgentTaskRequest, AgentTaskResponse, success_response


AGENT_NAME = "assessment"
AGENT_VERSION = "1.0"

app = FastAPI(
    title="LOOM Assessment Agent",
    version=AGENT_VERSION,
)


def create_quiz(request: AgentTaskRequest) -> dict:
    """Create one stable, concept-linked question per concept node."""

    quiz = [
        {
            "question": f"What is the main idea of {node.label}?",
            "concept_node_id": node.node_id,
        }
        for node in request.concept_graph.concept_nodes
    ]

    return {"quiz": quiz}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": AGENT_NAME}


@app.get("/.well-known/agent-card.json")
def agent_card() -> dict:
    return {
        "name": AGENT_NAME,
        "version": AGENT_VERSION,
        "url": "http://127.0.0.1:8104",
        "capabilities": ["create_quiz"],
    }


@app.post("/run", response_model=AgentTaskResponse)
def run(request: AgentTaskRequest) -> AgentTaskResponse:
    return success_response(
        agent=AGENT_NAME,
        version=AGENT_VERSION,
        result=create_quiz(request),
    )
