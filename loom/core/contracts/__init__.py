"""Data contracts v2 — the single source of truth (spec/05). JSON Schema and TS types are generated from here."""

from loom.core.contracts.a2a import AgentCard, ArtifactRef, JsonRpcRequest, JsonRpcResponse, Message, Task
from loom.core.contracts.common import SCHEMA_VERSION, Contract, canonical_json, sha256_of
from loom.core.contracts.cuts import CandidateCut, VerifiedCut
from loom.core.contracts.events import Event
from loom.core.contracts.graph import ConceptGraph, MeshGraphView, PlayerGraphView, SafetyGraphView, graph_view
from loom.core.contracts.issues import CriticIssue
from loom.core.contracts.learner import LearnerProfile
from loom.core.contracts.ops import Health, Job, ModelsReport, Readiness
from loom.core.contracts.session import ClientEventBatch, QuizAnswerRequest, QuizAnswerResult, SessionLog

# Top-level contracts exported as JSON Schema files and TypeScript types (`loom contracts export`).
EXPORTED: dict[str, type[Contract]] = {
    "concept-graph": ConceptGraph,
    "graph-view-mesh": MeshGraphView,
    "graph-view-safety": SafetyGraphView,
    "graph-view-player": PlayerGraphView,
    "learner-profile": LearnerProfile,
    "candidate-cut": CandidateCut,
    "verified-cut": VerifiedCut,
    "session-log": SessionLog,
    "client-event-batch": ClientEventBatch,
    "quiz-answer-request": QuizAnswerRequest,
    "quiz-answer-result": QuizAnswerResult,
    "event": Event,
    "critic-issue": CriticIssue,
    "agent-card": AgentCard,
    "artifact-ref": ArtifactRef,
    "a2a-message": Message,
    "a2a-task": Task,
    "jsonrpc-request": JsonRpcRequest,
    "jsonrpc-response": JsonRpcResponse,
    "health": Health,
    "readiness": Readiness,
    "models-report": ModelsReport,
    "job": Job,
}

__all__ = [
    "EXPORTED",
    "SCHEMA_VERSION",
    "AgentCard",
    "ArtifactRef",
    "CandidateCut",
    "ConceptGraph",
    "Contract",
    "CriticIssue",
    "Event",
    "Health",
    "Job",
    "LearnerProfile",
    "ModelsReport",
    "Readiness",
    "SessionLog",
    "VerifiedCut",
    "canonical_json",
    "graph_view",
    "sha256_of",
]
