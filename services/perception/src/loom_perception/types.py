"""Plain data types shared by every stage. Each maps 1:1 onto a part of concept-graph.json."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


def r(x: float, nd: int = 2) -> float:
    return round(float(x), nd)


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    speaker: str = "narrator"
    confidence: float | None = None

    def to_contract(self) -> dict:
        return {"start": r(self.start), "end": r(self.end), "speaker": self.speaker, "text": self.text}


@dataclass
class TextSpan:
    """One piece of on-screen text, visible continuously from start to end."""

    start: float
    end: float
    text: str
    bbox: list[float] | None = None  # [x, y, w, h], normalized 0–1, top-left origin
    confidence: float | None = None

    def to_contract(self) -> dict:
        return {"start": r(self.start), "end": r(self.end), "text": self.text}


@dataclass
class FrameDetection:
    """One object in one sampled frame, as reported by the segmenter."""

    t: float
    box: list[float]  # [x, y, w, h], normalized
    score: float
    rle: dict | None = None  # COCO RLE of the mask at frame resolution


@dataclass
class ObjectInstance:
    start: float
    end: float
    bbox: list[float]

    def to_contract(self) -> dict:
        return {"start": r(self.start), "end": r(self.end), "bbox": [r(v, 3) for v in self.bbox]}


@dataclass
class ObjectTrack:
    object_id: str
    label: str
    confidence: float
    instances: list[ObjectInstance]
    detections: list[FrameDetection] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    mask_ref: str | None = None

    @property
    def start(self) -> float:
        return min(i.start for i in self.instances)

    @property
    def end(self) -> float:
        return max(i.end for i in self.instances)

    def to_contract(self) -> dict:
        d = {
            "object_id": self.object_id,
            "label": self.label,
            "confidence": r(self.confidence),
            "instances": [i.to_contract() for i in self.instances],
        }
        if self.mask_ref:
            d["mask_ref"] = self.mask_ref
        return d


@dataclass
class ConceptNode:
    node_id: str
    label: str
    start: float
    end: float
    object_ids: list[str]
    transcript_refs: list[tuple[float, float]]
    on_screen_text_refs: list[tuple[float, float]]

    def to_contract(self) -> dict:
        return {
            "node_id": self.node_id,
            "object_ids": self.object_ids,
            "transcript_refs": [{"start": r(s), "end": r(e)} for s, e in self.transcript_refs],
            "on_screen_text_refs": [{"start": r(s), "end": r(e)} for s, e in self.on_screen_text_refs],
            "label": self.label,
            "start": r(self.start),
            "end": r(self.end),
        }


def dump(obj) -> dict:
    return asdict(obj)
