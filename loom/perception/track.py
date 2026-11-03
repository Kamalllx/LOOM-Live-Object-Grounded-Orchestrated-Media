"""Segmentation tier T0 `boxes` (spec/02 §10): IoU tracking of detection proposals within each shot.

Per shot and phrase, detections are linked over time when the box IoU ≥ 0.3 and the gap ≤ 1.5 sampling intervals.
A track is an object *instance*: start/end padded by half a sampling interval (clamped to the shot), a box per sample,
the mean detector score. Single-sample tracks below 0.4 are dropped as noise — except hazard classes (recall over
precision; verification decides). Tracks of one phrase are grouped into objects so that instances of an object never
overlap in time within a shot (contract rule); simultaneous same-label tracks become separate objects.
T1 (`sam2`) replaces the boxes with propagated pixel masks behind the same output type.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from loom.perception.detect import Box
from loom.perception.ocr import iou

STAGE_VERSION = "track@1"
LINK_IOU = 0.3
MIN_SINGLE_SCORE = 0.4


@dataclass
class Track:
    phrase: str
    shot_id: str
    samples: list[Box] = field(default_factory=list)
    start: float = 0.0
    end: float = 0.0

    @property
    def score(self) -> float:
        return round(sum(b.score for b in self.samples) / len(self.samples), 4)

    @property
    def best(self) -> list[Box]:
        return sorted(self.samples, key=lambda b: -b.score)[:3]


def track_shot(
    boxes: list[Box], shot_id: str, shot_start: float, shot_end: float, interval: float, hazards: set[str]
) -> list[Track]:
    tracks: list[Track] = []
    for phrase in sorted({b.phrase for b in boxes}):
        active: list[Track] = []
        for b in sorted((b for b in boxes if b.phrase == phrase), key=lambda b: (b.t, -b.score)):
            best, best_iou = None, LINK_IOU
            for tr in active:
                last = tr.samples[-1]
                if last.t >= b.t or b.t - last.t > 1.5 * interval + 1e-6:
                    continue
                o = iou(last.box, b.box)
                if o >= best_iou:
                    best, best_iou = tr, o
            if best is None:
                tr = Track(phrase=phrase, shot_id=shot_id, samples=[b])
                active.append(tr)
                tracks.append(tr)
            else:
                best.samples.append(b)
    kept = []
    for tr in tracks:
        if len(tr.samples) == 1 and tr.score < MIN_SINGLE_SCORE and tr.phrase not in hazards:
            continue
        tr.start = round(max(shot_start, tr.samples[0].t - interval / 2), 2)
        tr.end = round(min(shot_end, tr.samples[-1].t + interval / 2), 2)
        if tr.end <= tr.start:
            tr.end = round(tr.start + 0.05, 2)
        kept.append(tr)
    return kept


def group_into_objects(tracks: list[Track]) -> list[list[Track]]:
    """Same-phrase tracks → objects whose instances never overlap in time within one shot."""
    objects: list[list[Track]] = []
    for phrase in sorted({t.phrase for t in tracks}):
        groups: list[list[Track]] = []
        for tr in sorted((t for t in tracks if t.phrase == phrase), key=lambda t: (-len(t.samples), t.start)):
            for g in groups:
                if all(o.shot_id != tr.shot_id or o.end <= tr.start or tr.end <= o.start for o in g):
                    g.append(tr)
                    break
            else:
                groups.append([tr])
        objects.extend(sorted(g, key=lambda t: t.start) for g in groups)
    return objects
