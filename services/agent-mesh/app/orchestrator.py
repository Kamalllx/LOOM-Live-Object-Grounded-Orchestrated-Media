from typing import Any
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .agent_protocol import AgentTaskRequest, AgentTaskResponse
from .registry import AgentRegistry, default_registry
from .validation import parse_concept_graph, parse_learner_profile, validate_against_contract


class AgentCallError(RuntimeError):
    pass


class CandidateCutRequest(BaseModel):
    concept_graph: dict[str, Any]
    learner_profile: dict[str, Any]
    session_id: str | None = Field(default=None, min_length=1)


class AgentMeshOrchestrator:
    def __init__(
        self,
        registry: AgentRegistry | None = None,
        http_client: httpx.Client | None = None,
    ):
        self.registry = registry or default_registry()
        self.http_client = http_client or httpx.Client(timeout=10.0)

    def _call_agent(self, name: str, request: AgentTaskRequest) -> AgentTaskResponse:
        card = self.registry.get(name)

        try:
            response = self.http_client.post(
                f"{card.url}/run",
                json=request.model_dump(mode="json"),
            )
            response.raise_for_status()
            result = AgentTaskResponse.model_validate(response.json())
        except (httpx.HTTPError, ValueError) as error:
            raise AgentCallError(f"Unable to call {name}: {error}") from error

        if result.status == "error":
            raise AgentCallError(f"{name} returned an error: {result.error}")

        return result

    def run(
        self,
        concept_graph_document: dict[str, Any],
        learner_profile_document: dict[str, Any],
        session_id: str | None = None,
    ) -> dict[str, Any]:
        concept_graph = parse_concept_graph(concept_graph_document)
        learner_profile = parse_learner_profile(learner_profile_document)
        session_id = session_id or f"sess_{uuid4().hex[:8]}"

        curator_request = AgentTaskRequest(
            task_id=f"{session_id}_curator",
            concept_graph=concept_graph,
            learner_profile=learner_profile,
        )
        curator_response = self._call_agent("curator", curator_request)

        pedagogy_request = AgentTaskRequest(
            task_id=f"{session_id}_pedagogy",
            concept_graph=concept_graph,
            learner_profile=learner_profile,
        )
        pedagogy_response = self._call_agent("pedagogy", pedagogy_request)

        personalizer_request = AgentTaskRequest(
            task_id=f"{session_id}_personalizer",
            concept_graph=concept_graph,
            learner_profile=learner_profile,
            context={
                "curator": curator_response.model_dump(mode="json"),
                "pedagogy": pedagogy_response.model_dump(mode="json"),
            },
        )
        personalizer_response = self._call_agent("personalizer", personalizer_request)

        assessment_request = AgentTaskRequest(
            task_id=f"{session_id}_assessment",
            concept_graph=concept_graph,
            learner_profile=learner_profile,
        )
        assessment_response = self._call_agent("assessment", assessment_request)

        personalizer_result = personalizer_response.result
        candidate_cut = {
            "schema_version": "1.0",
            "session_id": session_id,
            "video_id": concept_graph.video_id,
            "learner_id": learner_profile.learner_id,
            "pass_number": 1,
            "threads": personalizer_result.get("threads", []),
            "redaction_requests": [],
            "explainer_requests": [],
            "quiz": assessment_response.result.get("quiz", []),
            "agent_trace": [
                {"agent": response.agent, "version": response.version}
                for response in (
                    curator_response,
                    pedagogy_response,
                    personalizer_response,
                    assessment_response,
                )
            ],
        }

        validate_against_contract(candidate_cut, "candidate-cut.schema.json")
        return candidate_cut


app = FastAPI(
    title="LOOM Agent Mesh Orchestrator",
    version="1.0.0",
)
orchestrator = AgentMeshOrchestrator()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "orchestrator"}


@app.post("/candidate-cut")
def candidate_cut(request: CandidateCutRequest) -> dict[str, Any]:
    try:
        return orchestrator.run(
            request.concept_graph,
            request.learner_profile,
            request.session_id,
        )
    except AgentCallError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except (ValueError, KeyError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
