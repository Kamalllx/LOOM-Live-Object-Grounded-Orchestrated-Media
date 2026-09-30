"""Loading the inputs Contract B points at: the concept graph and mask sidecars (Person 1) by video_id, and
the learner profile (Person 4) by learner_id. Files are tried first, then the owning service's HTTP API.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .config import Config
from .contracts import read_json

log = logging.getLogger(__name__)

DEFAULT_PROFILE = {"schema_version": "1.0", "mastery_graph": [], "preferences": {"pace": "standard", "language": "en"},
                   "family_safety_profile": {"redaction_level": "standard"}}


@dataclass
class GraphSource:
    graph: dict
    base_dir: Path | None = None      # folder holding concept-graph.json and its masks/ (Person 1 layout)
    base_url: str | None = None       # Person 1's service, when the graph came over HTTP
    warnings: list[str] = field(default_factory=list)

    @property
    def video_id(self) -> str:
        return self.graph["video_id"]

    def mask_frames(self, obj: dict) -> tuple[list[dict], float | None]:
        """Per-frame boxes (+ COCO RLE masks when available) for one object, and the rate they were sampled at.

        Person 1 writes masks/<object_id>.json ({"sample_fps", "frames": [{"t", "box", "score", "rle"}]}) and
        points to it with objects[].mask_ref. Graphs without sidecars fall back to the instance boxes.
        """
        side = None
        ref = obj.get("mask_ref")
        try:
            if ref and self.base_dir is not None and (self.base_dir / ref).is_file():
                side = read_json(self.base_dir / ref)
            elif self.base_url:
                r = httpx.get(f"{self.base_url}/v1/videos/{self.video_id}/masks/{obj['object_id']}", timeout=30)
                if r.status_code == 200:
                    side = r.json()
        except (OSError, json.JSONDecodeError, httpx.HTTPError) as e:
            self.warnings.append(f"mask sidecar for {obj['object_id']} unreadable ({e}); using instance boxes")
        if side and side.get("frames"):
            return side["frames"], side.get("sample_fps")
        frames = []
        for inst in obj.get("instances", []):
            track = inst.get("track")   # older graphs carried per-second boxes on the instance
            if track:
                frames += [{"t": p["t"], "box": p["bbox"]} for p in track]
            else:
                frames += [{"t": inst["start"], "box": inst["bbox"]}, {"t": inst["end"], "box": inst["bbox"]}]
        return sorted(frames, key=lambda f: f["t"]), None


def load_concept_graph(video_id: str, cfg: Config) -> GraphSource:
    for d in cfg.graph_dirs:
        for path in (d / video_id / "concept-graph.json", d / f"{video_id}.json"):
            if path.is_file():
                return GraphSource(read_json(path), base_dir=path.parent)
        fixture = d / "concept-graph.sample.json"
        if fixture.is_file():
            g = read_json(fixture)
            if g.get("video_id") == video_id:
                return GraphSource(g, base_dir=d)
    if cfg.perception_url:
        base = cfg.perception_url.rstrip("/")
        r = httpx.get(f"{base}/v1/videos/{video_id}/concept-graph", timeout=30)
        r.raise_for_status()
        return GraphSource(r.json(), base_url=base)
    raise FileNotFoundError(f"no concept graph for {video_id} (looked in {', '.join(map(str, cfg.graph_dirs))}"
                            f"{' and ' + cfg.perception_url if cfg.perception_url else ''})")


def load_learner_profile(learner_id: str, cfg: Config) -> tuple[dict, list[str]]:
    """Returns (profile, warnings). A learner we know nothing about gets the standard safety profile."""
    if cfg.learner_url:
        try:
            r = httpx.get(f"{cfg.learner_url.rstrip('/')}/api/learner/{learner_id}",
                          headers={"x-loom-api-key": cfg.loom_api_key}, timeout=15)
            if r.status_code == 200:
                return r.json(), []
            log.warning("learner API returned %s for %s", r.status_code, learner_id)
        except httpx.HTTPError as e:
            log.warning("learner API unreachable (%s)", e)
    for d in cfg.learner_dirs:
        for path in (d / f"{learner_id}.json", d / "learner-profile.sample.json"):
            if path.is_file():
                p = read_json(path)
                if p.get("learner_id") == learner_id:
                    return p, []
    return dict(DEFAULT_PROFILE, learner_id=learner_id), [
        f"no learner profile for {learner_id}; using the standard family safety profile"]
