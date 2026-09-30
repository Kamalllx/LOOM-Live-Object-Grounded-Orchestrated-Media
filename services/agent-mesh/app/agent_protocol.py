from typing import Any, Literal

from pydantic import BaseModel, Field

from .models import ConceptGraph, LearnerProfile


class AgentTaskRequest(BaseModel):
    """Common request sent from the orchestrator to an agent."""

    task_id: str = Field(min_length=1)
    concept_graph: ConceptGraph
    learner_profile: LearnerProfile
    context: dict[str, Any] = Field(default_factory=dict)


class AgentTraceEntry(BaseModel):
    agent: str = Field(min_length=1)
    version: str = Field(min_length=1)


class AgentTaskResponse(BaseModel):
    """Common response returned by every agent."""

    agent: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: Literal["ok", "error"]
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


def success_response(
    agent: str,
    result: dict[str, Any],
    version: str = "1.0",
) -> AgentTaskResponse:
    return AgentTaskResponse(
        agent=agent,
        version=version,
        status="ok",
        result=result,
    )


def error_response(
    agent: str,
    message: str,
    version: str = "1.0",
) -> AgentTaskResponse:
    return AgentTaskResponse(
        agent=agent,
        version=version,
        status="error",
        error=message,
    )
