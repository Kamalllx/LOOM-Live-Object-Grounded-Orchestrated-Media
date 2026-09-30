from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from loom_perception.config import PipelineConfig
from loom_perception.fusion import HashingEmbedder
from loom_perception.ocr import Line
from loom_perception.pipeline import Components
from loom_perception.sam import RawDetection, encode_mask
from loom_perception.types import TranscriptSegment

REPO = Path(__file__).resolve().parents[3]


def _mask(box, w=96, h=54):
    m = np.zeros((h, w), dtype=bool)
    x, y, bw, bh = box
    m[int(y * h) : int((y + bh) * h), int(x * w) : int((x + bw) * w)] = True
    return encode_mask(m)


class FakeTranscriber:
    """Reproduces the narration of the repo's sample lesson."""

    def __init__(self, cfg):
        pass

    def transcribe(self, wav):
        return (
            [
                TranscriptSegment(2.0, 6.0, "Today we look at what happens when an acid meets a base."),
                TranscriptSegment(12.0, 15.4, "Combine the two solutions slowly."),
                TranscriptSegment(16.0, 19.5, "The pink colour fades as the base neutralizes the acid."),
                TranscriptSegment(40.0, 44.0, "Always sweep broken glass into the sharps bin."),
                TranscriptSegment(44.5, 48.0, "Never pick up shards with your hands."),
            ],
            "en",
        )


class FakeOcrReader:
    def read(self, image):
        # Frames are generated with a bright band at the top while the equation is "on screen".
        if image[:20].mean() > 200:
            return [Line("NaOH + HCl -> NaCl + H2O", [0.3, 0.02, 0.4, 0.05], 0.97)]
        return []


class FakeSegmenter:
    """The beaker from 14.2–22.5 s; broken glass from 40–46 s."""

    def __init__(self, cfg):
        self.calls = []

    def segment_chunk(self, chunk, frames, prompts):
        self.calls.append((chunk, [f.t for f in frames], list(prompts)))
        for f in frames:
            if "beaker" in prompts and 14.2 <= f.t <= 22.5:
                box = [0.2, 0.34, 0.27, 0.58]
                yield RawDetection(chunk, "beaker", 1, f.t, box, 0.98, _mask(box))
            if "glass" in prompts and 40.0 <= f.t <= 46.0:
                box = [0.47, 0.7, 0.4, 0.22]
                yield RawDetection(chunk, "glass", 1, f.t, box, 0.9, _mask(box))


def fake_components(segmenter_holder: list | None = None) -> Components:
    def make_segmenter(cfg):
        s = FakeSegmenter(cfg)
        if segmenter_holder is not None:
            segmenter_holder.append(s)
        return s

    return Components(
        transcriber=FakeTranscriber,
        ocr_reader=FakeOcrReader,
        segmenter=make_segmenter,
        embedder=lambda cfg: HashingEmbedder(),
        gemini=lambda cfg: None,
    )


@pytest.fixture(scope="session")
def lesson_video(tmp_path_factory) -> Path:
    """60 s synthetic lesson: dark frames, a white band at the top from 20–25 s (the 'equation'), a tone track."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    out = tmp_path_factory.mktemp("media") / "lesson.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=0x202020:s=320x180:r=10:d=60",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=60",
            "-vf", "drawbox=x=0:y=0:w=iw:h=24:color=white:t=fill:enable='between(t,20,25)'",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out),
        ],
        check=True,
    )
    return out


@pytest.fixture
def cfg() -> PipelineConfig:
    c = PipelineConfig()
    c.sam.prompts = ["beaker", "glass"]
    c.sam.discover_prompts = False
    c.llm.enabled = False
    c.media.chunk_seconds = 30.0
    return c
