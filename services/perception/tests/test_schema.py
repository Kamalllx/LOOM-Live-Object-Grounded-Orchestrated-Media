from __future__ import annotations

import copy
import json

from conftest import REPO
from loom_perception.schema import validate

SAMPLE = json.loads((REPO / "fixtures" / "concept-graph.sample.json").read_text(encoding="utf-8-sig"))


def test_repo_sample_is_valid():
    assert validate(SAMPLE) == []


def test_missing_required_field_rejected():
    g = copy.deepcopy(SAMPLE)
    del g["concept_nodes"]
    assert any("concept_nodes" in e for e in validate(g))


def test_bbox_must_be_four_normalized_numbers():
    g = copy.deepcopy(SAMPLE)
    g["objects"][0]["instances"][0]["bbox"] = [0.3, 0.4, 1.5]
    assert validate(g)


def test_node_cannot_reference_unknown_object():
    g = copy.deepcopy(SAMPLE)
    g["concept_nodes"][0]["object_ids"] = ["obj_999"]
    assert any("obj_999" in e for e in validate(g))


def test_additive_fields_are_allowed():
    g = copy.deepcopy(SAMPLE)
    g["objects"][0]["mask_ref"] = "masks/obj_001.json"
    g["concept_nodes"][0]["start"] = 12.0
    assert validate(g) == []
