"""Raw per-chunk detections → stable, de-duplicated object tracks with instances.

Three steps, all pure functions so they can be tested without a GPU:
1. group detections into tracklets (one per chunk × prompt × SAM object id),
2. stitch tracklets of the same prompt across chunk boundaries (box IoU in the overlap),
3. merge tracklets that different prompts found for the same physical object (mask IoU),
then split each object's timeline into visible instances.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import median

from .config import SamConfig
from .sam import RawDetection
from .types import FrameDetection, ObjectInstance, ObjectTrack


def box_iou(a: list[float], b: list[float]) -> float:
    ax1, ay1, bx1, by1 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw, ih = max(0.0, min(ax1, bx1) - max(a[0], b[0])), max(0.0, min(ay1, by1) - max(a[1], b[1]))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def mask_iou(a: dict | None, b: dict | None) -> float | None:
    if a is None or b is None:
        return None
    from pycocotools import mask as mask_utils

    ra = {"size": a["size"], "counts": a["counts"].encode("ascii")}
    rb = {"size": b["size"], "counts": b["counts"].encode("ascii")}
    return float(mask_utils.iou([ra], [rb], [0])[0][0])


@dataclass
class Tracklet:
    key: tuple[int, str, int]
    dets: list[RawDetection] = field(default_factory=list)

    @property
    def prompt(self) -> str:
        return self.key[1]

    @property
    def chunk(self) -> int:
        return self.key[0]

    def at(self, t: float, tol: float) -> RawDetection | None:
        best = min(self.dets, key=lambda d: abs(d.t - t))
        return best if abs(best.t - t) <= tol else None

    @property
    def mean_score(self) -> float:
        return sum(d.score for d in self.dets) / len(self.dets)


class _UnionFind:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, i: int) -> int:
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a: int, b: int) -> None:
        self.p[self.find(a)] = self.find(b)


def group_tracklets(dets: list[RawDetection]) -> list[Tracklet]:
    groups: dict[tuple[int, str, int], Tracklet] = {}
    for d in dets:
        groups.setdefault((d.chunk, d.prompt, d.local_id), Tracklet(key=(d.chunk, d.prompt, d.local_id))).dets.append(d)
    for tr in groups.values():
        tr.dets.sort(key=lambda d: d.t)
    return list(groups.values())


def _similarity(a: Tracklet, b: Tracklet, tol: float, use_masks: bool) -> tuple[float, int]:
    """Mean IoU over the frames both tracklets cover, and how many frames that was."""
    scores = []
    for da in a.dets:
        db = b.at(da.t, tol)
        if db is None:
            continue
        m = mask_iou(da.rle, db.rle) if use_masks else None
        scores.append(m if m is not None else box_iou(da.box, db.box))
    return (sum(scores) / len(scores), len(scores)) if scores else (0.0, 0)


def link(tracklets: list[Tracklet], cfg: SamConfig, step: float) -> list[list[Tracklet]]:
    uf = _UnionFind(len(tracklets))
    tol = step * 0.5 + 1e-6
    # 1. same prompt, adjacent chunks, overlapping in time → same object continues.
    for i, a in enumerate(tracklets):
        for j, b in enumerate(tracklets):
            if j <= i or a.prompt != b.prompt or abs(a.chunk - b.chunk) != 1:
                continue
            iou, n = _similarity(a, b, tol, use_masks=False)
            if n and iou >= cfg.stitch_iou:
                uf.union(i, j)
    # 2. same chunk, masks overlapping on the frames both cover → the same physical object found twice
    #    (by two prompts, or twice by one prompt, e.g. a second, looser box around the same beaker).
    for i, a in enumerate(tracklets):
        for j, b in enumerate(tracklets):
            if j <= i or a.chunk != b.chunk:
                continue
            iou, n = _similarity(a, b, tol, use_masks=True)
            shorter = min(len(a.dets), len(b.dets))
            if n >= max(1, shorter // 2) and iou >= cfg.dedupe_iou:
                uf.union(i, j)
    groups: dict[int, list[Tracklet]] = defaultdict(list)
    for i, tr in enumerate(tracklets):
        groups[uf.find(i)].append(tr)
    return list(groups.values())


def build_tracks(dets: list[RawDetection], cfg: SamConfig, step: float) -> list[ObjectTrack]:
    tracklets = group_tracklets(dets)
    tracks: list[ObjectTrack] = []
    for group in link(tracklets, cfg, step):
        by_prompt: dict[str, list[float]] = defaultdict(list)
        for tr in group:
            by_prompt[tr.prompt].extend(d.score for d in tr.dets)
        label = max(by_prompt, key=lambda p: (sum(by_prompt[p]) / len(by_prompt[p]), len(by_prompt[p])))

        per_t: dict[float, RawDetection] = {}
        for tr in group:
            for d in tr.dets:
                key = round(d.t, 3)
                if key not in per_t or d.score > per_t[key].score:
                    per_t[key] = d
        frames = [per_t[k] for k in sorted(per_t)]

        instances = split_instances(frames, cfg, step)
        if not instances:
            continue
        kept = [d for d in frames if any(i.start - 1e-6 <= d.t < i.end + 1e-6 for i in instances)]
        if sum(d.score for d in kept) / len(kept) < cfg.min_confidence:
            continue
        tracks.append(
            ObjectTrack(
                object_id="",
                label=label,
                confidence=sum(d.score for d in kept) / len(kept),
                instances=instances,
                detections=[FrameDetection(t=d.t, box=d.box, score=d.score, rle=d.rle) for d in kept],
                aliases=sorted(p for p in by_prompt if p != label),
            )
        )
    tracks.sort(key=lambda t: (t.start, t.label))
    for n, t in enumerate(tracks, 1):
        t.object_id = f"obj_{n:03d}"
    return tracks


def split_instances(frames: list[RawDetection], cfg: SamConfig, step: float) -> list[ObjectInstance]:
    """Splits a track wherever the object is missing for longer than max_gap_seconds."""
    runs: list[list[RawDetection]] = []
    for d in frames:
        if runs and d.t - runs[-1][-1].t <= cfg.max_gap_seconds + 1e-6:
            runs[-1].append(d)
        else:
            runs.append([d])
    out = []
    for run in runs:
        start, end = run[0].t, run[-1].t + step
        if end - start < cfg.min_track_seconds:
            continue
        bbox = [median(d.box[k] for d in run) for k in range(4)]
        out.append(ObjectInstance(start=start, end=end, bbox=bbox))
    return out
