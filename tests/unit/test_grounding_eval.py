from __future__ import annotations

from loom.eval.grounding_eval import (
    hazard_intervals,
    hazard_seconds,
    meets_targets,
    merge,
    row_keep,
    sample_times,
    score_rows,
    segment_recall,
)
from loom.perception.detect import Box
from loom.perception.track import Track
from loom.perception.verify import TrackVerdict


def _track(phrase: str, start: float, end: float, shot: str = "sh_01") -> Track:
    tr = Track(phrase=phrase, shot_id=shot, samples=[Box(t=start, phrase=phrase, box=(0, 0, 0.1, 0.1), score=0.5)])
    tr.start, tr.end = start, end
    return tr


def test_sample_times_centred_inside_shots() -> None:
    assert sample_times([(0.0, 2.0), (2.0, 3.0)], 2.0) == [0.25, 0.75, 1.25, 1.75, 2.25, 2.75]


def test_merge_joins_touching_and_overlapping() -> None:
    assert merge([(5, 6), (0, 1), (1, 2), (5.5, 7)]) == [(0, 2), (5, 7)]


def test_hazard_seconds_perfect_and_partial() -> None:
    perfect = hazard_seconds([(10.0, 20.0)], [(10.0, 20.0)], 60.0)
    assert perfect == {"precision": 1.0, "recall": 1.0, "f1": 1.0, "false_block_s": 0.0, "missed_s": 0.0}
    partial = hazard_seconds([(8.0, 15.0)], [(10.0, 20.0)], 60.0)
    assert partial["false_block_s"] == 2.0 and partial["missed_s"] == 5.0
    assert partial["precision"] == round(5 / 7, 3) and partial["recall"] == 0.5


def test_hazard_seconds_nothing_predicted_is_zero_recall() -> None:
    m = hazard_seconds([], [(10.0, 12.0)], 60.0)
    assert m["recall"] == 0.0 and m["missed_s"] == 2.0 and m["precision"] == 0.0


def test_hazard_intervals_pad_clamp_and_ignore_non_hazards() -> None:
    tracks = [_track("broken glass", 0.2, 3.0), _track("beaker", 4.0, 9.0), _track("broken glass", 3.2, 5.0)]
    assert hazard_intervals(tracks, {"broken glass"}, 0.5, 4.8) == [(0.0, 4.8)]


def test_row_keep_rules() -> None:
    gen_fail, look_ok = TrackVerdict(siglip_pass=False), TrackVerdict(siglip_pass=True)
    assert row_keep("detector_only", True, gen_fail, gen_fail)
    assert not row_keep("+siglip_generic", False, gen_fail, look_ok)
    assert row_keep("+siglip_lookalikes", False, gen_fail, look_ok)
    # LOOM row fails closed: hazard with SigLIP rejection but VLM failure is kept
    assert row_keep("+vlm (LOOM)", True, gen_fail, TrackVerdict(siglip_pass=False, vlm="failed"))
    assert not row_keep("+vlm (LOOM)", True, gen_fail, TrackVerdict(siglip_pass=False, vlm="rejected"))


def test_segment_recall_proxy_uses_label_equivalents() -> None:
    segs = [{"id": "a", "start": 0, "end": 10, "objects": ["beaker", "gloves"]}]
    kept = [_track("glass beaker", 1, 3), _track("broken glass", 2, 4)]
    out = segment_recall(kept, segs, {"broken glass"})
    assert out["recall"] == 0.5 and out["rows"][0]["matched"] == "glass beaker"


def test_score_rows_lookalike_filter_removes_false_hazard() -> None:
    tracks = [_track("broken glass", 50.0, 55.0), _track("broken glass", 10.0, 14.0), _track("beaker", 10, 14)]
    generic = {0: TrackVerdict(siglip_pass=True), 1: TrackVerdict(siglip_pass=True), 2: TrackVerdict(siglip_pass=True)}
    look = {
        0: TrackVerdict(siglip_pass=True),
        1: TrackVerdict(siglip_pass=False, vlm="rejected"),  # beaker mistaken for broken glass
        2: TrackVerdict(siglip_pass=True),
    }
    segs = [{"id": "s", "start": 0, "end": 60, "objects": ["beaker"]}]
    rows = score_rows(tracks, generic, look, {"broken glass"}, [(50.0, 55.0)], segs, 0.0, 60.0)
    assert rows["detector_only"]["false_block_s"] == 4.0
    assert rows["+vlm (LOOM)"]["false_block_s"] == 0.0 and rows["+vlm (LOOM)"]["recall"] == 1.0
    assert meets_targets(rows["+vlm (LOOM)"]) and not meets_targets(rows["detector_only"])
