"""SSE event envelope and per-kind payloads (spec/05 §6). Payloads are validated against their kind on publish."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from loom.core.contracts.common import ConceptId, Contract, Degraded, LearnerId, VideoId
from loom.core.contracts.issues import CriticIssue, LoopAction

EventKind = Literal[
    "ingest_stage",
    "session_start",
    "agent_call",
    "agent_done",
    "candidate_ready",
    "loop_phase",
    "render_progress",
    "gpu_lease",
    "delivered",
    "degraded",
    "error",
    "agent_note",
]

Channel = Annotated[str, StringConstraints(pattern=r"^(sess|ingest|tap|job|system)_[A-Za-z0-9_]+$|^system$")]


class IngestStageData(Contract):
    stage: str
    status: Literal["started", "progress", "done", "failed", "skipped"]
    progress: float = Field(0.0, ge=0, le=1)
    eta_s: float | None = None
    detail: str = ""
    degraded: Degraded = []


class SessionStartData(Contract):
    video_id: VideoId
    learner_id: LearnerId
    cache_hit: bool


class AgentCallData(Contract):
    agent: str
    skill: str
    latency_ms: int | None = None
    status: Literal["started", "ok", "degraded", "failed"]
    degraded: Degraded = []


class CandidateReadyData(Contract):
    pass_number: int = Field(ge=1)
    threads: int = Field(ge=0)
    explainer_requests: int = Field(ge=0)
    redaction_requests: int = Field(ge=0)


class LoopPhaseData(Contract):
    phase: Literal["perceive", "plan", "verify", "act"]
    pass_number: int = Field(ge=1)
    scores: dict[str, float] | None = None
    issues: list[CriticIssue] | None = None
    actions: list[LoopAction] | None = None


class RenderProgressData(Contract):
    concept_node_id: ConceptId
    step: Literal["draft", "gate", "render", "layout", "narrate", "verify"]
    attempt: int = Field(ge=1)


class GpuLeaseData(Contract):
    holder: str | None
    waiting: int = Field(ge=0)
    priority: str | None
    state: Literal["granted", "released", "waiting"]


class DeliveredData(Contract):
    status: Literal["approved", "fallback"]
    pass_count: int = Field(ge=0)


class DegradedData(Contract):
    component: str
    reason: str


class AgentNoteData(Contract):
    """What an agent is doing right now, for the live views: a thought, an output, or progress."""

    agent: str
    text: str = Field(max_length=400)
    kind: Literal["thinking", "output", "progress"] = "thinking"
    progress: float | None = Field(None, ge=0, le=1)
    items: list[Annotated[str, StringConstraints(max_length=240)]] = Field(default=[], max_length=12)


class ErrorData(Contract):
    message: str
    where: str


EVENT_DATA_MODELS: dict[str, type[Contract]] = {
    "ingest_stage": IngestStageData,
    "session_start": SessionStartData,
    "agent_call": AgentCallData,
    "agent_done": AgentCallData,
    "candidate_ready": CandidateReadyData,
    "loop_phase": LoopPhaseData,
    "render_progress": RenderProgressData,
    "gpu_lease": GpuLeaseData,
    "delivered": DeliveredData,
    "degraded": DegradedData,
    "error": ErrorData,
    "agent_note": AgentNoteData,
}


class Event(Contract):
    id: int = Field(ge=1)
    channel: Channel
    ts: datetime
    kind: EventKind
    data: dict[str, Any]

    @model_validator(mode="after")
    def _data_matches_kind(self) -> Self:
        EVENT_DATA_MODELS[self.kind].model_validate(self.data)
        return self
