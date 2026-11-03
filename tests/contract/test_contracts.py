"""Contract tests for data contracts v2 (spec/05): golden fixtures validate, every validation rule rejects bad
input, views leak nothing they should not, and generated JSON Schema / TS types are up to date."""

from __future__ import annotations

import copy
import itertools
import json
from typing import Any

import pytest
from pydantic import ValidationError

from loom.core.contracts import EXPORTED
from loom.core.contracts.cuts import CandidateCut, VerifiedCut
from loom.core.contracts.events import Event
from loom.core.contracts.export import build_schemas
from loom.core.contracts.graph import ConceptGraph, mesh_view, player_view, safety_view
from loom.core.contracts.learner import LearnerProfile
from loom.core.contracts.session import QuizAnswerRequest
from tests.conftest import FIXTURES, load_fixture


@pytest.fixture
def graph_raw() -> dict[str, Any]:
    raw: dict[str, Any] = load_fixture("graph_demo_v2.json")
    return raw


def _unsealed(raw: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(raw)
    out["graph_sha"] = None
    return out


# ------------------------------------------------------------------------------------------------ fixtures


def test_golden_graph_is_valid_and_sealed(graph_raw: dict[str, Any]) -> None:
    g = ConceptGraph.model_validate(graph_raw)
    assert g.graph_sha == g.compute_sha()
    assert len(g.concept_nodes) == 6 and len(g.quiz_bank) == 18
    assert {(q.concept_node_id, q.level) for q in g.quiz_bank} == {
        (c.node_id, lvl) for c in g.concept_nodes for lvl in ("beginner", "intermediate", "expert")
    }  # >= 1 question per concept per level
    hazard = next(o for o in g.objects if o.label == "broken glass")
    assert hazard.is_hazard_class and hazard.safety.child_unsafe and "sharp_object" in hazard.safety.tags
    chain = {c.node_id: c.prerequisites for c in g.concept_nodes}
    assert chain["c_04"] == ["c_02", "c_03"] and chain["c_05"] == [
        "c_04"
    ]  # PPE -> dissociation -> neutral -> indicator


@pytest.mark.parametrize("name", ["learner_alex", "learner_priya", "learner_family"])
def test_learner_fixtures(name: str) -> None:
    p = LearnerProfile.model_validate(load_fixture(f"{name}.json"))
    assert p.learner_state_sha == p.compute_state_sha()


@pytest.mark.parametrize("name", ["alex", "priya", "family"])
def test_cut_fixtures_match_the_graph(name: str, graph_raw: dict[str, Any]) -> None:
    g = ConceptGraph.model_validate(graph_raw)
    cand = CandidateCut.model_validate(load_fixture(f"candidate_cut_{name}.json"))
    cut = VerifiedCut.model_validate(load_fixture(f"verified_cut_{name}.json"))
    assert cand.graph_sha == g.graph_sha and cut.video_id == g.video_id
    spans = sorted([(t.start, t.source_end) for t in cand.threads] + [(s.start, s.end) for s in cand.skipped])
    assert spans[0][0] == 0.0 and spans[-1][1] == pytest.approx(g.duration_seconds, abs=0.05)
    assert all(a[1] == pytest.approx(b[0]) for a, b in itertools.pairwise(spans))  # partition, no gaps
    assert "answer_index" not in json.dumps(load_fixture(f"verified_cut_{name}.json"))


def test_family_cut_masks_broken_glass_and_fallback_masks_everything(graph_raw: dict[str, Any]) -> None:
    g = ConceptGraph.model_validate(graph_raw)
    family = VerifiedCut.model_validate(load_fixture("verified_cut_family.json"))
    assert [m.label for m in family.redaction_masks] == ["broken glass"]
    fallback = VerifiedCut.model_validate(load_fixture("verified_cut_family_fallback.json"))
    assert fallback.status == "fallback" and fallback.fallback_reason
    assert {m.object_id for m in fallback.redaction_masks} == {o.object_id for o in g.objects}
    assert fallback.explainer_clips == [] and fallback.quiz == []  # no generated content in a fallback


# ------------------------------------------------------------------------------------------------ graph rules


def _mutate(raw: dict[str, Any], fn: Any) -> dict[str, Any]:
    out = _unsealed(raw)
    fn(out)
    return out


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda g: g["transcript"].append(dict(g["transcript"][0])), "duplicate sentence ids"),
        (lambda g: g["concept_nodes"][0]["evidence"]["segment_ids"].append("s_999"), "unknown sentence ids"),
        (lambda g: g["concept_nodes"][1]["evidence"].update(segment_ids=[], text_ids=[]), "must cite"),
        (lambda g: g["concept_nodes"][0]["prerequisites"].append("c_04"), "earlier concept"),
        (lambda g: g["concept_nodes"][0]["prerequisites"].append("c_00"), "unknown prerequisite"),
        (lambda g: g["transcript"][2].update(start=20.0, end=19.0), "must be < end"),
        (lambda g: g["transcript"][-1].update(end=999.0), "exceeds duration"),
        (lambda g: g["quiz_bank"][0].update(options=["a", "b", "a", "c"]), "distinct"),
        (lambda g: g["quiz_bank"][0].update(answer_index=4), "less than or equal to 3"),
        (lambda g: g["quiz_bank"][0].update(concept_node_id="c_09"), "unknown concept"),
        (lambda g: g["objects"][6]["safety"].update(status="unreviewed"), "unreviewed object cannot carry"),
        (
            lambda g: g["objects"][3]["instances"][1].update(
                shot_id=g["objects"][3]["instances"][0]["shot_id"],
                start=g["objects"][3]["instances"][0]["start"],
                end=g["objects"][3]["instances"][0]["end"],
                track=g["objects"][3]["instances"][0]["track"],
            ),
            "overlap",
        ),
        (lambda g: g["objects"][0]["instances"][0]["track"][0].update(bbox=[0.9, 0.1, 0.3, 0.1]), "outside"),
        (lambda g: g["objects"][0]["instances"][0]["track"][0].update(mask="png:abc"), "pattern"),
        (lambda g: g.update(colour="red"), "Extra inputs are not permitted"),
    ],
)
def test_graph_rules_reject(graph_raw: dict[str, Any], mutation: Any, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        ConceptGraph.model_validate(_mutate(graph_raw, mutation))


def test_tampered_graph_fails_sha(graph_raw: dict[str, Any]) -> None:
    bad = copy.deepcopy(graph_raw)
    bad["title"] = "Something else"
    with pytest.raises(ValidationError, match="graph_sha"):
        ConceptGraph.model_validate(bad)


def test_mask_rle_pattern_accepts_coco_strings(graph_raw: dict[str, Any]) -> None:
    ok = _mutate(graph_raw, lambda g: g["objects"][0]["instances"][0]["track"][0].update(mask="rle:720x1280:PPYo1"))
    ConceptGraph.model_validate(ok)


# ------------------------------------------------------------------------------------------------ views


def test_mesh_view_has_no_answers_and_no_tracks(graph_raw: dict[str, Any]) -> None:
    v = mesh_view(ConceptGraph.model_validate(graph_raw)).model_dump_json()
    assert "answer_index" not in v and "rationale" not in v.split('"quiz_bank"')[1]
    assert '"track"' not in v and '"words"' not in v and "verified_by" not in v


def test_player_view_has_boxes_but_no_masks_answers_or_safety(graph_raw: dict[str, Any]) -> None:
    v = player_view(ConceptGraph.model_validate(graph_raw))
    dumped = v.model_dump_json()
    assert v.objects[0].instances[0].track[0].bbox
    for leaked in ("mask", "answer_index", "quiz_bank", "child_unsafe", "severity"):
        assert leaked not in dumped


def test_safety_view_is_minimal(graph_raw: dict[str, Any]) -> None:
    v = safety_view(ConceptGraph.model_validate(graph_raw)).model_dump()
    assert set(v) == {"schema_version", "view", "video_id", "graph_sha", "duration_seconds", "objects"}


# ------------------------------------------------------------------------------------------------ cuts, learner, API


def test_verified_cut_cannot_carry_an_answer() -> None:
    raw = load_fixture("verified_cut_priya.json")
    raw["quiz"][0]["answer_index"] = 0
    with pytest.raises(ValidationError, match="answer_index"):
        VerifiedCut.model_validate(raw)


def test_fallback_needs_reason_and_approval_needs_a_pass() -> None:
    raw = load_fixture("verified_cut_family_fallback.json")
    raw["fallback_reason"] = None
    with pytest.raises(ValidationError, match="must say why"):
        VerifiedCut.model_validate(raw)
    ok = load_fixture("verified_cut_alex.json")
    ok["loop_trace"][-1]["approved"] = False
    with pytest.raises(ValidationError, match="approving final Critic pass"):
        VerifiedCut.model_validate(ok)


def test_candidate_thread_cannot_extend_past_source() -> None:
    raw = load_fixture("candidate_cut_alex.json")
    raw["threads"][0]["end"] = raw["threads"][0]["source_end"] + 5
    with pytest.raises(ValidationError, match="exceeds source_end"):
        CandidateCut.model_validate(raw)


def test_forged_correct_flag_is_rejected() -> None:
    QuizAnswerRequest.model_validate({"option_index": 2})
    with pytest.raises(ValidationError, match="correct"):
        QuizAnswerRequest.model_validate({"option_index": 2, "correct": True})


def test_learner_state_sha_rounds_mastery_to_005() -> None:
    base = load_fixture("learner_priya.json")
    a = LearnerProfile.model_validate(
        {
            **base,
            "mastery": [
                {"concept_key": "v_1/c_04", "level": 0.41, "last_seen": "2026-10-29T00:00:00Z", "evidence_count": 1}
            ],
        }
    )
    b = a.model_copy(update={"mastery": [a.mastery[0].model_copy(update={"level": 0.42})]})
    c = a.model_copy(update={"mastery": [a.mastery[0].model_copy(update={"level": 0.47})]})
    assert a.compute_state_sha() == b.compute_state_sha() != c.compute_state_sha()


def test_blocked_and_allowed_tags_disjoint() -> None:
    raw = load_fixture("learner_family.json")
    raw["safety_profile"]["allowed_tags"] = ["sharp_object"]
    with pytest.raises(ValidationError, match="both blocked and allowed"):
        LearnerProfile.model_validate(raw)


def test_event_payload_must_match_kind() -> None:
    ok = {
        "id": 1,
        "channel": "sess_abc",
        "ts": "2026-10-29T00:00:00Z",
        "kind": "delivered",
        "data": {"status": "approved", "pass_count": 1},
    }
    Event.model_validate(ok)
    with pytest.raises(ValidationError):
        Event.model_validate({**ok, "data": {"status": "maybe", "pass_count": 1}})


# ------------------------------------------------------------------------------------------------ export


def test_every_exported_schema_is_json_schema_with_version() -> None:
    schemas = build_schemas()
    assert len(schemas) == len(EXPORTED) + 1  # + bundle
    for name, text in schemas.items():
        s = json.loads(text)
        assert s["x-loom-schema-version"].startswith("2.")
        assert s["$id"].endswith(name)


def test_generated_files_are_up_to_date() -> None:
    from loom.core.config import PROJECT_ROOT

    on_disk = {p.name: p.read_text(encoding="utf-8") for p in (PROJECT_ROOT / "contracts").glob("*.schema.json")}
    assert on_disk == build_schemas(), "run `uv run loom contracts export`"


def test_fixture_dir_has_readme() -> None:
    assert (FIXTURES / "README.md").exists()
