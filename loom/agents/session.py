"""Session runner: orchestrates the mesh for one (video, learner) and runs the bounded verification loop.

Events on channel `sess_<id>`: session_start, agent_call/agent_done per skill, candidate_ready, loop_phase
(perceive/plan/verify/act), delivered. The verified cut is stored as JSON under `<data>/sessions/<id>.json`.
"""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loom.agents import mesh
from loom.core.contracts.cuts import CandidateCut, CriticScore, ExplainerClip, LoopPass, VerifiedCut
from loom.core.contracts.graph import ConceptGraph
from loom.core.contracts.issues import ISSUE_ROUTES, CriticIssue, LoopAction
from loom.core.contracts.learner import LearnerProfile, MasteryEntry, Preferences, SafetyProfile
from loom.core.store import Store, iso_now, utcnow

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


# ---------------------------------------------------------------- persistence


def graphs_dir(data: Path) -> Path:
    d = data / "graphs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_graphs(data: Path) -> list[ConceptGraph]:
    out = []
    for p in sorted(graphs_dir(data).glob("*.json")):
        out.append(ConceptGraph.model_validate_json(p.read_text(encoding="utf-8")))
    return out


def load_graph(data: Path, video_id: str) -> ConceptGraph:
    p = graphs_dir(data) / f"{video_id}.json"
    if not p.exists():
        raise FileNotFoundError(video_id)
    return ConceptGraph.model_validate_json(p.read_text(encoding="utf-8"))


def save_graph(data: Path, graph: ConceptGraph) -> Path:
    p = graphs_dir(data) / f"{graph.video_id}.json"
    p.write_text(graph.sealed().model_dump_json(indent=1), encoding="utf-8")
    return p


def seed(store: Store, data: Path) -> None:
    """First start: the three personas and (if no graph exists yet) the hand-checked demo graph."""
    if not store.query_one("SELECT id FROM learners LIMIT 1"):
        for name in ("alex", "priya", "family"):
            prof = LearnerProfile.model_validate_json((FIXTURES / f"learner_{name}.json").read_text(encoding="utf-8"))
            save_learner(store, prof.model_copy(update={"mastery": []}))
    if not any(graphs_dir(data).glob("*.json")) and (FIXTURES / "graph_demo_v2.json").exists():
        g = ConceptGraph.model_validate_json((FIXTURES / "graph_demo_v2.json").read_text(encoding="utf-8"))
        save_graph(data, g)


def save_learner(store: Store, p: LearnerProfile) -> None:
    with store.tx() as c:
        c.execute(
            "INSERT INTO learners (id, display_name, persona, preferences, safety_profile, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name, "
            "persona=excluded.persona, preferences=excluded.preferences, safety_profile=excluded.safety_profile",
            (
                p.learner_id,
                p.display_name,
                p.persona,
                p.preferences.model_dump_json(),
                p.safety_profile.model_dump_json(),
                iso_now(),
            ),
        )
        c.execute("DELETE FROM mastery WHERE learner_id = ?", (p.learner_id,))
        for m in p.mastery:
            c.execute(
                "INSERT INTO mastery (learner_id, concept_key, level, last_seen, evidence_count) VALUES (?,?,?,?,?)",
                (p.learner_id, m.concept_key, m.level, m.last_seen.isoformat(), m.evidence_count),
            )


def load_learner(store: Store, learner_id: str) -> LearnerProfile:
    r = store.query_one("SELECT * FROM learners WHERE id = ?", (learner_id,))
    if r is None:
        raise KeyError(learner_id)
    mastery = [
        MasteryEntry(
            concept_key=m["concept_key"], level=m["level"], last_seen=m["last_seen"], evidence_count=m["evidence_count"]
        )
        for m in store.query("SELECT * FROM mastery WHERE learner_id = ? ORDER BY concept_key", (learner_id,))
    ]
    return LearnerProfile(
        learner_id=r["id"],
        display_name=r["display_name"],
        persona=r["persona"],
        preferences=Preferences.model_validate_json(r["preferences"]),
        safety_profile=SafetyProfile.model_validate_json(r["safety_profile"]),
        mastery=mastery,
    ).with_state_sha()


def list_learners(store: Store) -> list[LearnerProfile]:
    return [load_learner(store, r["id"]) for r in store.query("SELECT id FROM learners ORDER BY created_at, id")]


def sessions_dir(data: Path) -> Path:
    d = data / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_session_id() -> str:
    return f"sess_{secrets.token_hex(4)}"


# ---------------------------------------------------------------- explainers available for a cut


