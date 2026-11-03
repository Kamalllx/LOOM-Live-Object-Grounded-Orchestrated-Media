"""Segmentation tier T1 `sam2` (spec/02 §10, spec/04 FR-PER-06): SAM 2.1 video propagation per shot.

Each verified T0 track seeds one SAM 2.1 object at its best-scoring sample (box prompt). The shot's frames at
`sample_fps` form the video; prompted frames are run first, then masks are propagated forward from the earliest seed
and backward from the latest. Per sample and object: a pixel mask (COCO RLE, cropped to the picture so it lines up
with picture-normalized boxes) and its bounding box. Presence runs become instances; a single missing sample inside a
run is bridged (one sampling interval of slack, the same slack the mask time padding gives).

The output type mirrors T0 (`Track` with boxes) plus masks, so the rest of the pipeline is tier-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from loom.core.weights import cached_snapshot
from loom.perception.detect import Box
from loom.perception.track import Track

STAGE_VERSION = "segment-sam2@1"
REPO = "facebook/sam2.1-hiera-base-plus"
MIN_AREA = 0.0005  # fraction of the picture; smaller masks count as "not present"
BRIDGE_GAP = 1  # missing samples bridged inside one instance


# ---------------------------------------------------------------- pure helpers (unit-tested)


def encode_rle(mask: np.ndarray) -> str:
    """Bool/uint8 HxW mask → "rle:<h>x<w>:<COCO compressed counts>" (contract `MaskRle`)."""
    from pycocotools import mask as mask_utils

    h, w = mask.shape
    rle = mask_utils.encode(np.asfortranarray(mask.astype(np.uint8)))
    counts = rle["counts"]
    return f"rle:{h}x{w}:{counts.decode('ascii') if isinstance(counts, bytes) else counts}"


def decode_rle(value: str) -> np.ndarray:
    from pycocotools import mask as mask_utils

    _, size, counts = value.split(":", 2)
    h, w = (int(v) for v in size.split("x"))
    return np.asarray(mask_utils.decode({"size": [h, w], "counts": counts.encode("ascii")}), dtype=bool)


def crop_to_picture(mask: np.ndarray, rect: tuple[float, float, float, float]) -> np.ndarray:
    """Frame-sized mask → the part inside the picture (`content_rect`, normalized over the frame)."""
    fh, fw = mask.shape
    rx, ry, rw, rh = rect
    x0, y0 = round(rx * fw), round(ry * fh)
    x1, y1 = max(x0 + 1, round((rx + rw) * fw)), max(y0 + 1, round((ry + rh) * fh))
    return mask[y0:y1, x0:x1]


def mask_bbox(mask: np.ndarray) -> tuple[float, float, float, float] | None:
    """Picture mask → normalized [x, y, w, h], or None if (almost) empty."""
    h, w = mask.shape
    if mask.sum() < MIN_AREA * h * w:
        return None
    ys, xs = np.nonzero(mask)
    x0, x1, y0, y1 = xs.min() / w, (xs.max() + 1) / w, ys.min() / h, (ys.max() + 1) / h
    return (round(float(x0), 4), round(float(y0), 4), round(float(x1 - x0), 4), round(float(y1 - y0), 4))


def picture_box_to_frame_xyxy(
    box: tuple[float, float, float, float], rect: tuple[float, float, float, float], fw: int, fh: int
) -> list[float]:
    x, y, w, h = box
    rx, ry, rw, rh = rect
    return [(rx + x * rw) * fw, (ry + y * rh) * fh, (rx + (x + w) * rw) * fw, (ry + (y + h) * rh) * fh]


def presence_runs(present: list[bool], gap: int = BRIDGE_GAP) -> list[tuple[int, int]]:
    """Index runs [first, last] of True, bridging up to `gap` consecutive False values inside a run."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    last_true = -1
    for i, p in enumerate(present):
        if p:
            if start is None:
                start = i
            elif i - last_true - 1 > gap:
                runs.append((start, last_true))
                start = i
            last_true = i
    if start is not None:
        runs.append((start, last_true))
    return runs


@dataclass
class MaskSample:
    t: float
    box: tuple[float, float, float, float]
    rle: str
    area: float  # fraction of the picture


@dataclass
class MaskTrack:
    """A T1 instance: the T0 track it was seeded from, plus per-sample masks."""

    phrase: str
    shot_id: str
    seed_index: int  # index of the seeding T0 track in the caller's list
    start: float
    end: float
    score: float
    samples: list[MaskSample] = field(default_factory=list)

    def as_track(self) -> Track:
        tr = Track(
            phrase=self.phrase,
            shot_id=self.shot_id,
            samples=[Box(t=s.t, phrase=self.phrase, box=s.box, score=self.score) for s in self.samples],
        )
        tr.start, tr.end = self.start, self.end
        return tr


