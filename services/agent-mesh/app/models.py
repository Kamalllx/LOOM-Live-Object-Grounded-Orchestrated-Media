from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TimeReference(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)


class ObjectInstance(TimeReference):
    bbox: list[float] = Field(min_length=4, max_length=4)


class ConceptObject(BaseModel):
    model_config = ConfigDict(extra="allow")

    object_id: str
    label: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    instances: list[ObjectInstance] = Field(default_factory=list)


class TranscriptSegment(TimeReference):
    speaker: str | None = None
    text: str


class OnScreenText(TimeReference):
    text: str


class ConceptNode(BaseModel):
    model_config = ConfigDict(extra="allow")

    node_id: str
    object_ids: list[str] = Field(default_factory=list)
    transcript_refs: list[TimeReference] = Field(default_factory=list)
    on_screen_text_refs: list[TimeReference] = Field(default_factory=list)
    label: str


class ConceptGraph(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str
    video_id: str
    objects: list[ConceptObject]
    transcript: list[TranscriptSegment]
    concept_nodes: list[ConceptNode]
    duration_seconds: float | None = Field(default=None, ge=0)
    on_screen_text: list[OnScreenText] = Field(default_factory=list)


class MasteryEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    concept_id: str
    level: float = Field(ge=0, le=1)
    last_seen: str | None = None


class LearnerProfile(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str
    learner_id: str
    mastery_graph: list[MasteryEntry]
    preferences: dict[str, Any] = Field(default_factory=dict)
    family_safety_profile: dict[str, Any] = Field(default_factory=dict)
