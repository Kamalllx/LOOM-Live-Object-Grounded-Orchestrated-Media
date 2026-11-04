"""Board & animation understanding: board memory, occlusion, element tracking, OCR line merging."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from loom.perception.board import (  # noqa: E402
    analyse_frame,
    boxes_overlap,
    is_noise,
    merge_lines,
    scan_board,
)

W, H = 640, 360


def board(t: float, presenter_x: int | None, written: int) -> np.ndarray:
    """A whiteboard: `written` lines of text appear one per 3 s; an optional solid presenter stands in front."""
    img = np.full((H, W, 3), 245, np.uint8)
    for k in range(written):
        cv2.putText(img, f"step {k + 1}: x = {k}", (360, 60 + 40 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (30, 30, 30), 2)
    cv2.rectangle(img, (40, 40), (220, 220), (30, 30, 30), 2)  # a drawn diagram: grid
    for g in (100, 160):
        cv2.line(img, (g, 40), (g, 220), (30, 30, 30), 2)
        cv2.line(img, (40, g), (220, g), (30, 30, 30), 2)
    if presenter_x is not None:  # a person in a black shirt: solid, far from the board colour
        cv2.ellipse(img, (presenter_x, 360), (90, 200), 0, 0, 360, (20, 20, 20), -1)
        cv2.circle(img, (presenter_x, 130), 40, (120, 150, 200), -1)
    return img


def test_presenter_is_occluder_not_ink() -> None:
    ink, visible, frac, _ = analyse_frame(board(0, 330, 2))
    assert frac > 0.5
    assert not visible[300, 330]  # the shirt is not board
    assert ink[300, 330] == 0  # and never ink
    assert ink[60:240, 40:222].any()  # the drawn grid is ink


def test_elements_grow_and_survive_occlusion() -> None:
    frames = []
    for t in range(40):
        written = min(4, 1 + t // 3)
        presenter = 480 if 14 <= t < 30 else None  # stands in front of the text lines for 16 s
        frames.append((float(t), board(t, presenter, written)))
    scan = scan_board(iter(frames), [], 1.0)
    assert scan.board_ratio == 1.0
    boxes = [e.box for e in scan.elements]
    grid = [e for e, b in zip(scan.elements, boxes) if b[0] < 60 and b[2] > 150]
    text = [e for e, b in zip(scan.elements, boxes) if b[0] >= 340]
    # each written line is one element: all four were written before the presenter walked in, and standing in front
    # of them for 16 s neither erased nor split them
    assert len(text) == 4
    assert all(e.life >= 25 and e.last_t >= 39 for e in text)
    longest = max(text, key=lambda e: e.life)
    # no element was made of the presenter
    assert all(not (b[0] < 480 < b[0] + b[2] and b[1] + b[3] > 300) for b in boxes)
    # masks are picture-relative RLE at the mask width
    t, rle, box = longest.samples[-1]
    assert rle.startswith("rle:") and 0 <= box[0] <= 1


def test_new_slide_starts_new_elements() -> None:
    a = np.full((H, W, 3), (190, 120, 40), np.uint8)  # flat blue animation background
    cv2.putText(a, "BIOS checks CPU RAM", (60, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    b = np.full((H, W, 3), (190, 120, 40), np.uint8)
    cv2.putText(b, "MBR at cylinder 0", (300, 280), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    scan = scan_board(iter([(float(t), a) for t in range(6)] + [(float(t), b) for t in range(6, 12)]), [6.0], 1.0)
    assert len(scan.elements) == 2
    first, second = sorted(scan.elements, key=lambda e: e.first_t)
    assert first.epoch != second.epoch and first.last_t < 6 <= second.first_t


@dataclass
class Span:
    text_id: str
    start: float
    end: float
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float


def test_merge_lines_joins_words_on_one_line() -> None:
    spans = [Span("x_001", 2, 9, "The", (0.07, 0.37, 0.04, 0.05), 0.9),
             Span("x_002", 2.5, 9, "animal", (0.14, 0.37, 0.06, 0.05), 0.9),
             Span("x_003", 2.5, 9, "didn't", (0.23, 0.36, 0.05, 0.05), 0.9),
             Span("x_004", 2, 9, "How do transformers work?", (0.06, 0.04, 0.5, 0.07), 0.95)]
    out = merge_lines(spans, lambda f, text, a, b, box, conf: Span(f.text_id, a, b, text, box, conf))
    texts = sorted(s.text for s in out)
    assert texts == ["How do transformers work?", "The animal didn't"]


def test_scribble_noise_is_dropped() -> None:
    assert is_noise("imom", 0.8) and is_noise("minn", 0.9) and is_noise("immmn", 0.9) and is_noise("m", 0.5)
    assert not is_noise("N-Queens", 0.8) and not is_noise("Q1", 0.95) and not is_noise("row", 0.9)


def test_boxes_overlap_is_over_the_smaller_box() -> None:
    assert boxes_overlap((0, 0, 1, 1), (0.2, 0.2, 0.1, 0.1)) == pytest.approx(1.0)
    assert boxes_overlap((0, 0, 0.1, 0.1), (0.5, 0.5, 0.1, 0.1)) == 0.0


def test_same_label_on_screen_together_never_overlaps(tmp_path) -> None:
    """Regression (N-Queens ingest): two simultaneous marks the VLM names alike must not become one object with
    overlapping instances (ConceptGraph rejects that and the whole ingest was lost)."""
    import asyncio
    from types import SimpleNamespace

    from loom.perception.board import BoardScan, ElementTrack, read_elements

    class FakeLLM:
        async def call(self, *a, **k):  # every element reads as "Q1"
            return SimpleNamespace(value=SimpleNamespace(is_content=True, kind="text", label="Q1", content="Q1",
                                                         meaning="queen 1"))

    def el(i: int, a: float, b: float) -> ElementTrack:
        e = ElementTrack(track_id=i, box=(10 * i, 10, 20, 20), first_t=a, last_t=b, epoch=1)
        e.samples = [(a, "rle:2x2:4", (0.1, 0.1, 0.1, 0.1))]
        e.crop = np.full((20, 20, 3), 255, np.uint8)
        return e

    scan = BoardScan(elements=[el(0, 10, 50), el(1, 20, 60), el(2, 70, 90)], board_ratio=1.0, samples=100,
                     picture_hw=(360, 640))
    shots = [SimpleNamespace(shot_id="sh_01", start=0.0, end=100.0)]
    objs, _ = asyncio.run(read_elements(FakeLLM(), scan, [], [], shots, 100.0, 1.0, 1, tmp_path))
    assert sorted(o.label for o in objs) == ["Q1", "Q1 (2)"]
    for o in objs:  # no object has instances overlapping in time
        spans = sorted((i.start, i.end) for i in o.instances)
        assert all(b0 <= a1 for (_, b0), (a1, _) in zip(spans, spans[1:]))


def test_split_overlaps_moves_overlapping_instances_to_a_new_object() -> None:
    from loom.core.contracts.graph import GraphObject, ObjectInstance, SafetyRecord, TrackSample, Verification
    from loom.perception.pipeline import split_overlaps

    def inst(k: int, a: float, b: float) -> ObjectInstance:
        return ObjectInstance(instance_id=f"o_001_{k}", shot_id="sh_01", start=a, end=b, score=0.9,
                              track=[TrackSample(t=a, bbox=(0.1, 0.1, 0.1, 0.1))],
                              verification=Verification(status="verified"))

    o = GraphObject.model_construct(object_id="o_001", label="Q1", phrase_source="board", is_hazard_class=False,
                                    instances=[inst(0, 0, 10), inst(1, 5, 15), inst(2, 20, 30)],
                                    safety=SafetyRecord(status="unreviewed"), element_kind="text", content=None,
                                    description=None)
    out = split_overlaps([o])
    assert [x.label for x in out] == ["Q1", "Q1 (2)"]
    assert [x.object_id for x in out] == ["o_001", "o_002"]
    assert [len(x.instances) for x in out] == [2, 1]
    assert out[1].instances[0].instance_id == "o_002_0"