def instances_from_masks(
    times: list[float],
    masks: list[tuple[tuple[float, float, float, float], str, float] | None],
    seed: Track,
    seed_index: int,
    shot_start: float,
    shot_end: float,
    interval: float,
) -> list[MaskTrack]:
    """Per-sample (box, rle, area) or None → instances (presence runs, padded by half an interval, clamped)."""
    out = []
    for a, b in presence_runs([m is not None for m in masks]):
        samples = [MaskSample(t=times[i], box=m[0], rle=m[1], area=m[2]) for i in range(a, b + 1) if (m := masks[i])]
        start = round(max(shot_start, times[a] - interval / 2), 2)
        end = round(min(shot_end, times[b] + interval / 2), 2)
        out.append(
            MaskTrack(
                phrase=seed.phrase,
                shot_id=seed.shot_id,
                seed_index=seed_index,
                start=start,
                end=max(end, round(start + 0.05, 2)),
                score=seed.score,
                samples=samples,
            )
        )
    return out


# ---------------------------------------------------------------- SAM 2.1 (GPU)


class Sam2Segmenter:
    def __init__(self, repo: str = REPO, device: str = "cuda") -> None:
        import torch
        from transformers import Sam2VideoModel, Sam2VideoProcessor

        snap = cached_snapshot(repo)
        src = str(snap) if snap else repo
        self.device = device if torch.cuda.is_available() else "cpu"
        self.dtype = torch.bfloat16 if self.device == "cuda" else torch.float32
        self.processor = Sam2VideoProcessor.from_pretrained(src)
        model: Any = Sam2VideoModel.from_pretrained(src, dtype=self.dtype)
        self.model = model.to(self.device).eval()

    def segment_shot(
        self,
        frames: list[tuple[float, Any]],
        seeds: list[tuple[int, Track]],
        rect: tuple[float, float, float, float],
        shot_start: float,
        shot_end: float,
        interval: float,
    ) -> list[MaskTrack]:
        """frames: [(t, RGB uint8 HxWx3)] of one shot, sorted; seeds: [(index, T0 track)] inside that shot."""
        import torch

        if not frames or not seeds:
            return []
        times = [t for t, _ in frames]
        fh, fw = frames[0][1].shape[:2]
        session = self.processor.init_video_session(
            video=[f for _, f in frames], inference_device=self.device, video_storage_device="cpu", dtype=self.dtype
        )
        prompted: dict[int, list[tuple[int, list[float]]]] = {}
        for obj_id, (_, tr) in enumerate(seeds, start=1):
            best = max(tr.samples, key=lambda b: b.score)
            fi = min(range(len(times)), key=lambda i: abs(times[i] - best.t))
            prompted.setdefault(fi, []).append((obj_id, picture_box_to_frame_xyxy(best.box, rect, fw, fh)))
        with torch.inference_mode():
            for fi, items in sorted(prompted.items()):
                self.processor.add_inputs_to_inference_session(
                    inference_session=session,
                    frame_idx=fi,
                    obj_ids=[o for o, _ in items],
                    input_boxes=[[box for _, box in items]],
                )
                self.model(inference_session=session, frame_idx=fi)
            # forward from the earliest seed + backward from the latest: an object seeded later has no memory in the
            # forward pass before its seed, so the two passes are merged by union (errs toward covering)
            per_frame: dict[int, Any] = {}
            first, last = min(prompted), max(prompted)
            for reverse, start in ((False, first), (True, last)):
                for out in self.model.propagate_in_video_iterator(session, start_frame_idx=start, reverse=reverse):
                    masks = self.processor.post_process_masks(
                        [out.pred_masks], original_sizes=[[session.video_height, session.video_width]], binarize=True
                    )[0]
                    m = masks.squeeze(1).cpu().numpy().astype(bool)
                    prev = per_frame.get(out.frame_idx)
                    per_frame[out.frame_idx] = m if prev is None else (prev | m)
        obj_order = list(session.obj_ids)
        tracks: list[MaskTrack] = []
        for obj_id, (index, tr) in enumerate(seeds, start=1):
            k = obj_order.index(obj_id)
            series: list[tuple[tuple[float, float, float, float], str, float] | None] = []
            for fi in range(len(times)):
                m = per_frame.get(fi)
                if m is None:
                    series.append(None)
                    continue
                pic = crop_to_picture(np.asarray(m[k], dtype=bool), rect)
                box = mask_bbox(pic)
                series.append(None if box is None else (box, encode_rle(pic), round(float(pic.mean()), 5)))
            tracks += instances_from_masks(times, series, tr, index, shot_start, shot_end, interval)
        return tracks

    def peak_vram_gb(self) -> float:
        import torch

        return round(torch.cuda.max_memory_allocated() / 1e9, 2) if torch.cuda.is_available() else 0.0

    def close(self) -> None:
        import torch

        del self.model
        torch.cuda.empty_cache()
