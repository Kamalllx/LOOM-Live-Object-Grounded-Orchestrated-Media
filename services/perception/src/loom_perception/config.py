"""Every tunable of the pipeline in one place. CLI flags and the HTTP API both build a PipelineConfig."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field


@dataclass
class MediaConfig:
    sample_fps: float = 2.0  # frames per second fed to SAM (architecture: 1–2 FPS)
    frame_width: int = 960  # frames are downscaled before segmentation to bound GPU/CPU memory
    chunk_seconds: float = 60.0  # SAM sessions are run per chunk so long lectures fit in 8 GB
    chunk_overlap_seconds: float = 1.0  # shared frames used to stitch tracks across chunks


@dataclass
class AsrConfig:
    enabled: bool = True
    model: str = "large-v3-turbo"
    device: str = "auto"  # auto | cuda | cpu
    compute_type: str = "auto"
    language: str | None = None
    vad: bool = True
    max_segment_seconds: float = 12.0  # long segments are re-split on sentence punctuation
    diarize: bool = False  # pyannote speaker diarization (needs HF access to pyannote/speaker-diarization-3.1)
    default_speaker: str = "narrator"


@dataclass
class OcrConfig:
    enabled: bool = True
    sample_fps: float = 1.0
    min_confidence: float = 0.6
    min_chars: int = 2
    min_letters: int = 2  # drops bare numbers such as the graduation marks printed on glassware
    min_frames: int = 2  # a reading seen in a single sampled frame is usually a misread
    change_threshold: float = 4.0  # mean abs pixel diff (0–255) below which a frame reuses the previous OCR result
    merge_similarity: float = 0.85  # fuzzy text match for "same text in the next frame"
    max_gap_seconds: float = 1.5
    min_duration_seconds: float = 0.5


@dataclass
class SamConfig:
    enabled: bool = True
    # "light": Grounding DINO tiny + SAM 2.1 tiny (~210M params, runs on laptops).
    # "sam3": SAM 3.1 Object Multiplex (~850M params; needs a strong GPU).
    backend: str = "light"
    detector_model: str = "IDEA-Research/grounding-dino-tiny"
    mask_model: str = "facebook/sam2.1-hiera-tiny"
    box_threshold: float = 0.35
    text_threshold: float = 0.25
    max_box_area: float = 0.8  # boxes covering more of the frame than this are dropped
    track_iou: float = 0.2  # box affinity (IoU, or centre closeness) that links a detection to the previous frame
    shot_cut_similarity: float = 0.7  # colour-histogram correlation below which consecutive frames are a new shot
    # Re-judge each track's name from its clearest crop: "gemini" (vision LLM), "clip" (local), or "off".
    verify_labels: str = "gemini"
    verify_model: str = "openai/clip-vit-base-patch32"  # used when verify_labels == "clip"
    verify_weight: float = 0.7  # CLIP's share of the naming decision; the detector's vote gets the rest
    cross_prompt_iou: float = 0.7  # boxes of different prompts overlapping this much: keep the most confident
    min_confidence: float = 0.35  # tracks whose mean score is below this are dropped
    checkpoint: str | None = None  # sam3 backend: None → facebook/sam3.1 from Hugging Face
    prompts: list[str] = field(default_factory=list)  # always-on concept prompts
    discover_prompts: bool = True  # propose prompts from transcript/OCR/keyframes
    max_prompts: int = 12
    score_threshold: float = 0.5
    min_track_seconds: float = 1.5
    max_gap_seconds: float = 2.0  # a track absent longer than this (e.g. hidden behind a hand) starts a new instance
    stitch_iou: float = 0.4  # box IoU to link tracks across chunk boundaries
    dedupe_iou: float = 0.7  # mask IoU at which two prompts found the same physical object
    save_masks: bool = True
    offload_to_cpu: bool = True


@dataclass
class FusionConfig:
    embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    merge_similarity: float = 0.45  # consecutive transcript sentences above this join the same concept
    max_node_seconds: float = 90.0
    max_pause_seconds: float = 4.0
    time_padding_seconds: float = 2.0  # objects/text this close to a concept's window can attach to it
    object_relevance: float = 0.35  # label↔text similarity for an object to attach without long on-screen presence
    object_presence: float = 0.5  # fraction of the window an object must be on screen to attach regardless
    object_share: float = 0.5  # fraction of an object's own screen time inside the window that makes it belong there
    max_objects_per_node: int = 6


@dataclass
class LlmConfig:
    enabled: bool = True
    model: str = "gemini-2.5-flash"
    project: str | None = field(default_factory=lambda: os.environ.get("GOOGLE_CLOUD_PROJECT"))
    location: str = field(default_factory=lambda: os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
    keyframes_per_chunk: int = 3


@dataclass
class PipelineConfig:
    media: MediaConfig = field(default_factory=MediaConfig)
    asr: AsrConfig = field(default_factory=AsrConfig)
    ocr: OcrConfig = field(default_factory=OcrConfig)
    sam: SamConfig = field(default_factory=SamConfig)
    fusion: FusionConfig = field(default_factory=FusionConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)

    def to_dict(self) -> dict:
        return asdict(self)
