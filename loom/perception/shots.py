"""Shot detection and keyframes (spec/04 FR-PER-03): PySceneDetect `ContentDetector` → shots `sh_01…`.

Keyframes: just after the first frame and the middle of each shot (the OCR stage adds frames where on-screen text
changes). Tracks never cross a shot boundary.
"""

from __future__ import annotations

import itertools
from pathlib import Path

from loom.perception.models import ShotSpan, ShotsResult

STAGE_VERSION = "shots@1"
THRESHOLD = 27.0  # ContentDetector default
MIN_SHOT_S = 0.5


def keyframes_for(start: float, end: float) -> list[float]:
    first = min(start + 0.1, end)
    mid = (start + end) / 2
    return sorted({round(first, 2), round(mid, 2)})


def shots_from_cuts(cuts: list[float], duration: float) -> list[ShotSpan]:
    """Turn cut times into contiguous shots covering [0, duration]; cuts closer than MIN_SHOT_S are merged."""
    bounds = [0.0]
    for c in sorted(cuts):
        if MIN_SHOT_S <= c <= duration - MIN_SHOT_S and c - bounds[-1] >= MIN_SHOT_S:
            bounds.append(round(c, 3))
    bounds.append(round(duration, 3))
    return [
        ShotSpan(shot_id=f"sh_{i + 1:02d}", start=a, end=b, keyframes=keyframes_for(a, b))
        for i, (a, b) in enumerate(itertools.pairwise(bounds))
    ]


def detect_cuts(path: Path, threshold: float = THRESHOLD) -> list[float]:
    from scenedetect import ContentDetector, SceneManager, open_video

    video = open_video(str(path))
    manager = SceneManager()
    manager.add_detector(ContentDetector(threshold=threshold, min_scene_len=int(max(1, MIN_SHOT_S * video.frame_rate))))
    manager.detect_scenes(video, show_progress=False)
    scenes = manager.get_scene_list()
    return [s[0].get_seconds() for s in scenes[1:]]


def detect_shots(path: Path, duration: float) -> ShotsResult:
    return ShotsResult(
        shots=shots_from_cuts(detect_cuts(path), duration), detector=f"pyscenedetect-content@{THRESHOLD}"
    )
