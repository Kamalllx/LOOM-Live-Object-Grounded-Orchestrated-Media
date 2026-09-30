"""Real models on samples/lesson.mp4: Grounding DINO + SAM 2.1 (light segmenter), faster-whisper, RapidOCR.

Run with `pytest -m gpu`. Set LOOM_SEGMENTER=sam3 to exercise SAM 3.1 instead (needs a strong GPU).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from loom_perception.config import PipelineConfig
from loom_perception.pipeline import Pipeline
from loom_perception.schema import validate

LESSON = Path(__file__).resolve().parents[1] / "samples" / "lesson.mp4"
pytestmark = [pytest.mark.gpu, pytest.mark.network]


@pytest.fixture(scope="module")
def graph(tmp_path_factory):
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("no CUDA GPU")
    if not LESSON.is_file():
        pytest.skip("run scripts/make_sample_lesson.py first")
    cfg = PipelineConfig()
    cfg.sam.backend = os.environ.get("LOOM_SEGMENTER", "light")
    cfg.sam.prompts = ["beaker", "glass shards"]
    cfg.sam.discover_prompts = False  # fixed prompts; Gemini still verifies object names and labels concepts
    return Pipeline(cfg).run(LESSON, tmp_path_factory.mktemp("gpu"), video_id="vid_lesson")


def test_contract(graph):
    assert validate(graph) == []


def test_transcript_heard_the_narration(graph):
    said = " ".join(s["text"] for s in graph["transcript"]).lower()
    assert "combine the two solutions slowly" in said
    assert "sharps bin" in said


def test_ocr_read_the_equation_while_it_was_on_screen(graph):
    eq = next(s for s in graph["on_screen_text"] if "NaOH" in s["text"])
    assert 8.0 <= eq["start"] <= 10.5 and 15.0 <= eq["end"] <= 17.5


def test_sam_found_and_tracked_the_beaker_and_the_glass(graph):
    labels = {o["label"]: o for o in graph["objects"]}
    beaker = labels["beaker"]
    assert beaker["confidence"] > 0.5
    first = beaker["instances"][0]
    assert first["start"] < 2.0 and first["end"] > 12.0  # on screen for the whole demo
    x, y, w, h = first["bbox"]
    assert 0.1 < x < 0.35 and 0.25 < y < 0.5  # left of centre, where the beaker is
    shards = labels["glass shards"]["instances"][0]
    assert shards["start"] >= 15.0  # only after the cut to the safety shot
    sx, sy, _, _ = shards["bbox"]
    assert 0.4 < sx < 0.55 and sy > 0.6  # lower right of the bench
    assert all(i["end"] <= 16.5 for i in beaker["instances"])  # tracks don't leak across the shot cut


def test_concepts_separate_the_demo_from_the_safety_note(graph):
    nodes = graph["concept_nodes"]
    assert len(nodes) >= 2
    ids = {o["label"]: o["object_id"] for o in graph["objects"]}

    def owner(text: str) -> dict:
        span = next(t for t in graph["on_screen_text"] if text in t["text"])
        return next(n for n in nodes if any(abs(r["start"] - span["start"]) < 1e-6 for r in n["on_screen_text_refs"]))

    demo, safety = owner("NaOH"), owner("SAFETY")
    assert demo is not safety
    assert ids["beaker"] in demo["object_ids"]
    assert ids["glass shards"] in safety["object_ids"] and ids["beaker"] not in safety["object_ids"]
