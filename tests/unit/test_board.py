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
    # e.box lives on the pan-following board canvas; the reported samples are in frame coordinates
    boxes = [tuple(round(v * s) for v, s in zip(e.samples[-1][2], (W, H, W, H), strict=True)) for e in scan.elements]
    grid = [e for e, b in zip(scan.elements, boxes, strict=True) if b[0] < 60 and b[2] > 150]
    text = [e for e, b in zip(scan.elements, boxes, strict=True) if b[0] >= 340]
    assert len(grid) == 1
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


def test_fit_ctx_grows_with_the_payload_and_is_capped() -> None:
    from loom.perception.pipeline import fit_ctx

    assert fit_ctx({"sentences": []}) == 6144
    big = {"objects": [{"content": "x" * 180, "meaning": "y" * 140} for _ in range(60)]}
    assert 6144 < fit_ctx(big) <= 16384 and fit_ctx(big) % 2048 == 0
    assert fit_ctx({"s": "z" * 200000}) == 16384


def chalkboard(shift: tuple[int, int] = (0, 0)) -> np.ndarray:
    """A phone filming a green chalkboard: more wall than board, a person in dark jeans in front of the wall."""
    img = np.full((H, W, 3), (200, 205, 210), np.uint8)  # white wall: the largest colour in the picture
    cv2.rectangle(img, (40, 60), (600, 230), (50, 70, 45), -1)  # the board
    for k, txt in enumerate(("food making process", "6CO2 + 6H2O -> C6H12O6")):
        cv2.putText(img, txt, (70, 110 + 50 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (225, 230, 225), 2)
    cv2.rectangle(img, (470, 250), (520, 350), (55, 72, 50), -1)  # jeans: board-coloured, below the board
    cv2.rectangle(img, (485, 280), (500, 320), (190, 190, 190), -1)  # a faded patch on them
    return np.roll(img, shift, axis=(0, 1))


def test_board_is_the_written_surface_not_the_largest_one() -> None:
    ink, _, _, colour = analyse_frame(chalkboard())
    assert colour[1] < 120  # green board, not the white wall
    assert ink[90:200, 60:580].sum() > 500  # the chalk is read
    assert ink[250:350, 460:530].sum() == 0  # the jeans are neither board nor ink


def test_handheld_shake_keeps_elements() -> None:
    rng = np.random.default_rng(3)
    frames = [(float(t), chalkboard((int(rng.integers(-2, 3)), int(rng.integers(-2, 3))))) for t in range(20)]
    scan = scan_board(iter(frames), [], 1.0)
    assert scan.board_ratio == 1.0
    assert len(scan.elements) >= 1
    assert max(e.life for e in scan.elements) >= 15  # one element for the whole clip, not a new one every few seconds
    assert max(e.track_id for e in scan.elements) < 8


def test_long_strokes_do_not_chain_a_drawing_to_its_neighbours() -> None:
    from loom.perception.board import group_elements

    mem = np.zeros((H, W), bool)
    canvas = np.zeros((H, W), np.uint8)
    cv2.circle(canvas, (150, 120), 40, 1, 2)  # a drawing (the sun)
    cv2.circle(canvas, (450, 120), 40, 1, 2)  # another drawing (a flower)
    xs = np.arange(60, 580)
    pts = np.stack([xs, 175 + (6 * np.sin(xs / 12)).astype(int)], 1)  # the wavy soil line touching both
    cv2.polylines(canvas, [pts.reshape(-1, 1, 2).astype(np.int32)], False, 1, 2)
    cv2.line(canvas, (150, 160), (150, 175), 1, 2)
    cv2.line(canvas, (450, 160), (450, 175), 1, 2)
    mem[:] = canvas > 0
    boxes = [b for b, _, _ in group_elements(mem)]
    wide = [b for b in boxes if b[2] > 400]
    assert len(wide) == 1 and wide[0][3] < 30  # the line on its own
    assert sum(1 for b in boxes if 60 <= b[2] <= 120) >= 2  # the two drawings apart


def test_a_wide_caption_stays_one_line_not_letters() -> None:
    from loom.perception.board import group_elements

    h, w = 1138, 640  # a portrait Short at analysis width
    canvas = np.zeros((h, w), np.uint8)
    cv2.putText(canvas, "Bisect angle!", (40, 860), cv2.FONT_HERSHEY_DUPLEX, 2.4, 1, 5)  # big, widely spaced letters
    cv2.putText(canvas, "D", (60, 300), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 1, 2)  # a label far above: not the same line
    boxes = [b for b, _, _ in group_elements(canvas > 0)]
    caption = [b for b in boxes if 800 <= b[1] + b[3] / 2 <= 880]
    assert len(caption) == 1 and caption[0][2] > 0.55 * w  # one element across the line
    assert any(b[1] < 400 for b in boxes)  # the label is still its own element


def test_ocr_boxes_on_the_picture_edge_are_kept_inside() -> None:
    from loom.core.contracts.common import _check_bbox
    from loom.perception.ocr import clamp_box

    b = clamp_box((0.1595, 1.0, 0.0967, 0.04))  # the box that failed a batch short
    assert _check_bbox(b) == b
