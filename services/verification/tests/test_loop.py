"""The bounded loop: repairs what it finds, respects the budget, and never ships an unchecked cut."""

import copy

from .conftest import FakeAnimator


def test_approves_first_pass(verifier, candidate, graph_source, family_profile):
    doc = verifier.verify(candidate, graph_source=graph_source, profile=family_profile)
    assert doc["status"] == "approved" and doc["pass_count"] == 1
    assert [m["object_id"] for m in doc["redaction_masks"]] == ["obj_004"]
    assert doc["explainer_clips"][0]["anchor_seconds"] == 12.0


def test_unfaithful_explainer_is_rerendered_with_feedback(verifier, candidate, graph_source, family_profile):
    verifier.animator = FakeAnimator({"c_01": [["The indicator turns bright purple at pH 12."],
                                               ["Combine the two solutions slowly."]]})
    doc = verifier.verify(candidate, graph_source=graph_source, profile=family_profile)
    assert doc["status"] == "approved" and doc["pass_count"] == 2
    assert verifier.animator.calls[1][1]          # the second render received the Critic's feedback
    assert doc["loop_trace"][0]["approved"] is False and doc["loop_trace"][1]["approved"] is True


def test_persistently_unfaithful_explainer_is_dropped(verifier, candidate, graph_source, family_profile):
    verifier.animator = FakeAnimator({"c_01": [["The indicator turns bright purple at pH 12."]]})
    doc = verifier.verify(candidate, graph_source=graph_source, profile=family_profile)
    assert doc["status"] == "approved" and doc["explainer_clips"] == []


def test_mid_sentence_cut_is_repaired_locally(verifier, candidate, graph_source, family_profile):
    cand = copy.deepcopy(candidate)
    cand["threads"][0]["end"] = 14.0
    doc = verifier.verify(cand, graph_source=graph_source, profile=family_profile)
    assert doc["status"] == "approved" and doc["final_threads"][0]["end"] == 15.4


def test_wrong_quiz_answer_is_dropped_not_shipped(verifier, candidate, graph_source, family_profile):
    cand = copy.deepcopy(candidate)
    cand["quiz"] = [{"question": "What does it form?", "concept_node_id": "c_01",
                     "options": ["rocket fuel and lava", "salt and water"], "answer_index": 0}]
    doc = verifier.verify(cand, graph_source=graph_source, profile=family_profile)
    assert doc["status"] == "approved" and doc["quiz"] == []


def test_budget_exhausted_falls_back_to_a_safe_baseline(verifier, candidate, graph_source, family_profile):
    cand = copy.deepcopy(candidate)
    cand["threads"] = []                           # nothing local can fix an empty cut
    doc = verifier.verify(cand, graph_source=graph_source, profile=family_profile)
    assert doc["status"] == "fallback" and doc["pass_count"] == verifier.cfg.loop_budget
    assert doc["final_threads"][0]["thread_id"] == "t_full" and doc["explainer_clips"] == [] and doc["quiz"] == []
    assert doc["critic_score"]["safety"] == 1.0 and doc["redaction_masks"]


def test_fallback_prefers_the_last_verified_cut(verifier, candidate, graph_source, family_profile):
    good = verifier.verify(candidate, graph_source=graph_source, profile=family_profile)
    cand = copy.deepcopy(candidate)
    cand["session_id"], cand["threads"] = "sess_next", []
    doc = verifier.verify(cand, graph_source=graph_source, profile=family_profile)
    assert doc["status"] == "fallback" and doc["session_id"] == "sess_next"
    assert doc["final_threads"] == good["final_threads"]


def test_reports_are_stored_for_the_delivery_client(verifier, candidate, graph_source, family_profile):
    verifier.verify(candidate, graph_source=graph_source, profile=family_profile)
    d = verifier.cfg.sessions_dir / "sess_88a1"
    assert (d / "verified-cut.json").exists() and (d / "report.json").exists()
