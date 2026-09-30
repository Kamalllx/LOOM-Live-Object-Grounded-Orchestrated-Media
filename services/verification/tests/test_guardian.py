import pytest

from loom_verification.guardian import Guardian, _union_box, lexicon_tags
from loom_verification.matte import decode_rle, rle_counts_from_string


def test_lexicon_flags_hazards_and_passes_lab_equipment():
    assert "sharp_object" in lexicon_tags("glass shards")["tags"]
    assert lexicon_tags("beaker")["tags"] == ["none"]


def _decide(graph_source, level, blocked=(), requests=()):
    tags = {o["object_id"]: lexicon_tags(o["label"]) for o in graph_source.graph["objects"]}
    profile = {"family_safety_profile": {"redaction_level": level, "blocked_tags": list(blocked)}}
    return Guardian.decide(graph_source.graph, profile, list(requests), tags)


def test_policy_levels(graph_source):
    assert _decide(graph_source, "off") == {}
    assert set(_decide(graph_source, "standard")) == {"obj_004"}
    assert "obj_001" not in _decide(graph_source, "strict")           # a beaker is never a hazard
    assert set(_decide(graph_source, "off", blocked=["sharp_object"])) == {"obj_004"}   # blocked tags always win


def test_mesh_requests_are_honoured_but_unknown_objects_ignored(graph_source):
    d = _decide(graph_source, "standard", requests=[{"object_id": "obj_001", "reason": "parent asked"},
                                                     {"object_id": "obj_999"}])
    assert d["obj_001"] == "parent asked" and "obj_999" not in d


def test_masks_padded_in_time_and_cover_every_box(cfg, graph_source):
    g = Guardian(cfg, None)
    masks = g.build_masks(graph_source, [{"start": 0, "end": 60}], {"obj_004": "hazard"}, render=False)
    (m,) = masks
    assert m["start"] < 40.0 and m["end"] > 46.0 and m["mask_url"] == "s3://loom-masks/vid_00123/obj_004_0.mp4"
    x, y, w, h = m["fallback_bbox"]
    assert x <= 0.5 and y <= 0.6 and x + w >= 0.7 and y + h >= 0.8


def test_mask_outside_the_cut_is_not_emitted(cfg, graph_source):
    g = Guardian(cfg, None)
    assert g.build_masks(graph_source, [{"start": 0, "end": 20}], {"obj_004": "hazard"}, render=False) == []


def test_union_box_covers_a_moving_object():
    x, y, w, h = _union_box([[0.1, 0.1, 0.1, 0.1], [0.5, 0.5, 0.1, 0.1]], 0.0)
    assert (x, y, round(x + w, 4), round(y + h, 4)) == (0.1, 0.1, 0.6, 0.6)


def test_rle_decoding_matches_the_coco_layout():
    # uncompressed counts, column-major: a 3x2 mask with the middle row set
    m = decode_rle({"size": [3, 2], "counts": [1, 1, 2, 1, 1]})
    assert m.tolist() == [[False, False], [True, True], [False, False]]
    # compressed strings store counts after the first two as deltas from the count two places earlier
    assert rle_counts_from_string("0120") == [0, 1, 2, 1]


def test_rle_decoding_matches_pycocotools():
    """Person 1 encodes masks with pycocotools; our dependency-free decoder must read them identically."""
    np = pytest.importorskip("numpy")
    mask_utils = pytest.importorskip("pycocotools.mask")
    rng = np.random.default_rng(0)
    m = np.zeros((54, 96), dtype=np.uint8)
    m[10:30, 20:70] = 1
    m[rng.random(m.shape) > 0.97] = 1                 # speckle, so counts get large and irregular
    rle = mask_utils.encode(np.asfortranarray(m))
    rle["counts"] = rle["counts"].decode("ascii")    # Person 1's sidecars store the string form
    assert (decode_rle(rle) == m.astype(bool)).all()
