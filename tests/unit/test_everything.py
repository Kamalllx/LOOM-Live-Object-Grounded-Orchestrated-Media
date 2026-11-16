"""Segment everything: the graphic gate, candidate filters, de-duplication, linking through time, board de-dup."""

from __future__ import annotations

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from loom.perception.everything import (  # noqa: E402
    Element,
    EverythingScan,
    dedupe,
    graphic_score,
    grid_points,
    is_element,
    link,
    outlined_crop,
    scan_interval,
    stability,
    to_tracks,
)

H, W = 270, 480


def disc(cx: int, cy: int, r: int) -> np.ndarray:
    m = np.zeros((H, W), np.uint8)
    cv2.circle(m, (cx, cy), r, 1, -1)
    return m > 0


def test_graphic_gate_separates_drawn_frames_from_footage() -> None:
    drawn = np.full((360, 640, 3), 240, np.uint8)
    cv2.rectangle(drawn, (100, 80), (300, 200), (40, 120, 220), -1)
    cv2.putText(drawn, "BIOS", (130, 150), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
    rng = np.random.default_rng(0)
    footage = np.clip(drawn.astype(np.int16) + rng.normal(0, 3, drawn.shape), 0, 255).astype(np.uint8)
    assert graphic_score(drawn) > 0.9
    assert graphic_score(footage) < 0.9


def test_grid_points_cover_the_picture() -> None:
    pts = grid_points(100, 50, n=4)
    assert pts.shape == (16, 2)
    assert pts[:, 0].min() == pytest.approx(12.5) and pts[:, 0].max() == pytest.approx(87.5)
    assert pts[:, 1].min() == pytest.approx(6.25)


def test_stability_is_high_for_crisp_logits() -> None:
    crisp = np.where(disc(100, 100, 30), 8.0, -8.0)[None]
    soft = np.where(disc(100, 100, 30), 0.5, -0.5)[None]
    assert stability(crisp)[0] == pytest.approx(1.0)
    assert stability(soft)[0] == 0.0


def test_is_element_rejects_background_and_specks() -> None:
    assert is_element(disc(200, 120, 30))
    assert not is_element(disc(200, 120, 2))  # speck
    bg = np.ones((H, W), bool)
    bg[100:150, 200:260] = False  # the background around one object
    assert not is_element(bg)
    corner_panel = np.zeros((H, W), bool)
    corner_panel[:200, :240] = True  # a big panel glued to two frame edges
    assert not is_element(corner_panel)


def test_dedupe_keeps_best_of_near_identical_masks() -> None:
    a, b, c = disc(100, 100, 30), disc(101, 100, 30), disc(300, 150, 20)
    assert dedupe([a, b, c], [0.8, 0.9, 0.7]) == [1, 2]


def test_link_keeps_ids_through_motion_and_splits_shots() -> None:
    els: list[Element] = []
    _, nid = link(els, [(disc(100, 100, 30), 0.9), (disc(300, 150, 20), 0.9)], 0.0, 1, 0, 0)
    _, nid = link(els, [(disc(108, 100, 30), 0.9), (disc(300, 150, 20), 0.9)], 1.0, 2, 0, nid)  # first one moved
    assert nid == 2 and [len(e.samples) for e in els] == [2, 2]
    _, nid = link(els, [(disc(108, 100, 30), 0.9)], 2.0, 3, 1, nid)  # new shot: a new element, same place
    assert nid == 3 and len(els[2].samples) == 1


def test_link_ends_elements_after_a_gap() -> None:
    els: list[Element] = []
    _, nid = link(els, [(disc(100, 100, 30), 0.9)], 0.0, 1, 0, 0)
    _, nid = link(els, [(disc(100, 100, 30), 0.9)], 9.0, 9, 0, nid)  # unseen for 7 samples: it went away
    assert nid == 2


def test_outlined_crop_dims_the_surroundings() -> None:
    img = np.full((H, W, 3), 200, np.uint8)
    m = disc(200, 120, 30)
    crop = outlined_crop(img, m, (170, 90, 231, 151))
    assert crop.shape[0] > 61 and crop.shape[1] > 61
    assert crop[2, 2].max() < 120  # outside the element: dimmed
    assert crop[crop.shape[0] // 2, crop.shape[1] // 2].tolist() == [200, 200, 200]


def test_scan_interval_grows_with_length() -> None:
    assert scan_interval(120) == 1.0 and scan_interval(400) == 2.0 and scan_interval(900) == 3.0


def test_to_tracks_drops_copies_of_board_ink_but_keeps_nested_elements() -> None:
    from loom.perception.board import ElementTrack

    def el(i: int, m: np.ndarray) -> Element:
        e = Element(track_id=i, shot=0)
        for t in (1.0, 2.0):
            ys, xs = np.nonzero(m)
            box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
            e.samples.append((t, m, box, float(m.mean())))
        e.best, e.crop = (0.5, 1.0), np.zeros((4, 4, 3), np.uint8)
        return e

    line = disc(100, 100, 20)  # read as ink already: same box as the ink element
    chip = disc(350, 150, 25)  # elsewhere: kept
    row = disc(200, 200, 15)  # inside a big ink block (a whole table) but not a copy of it: kept, stays hoverable
    ink = [ElementTrack(track_id=0, box=(0, 0, 0, 0), first_t=0.0, last_t=3.0, epoch=1,
                        samples=[(1.0, "rle", (78 / W, 78 / H, 44 / W, 44 / H))]),
           ElementTrack(track_id=1, box=(0, 0, 0, 0), first_t=0.0, last_t=3.0, epoch=1,
                        samples=[(1.0, "rle", (150 / W, 160 / H, 200 / W, 100 / H))])]
    scan = EverythingScan(elements=[el(1, line), el(2, chip), el(3, row)], graphic_ratio=1.0, samples=2,
                          picture_hw=(H, W))
    out = to_tracks(scan, ink)
    assert [t.track_id for t in out] == [2, 3]
    _, rle, box = out[0].samples[0]
    assert rle.startswith(f"rle:{H}x{W}:") and box[0] == pytest.approx(325 / W, abs=1e-3)


def test_tidy_text_joins_words_on_a_line_and_drops_stray_letters() -> None:
    from loom.perception.everything import tidy_text

    img = np.full((H, W), 30, np.uint8)
    cv2.putText(img, "Kevin", (100, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.5, 230, 1)
    cv2.putText(img, "Durant", (152, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.5, 230, 1)
    cv2.rectangle(img, (300, 60), (340, 100), 160, -1)  # a solid drawn part next to it: not text
    cv2.rectangle(img, (346, 60), (386, 100), 160, -1)  # and a second one right beside it
    box = lambda x0, y0, x1, y1: np.pad(np.ones((y1 - y0, x1 - x0), bool), ((y0, H - y1), (x0, W - x1)))  # noqa: E731
    glyphs = cv2.dilate((img > 100).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0  # SAM word masks hug letters
    kevin, durant = box(98, 86, 148, 104) & glyphs, box(150, 86, 210, 104) & glyphs
    part_a, part_b = box(300, 60, 341, 101), box(346, 60, 387, 101)
    panel = box(80, 40, 240, 140)
    letter = box(120, 50, 130, 62)  # inside the panel, letter-sized
    masks, _ = tidy_text([kevin, durant, part_a, part_b, panel, letter], [0.9] * 6, img)
    sizes = sorted(int(m.sum()) for m in masks)
    assert len(masks) == 4  # "Kevin Durant" as one line, the two parts apart, the panel; the letter is gone
    assert int((kevin | durant).sum()) in sizes and int(part_a.sum()) in sizes and int(part_b.sum()) in sizes


def test_pick_parts_keeps_inner_regions_and_drops_whole_and_specks() -> None:
    from loom.perception.everything import pick_parts

    element = disc(200, 130, 80)
    petal_a, petal_b = disc(170, 110, 18), disc(230, 110, 18)
    whole = disc(200, 130, 78)  # nearly the element itself: not a part
    speck = disc(200, 160, 2)
    outside = disc(400, 60, 20)
    parts = pick_parts(element, [whole, petal_a, speck, petal_b, outside, petal_a.copy()])
    assert len(parts) == 2 and all(int(p.sum()) == int(petal_a.sum()) for p in parts)
    assert pick_parts(element, [petal_a]) == []  # one region is not a split
