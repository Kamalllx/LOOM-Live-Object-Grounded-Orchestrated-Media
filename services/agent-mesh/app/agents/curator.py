from fastapi import FastAPI

from ..agent_protocol import AgentTaskRequest, AgentTaskResponse, success_response
from ..models import ConceptGraph, ConceptNode


AGENT_NAME = "curator"
AGENT_VERSION = "1.0"

app = FastAPI(
    title="LOOM Curator Agent",
    version=AGENT_VERSION,
)


def _times_for_node(graph: ConceptGraph, node: ConceptNode) -> list[tuple[float, float]]:
    """Collect all known time ranges connected to a concept node."""

    ranges: list[tuple[float, float]] = []
    ranges.extend((item.start, item.end) for item in node.transcript_refs)
    ranges.extend((item.start, item.end) for item in node.on_screen_text_refs)

    objects_by_id = {item.object_id: item for item in graph.objects}
    for object_id in node.object_ids:
        concept_object = objects_by_id.get(object_id)
        if concept_object:
            ranges.extend(
                (instance.start, instance.end)
                for instance in concept_object.instances
            )

    return ranges


def curate(request: AgentTaskRequest) -> dict:
    """Select one candidate thread for each time-grounded concept node."""

    threads = []

    for index, node in enumerate(request.concept_graph.concept_nodes, start=1):
        ranges = _times_for_node(request.concept_graph, node)
        if not ranges:
            # A concept without timestamps cannot be safely placed in a video cut.
            continue

        start = min(item[0] for item in ranges)
        end = max(item[1] for item in ranges)

        threads.append(
            {
                "thread_id": f"t{index}",
                "concept_node_ids": [node.node_id],
                "start": start,
                "end": end,
            }
        )

    return {"threads": threads}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": AGENT_NAME}


@app.get("/.well-known/agent-card.json")
def agent_card() -> dict:
    return {
        "name": AGENT_NAME,
        "version": AGENT_VERSION,
        "url": "http://127.0.0.1:8101",
        "capabilities": ["select_threads"],
    }


@app.post("/run", response_model=AgentTaskResponse)
def run(request: AgentTaskRequest) -> AgentTaskResponse:
    return success_response(
        agent=AGENT_NAME,
        version=AGENT_VERSION,
        result=curate(request),
    )
