from __future__ import annotations

import tempfile
from pathlib import Path

from loom.agents import mesh
from loom.agents import session as S
from loom.core.config import load_config
from loom.core.contracts.graph import ConceptGraph, SafetyRecord
from loom.core.contracts.learner import LearnerProfile
from loom.core.store import Store

FIX = Path(__file__).resolve().parents[1] / "fixtures"
CFG = load_config()


def _graph() -> ConceptGraph:
    return ConceptGraph.model_validate_json((FIX / "graph_demo_v2.json").read_text(encoding="utf-8"))


def _learner(name: str) -> LearnerProfile:
    p = LearnerProfile.model_validate_json((FIX / f"learner_{name}.json").read_text(encoding="utf-8"))
    return p.model_copy(update={"mastery": []}).with_state_sha()


def _cut(name: str) -> mesh.CandidateCut:
    g, p = _graph(), _learner(name)
    threads = mesh.plan_threads(mesh.build_threads(g), g, p, CFG)
    return mesh.assemble_cut(threads, g, p, CFG, "sess_test1")


def test_threads_partition_the_timeline_at_sentence_boundaries() -> None:
    g = _graph()
    th = mesh.build_threads(g)
    assert th[0].start == 0.0 and th[-1].end == g.duration_seconds
    assert all(a.end == b.start for a, b in zip(th, th[1:], strict=False))


def test_expert_never_skips_core_or_safety() -> None:
    g, p = _graph(), _learner("alex")
    for t in mesh.plan_threads(mesh.build_threads(g), g, p, CFG):
        if t.role in ("core", "safety"):
            assert t.action != "skip", t


def test_critic_finds_hazard_guardian_did_not_mask() -> None:
    g, p = _graph(), _learner("family")
    cut = _cut("family")
    score, issues = mesh.critic_score(cut, g, p, masks=[], clips={}, cfg=CFG)  # Guardian produced nothing
    assert score.safety < 1.0
    assert any(i.code == "unmasked_hazard" for i in issues)


def test_unreviewed_objects_are_masked_for_redaction_on_viewers_only() -> None:
    g = _graph()
    g = g.model_copy(update={"objects": [o.model_copy(update={"safety": SafetyRecord(status="unreviewed")})
                                         for o in g.objects]})
    fam, alex = _learner("family"), _learner("alex")
    assert len(mesh.redaction_decisions(g, fam, _cut("family"), CFG)) == len(g.objects)
    assert mesh.redaction_decisions(g, alex, _cut("alex"), CFG) == {}


def test_quiz_options_are_shuffled_and_graded_server_side() -> None:
    orders = {tuple(mesh.option_order(f"sess_{i}", "q_c01_b_1")) for i in range(20)}
    assert len(orders) > 1  # the correct option is not always first
    with tempfile.TemporaryDirectory() as d:
        data = Path(d)
        st = Store(data / "t.db")
        st.migrate()
        S.seed(st, data)
        g = S.list_graphs(data)[0]
        cut = S.run_session(CFG, st, data, g.video_id, "learner_priya", "sess_grade1", lambda k, v: None)
        q = cut.quiz[0]
        bank = next(b for b in g.quiz_bank if b.question_id == q.question_id)
        right = q.options.index(bank.options[bank.answer_index])
        assert S.grade(st, data, "sess_grade1", q.question_id, right)["correct"] is True
        assert S.grade(st, data, "sess_grade1", q.question_id, (right + 1) % 4)["correct"] is False
        st.close()


def test_mastery_update_rule() -> None:
    out = mesh.update_mastery({"c_01": 0.4}, [("quiz", "c_01", True)], CFG)
    assert out["c_01"][1] == round(0.4 + 0.35 * 0.6, 3)
    out = mesh.update_mastery({"c_01": 0.4}, [("quiz", "c_01", False)], CFG)
    assert out["c_01"][1] == 0.3


def test_condensed_end_never_exceeds_unrounded_source_end() -> None:
    g = _graph()
    t = mesh.build_threads(g)[-1]
    t.end = 68.733
    t.sentence_ends = [60.0, 68.734]
    assert mesh.condensed_end(t, g, CFG) <= t.end
