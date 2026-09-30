from loom_perception.light import IouTracker, match_prompt, vote_labels
from loom_perception.sam import RawDetection


def test_track_label_is_the_confidence_weighted_vote():
    box = [0.2, 0.3, 0.3, 0.5]
    dets = [RawDetection(0, "beaker", 1, t / 2, box, 0.7, None) for t in range(8)]
    dets += [RawDetection(0, "glass shards", 1, 4.0 + t / 2, box, 0.45, None) for t in range(3)]
    dets += [RawDetection(0, "glass shards", 2, 20.0, [0.5, 0.7, 0.4, 0.2], 0.4, None)]
    out = vote_labels(dets)
    assert {d.prompt for d in out if d.local_id == 1} == {"beaker"}
    assert [d.prompt for d in out if d.local_id == 2] == ["glass shards"]

PROMPTS = ["beaker", "conical flask", "broken glass", "test tube rack"]


def test_clip_judgement_overrides_a_detector_vote_it_disagrees_with():
    box = [0.2, 0.3, 0.3, 0.5]
    dets = [RawDetection(0, "glass shards", 1, t / 2, box, 0.6, None) for t in range(6)]
    dets += [RawDetection(0, "beaker", 1, 3.0 + t / 2, box, 0.4, None) for t in range(2)]
    out = vote_labels(dets, {1: {"beaker": 0.9, "glass shards": 0.1}}, verify_weight=0.7)
    assert {d.prompt for d in out} == {"beaker"}


def test_tracks_clip_calls_none_of_the_prompts_are_dropped():
    box = [0.2, 0.3, 0.3, 0.5]
    dets = [RawDetection(0, "glass shards", 1, t / 2, box, 0.5, None) for t in range(6)]
    dets += [RawDetection(0, "beaker", 2, t / 2, [0.6, 0.3, 0.2, 0.4], 0.6, None) for t in range(6)]
    verified = {1: {"beaker": 0.1, "glass shards": 0.2, "__other__": 0.7}, 2: {"beaker": 0.8, "glass shards": 0.1, "__other__": 0.1}}
    out = vote_labels(dets, verified)
    assert {d.local_id for d in out} == {2}


def test_detector_labels_map_back_to_prompts():
    assert match_prompt("beaker", PROMPTS) == "beaker"
    assert match_prompt("flask", PROMPTS) == "conical flask"
    assert match_prompt("test tube", PROMPTS) == "test tube rack"
    assert match_prompt("glass", PROMPTS) == "broken glass"
    assert match_prompt("person", PROMPTS) is None


def test_tracker_keeps_ids_for_overlapping_boxes_and_splits_new_objects():
    tr = IouTracker(max_gap=1.0, min_iou=0.3)
    a, b = [0.1, 0.1, 0.2, 0.3], [0.6, 0.1, 0.2, 0.3]
    first = tr.assign("beaker", 0.0, [a, b])
    moved = tr.assign("beaker", 0.5, [[0.62, 0.1, 0.2, 0.3], [0.11, 0.1, 0.2, 0.3]])
    assert moved == [first[1], first[0]]  # matched by overlap, not by order


def test_tracker_starts_a_new_id_after_a_long_gap():
    tr = IouTracker(max_gap=1.0, min_iou=0.3)
    box = [0.1, 0.1, 0.2, 0.3]
    (first,) = tr.assign("beaker", 0.0, [box])
    (later,) = tr.assign("beaker", 5.0, [box])
    assert later != first


def test_prompts_are_tracked_independently():
    tr = IouTracker(max_gap=1.0, min_iou=0.3)
    box = [0.1, 0.1, 0.2, 0.3]
    (b1,) = tr.assign("beaker", 0.0, [box])
    (g1,) = tr.assign("broken glass", 0.0, [box])
    assert b1 != g1
