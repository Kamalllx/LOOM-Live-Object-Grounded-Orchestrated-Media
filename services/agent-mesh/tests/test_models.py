import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models import LearnerProfile
from app.validation import parse_concept_graph, parse_learner_profile


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPOSITORY_ROOT / "fixtures"


def load_fixture(filename: str) -> dict:
    with (FIXTURES_DIR / filename).open(encoding="utf-8-sig") as fixture_file:
        return json.load(fixture_file)


def test_concept_graph_fixture_is_valid():
    graph = parse_concept_graph(load_fixture("concept-graph.sample.json"))

    assert graph.video_id == "vid_00123"
    assert graph.concept_nodes[0].node_id == "c_01"


def test_learner_profile_fixture_is_valid():
    profile = parse_learner_profile(load_fixture("learner-profile.sample.json"))

    assert profile.learner_id == "learner_al91"
    assert profile.mastery_graph[0].level == 0.42


@pytest.mark.parametrize("level", [-0.1, 1.1])
def test_mastery_level_must_be_between_zero_and_one(level: float):
    with pytest.raises(ValidationError):
        LearnerProfile.model_validate(
            {
                "schema_version": "1.0",
                "learner_id": "learner_test",
                "mastery_graph": [{"concept_id": "c_01", "level": level}],
            }
        )


def test_missing_learner_id_is_rejected():
    document = load_fixture("learner-profile.sample.json")
    document.pop("learner_id")

    with pytest.raises(ValueError):
        parse_learner_profile(document)


def test_unknown_object_reference_is_rejected():
    document = load_fixture("concept-graph.sample.json")
    document["concept_nodes"][0]["object_ids"] = ["obj_missing"]

    with pytest.raises(ValueError, match="unknown object IDs"):
        parse_concept_graph(document)