def verified_clips(store: Store, graph: ConceptGraph) -> dict[str, dict[str, ExplainerClip]]:
    """concept_id -> level -> latest verified clip (from the Animator's `explainers` table)."""
    out: dict[str, dict[str, ExplainerClip]] = {}
    sha = graph.graph_sha or graph.compute_sha()
    labels = {c.node_id: c.label for c in graph.concept_nodes}
    rows = store.query(
        "SELECT * FROM explainers WHERE verified = 1 AND concept_key LIKE ? ORDER BY created_at",
        (f"{graph.video_id}/%",),
    )
    for r in rows:
        cid = r["concept_key"].split("/", 1)[1]
        if not cid.startswith("c_"):
            continue
        meta = json.loads(r["storyboard"])
        out.setdefault(cid, {})[r["level"]] = ExplainerClip(
            concept_node_id=cid,
            trigger="auto",
            anchor_seconds=0.0,
            clip_url=r["clip_ref"],
            content_hash=r["content_hash"],
            title=labels.get(cid, cid),
            duration_seconds=float(meta.get("duration", 15.0)),
            storyboard=meta["lines"],
            verified_by=r["judge_model"] or "judge",
        )
    del sha
    return out


def clips_for_cut(cut: CandidateCut, available: dict[str, dict[str, ExplainerClip]]) -> dict[str, ExplainerClip]:
    out = {}
    for e in cut.explainer_requests:
        if e.trigger != "auto" or e.concept_node_id not in available:
            continue
        levels = available[e.concept_node_id]
        clip = levels.get(e.level) or next(iter(levels.values()))
        out[e.concept_node_id] = clip.model_copy(update={"anchor_seconds": e.anchor_time})
    return out


# ---------------------------------------------------------------- the run


Publish = Callable[[str, dict[str, Any]], None]


