from __future__ import annotations

import copy
from pathlib import Path

import pytest

from loom_verification.animator import Explainer
from loom_verification.config import Config
from loom_verification.contracts import read_json
from loom_verification.loop import Verifier
from loom_verification.sources import GraphSource

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "fixtures"


@pytest.fixture
def cfg(tmp_path) -> Config:
    c = Config(data_dir=tmp_path / "data")
    c.llm_provider = "none"
    c.graph_dirs = [FIXTURES]
    c.learner_dirs = [FIXTURES]
    c.learner_url = None
    c.perception_url = None
    c.mesh_revise_url = None
    return c


def lesson_graph() -> dict:
    """The team's concept-graph fixture, extended to a realistic lesson: two concepts, a hazard (broken glass)
    with a per-frame track, and a transcript with sentence boundaries."""
    g = copy.deepcopy(read_json(FIXTURES / "concept-graph.sample.json"))
    g["duration_seconds"] = 60.0
    g["objects"].append({"object_id": "obj_004", "label": "glass shards", "confidence": 0.9,
                         "instances": [{"start": 40.0, "end": 46.0, "bbox": [0.5, 0.6, 0.2, 0.2]}]})
    g["transcript"] += [
        {"start": 16.0, "end": 24.0, "speaker": "narrator", "text": "The acid and the base neutralize each other and form salt and water."},
        {"start": 40.0, "end": 44.0, "speaker": "narrator", "text": "Always sweep broken glass into the sharps bin."},
        {"start": 44.5, "end": 48.0, "speaker": "narrator", "text": "Never pick up shards with your hands."},
    ]
    g["concept_nodes"].append({"node_id": "c_02", "object_ids": ["obj_004"], "label": "lab safety",
                               "transcript_refs": [{"start": 40.0, "end": 44.0}, {"start": 44.5, "end": 48.0}],
                               "on_screen_text_refs": []})
    return g


@pytest.fixture
def graph_source() -> GraphSource:
    return GraphSource(lesson_graph())


@pytest.fixture
def candidate() -> dict:
    c = copy.deepcopy(read_json(FIXTURES / "candidate-cut.sample.json"))
    c["threads"].append({"thread_id": "t2", "concept_node_ids": ["c_02"], "action": "keep", "start": 40.0, "end": 48.0})
    return c


@pytest.fixture
def family_profile() -> dict:
    return {"schema_version": "1.0", "learner_id": "learner_al91", "mastery_graph": [],
            "family_safety_profile": {"redaction_level": "standard"}}


class FakeAnimator:
    """Renders nothing; returns a storyboard taken from the lesson (faithful) unless told otherwise."""

    def __init__(self, storyboards: dict[str, list[list[str]]] | None = None, fail: set[str] | None = None):
        self.storyboards = storyboards or {}
        self.fail = fail or set()
        self.calls: list[tuple[str, list[str] | None]] = []

    @staticmethod
    def available() -> bool:
        return True

    def render(self, src, cid, level="beginner", feedback=None):
        from loom_verification.animator import AnimatorError
        self.calls.append((cid, feedback))
        if cid in self.fail:
            raise AnimatorError("render failed")
        versions = self.storyboards.get(cid) or [["Combine the two solutions slowly."]]
        story = versions[min(len([c for c in self.calls if c[0] == cid]) - 1, len(versions) - 1)]
        return Explainer(cid, f"{src.video_id}/{cid}.mp4", f"s3://loom-clips/{src.video_id}/{cid}.mp4", story,
                         False, 1, 0.1, 12.5, "fake")


@pytest.fixture
def verifier(cfg) -> Verifier:
    v = Verifier(cfg, None)
    v.animator = FakeAnimator()
    return v
