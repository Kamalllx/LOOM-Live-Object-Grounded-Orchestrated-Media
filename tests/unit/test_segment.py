from __future__ import annotations

import numpy as np

from loom.core.contracts.graph import TrackSample
from loom.perception.detect import Box
from loom.perception.segment import (
    crop_to_picture,
    decode_rle,
    encode_rle,
    instances_from_masks,
    mask_bbox,
    picture_box_to_frame_xyxy,
    presence_runs,
)
from loom.perception.track import Track


def test_rle_round_trip_and_contract_pattern() -> None:
    m = np.zeros((54, 96), dtype=bool)
    m[10:20, 30:60] = True
    value = encode_rle(m)
    assert value.startswith("rle:54x96:")
    assert (decode_rle(value) == m).all()
    TrackSample(t=1.0, bbox=(0.1, 0.1, 0.2, 0.2), mask=value)  # validates against MaskRle


def test_crop_and_bbox_are_picture_relative() -> None:
    frame = np.zeros((100, 200), dtype=bool)
    frame[20:40, 50:100] = True  # picture = middle half horizontally (letterboxed sides)
    pic = crop_to_picture(frame, (0.25, 0.0, 0.5, 1.0))
    assert pic.shape == (100, 100)
    assert mask_bbox(pic) == (0.0, 0.2, 0.5, 0.2)


def test_tiny_mask_counts_as_absent() -> None:
    m = np.zeros((100, 100), dtype=bool)
    m[0, 0] = True
    assert mask_bbox(m) is None


def test_picture_box_to_frame_pixels() -> None:
    assert picture_box_to_frame_xyxy((0.0, 0.5, 0.5, 0.5), (0.25, 0.0, 0.5, 1.0), 200, 100) == [
        50.0,
        50.0,
        100.0,
        100.0,
    ]


def test_presence_runs_bridge_single_gaps_only() -> None:
    assert presence_runs([True, False, True, False, False, True]) == [(0, 2), (5, 5)]
    assert presence_runs([False, False]) == []


def test_instances_padded_and_clamped_to_shot() -> None:
    seed = Track(phrase="beaker", shot_id="sh_02", samples=[Box(t=10.25, phrase="beaker", box=(0, 0, 1, 1), score=0.6)])
    times = [10.25, 10.75, 11.25, 11.75]
    s = ((0.1, 0.1, 0.2, 0.2), "rle:1x1:1", 0.04)
    out = instances_from_masks(times, [s, s, None, None], seed, 3, 10.0, 12.0, 0.5)
    assert len(out) == 1
    inst = out[0]
    assert (inst.start, inst.end, inst.seed_index, len(inst.samples)) == (10.0, 11.0, 3, 2)
    assert inst.as_track().phrase == "beaker" and inst.as_track().end == 11.0
