"""`loom eval critic-faults` — fault injection against the Critic (spec/07 §4), on the current build.

For every lesson × built-in viewer, the clean state is what the verifier loop approves (the same Curator → Pedagogy →
Personalizer → Assessment → Guardian → Critic sequence as `session.run_session`, without the store or events). Each
approved state is a **control**: the Critic must raise nothing. Then single faults are planted into a copy of it and
`mesh.critic_score` must report the expected issue code (**detection**); the loop's own repair (force-mask / revise)
is then applied and the state re-scored (**repair**: the issue is gone within the loop budget).

Pure Python: no models, no GPU, deterministic.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable
from typing import Any

from loom.agents import mesh
from loom.agents.session import FIXTURES, load_graph
from loom.core.config import LoomConfig
from loom.core.contracts.cuts import CandidateCut, ExplainerClip, QuizRef
from loom.core.contracts.graph import ConceptGraph
from loom.core.contracts.issues import ISSUE_ROUTES, CriticIssue
from loom.core.contracts.learner import LearnerProfile
from loom.eval.common import machine_info

LESSONS = (
    "acid_base_neutralization_d752a6",
    "water_sciences_laboratory_tutorial_glass_a98109",
    "sql_explained_in_100_seconds_4462e4",
)
VIEWERS = ("alex", "priya", "family")


def _profile(name: str) -> LearnerProfile:
    p = LearnerProfile.model_validate_json((FIXTURES / f"learner_{name}.json").read_text(encoding="utf-8"))
    return p.model_copy(update={"mastery": []})


def _clip(cid: str) -> ExplainerClip:
    return ExplainerClip(
        concept_node_id=cid,
        trigger="auto",
        anchor_seconds=0.0,
        clip_url=f"/media/x/{cid}.json",
        content_hash="sha256:" + "0" * 64,
        title=cid,
        duration_seconds=5.0,
        storyboard=["x"],
        verified_by="judge",
    )


class State:
    def __init__(
        self,
        graph: ConceptGraph,
        profile: LearnerProfile,
        cut: CandidateCut,
        masks: list[Any],
        clips: dict[str, ExplainerClip],
        threads: list[mesh.Thread],
    ) -> None:
        self.graph, self.profile, self.cut, self.masks, self.clips, self.threads = (
            graph,
            profile,
            cut,
            masks,
            clips,
            threads,
        )

    def score(self, cfg: LoomConfig) -> list[CriticIssue]:
        return mesh.critic_score(self.cut, self.graph, self.profile, self.masks, self.clips, cfg)[1]

    def copy(self, **kw: Any) -> State:
        d = {
            "graph": self.graph,
            "profile": self.profile,
            "cut": self.cut,
            "masks": list(self.masks),
            "clips": dict(self.clips),
            "threads": self.threads,
        }
        d.update(kw)
        return State(**d)


def _noop(_rel: str, _payload: Any) -> None:
    return None


def approved_state(cfg: LoomConfig, graph: ConceptGraph, profile: LearnerProfile) -> tuple[State, int]:
    """What the loop approves for this viewer (clips stand in for verified explainers). Returns (state, passes)."""
    threads = mesh.plan_threads(mesh.build_threads(graph), graph, profile, cfg)
    cut = mesh.assemble_cut(threads, graph, profile, cfg, "sess_faults")
    cut = cut.model_copy(update={"quiz": mesh.select_quiz(cut, graph, profile, cfg.assessment.max_questions, set())})
    clips = {e.concept_node_id: _clip(e.concept_node_id) for e in cut.explainer_requests if e.trigger == "auto"}
    forced: dict[str, tuple[str, str]] = {}
    for n in range(1, cfg.loop.budget + 1):
        masks = mesh.build_masks(
            graph, cut, {**mesh.redaction_decisions(graph, profile, cut, cfg), **forced}, cfg, _noop
        )
        st = State(graph, profile, cut, masks, clips, threads)
        issues = st.score(cfg)
        if not issues:
            return st, n
        st, forced = repair(cfg, st, issues, forced)
        cut = st.cut
    return st, cfg.loop.budget + 1


def repair(
    cfg: LoomConfig, st: State, issues: list[CriticIssue], forced: dict[str, tuple[str, str]]
) -> tuple[State, dict[str, tuple[str, str]]]:
    """The loop's action for each issue (session.run_session): force a mask, or send mesh issues to revise_cut."""
    forced = dict(forced)
    mesh_issues = []
    for i in issues:
        if i.code == "unmasked_hazard" and i.object_id:
            forced[i.object_id] = ("critic: unmasked hazard", "critic")
        elif i.code != "quiz_missing" and ISSUE_ROUTES.get(i.code, "mesh") == "mesh":
            mesh_issues.append(i)
    cut = mesh.revise_cut(st.cut, st.threads, st.graph, mesh_issues) if mesh_issues else st.cut
    masks = mesh.build_masks(
        st.graph, cut, {**mesh.redaction_decisions(st.graph, st.profile, cut, cfg), **forced}, cfg, _noop
    )
    return st.copy(cut=cut, masks=masks), forced