def run_session(
    cfg: Any, store: Store, data: Path, video_id: str, learner_id: str, session_id: str, publish: Publish
) -> VerifiedCut:
    graph = load_graph(data, video_id)
    profile = load_learner(store, learner_id)
    store.execute(
        "INSERT OR REPLACE INTO sessions (id, video_id, learner_id, status, created_at) VALUES (?,?,?,?,?)",
        (session_id, video_id, learner_id, "running", iso_now()),
    )
    publish("session_start", {"video_id": video_id, "learner_id": learner_id, "cache_hit": False})

    def call(agent: str, skill: str, fn: Callable[[], Any]) -> Any:
        publish("agent_call", {"agent": agent, "skill": skill, "status": "started"})
        t0 = time.perf_counter()
        out = fn()
        publish(
            "agent_done",
            {"agent": agent, "skill": skill, "status": "ok", "latency_ms": int((time.perf_counter() - t0) * 1000)},
        )
        return out

    def note(agent: str, text: str, kind: str = "thinking", items: list[str] | None = None) -> None:
        publish("agent_note", {"agent": agent, "text": text[:400], "kind": kind,
                               "items": [i[:240] for i in (items or [])][:12]})

    name = profile.display_name
    note("loom-curator", f"Reading {len(graph.transcript)} sentences, {len(graph.concept_nodes)} concepts and "
                         f"{len(graph.objects)} tracked objects to cut the lesson into self-contained threads.")
    threads = call("loom-curator", "build_threads", lambda: mesh.build_threads(graph))
    note("loom-curator", f"Cut the lesson into {len(threads)} threads at sentence boundaries.", "output",
         [f"{t.thread_id} {t.role}, {t.start:.0f}-{t.end:.0f}s: {t.text[:90]}" for t in threads])
    note("loom-pedagogy", f"Comparing each thread with what {name} already knows "
                          f"(prior knowledge {profile.preferences.prior_knowledge:.2f}, pace {profile.preferences.pace}).")
    threads = call("loom-pedagogy", "plan_threads", lambda: mesh.plan_threads(threads, graph, profile, cfg))
    note("loom-pedagogy", f"Decided how {name} should see each thread.", "output",
         [f"{t.thread_id} {t.action}: {t.rationale}" for t in threads])
    note("loom-personalizer", "Assembling the cut: shortening refreshers on sentence boundaries, placing explainers, "
                              "listing objects to review for safety.")
    cut: CandidateCut = call(
        "loom-personalizer", "assemble_cut", lambda: mesh.assemble_cut(threads, graph, profile, cfg, session_id)
    )
    kept_s = sum(t.end - t.start for t in cut.threads)
    note("loom-personalizer", f"The cut keeps {kept_s:.0f}s of {graph.duration_seconds:.0f}s.", "output",
         [f"{len([e for e in cut.explainer_requests if e.trigger == 'auto'])} explainers placed",
          f"{len(cut.redaction_requests)} objects sent to the Guardian", f"{len(cut.skipped)} threads skipped"])
    note("loom-assessment", "Picking verified questions on the concepts this viewer knows least.")
    recent = {
        r["question_id"]
        for r in store.query(
            "SELECT q.question_id FROM quiz_attempts q JOIN sessions s ON s.id = q.session_id WHERE s.learner_id = ?",
            (learner_id,),
        )
    }
    quiz = call(
        "loom-assessment",
        "select_quiz",
        lambda: mesh.select_quiz(cut, graph, profile, cfg.assessment.max_questions, recent),
    )
    cut = cut.model_copy(update={"quiz": quiz})
    stems = {q.question_id: q.stem for q in graph.quiz_bank}
    note("loom-assessment", f"Chose {len(quiz)} questions.", "output", [stems.get(q.question_id, q.question_id) for q in quiz])
    publish(
        "candidate_ready",
        {
            "pass_number": 1,
            "threads": len(cut.threads),
            "explainer_requests": len(cut.explainer_requests),
            "redaction_requests": len(cut.redaction_requests),
        },
    )

    available = verified_clips(store, graph)
    masks_root = data / "media"

    def write(rel: str, payload: dict[str, Any]) -> None:
        p = masks_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload), encoding="utf-8")

    passes: list[LoopPass] = []
    forced: dict[str, tuple[str, str]] = {}
    score = CriticScore(safety=0, coherence=0, factuality=0, completeness=0)
    masks: list[Any] = []
    clips: dict[str, ExplainerClip] = {}
    for pass_no in range(1, cfg.loop.budget + 1):
        t0 = time.perf_counter()
        publish("loop_phase", {"phase": "perceive", "pass_number": pass_no})
        decisions = call(
            "loom-guardian", "review_objects", lambda: {**mesh.redaction_decisions(graph, profile, cut, cfg), **forced}
        )
        masks = mesh.build_masks(graph, cut, decisions, cfg, write)
        labels = {o.object_id: o.label for o in graph.objects}
        note("loom-guardian", f"Reviewed {len(graph.objects)} objects for {name}." if decisions else
             f"Nothing needs masking for {name}.", "output",
             [f"mask {labels.get(o, o)}: {why[0]}" for o, why in decisions.items()])
        clips = call("loom-animator", "render_explainer", lambda: clips_for_cut(cut, available))
        publish("loop_phase", {"phase": "plan", "pass_number": pass_no})
        score, issues = call(
            "loom-critic", "score_cut", lambda: mesh.critic_score(cut, graph, profile, masks, clips, cfg)
        )
        approved = not issues
        note("loom-critic", ("Approved. " if approved else "Sending it back. ") +
             f"Safety {score.safety:.2f}, coherence {score.coherence:.2f}, facts {score.factuality:.2f}, "
             f"completeness {score.completeness:.2f}.", "output", [f"{i.code}: {i.detail}" for i in issues])
        publish(
            "loop_phase",
            {
                "phase": "verify",
                "pass_number": pass_no,
                "scores": score.model_dump(),
                "issues": [i.model_dump(mode="json") for i in issues],
            },
        )
        actions: list[LoopAction] = []
        if not approved and pass_no < cfg.loop.budget:
            mesh_issues: list[CriticIssue] = []
            for i in issues:
                route = ISSUE_ROUTES.get(i.code, "mesh")
                if i.code == "unmasked_hazard" and i.object_id:
                    forced[i.object_id] = ("critic: unmasked hazard", "critic")
                    actions.append(LoopAction(issue_code=i.code, action="force_mask", target=i.object_id))
                elif i.code == "quiz_missing":
                    actions.append(LoopAction(issue_code=i.code, action="reselect_quiz", result="skipped"))
                elif route == "mesh":
                    mesh_issues.append(i)
                    actions.append(
                        LoopAction(issue_code=i.code, action="revise_cut", target=i.thread_id or i.concept_node_id)
                    )
            publish(
                "loop_phase",
                {"phase": "act", "pass_number": pass_no, "actions": [a.model_dump(mode="json") for a in actions]},
            )
            if mesh_issues:
                cut = call("loom-orchestrator", "revise_cut", lambda: mesh.revise_cut(cut, threads, graph, mesh_issues))
        passes.append(
            LoopPass(
                pass_number=pass_no,
                approved=approved,
                scores=score,
                issues=issues,
                actions=actions,
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )
        )
        if approved:
            break
    if passes and passes[-1].approved:
        verified = mesh.to_verified(cut, graph, masks, clips, passes, "approved", score)
    else:
        verified = fallback(cfg, graph, profile, cut, passes, write)
    store.execute(
        "UPDATE sessions SET status = ?, pass_count = ?, verified_cut_ref = ? WHERE id = ?",
        (verified.status, verified.pass_count, f"sessions/{session_id}.json", session_id),
    )
    (sessions_dir(data) / f"{session_id}.json").write_text(verified.model_dump_json(indent=1), encoding="utf-8")
    publish("delivered", {"status": verified.status, "pass_count": verified.pass_count})
    return verified


