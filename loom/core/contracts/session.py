"""Session log (Contract D, spec/05 §5) and the quiz-answer API payloads (FR-MEM-03).

`quiz_attempts` and `mastery_updates` are written only by the server. The client's answer payload carries the chosen
option and nothing else: a forged `correct` field is rejected by `extra="forbid"`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from loom.core.contracts.common import (
    SCHEMA_VERSION,
    ConceptKey,
    Contract,
    LearnerId,
    QuestionId,
    SchemaVersion,
    SentenceId,
    SessionId,
    Unit,
    VideoId,
)

SessionEventType = Literal[
    "play",
    "pause",
    "seek",
    "thread_complete",
    "object_tapped",
    "explainer_shown",
    "explainer_skipped",
    "mask_shown",
    "mask_revealed",
    "quiz_answered",
    "session_end",
]

MasteryCause = Literal["quiz_correct", "quiz_wrong", "explainer_watched", "thread_completed"]


class SessionEvent(Contract):
    seq: int = Field(ge=0)
    type: SessionEventType
    client_ts: float = Field(ge=0)
    server_ts: datetime
    payload: dict[str, Any] = {}


class ClientSessionEvent(Contract):
    """What the client may post (server stamps `server_ts`)."""

    seq: int = Field(ge=0)
    type: SessionEventType
    client_ts: float = Field(ge=0)
    payload: dict[str, Any] = {}


class ClientEventBatch(Contract):
    events: list[ClientSessionEvent] = Field(max_length=500)


class QuizAttempt(Contract):
    question_id: QuestionId
    option_index: int = Field(ge=0, le=3)
    correct: bool
    server_ts: datetime


class MasteryUpdate(Contract):
    concept_key: ConceptKey
    before: Unit
    after: Unit
    cause: MasteryCause


class SessionLog(Contract):
    schema_version: SchemaVersion = SCHEMA_VERSION
    session_id: SessionId
    learner_id: LearnerId
    video_id: VideoId
    events: list[SessionEvent] = []
    quiz_attempts: list[QuizAttempt] = []
    mastery_updates: list[MasteryUpdate] = []


class QuizAnswerRequest(Contract):
    option_index: int = Field(ge=0, le=3)


class QuizAnswerResult(Contract):
    correct: bool
    correct_index: int = Field(ge=0, le=3)
    rationale: str
    evidence: list[SentenceId]
