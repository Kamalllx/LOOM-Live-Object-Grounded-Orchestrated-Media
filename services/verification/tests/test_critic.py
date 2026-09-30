"""Fault injection: every planted fault is flagged AND blocks approval; correct cuts pass."""

import copy

import pytest

from loom_verification.animator import Explainer
from loom_verification.critic import Critic
from loom_verification.guardian import Guardian


def _ex(cid, story):
    return Explainer(cid, "", f"s3://loom-clips/{cid}-{hash(tuple(story))}.mp4", story, False, 1, 0, 10, "t")


@pytest.fixture
def critic(cfg):
    return Critic(cfg, None)


@pytest.fixture
def masks(cfg, graph_source):
    return Guardian(cfg, None).build_masks(graph_source, [{"start": 0, "end": 60}], {"obj_004": "hazard"}, render=False)


def score(critic, cand, graph_source, profile, flagged=(), masks=(), explainers=None, failures=None):
    return critic.score(cand["threads"], cand.get("quiz", []), graph_source.graph, profile, set(flagged), list(masks),
                        explainers or {}, failures or {})


def test_clean_cut_is_approved(critic, candidate, graph_source, family_profile, masks):
    v = score(critic, candidate, graph_source, family_profile, {"obj_004"}, masks,
              {"c_01": _ex("c_01", ["Combine the two solutions slowly."])})
    assert v["approved"] and v["scores"] == {"factuality": 1.0, "coherence": 1.0, "safety": 1.0}


def test_unmasked_hazard(critic, candidate, graph_source, family_profile):
    v = score(critic, candidate, graph_source, family_profile, {"obj_004"}, [])
    assert not v["approved"] and v["scores"]["safety"] == 0.0
    assert {i["code"] for i in v["issues"]} == {"unmasked_hazard"}


def test_mask_cut_short(critic, candidate, graph_source, family_profile, masks):
    short = [dict(m, end=m["start"] + 2) for m in masks]
    v = score(critic, candidate, graph_source, family_profile, {"obj_004"}, short)
    assert not v["approved"] and 0 < v["scores"]["safety"] < 1


def test_wrong_quiz_answer(critic, candidate, graph_source, family_profile, masks):
    cand = copy.deepcopy(candidate)
    cand["quiz"] = [{"question": "What does the reaction form?", "concept_node_id": "c_01",
                     "options": ["rocket fuel and lava", "salt and water"], "answer_index": 0}]
    v = score(critic, cand, graph_source, family_profile, {"obj_004"}, masks)
    assert not v["approved"] and "quiz_unsupported" in {i["code"] for i in v["issues"]}
    cand["quiz"][0]["answer_index"] = 1
    assert score(critic, cand, graph_source, family_profile, {"obj_004"}, masks)["approved"]


def test_unfaithful_explainer(critic, candidate, graph_source, family_profile, masks):
    v = score(critic, candidate, graph_source, family_profile, {"obj_004"}, masks,
              {"c_01": _ex("c_01", ["The indicator turns bright purple at exactly pH 12."])})
    assert not v["approved"] and "explainer_unfaithful" in {i["code"] for i in v["issues"]}


@pytest.mark.parametrize("mutate,code", [
    (lambda c: c["threads"][0].update(end=14.0), "cut_mid_sentence"),
    (lambda c: c["threads"][1].update(start=20.0), "overlapping_threads"),
    (lambda c: c["threads"][0].update(end=90.0), "thread_out_of_bounds"),
    (lambda c: c["threads"][0].update(concept_node_ids=["c_77"]), "unknown_concept"),
    (lambda c: c.update(threads=[]), "empty_cut"),
])
def test_structural_faults(critic, candidate, graph_source, family_profile, masks, mutate, code):
    cand = copy.deepcopy(candidate)
    mutate(cand)
    v = score(critic, cand, graph_source, family_profile, {"obj_004"}, masks)
    assert not v["approved"] and code in {i["code"] for i in v["issues"]}


def test_missing_prerequisite(critic, candidate, graph_source, family_profile, masks):
    graph_source.graph["concept_nodes"][1]["prerequisites"] = ["c_01"]
    cand = copy.deepcopy(candidate)
    cand["threads"] = [cand["threads"][1]]
    v = score(critic, cand, graph_source, family_profile, {"obj_004"}, masks)
    assert "missing_prerequisite" in {i["code"] for i in v["issues"]}


def test_unavailable_explainer_blocks(critic, candidate, graph_source, family_profile, masks):
    v = score(critic, candidate, graph_source, family_profile, {"obj_004"}, masks, failures={"c_01": "manim missing"})
    assert not v["approved"] and "explainer_unavailable" in {i["code"] for i in v["issues"]}