def fallback(
    cfg: Any,
    graph: ConceptGraph,
    profile: LearnerProfile,
    cut: CandidateCut,
    passes: list[LoopPass],
    write: Callable[[str, dict[str, Any]], None],
) -> VerifiedCut:
    """Budget spent: the whole lesson, every object masked for redaction-on viewers, no generated content."""
    full = [t for t in mesh.build_threads(graph)]
    for t in full:
        t.action, t.rationale = "keep", "fallback: the full lesson"
    base = mesh.assemble_cut(full, graph, profile, cfg, cut.session_id).model_copy(
        update={"explainer_requests": [], "quiz": []}
    )
    decisions = (
        {o.object_id: ("fallback: every object masked", "guardian") for o in graph.objects}
        if profile.safety_profile.redaction_level != "off"
        else {}
    )
    masks = mesh.build_masks(graph, base, decisions, cfg, write)
    score = passes[-1].scores if passes else CriticScore(safety=0, coherence=0, factuality=0, completeness=0)
    return mesh.to_verified(
        base, graph, masks, {}, passes, "fallback", score, reason="the Critic did not approve within the loop budget"
    )


# ---------------------------------------------------------------- quiz + mastery


def grade(store: Store, data: Path, session_id: str, question_id: str, option_index: int) -> dict[str, Any]:
    row = store.query_one("SELECT video_id FROM sessions WHERE id = ?", (session_id,))
    if row is None:
        raise KeyError(session_id)
    graph = load_graph(data, row["video_id"])
    q = next(q for q in graph.quiz_bank if q.question_id == question_id)
    order = mesh.option_order(session_id, question_id)
    correct_shown = order.index(q.answer_index)
    correct = option_index == correct_shown
    store.execute(
        "INSERT INTO quiz_attempts (session_id, question_id, option_index, correct, ts) VALUES (?,?,?,?,?)",
        (session_id, question_id, option_index, int(correct), iso_now()),
    )
    sent = {s.seg_id: s for s in graph.transcript}
    ev = [sent[s] for s in q.evidence_segment_ids if s in sent]
    return {
        "correct": correct,
        "correct_index": correct_shown,
        "rationale": q.rationale,
        "evidence": [{"seg_id": s.seg_id, "start": s.start, "text": s.text} for s in ev],
    }


def finish(cfg: Any, store: Store, data: Path, session_id: str, watched: list[str]) -> dict[str, Any]:
    row = store.query_one("SELECT video_id, learner_id FROM sessions WHERE id = ?", (session_id,))
    if row is None:
        raise KeyError(session_id)
    graph = load_graph(data, row["video_id"])
    profile = load_learner(store, row["learner_id"])
    table = mesh.mastery_table(profile, graph.video_id)
    bank = {q.question_id: q for q in graph.quiz_bank}
    events: list[tuple[str, str, bool]] = []
    for r in store.query(
        "SELECT question_id, correct FROM quiz_attempts WHERE session_id = ? ORDER BY ts", (session_id,)
    ):
        if r["question_id"] in bank:
            events.append(("quiz", bank[r["question_id"]].concept_node_id, bool(r["correct"])))
    for cid in watched:
        events.append(("explainer", cid, True))
    concepts = {cid for _, cid, _ in events}
    levels = {c: table.get(c, profile.preferences.prior_knowledge) for c in concepts}
    updates = mesh.update_mastery(levels, events, cfg)
    now = utcnow()
    keep = {m.concept_key: m for m in profile.mastery}
    for cid, (_, after, _) in updates.items():
        key = f"{graph.video_id}/{cid}"
        prev = keep.get(key)
        keep[key] = MasteryEntry(
            concept_key=key, level=after, last_seen=now, evidence_count=(prev.evidence_count if prev else 0) + 1
        )
    save_learner(store, profile.model_copy(update={"mastery": list(keep.values())}))
    store.execute("UPDATE sessions SET finished_at = ? WHERE id = ?", (iso_now(), session_id))
    labels = {c.node_id: c.label for c in graph.concept_nodes}
    return {
        "mastery_updates": [
            {"concept_key": f"{graph.video_id}/{c}", "label": labels.get(c, c), "before": b, "after": a, "cause": why}
            for c, (b, a, why) in updates.items()
        ]
    }
