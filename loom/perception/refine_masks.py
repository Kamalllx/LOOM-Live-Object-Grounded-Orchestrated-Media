"""Exact-shape masks (tier T1 `sam2`, FR-PER-06): re-segment every object instance of a graph with SAM 2.1.

Per shot, every instance is seeded at its best-scoring sample (box prompt) and propagated through the shot at
`MASK_FPS`. Each instance's track is replaced by per-sample pixel masks (COCO RLE, picture-relative, downscaled to
`MASK_WIDTH` px) inside the instance's span; samples where SAM loses the object keep the original box (fail closed:
the player falls back to the box, never to nothing). The graph is re-sealed with tier `sam2`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import numpy as np

from loom.core.contracts.graph import ConceptGraph, TrackSample

MASK_FPS = 5.0
WINDOW_S = 20.0  # long shots are segmented in windows: SAM 2 memory grows with frames (8 GB VRAM)
MASK_WIDTH = 480
DILATE_PX = 3


def _frames(video: Any, times: list[float], width: int) -> list[tuple[float, Any]]:
    import cv2

    from loom.perception.ocr import FrameReader

    reader = FrameReader(video)
    out = []
    try:
        for t in times:
            f = reader.at(t)
            if f is None:
                continue
            h, w = f.shape[:2]
            if w > width:
                f = cv2.resize(f, (width, round(h * width / w)), interpolation=cv2.INTER_AREA)
            out.append((t, cv2.cvtColor(f, cv2.COLOR_BGR2RGB)))
    finally:
        reader.close()
    return out


def _small(rle: str) -> str:
    """Downscale + slightly dilate a picture mask so the JSON stays light and edges never peek out."""
    import cv2

    from loom.perception.segment import decode_rle, encode_rle

    m = decode_rle(rle).astype(np.uint8)
    h, w = m.shape
    if w > MASK_WIDTH:
        m = cv2.resize(m, (MASK_WIDTH, max(1, round(h * MASK_WIDTH / w))), interpolation=cv2.INTER_NEAREST)
    m = cv2.dilate(m, np.ones((2 * DILATE_PX + 1, 2 * DILATE_PX + 1), np.uint8))
    return encode_rle(m.astype(bool))


def refine(cfg: Any, graph: ConceptGraph, progress: Callable[[str], None] = print) -> ConceptGraph:
    from loom.perception.detect import Box
    from loom.perception.segment import Sam2Segmenter
    from loom.perception.track import Track

    video = cfg.data_dir / "media" / "videos" / f"{graph.video_id}.mp4"
    rect = tuple(graph.frame.content_rect)
    interval = 1.0 / MASK_FPS
    t0 = time.perf_counter()
    seg = Sam2Segmenter()
    objects = [o.model_copy(deep=True) for o in graph.objects]
    masked = total = 0
    try:
        windows = []
        for shot in graph.shots:
            a = shot.start
            while a < shot.end - 1e-6:
                windows.append((shot, a, min(shot.end, a + WINDOW_S)))
                a += WINDOW_S
        collected: dict[tuple[int, int], list[Any]] = {}
        for shot, w0, w1 in windows:
            seeds: list[tuple[int, Track]] = []
            owners: list[tuple[int, int]] = []
            for oi, o in enumerate(objects):
                if o.phrase_source == "board":
                    continue
                for ii, inst in enumerate(o.instances):
                    if inst.shot_id != shot.shot_id or not inst.track or inst.end <= w0 or inst.start >= w1:
                        continue
                    inside = [s for s in inst.track if w0 <= s.t < w1] or [min(inst.track, key=lambda s: abs(s.t - (w0 + w1) / 2))]
                    mid = inside[len(inside) // 2]
                    tr = Track(phrase=o.label, shot_id=shot.shot_id,
                               samples=[Box(t=min(max(mid.t, w0), w1 - 0.01), phrase=o.label, box=tuple(mid.bbox), score=inst.score)])  # type: ignore[arg-type]
                    tr.start, tr.end = max(inst.start, w0), min(inst.end, w1)
                    owners.append((oi, ii))
                    seeds.append((len(seeds), tr))
            if not seeds:
                continue
            times = [round(w0 + interval / 2 + k * interval, 3) for k in range(int((w1 - w0) / interval) + 1)
                     if w0 + interval / 2 + k * interval < w1]
            frames = _frames(video, times, cfg.perception.frame_width)
            out = seg.segment_shot(frames, seeds, rect, w0, w1, interval)  # type: ignore[arg-type]
            for k, (oi, ii) in enumerate(owners):
                inst = objects[oi].instances[ii]
                collected.setdefault((oi, ii), []).extend(
                    s for mt in out if mt.seed_index == k for s in mt.samples if inst.start - 1e-6 <= s.t <= inst.end + 1e-6)
            progress(f"{shot.shot_id} {w0:.0f}-{w1:.0f}s: {len(seeds)} instances")
        for oi, o in enumerate(objects):
            if o.phrase_source == "board":
                continue
            for ii, inst in enumerate(o.instances):
                total += 1
                samples = sorted({round(s.t, 3): s for s in collected.get((oi, ii), [])}.values(), key=lambda s: s.t)
                if not samples:
                    continue
                masked += 1
                objects[oi].instances[ii] = inst.model_copy(update={"track": [
                    TrackSample(t=s.t, bbox=s.box, mask=_small(s.rle)) for s in samples]})
        peak = seg.peak_vram_gb()
    finally:
        seg.close()
    meta = graph.perception_meta.model_copy(update={
        "segmentation_tier": "sam2",
        "timings_s": {**graph.perception_meta.timings_s, "segment_sam2": round(time.perf_counter() - t0, 1)},
        "models": {**graph.perception_meta.models, "segmenter": "facebook/sam2.1-hiera-base-plus",
                   "sam2_peak_vram_gb": str(peak), "sam2_masked_instances": f"{masked}/{total}"},
    })
    return graph.model_copy(update={"objects": objects, "perception_meta": meta, "graph_sha": None}).sealed()
