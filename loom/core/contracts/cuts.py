"""Candidate cut (Contract B) and verified cut (Contract C) — spec/05 §3–4.

The verified cut is what clients receive: its quiz items carry no `answer_index` (B9, FR-MEM-03), and the strict
`extra="forbid"` config makes adding one a validation error rather than a leak.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from loom.core.contracts.common import (
    SCHEMA_VERSION,
    BBox,
    ConceptId,
    Contract,
    Degraded,
    EffectSource,
    LearnerId,
    Level,
    ObjectId,
    QuestionId,
    SchemaVersion,
    Seconds,
    SessionId,
    Sha256,
    ThreadId,
    ThreadRole,
    Unit,
    VideoId,
    check_span,
    find_duplicates,
)
from loom.core.contracts.issues import CriticIssue, LoopAction

ThreadAction = Literal["keep", "condense", "expand"]
TraceStatus = Literal["ok", "degraded", "failed"]


class CandidateThread(Contract):
    thread_id: ThreadId
    concept_node_ids: list[ConceptId] = []
    role: ThreadRole
    action: ThreadAction
    start: Seconds
    end: Seconds
    source_end: Seconds
    rationale: str = Field(min_length=1)
    source: EffectSource = "pedagogy"

    @model_validator(mode="after")
    def _times(self) -> Self:
        check_span(self.start, self.end, self.thread_id)
        if self.end > self.source_end + 1e-6:
            raise ValueError(f"{self.thread_id}: end {self.end} exceeds source_end {self.source_end}")
        return self


class SkippedThread(Contract):
    thread_id: ThreadId
    start: Seconds
    end: Seconds
    rationale: str = Field(min_length=1)
    source: EffectSource = "pedagogy"


class ExplainerRequest(Contract):
    concept_node_id: ConceptId
    trigger: Literal["auto", "tap"]
    level: Level
    anchor_time: Seconds


class RedactionRequest(Contract):
    object_id: ObjectId
    reason: str = Field(min_length=1)
    source: EffectSource


class QuizRef(Contract):
    question_id: QuestionId


class AgentTraceEntry(Contract):
    agent: str
    version: str
    skill: str
    latency_ms: int = Field(ge=0)
    status: TraceStatus
    degraded: Degraded = []


class CandidateCut(Contract):
    schema_version: SchemaVersion = SCHEMA_VERSION
    session_id: SessionId
    video_id: VideoId
    graph_sha: Sha256
    learner_id: LearnerId
    learner_state_sha: Sha256
    pass_number: int = Field(ge=1)
    threads: list[CandidateThread]
    skipped: list[SkippedThread] = []
    explainer_requests: list[ExplainerRequest] = []
    redaction_requests: list[RedactionRequest] = []
    quiz: list[QuizRef] = []
    agent_trace: list[AgentTraceEntry] = []
    degraded: Degraded = []

    @model_validator(mode="after")
    def _unique_threads(self) -> Self:
        ids = [t.thread_id for t in self.threads] + [s.thread_id for s in self.skipped]
        if dups := find_duplicates(ids):
            raise ValueError(f"thread ids appear more than once: {dups}")
        return self


class CriticScore(Contract):
    safety: Unit
    coherence: Unit
    factuality: Unit
    completeness: Unit


class FinalThread(Contract):
    thread_id: ThreadId
    start: Seconds
    end: Seconds
    action: ThreadAction
    label: str
    rationale: str
    source: EffectSource = "pedagogy"

    @model_validator(mode="after")
    def _times(self) -> Self:
        check_span(self.start, self.end, self.thread_id)
        return self


class VerifiedSkip(Contract):
    start: Seconds
    end: Seconds
    rationale: str
    source: EffectSource = "pedagogy"


class RedactionMask(Contract):
    mask_id: str = Field(pattern=r"^m_o_\d{3,}_\d+$")
    object_id: ObjectId
    label: str
    start: Seconds
    end: Seconds
    track_url: str
    fallback_bbox: BBox
    style: Literal["blur", "pixelate", "solid"] = "blur"
    reason: str = Field(min_length=1)
    source: EffectSource
    enforced: bool = False

    @model_validator(mode="after")
    def _times(self) -> Self:
        check_span(self.start, self.end, self.mask_id)
        return self


class ExplainerClip(Contract):
    concept_node_id: ConceptId
    trigger: Literal["auto", "tap"]
    anchor_seconds: Seconds
    clip_url: str
    content_hash: Sha256
    title: str
    duration_seconds: float = Field(gt=0)
    storyboard: list[str] = Field(min_length=1)
    verified_by: str


class TapTarget(Contract):
    object_id: ObjectId
    concept_node_id: ConceptId


class PlayerQuizItem(Contract):
    """Quiz item as sent to clients: no answer, no rationale (graded server-side)."""

    question_id: QuestionId
    stem: str
    options: list[str] = Field(min_length=4, max_length=4)


class LoopPass(Contract):
    pass_number: int = Field(ge=1)
    approved: bool
    scores: CriticScore
    issues: list[CriticIssue] = []
    actions: list[LoopAction] = []
    latency_ms: int = Field(ge=0)


class VerifiedCut(Contract):
    schema_version: SchemaVersion = SCHEMA_VERSION
    session_id: SessionId
    video_id: VideoId
    learner_id: LearnerId
    status: Literal["approved", "fallback"]
    fallback_reason: str | None = None
    pass_count: int = Field(ge=0)
    cache_hit: bool = False
    critic_score: CriticScore
    final_threads: list[FinalThread]
    skipped: list[VerifiedSkip] = []
    redaction_masks: list[RedactionMask] = []
    explainer_clips: list[ExplainerClip] = []
    tap_targets: list[TapTarget] = []
    quiz: list[PlayerQuizItem] = []
    loop_trace: list[LoopPass] = []
    degraded: Degraded = []
    created_at: datetime

    @model_validator(mode="after")
    def _status_consistency(self) -> Self:
        if self.status == "fallback" and not self.fallback_reason:
            raise ValueError("a fallback cut must say why (fallback_reason)")
        if self.status == "approved":
            if self.fallback_reason is not None:
                raise ValueError("an approved cut has no fallback_reason")
            final_approved = bool(self.loop_trace) and self.loop_trace[-1].approved
            if not final_approved and not self.cache_hit:
                raise ValueError("an approved cut needs an approving final Critic pass in loop_trace")
        if dups := find_duplicates([m.mask_id for m in self.redaction_masks]):
            raise ValueError(f"duplicate mask ids: {dups}")
        return self
