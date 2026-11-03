"""Shared contract primitives (spec/05 conventions).

Times are seconds from the start of the normalized video; boxes are normalized `[x, y, w, h]` relative to the
picture; ids are stable, prefixed strings. Every contract forbids unknown fields: an invalid payload is an error,
not a best-effort parse (NFR-REL-05).
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

SCHEMA_VERSION = "2.0"
SchemaVersion = Annotated[str, StringConstraints(pattern=r"^2\.\d+$")]

TIME_EPS = 0.05  # tolerance for float times at the end of a video


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, validate_assignment=False)


def _id(pattern: str) -> Any:
    return Annotated[str, StringConstraints(pattern=pattern)]


SentenceId = _id(r"^s_\d{3,}$")
TextId = _id(r"^x_\d{3,}$")
ObjectId = _id(r"^o_\d{3,}$")
InstanceId = _id(r"^o_\d{3,}_\d+$")
ConceptId = _id(r"^c_\d{2,}$")
ThreadId = _id(r"^t\d+$")
QuestionId = _id(r"^q_[a-z0-9_]+$")
ShotId = _id(r"^sh_\d{2,}$")
SessionId = _id(r"^sess_[a-z0-9]+$")
VideoId = _id(r"^[a-z0-9][a-z0-9_]*$")
LearnerId = _id(r"^[a-z0-9][a-z0-9_]*$")
Sha256 = _id(r"^sha256:[0-9a-f]{64}$")
# "video_id/concept_id" for per-video mastery, or "concept:<canonical>" for a cross-video key (FR-MEM-01).
ConceptKey = _id(r"^([a-z0-9][a-z0-9_]*/c_\d{2,}|concept:[a-z0-9_]+)$")
# "pedagogy", "personalizer", "guardian", "critic", or "plugin:<name>"
EffectSource = _id(r"^(pedagogy|personalizer|curator|assessment|guardian|critic|plugin:[a-z0-9][a-z0-9_-]*)$")

Seconds = Annotated[float, Field(ge=0.0)]
Unit = Annotated[float, Field(ge=0.0, le=1.0)]
Degraded = list[Annotated[str, StringConstraints(min_length=1, max_length=200)]]

Level = Literal["beginner", "intermediate", "expert"]
ThreadRole = Literal["intro", "setup", "core", "safety", "summary"]
SafetyTag = Literal[
    "sharp_object",
    "injury_risk",
    "fire_or_explosion",
    "weapon",
    "blood_or_gore",
    "nudity",
    "drugs_or_alcohol",
    "hazardous_chemical",
    "disturbing",
]


def _check_bbox(v: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    x, y, w, h = v
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and 0.0 < w <= 1.0 and 0.0 < h <= 1.0):
        raise ValueError(f"bbox {v} must be normalized [x, y, w, h] with w, h > 0")
    if x + w > 1.0 + 1e-3 or y + h > 1.0 + 1e-3:
        raise ValueError(f"bbox {v} extends outside the picture")
    return v


BBox = Annotated[tuple[float, float, float, float], AfterValidator(_check_bbox)]


def check_span(start: float, end: float, where: str, duration: float | None = None) -> None:
    if not start < end:
        raise ValueError(f"{where}: start {start} must be < end {end}")
    if duration is not None and end > duration + TIME_EPS:
        raise ValueError(f"{where}: end {end} exceeds duration {duration}")


def canonical_json(obj: Any) -> bytes:
    """Deterministic JSON bytes used for every content hash."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def sha256_of(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(obj)).hexdigest()


def find_duplicates(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    dup: set[str] = set()
    for i in ids:
        (dup if i in seen else seen).add(i)
    return sorted(dup)