# ---------------------------------------------------------------- faults: (family, name, expected code, inject)

Fault = tuple[str, str, str, Callable[[State], State | None]]


def _threads(st: State, threads: list[Any]) -> State:
    return st.copy(cut=st.cut.model_copy(update={"threads": threads}))


def f_overlap(st: State) -> State | None:
    th = st.cut.threads
    if len(th) < 2:
        return None
    t = list(th)
    t[1] = t[1].model_copy(update={"start": max(t[0].start, t[0].end - 2.0)})
    return _threads(st, t)


def f_out_of_order(st: State) -> State | None:
    th = st.cut.threads
    return _threads(st, [th[1], th[0], *th[2:]]) if len(th) >= 2 else None


def f_empty(st: State) -> State | None:
    return _threads(st, [])


def f_mid_sentence(which: float) -> Callable[[State], State | None]:
    def inject(st: State) -> State | None:
        for k, t in enumerate(st.cut.threads):
            inside = [s for s in st.graph.transcript if t.start < s.start and s.end <= t.end and s.end - s.start > 1.5]
            if inside:
                s = inside[min(len(inside) - 1, int(which * len(inside)))]
                th = list(st.cut.threads)
                th[k] = t.model_copy(update={"end": round(s.start + (s.end - s.start) * 0.5, 2)})
                return _threads(st, th)
        return None

    return inject


def f_quiz_unsupported(st: State) -> State | None:
    if not st.graph.quiz_bank or not st.graph.concept_nodes:
        return None
    bad = QuizRef(question_id="q_999")
    return st.copy(cut=st.cut.model_copy(update={"quiz": [*st.cut.quiz, bad]}))


def f_quiz_missing(st: State) -> State | None:
    in_cut = {c for t in st.cut.threads for c in t.concept_node_ids}
    if not st.cut.quiz or not (in_cut & {q.concept_node_id for q in st.graph.quiz_bank}):
        return None
    return st.copy(cut=st.cut.model_copy(update={"quiz": []}))


PREREQ_MASTERY = 0.6  # set from the config in run_critic_faults


def f_missing_prereq(st: State) -> State | None:
    """Drop the thread that teaches a prerequisite of a kept concept (the viewer is below mastery on it)."""
    kept = {c for t in st.cut.threads for c in t.concept_node_ids}
    table = mesh.mastery_table(st.profile, st.graph.video_id)
    for c in st.graph.concept_nodes:
        for p in c.prerequisites:
            known = table.get(p, st.profile.preferences.prior_knowledge) >= PREREQ_MASTERY
            if c.node_id in kept and p in kept and not known:  # a viewer who already knows it may skip it
                th = [t for t in st.cut.threads if p not in t.concept_node_ids or c.node_id in t.concept_node_ids]
                if len(th) < len(st.cut.threads):
                    return _threads(st, th)
    return None


def f_no_masks(st: State) -> State | None:
    return st.copy(masks=[]) if st.masks else None


def f_mask_early(st: State) -> State | None:
    if not st.masks:
        return None
    return st.copy(masks=[m.model_copy(update={"end": max(m.start, m.end - 1.0)}) for m in st.masks])


def f_mask_wrong_object(st: State) -> State | None:
    if not st.masks:
        return None
    others = [o.object_id for o in st.graph.objects if o.object_id not in {m.object_id for m in st.masks}]
    if not others:
        return None
    return st.copy(masks=[m.model_copy(update={"object_id": others[0]}) for m in st.masks])


def f_explainer_unavailable(st: State) -> State | None:
    return st.copy(clips={}) if st.clips else None


FAULTS: list[Fault] = [
    ("F1 structure", "overlapping threads", "overlapping_threads", f_overlap),
    ("F1 structure", "out-of-order threads", "overlapping_threads", f_out_of_order),
    ("F1 structure", "empty cut", "empty_cut", f_empty),
    ("F2 sentence", "ends mid-sentence (early)", "cut_mid_sentence", f_mid_sentence(0.0)),
    ("F2 sentence", "ends mid-sentence (middle)", "cut_mid_sentence", f_mid_sentence(0.5)),
    ("F2 sentence", "ends mid-sentence (late)", "cut_mid_sentence", f_mid_sentence(0.99)),
    ("F3 factuality", "quiz question not in the verified bank", "quiz_unsupported", f_quiz_unsupported),
    ("F4 prerequisite", "prerequisite thread dropped", "missing_prerequisite", f_missing_prereq),
    ("F5 safety", "Guardian returns no masks", "unmasked_hazard", f_no_masks),
    ("F5 safety", "masks end 1 s early", "unmasked_hazard", f_mask_early),
    ("F5 safety", "mask on the wrong object", "unmasked_hazard", f_mask_wrong_object),
    ("F6 explainer", "verified explainer missing", "explainer_unavailable", f_explainer_unavailable),
    ("F8 completeness", "empty quiz with a non-empty bank", "quiz_missing", f_quiz_missing),
]


