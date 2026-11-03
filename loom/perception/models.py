"""Intermediate stage outputs of the perception pipeline (internal; the public contract is the concept graph).

Each is a strict Pydantic model so a stage output read back from the blob cache is validated like any other hop.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from loom.core.contracts.common import BBox, Contract, Seconds


class ProbeResult(Contract):
    """The normalized video LOOM works on (spec/04 FR-ING-01)."""

    video_sha256: str
    path: str  # normalized MP4 (blob path)
    duration_s: float = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)
    has_audio: bool
    content_rect: BBox = (0.0, 0.0, 1.0, 1.0)
    source_duration_s: float = Field(gt=0)
    trimmed: bool = False
    encoder: str


class ShotSpan(Contract):
    shot_id: str
    start: Seconds
    end: Seconds
    keyframes: list[Seconds]


class ShotsResult(Contract):
    shots: list[ShotSpan]
    detector: str


class WordTiming(Contract):
    w: str
    start: Seconds
    end: Seconds
    p: float = Field(ge=0, le=1)


class SentenceTiming(Contract):
    seg_id: str
    start: Seconds
    end: Seconds
    text: str
    words: list[WordTiming]


class AsrResult(Contract):
    language: str | None
    language_probability: float | None = None
    sentences: list[SentenceTiming]
    model: str
    device: str
    compute_type: str
    degraded: list[str] = []


class StageInfo(Contract):
    name: str
    version: str
    status: Literal["done", "cached", "skipped", "failed"]
    seconds: float
    key: str
