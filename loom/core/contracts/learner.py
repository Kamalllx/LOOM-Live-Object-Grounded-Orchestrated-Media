"""Learner profile and mastery graph (spec/05 §2, FR-MEM-01, FR-SAF-01)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from loom.core.contracts.common import (
    SCHEMA_VERSION,
    ConceptKey,
    Contract,
    LearnerId,
    SafetyTag,
    SchemaVersion,
    Sha256,
    Unit,
    find_duplicates,
    sha256_of,
)

Pace = Literal["condensed", "standard", "detailed"]
RedactionLevel = Literal["off", "standard", "strict"]

MASTERY_ROUNDING = 0.05  # learner-state hash granularity (FR-VER-08)


class Preferences(Contract):
    pace: Pace = "standard"
    language: str = "en"
    prior_knowledge: Unit = 0.4
    explainers: Literal["auto", "tap_only", "off"] = "auto"
    never_skip: bool = False


class SafetyProfile(Contract):
    redaction_level: RedactionLevel = "off"
    blocked_tags: list[SafetyTag] = []
    allowed_tags: list[SafetyTag] = []
    parent_lock: bool = False

    @model_validator(mode="after")
    def _tags_disjoint(self) -> Self:
        if both := sorted(set(self.blocked_tags) & set(self.allowed_tags)):
            raise ValueError(f"tags cannot be both blocked and allowed: {both}")
        return self


class MasteryEntry(Contract):
    concept_key: ConceptKey
    level: Unit
    last_seen: datetime
    evidence_count: int = Field(ge=0)


class LearnerProfile(Contract):
    schema_version: SchemaVersion = SCHEMA_VERSION
    learner_id: LearnerId
    display_name: str = Field(min_length=1)
    persona: str = ""
    preferences: Preferences = Preferences()
    safety_profile: SafetyProfile = SafetyProfile()
    mastery: list[MasteryEntry] = []
    learner_state_sha: Sha256 | None = None

    @model_validator(mode="after")
    def _unique_mastery(self) -> Self:
        if dups := find_duplicates([m.concept_key for m in self.mastery]):
            raise ValueError(f"duplicate mastery keys: {dups}")
        return self

    def compute_state_sha(self) -> str:
        """Hash of everything that can change a cut: preferences, safety profile, mastery rounded to 0.05."""
        state = {
            "preferences": self.preferences.model_dump(mode="json"),
            "safety_profile": self.safety_profile.model_dump(mode="json"),
            "mastery": sorted(
                (m.concept_key, round(round(m.level / MASTERY_ROUNDING) * MASTERY_ROUNDING, 2)) for m in self.mastery
            ),
        }
        return sha256_of(state)

    def with_state_sha(self) -> LearnerProfile:
        return self.model_copy(update={"learner_state_sha": self.compute_state_sha()})