def run_critic_faults(cfg: LoomConfig) -> dict[str, Any]:
    global PREREQ_MASTERY
    PREREQ_MASTERY = cfg.pedagogy.prereq_mastery
    t0 = time.perf_counter()
    controls, faults, skipped = [], [], []
    for vid in LESSONS:
        graph = load_graph(cfg.data_dir, vid)
        for name in VIEWERS:
            profile = _profile(name)
            st, passes = approved_state(cfg, graph, profile)
            issues = st.score(cfg)
            controls.append(
                {
                    "lesson": vid,
                    "viewer": name,
                    "passes_to_approval": passes,
                    "approved": not issues,
                    "issues": [i.code for i in issues],
                    "masks": len(st.masks),
                    "threads": len(st.cut.threads),
                    "quiz": len(st.cut.quiz),
                }
            )
            if issues:
                continue
            for family, fname, code, inject in FAULTS:
                bad = inject(st)
                if bad is None:
                    skipped.append(
                        {"lesson": vid, "viewer": name, "fault": fname, "why": "not applicable to this state"}
                    )
                    continue
                found = bad.score(cfg)
                codes = [i.code for i in found]
                fixed, forced, rounds = bad, {}, 0
                while rounds < cfg.loop.budget - 1:
                    left = fixed.score(cfg)
                    if not left:
                        break
                    fixed, forced = repair(cfg, fixed, left, forced)
                    rounds += 1
                left = [i.code for i in fixed.score(cfg)]
                faults.append(
                    {
                        "lesson": vid,
                        "viewer": name,
                        "family": family,
                        "fault": fname,
                        "expected": code,
                        "detected": code in codes,
                        "codes": codes,
                        "repaired": code not in left,
                        "repair_rounds": rounds,
                        "left_after_repair": left,
                        # what the viewer gets: the repaired cut, or (budget spent) session.fallback: the full
                        # lesson, no generated content, every object masked for redaction-on viewers
                        "delivered": "repaired cut" if not left else "fallback",
                    }
                )
    fam: dict[str, dict[str, int]] = {}
    for f in faults:
        d = fam.setdefault(f["family"], {"injected": 0, "detected": 0, "repaired": 0})
        d["injected"] += 1
        d["detected"] += f["detected"]
        d["repaired"] += f["repaired"]
    ok_controls = [c for c in controls if c["approved"]]
    return {
        "suite": "critic_faults",
        "machine": machine_info(),
        "lessons": list(LESSONS),
        "viewers": list(VIEWERS),
        "controls": controls,
        "faults": faults,
        "not_applicable": skipped,
        "summary": {
            "controls": len(controls),
            "controls_approved": len(ok_controls),
            "false_rejections": len(controls) - len(ok_controls),
            "faults_injected": len(faults),
            "detected": sum(f["detected"] for f in faults),
            "detection_rate": round(sum(f["detected"] for f in faults) / max(1, len(faults)), 3),
            "repaired": sum(f["repaired"] for f in faults),
            "repair_rate": round(sum(f["repaired"] for f in faults) / max(1, len(faults)), 3),
            "per_family": fam,
            "delivered_with_fault": 0,  # by construction: an unapproved state is never delivered (fallback instead)
            "fallbacks": sum(1 for f in faults if f["delivered"] == "fallback"),
            "codes_seen": dict(Counter(c for f in faults for c in f["codes"])),
        },
        "targets": {"detection_rate": 1.0, "min_faults": 20, "false_rejections": 0, "min_controls": 8},
        "seconds": round(time.perf_counter() - t0, 2),
    }


def main() -> None:
    from loom.core.config import load_config

    cfg = load_config()
    body = run_critic_faults(cfg)
    out = cfg.data_dir / "eval" / "critic_faults.json"
    out.write_text(json.dumps(body, indent=1), encoding="utf-8")
    print(json.dumps(body["summary"], indent=1))
    for c in body["controls"]:
        print(
            "control",
            c["lesson"][:24],
            c["viewer"],
            "approved" if c["approved"] else c["issues"],
            "passes",
            c["passes_to_approval"],
        )
    for f in body["faults"]:
        if not f["detected"] or not f["repaired"]:
            print(
                "MISS" if not f["detected"] else "UNREPAIRED",
                f["lesson"][:24],
                f["viewer"],
                f["fault"],
                f["codes"],
                f["left_after_repair"],
            )


if __name__ == "__main__":
    main()
