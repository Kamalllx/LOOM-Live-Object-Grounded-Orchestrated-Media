"""Agent mesh + verification loop (spec/04 B, C): Curator, Pedagogy, Personalizer, Assessment, Guardian, Critic,
Verifier. All agents are deterministic over the ingest-time concept graph (spec/02 §1: model work happens at ingest),
so a session is fast and auditable. Each agent is a plain function; `loom.agents.a2a_mount` exposes them as A2A
skills, and the session runner publishes `agent_call`/`agent_done` events for the live loop panel.

Fail-closed rules: an object whose safety review is not `reviewed` is masked for every viewer with redaction on
(FR-SAF-04); the Critic derives its own hazard set (FR-VER-03); a missing quiz is an issue (FR-VER-05); when the loop
budget is spent the viewer gets a conservative fallback (FR-VER-07).
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from typing import Any

from loom.core.contracts.cuts import (
    CandidateCut,
    CandidateThread,
    CriticScore,
    ExplainerClip,
    ExplainerRequest,
    FinalThread,
    LoopPass,
    PlayerQuizItem,
    QuizRef,
    RedactionMask,
    RedactionRequest,
    SkippedThread,
    TapTarget,
    VerifiedCut,
    VerifiedSkip,
)
from loom.core.contracts.graph import ConceptGraph, GraphObject, QuizQuestion
from loom.core.contracts.issues import CriticIssue
from loom.core.contracts.learner import LearnerProfile
from loom.core.store import utcnow

HAZARD_DEFAULT_TAGS = {"sharp_object", "injury_risk", "weapon", "blood_or_gore", "fire_or_explosion"}
LEVELS = ("beginner", "intermediate", "expert")


# ---------------------------------------------------------------- shared


@dataclass
class Thread:
    thread_id: str
    role: str
    start: float
    end: float
    segment_ids: list[str]
    concept_ids: list[str]
    text: str
    sentence_ends: list[float]
    gist: str = ""
    # set by Pedagogy
    action: str = "keep"
    mastery: float = 0.0
    level: str = "intermediate"
    rationale: str = ""


def level_of(m: float) -> str:
    return "expert" if m >= 0.75 else "intermediate" if m >= 0.45 else "beginner"


def mastery_table(profile: LearnerProfile, video_id: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for m in profile.mastery:
        key = m.concept_key
        if key.startswith(f"{video_id}/"):
            out[key.split("/", 1)[1]] = m.level
    return out


def concept_mastery(cid: str, table: dict[str, float], profile: LearnerProfile) -> tuple[float, str]:
    if cid in table:
        return table[cid], "mastery graph"
    return profile.preferences.prior_knowledge, "prior knowledge"


# ---------------------------------------------------------------- Curator (FR-MESH-04)


def build_threads(graph: ConceptGraph) -> list[Thread]:
    """Partition the timeline into sentence-aligned threads, one per ingest-time role assignment."""
    sent = {s.seg_id: s for s in graph.transcript}
    roles = [r for r in graph.thread_roles if all(sid in sent for sid in r.segment_ids)]
    if not roles:  # no roles: one thread per sentence group of the concepts, all core
        roles = []
    threads: list[Thread] = []
    for k, r in enumerate(roles):
        sids = r.segment_ids
        start = 0.0 if k == 0 else sent[sids[0]].start
        end = graph.duration_seconds if k == len(roles) - 1 else sent[roles[k + 1].segment_ids[0]].start
        cids = sorted(
            {c.node_id for c in graph.concept_nodes if set(c.evidence.segment_ids) & set(sids)},
            key=lambda cid: (
                -len(set(next(c for c in graph.concept_nodes if c.node_id == cid).evidence.segment_ids) & set(sids))
            ),
        )
        threads.append(
            Thread(
                thread_id=f"t{k + 1}",
                role=r.role,
                start=round(start, 2),
                end=graph.duration_seconds if k == len(roles) - 1 else round(end, 2),
                segment_ids=list(sids),
                concept_ids=cids,
                text=" ".join(sent[s].text for s in sids),
                sentence_ends=[round(sent[s].end, 2) for s in sids],
                gist=r.gist,
            )
        )
    return threads


# ---------------------------------------------------------------- Pedagogy (FR-MESH-05)


def plan_threads(threads: list[Thread], graph: ConceptGraph, profile: LearnerProfile, cfg: Any) -> list[Thread]:
    pc = cfg.pedagogy
    shift = pc.pace_shift.get(profile.preferences.pace, 0.0)
    table = mastery_table(profile, graph.video_id)
    prereqs = {c.node_id: c.prerequisites for c in graph.concept_nodes}
    for t in threads:
        vals = [concept_mastery(c, table, profile) for c in t.concept_ids] or [
            (profile.preferences.prior_knowledge, "prior knowledge")
        ]
        m = sum(v for v, _ in vals) / len(vals)
        src = vals[0][1]
        t.mastery, t.level = round(m, 2), level_of(m)
        if m >= pc.skip + shift:
            action, why = "skip", f"mastery {m:.2f} ({src}) - you already know this"
        elif m >= pc.condense + shift:
            action, why = "condense", f"mastery {m:.2f} ({src}) - quick refresher"
        elif m >= pc.keep + shift:
            action, why = "keep", f"mastery {m:.2f} ({src}) - standard pacing"
        else:
            action, why = "expand", f"mastery {m:.2f} ({src}) - explained in more depth"
        if action == "skip" and t.role in ("core", "safety"):
            action, why = "condense", f"{t.role} content is never skipped - kept as a refresher"
        missing = [
            p
            for c in t.concept_ids
            for p in prereqs.get(c, [])
            if table.get(p, profile.preferences.prior_knowledge) < pc.keep
        ]
        if action == "skip" and missing:
            action, why = "condense", f"prerequisite {missing[0]} not yet mastered"
        if action == "skip" and t.role == "summary" and m < 0.9:
            action, why = "condense", "a short recap is kept"
        if action == "skip" and profile.preferences.never_skip:
            action, why = "condense", "you asked to never skip"
        if action == "expand" and t.role not in ("core", "setup"):
            action, why = "keep", f"mastery {m:.2f} - {t.role} segment kept, explainers go to core ideas"
        t.action, t.rationale = action, why
    return threads


# ---------------------------------------------------------------- Personalizer (FR-MESH-06)


def condensed_end(t: Thread, graph: ConceptGraph, cfg: Any) -> float:
    pc = cfg.personalizer
    target = t.start + max(pc.condense_min_s, pc.condense_ratio * (t.end - t.start))
    for span in graph.on_screen_text:
        if t.start <= span.start < t.end:
            target = max(target, span.start + pc.formula_hold_s)
    ends = [e for e in t.sentence_ends if e >= target - 1e-6]
    return min(round(ends[0], 2) if ends else t.end, t.end)


def assemble_cut(
    threads: list[Thread],
    graph: ConceptGraph,
    profile: LearnerProfile,
    cfg: Any,
    session_id: str,
    pass_number: int = 1,
    plugin_requests: list[RedactionRequest] | None = None,
) -> CandidateCut:
    kept, skipped, explainers = [], [], []
    for t in threads:
        if t.action == "skip":
            skipped.append(
                SkippedThread(thread_id=t.thread_id, start=t.start, end=t.end, rationale=t.rationale, source="pedagogy")
            )
            continue
        end = condensed_end(t, graph, cfg) if t.action == "condense" else t.end
        kept.append(
            CandidateThread(
                thread_id=t.thread_id,
                concept_node_ids=t.concept_ids,
                role=t.role,  # type: ignore[arg-type]
                action=t.action,  # type: ignore[arg-type]
                start=t.start,
                end=end,
                source_end=t.end,
                rationale=t.rationale,
            )
        )
        if t.action == "expand" and t.concept_ids and profile.preferences.explainers == "auto":
            explainers.append(
                ExplainerRequest(
                    concept_node_id=t.concept_ids[0],
                    trigger="auto",
                    level=t.level,
                    anchor_time=end,  # type: ignore[arg-type]
                )
            )
    auto = {e.concept_node_id for e in explainers}
    if profile.preferences.explainers != "off":
        for c in graph.concept_nodes:
            if c.evidence.object_ids and c.node_id not in auto:
                explainers.append(
                    ExplainerRequest(
                        concept_node_id=c.node_id,
                        trigger="tap",
                        level=_level_for(profile, graph, c.node_id),
                        anchor_time=0.0,
                    )
                )
    redactions = []
    if profile.safety_profile.redaction_level != "off":
        for o in graph.objects:
            if _visible(o, kept):
                redactions.append(
                    RedactionRequest(
                        object_id=o.object_id, reason="review under the viewer's safety profile", source="personalizer"
                    )
                )
    known = {r.object_id for r in redactions}
    for r in plugin_requests or []:
        if r.object_id not in known:
            redactions.append(r)
            known.add(r.object_id)
    return CandidateCut(
        session_id=session_id,
        video_id=graph.video_id,
        graph_sha=graph.graph_sha or graph.compute_sha(),
        learner_id=profile.learner_id,
        learner_state_sha=profile.learner_state_sha or profile.compute_state_sha(),
        pass_number=pass_number,
        threads=kept,
        skipped=skipped,
        explainer_requests=explainers,
        redaction_requests=redactions,
    )


def _level_for(profile: LearnerProfile, graph: ConceptGraph, cid: str) -> str:
    return level_of(concept_mastery(cid, mastery_table(profile, graph.video_id), profile)[0])


def _visible(o: GraphObject, threads: list[CandidateThread], pad: float = 0.0) -> bool:
    return any(i.start - pad < t.end and t.start < i.end + pad for i in o.instances for t in threads)


def revise_cut(
    cut: CandidateCut, threads: list[Thread], graph: ConceptGraph, issues: list[CriticIssue]
) -> CandidateCut:
    """Apply the Critic's structured mesh issues to produce the next pass (spec/05 §7 routing)."""
    by_id = {t.thread_id: t for t in threads}
    kept = [t.model_copy() for t in cut.threads]
    skipped = list(cut.skipped)
    explainers = list(cut.explainer_requests)
    for issue in issues:
        code = issue.code
        if code == "cut_mid_sentence" and issue.thread_id:
            for i, t in enumerate(kept):
                if t.thread_id == issue.thread_id:
                    ends = [e for e in by_id[t.thread_id].sentence_ends if e >= t.end - 1e-6]
                    kept[i] = t.model_copy(update={"end": ends[0] if ends else t.source_end})
        elif code == "missing_prerequisite" and issue.concept_node_id:
            src = next((t for t in threads if issue.concept_node_id in t.concept_ids), None)
            if src and all(k.thread_id != src.thread_id for k in kept):
                skipped = [s for s in skipped if s.thread_id != src.thread_id]
                kept.append(
                    CandidateThread(
                        thread_id=src.thread_id,
                        concept_node_ids=src.concept_ids,
                        role=src.role,  # type: ignore[arg-type]
                        action="condense",
                        start=src.start,
                        end=src.end,
                        source_end=src.end,
                        rationale=f"re-added: prerequisite {issue.concept_node_id}",
                        source="critic",
                    )
                )
        elif code in ("explainer_unavailable", "explainer_missing") and issue.concept_node_id:
            explainers = [
                e for e in explainers if not (e.concept_node_id == issue.concept_node_id and e.trigger == "auto")
            ]
        elif code in ("overlapping_threads", "out_of_order"):
            kept.sort(key=lambda t: t.start)
            for i in range(len(kept) - 1):
                if kept[i + 1].start < kept[i].end:
                    kept[i] = kept[i].model_copy(update={"end": kept[i + 1].start})
        elif code == "empty_cut":
            skipped = []
            kept = [
                CandidateThread(
                    thread_id=t.thread_id,
                    concept_node_ids=t.concept_ids,
                    role=t.role,  # type: ignore[arg-type]
                    action="keep",
                    start=t.start,
                    end=t.end,
                    source_end=t.end,
                    rationale="restored: the cut was empty",
                    source="critic",
                )
                for t in threads
            ]
    kept.sort(key=lambda t: t.start)
    return cut.model_copy(
        update={
            "threads": kept,
            "skipped": skipped,
            "explainer_requests": explainers,
            "pass_number": cut.pass_number + 1,
        }
    )


# ---------------------------------------------------------------- Assessment (FR-MESH-08)


def select_quiz(
    cut: CandidateCut, graph: ConceptGraph, profile: LearnerProfile, limit: int, recent: set[str]
) -> list[QuizRef]:
    table = mastery_table(profile, graph.video_id)
    in_cut = list(dict.fromkeys(c for t in cut.threads for c in t.concept_node_ids))
    bank: dict[tuple[str, str], list[QuizQuestion]] = {}
    for q in graph.quiz_bank:
        bank.setdefault((q.concept_node_id, q.level), []).append(q)
    targets = sorted(in_cut, key=lambda c: concept_mastery(c, table, profile)[0])
    out: list[QuizRef] = []
    for cid in targets:
        lvl = level_of(concept_mastery(cid, table, profile)[0])
        order = [lvl] + [x for x in LEVELS if x != lvl]
        pick = None
        for level in order:
            cands = [q for q in bank.get((cid, level), []) if q.question_id not in recent] or bank.get((cid, level), [])
            if cands:
                pick = cands[0]
                break
        if pick:
            out.append(QuizRef(question_id=pick.question_id))
        if len(out) >= limit:
            break
    return out


def option_order(session_id: str, question_id: str) -> list[int]:
    """Deterministic per-session shuffle so the correct option is not always first; graded server-side."""
    rng = random.Random(hashlib.sha256(f"{session_id}:{question_id}".encode()).hexdigest())
    order = [0, 1, 2, 3]
    rng.shuffle(order)
    return order


def update_mastery(
    levels: dict[str, float], events: list[tuple[str, str, bool]], cfg: Any
) -> dict[str, tuple[float, float, str]]:
    """events: [(kind, concept_id, correct)] -> {concept_id: (before, after, cause)} (EMA rule, server events only)."""
    ac = cfg.assessment
    out: dict[str, tuple[float, float, str]] = {}
    for kind, cid, correct in events:
        before = out[cid][1] if cid in out else levels[cid]
        if kind == "quiz":
            after = before + ac.correct_gain * (1 - before) if correct else before * ac.wrong_decay
            cause = "quiz_correct" if correct else "quiz_wrong"
        elif kind == "explainer":
            after, cause = before + ac.explainer_gain * (1 - before), "explainer_watched"
        else:
            after, cause = before + ac.exposure_gain * (1 - before), "thread_completed"
        out[cid] = (out[cid][0] if cid in out else before, round(min(1.0, max(0.0, after)), 3), cause)
    return out


# ---------------------------------------------------------------- Guardian (FR-SAF-01..04)


def redaction_decisions(
    graph: ConceptGraph, profile: LearnerProfile, cut: CandidateCut, cfg: Any
) -> dict[str, tuple[str, str]]:
    """object_id -> (reason, source) for every object to mask for this viewer."""
    sp = profile.safety_profile
    level = sp.redaction_level
    if level == "off":
        return {}
    threshold = cfg.safety.strict_threshold if level == "strict" else cfg.safety.standard_threshold
    blocked = set(sp.blocked_tags)
    allowed = set(sp.allowed_tags)
    out: dict[str, tuple[str, str]] = {}
    for o in graph.objects:
        s = o.safety
        tags = set(s.tags) - allowed
        if s.status != "reviewed":
            out[o.object_id] = (f"safety review {s.status} - masked to be safe", "guardian")
        elif blocked & tags:
            out[o.object_id] = (f"blocked tag {sorted(blocked & tags)[0]}", "guardian")
        elif tags and s.severity >= threshold and (level == "strict" or s.child_unsafe):
            out[o.object_id] = (f"{level} profile: {', '.join(sorted(tags))}", "guardian")
    for r in cut.redaction_requests:
        if r.source.startswith("plugin:") and r.object_id not in out:
            out[r.object_id] = (r.reason, r.source)
    return out


def _pad_box(b: tuple[float, float, float, float], pad: float) -> tuple[float, float, float, float]:
    x, y = max(0.0, b[0] - pad), max(0.0, b[1] - pad)
    return (round(x, 4), round(y, 4), round(min(1 - x, b[2] + 2 * pad), 4), round(min(1 - y, b[3] + 2 * pad), 4))


def build_masks(
    graph: ConceptGraph, cut: CandidateCut, decisions: dict[str, tuple[str, str]], cfg: Any, write: Any
) -> list[RedactionMask]:
    """One mask per visible instance; `write(rel_path, payload)` stores the per-sample track for the player."""
    pad_t, pad = cfg.safety.time_pad_s, cfg.safety.mask_pad
    masks = []
    for o in graph.objects:
        if o.object_id not in decisions:
            continue
        reason, source = decisions[o.object_id]
        o_pad = pad * 3 if o.safety.child_unsafe else pad  # hazards err toward covering (FR-SAF-03)
        for k, inst in enumerate(o.instances):
            if not any(inst.start - pad_t < t.end and t.start < inst.end + pad_t for t in cut.threads):
                continue
            xs = [s.bbox for s in inst.track]
            x0, y0 = min(b[0] for b in xs), min(b[1] for b in xs)
            x1, y1 = max(b[0] + b[2] for b in xs), max(b[1] + b[3] for b in xs)
            rel = f"masks/{graph.video_id}/{o.object_id}_{k}.json"
            write(
                rel,
                {
                    "object_id": o.object_id,
                    "label": o.label,
                    "pad": o_pad,
                    "samples": [{"t": s.t, "bbox": _pad_box(s.bbox, o_pad), "mask": s.mask} for s in inst.track],
                },
            )
            masks.append(
                RedactionMask(
                    mask_id=f"m_{o.object_id}_{k}",
                    object_id=o.object_id,
                    label=o.label,
                    start=round(max(0.0, inst.start - pad_t), 2),
                    end=round(min(graph.duration_seconds, inst.end + pad_t), 2),
                    track_url=f"/media/{rel}",
                    fallback_bbox=_pad_box((x0, y0, x1 - x0, y1 - y0), o_pad),
                    reason=reason,
                    source=source,  # type: ignore[arg-type]
                    enforced=profile_enforced(source),
                )
            )
    return masks


def profile_enforced(source: str) -> bool:
    return source in ("guardian", "critic") or source.startswith("plugin:")


# ---------------------------------------------------------------- Critic (FR-VER-02..05)


def critic_hazards(graph: ConceptGraph, profile: LearnerProfile, cut: CandidateCut, cfg: Any) -> set[str]:
    """The Critic's own hazard set - not Guardian's output (FR-VER-03)."""
    if profile.safety_profile.redaction_level == "off":
        return set()
    hazard_classes = set(cfg.perception.hazard_classes)
    allowed = set(profile.safety_profile.allowed_tags)
    out = set()
    for o in graph.objects:
        s = o.safety
        if s.status != "reviewed" or ((set(s.tags) - allowed) & (
            set(profile.safety_profile.blocked_tags) | HAZARD_DEFAULT_TAGS
        ) and s.child_unsafe) or (o.label in hazard_classes and not (set(s.tags) <= allowed and s.tags)):
            out.add(o.object_id)
    out |= {r.object_id for r in cut.redaction_requests if r.source.startswith("plugin:")}
    return out


def critic_score(
    cut: CandidateCut,
    graph: ConceptGraph,
    profile: LearnerProfile,
    masks: list[RedactionMask],
    clips: dict[str, ExplainerClip],
    cfg: Any,
) -> tuple[CriticScore, list[CriticIssue]]:
    issues: list[CriticIssue] = []
    threads = cut.threads
    # safety: 0.1 s coverage of the Critic's hazard set inside the cut
    hazards = critic_hazards(graph, profile, cut, cfg)
    need = covered = 0
    uncovered: set[str] = set()
    for o in graph.objects:
        if o.object_id not in hazards:
            continue
        om = [m for m in masks if m.object_id == o.object_id]
        for inst in o.instances:
            t = inst.start
            while t < inst.end:
                if any(th.start <= t < th.end for th in threads):
                    need += 1
                    if any(m.start <= t < m.end for m in om):
                        covered += 1
                    else:
                        uncovered.add(o.object_id)
                t = round(t + 0.1, 2)
    safety = 1.0 if need == 0 else covered / need
    issues += [
        CriticIssue(code="unmasked_hazard", object_id=o, detail=f"{o} visible without a mask")
        for o in sorted(uncovered)
    ]
    # coherence
    penalty = 0.0
    if not threads:
        issues.append(CriticIssue(code="empty_cut", detail="the cut has no threads"))
        penalty = 1.0
    starts = [t.start for t in threads]
    if starts != sorted(starts) or any(b.start < a.end - 0.05 for a, b in zip(threads, threads[1:], strict=False)):
        penalty += 0.25
        issues.append(CriticIssue(code="overlapping_threads", detail="threads overlap or are out of order"))
    for t in threads:
        for s in graph.transcript:
            if s.start + 0.3 < t.end < s.end - 0.3:
                penalty += 0.15
                issues.append(
                    CriticIssue(
                        code="cut_mid_sentence",
                        thread_id=t.thread_id,
                        detail=f"{t.thread_id} ends mid-sentence at {t.end:.1f}s",
                    )
                )
                break
    table = mastery_table(profile, graph.video_id)
    in_cut = {c for t in threads for c in t.concept_node_ids}
    for c in graph.concept_nodes:
        if c.node_id in in_cut:
            for p in c.prerequisites:
                if p not in in_cut and table.get(p, profile.preferences.prior_knowledge) < cfg.pedagogy.prereq_mastery:
                    penalty += 0.1
                    issues.append(
                        CriticIssue(
                            code="missing_prerequisite",
                            concept_node_id=p,
                            detail=f"{c.node_id} needs {p}, not yet mastered",
                        )
                    )
    for e in cut.explainer_requests:
        if e.trigger == "auto" and e.concept_node_id not in clips:
            penalty += 0.05
            issues.append(
                CriticIssue(
                    code="explainer_unavailable",
                    concept_node_id=e.concept_node_id,
                    detail=f"no verified explainer for {e.concept_node_id} yet",
                )
            )
    coherence = max(0.0, 1.0 - penalty)
    # factuality: quiz comes only from the ingest-verified bank; clips only if judge-verified
    bank = {q.question_id for q in graph.quiz_bank}
    bad_quiz = [q.question_id for q in cut.quiz if q.question_id not in bank]
    issues += [
        CriticIssue(code="quiz_unsupported", question_id=q, detail="question not in the verified bank")
        for q in bad_quiz
    ]
    factuality = 1.0 if not cut.quiz else 1 - len(bad_quiz) / len(cut.quiz)
    # completeness
    completeness = 1.0
    bank_concepts = {q.concept_node_id for q in graph.quiz_bank}
    if not cut.quiz and in_cut & bank_concepts:
        completeness = 0.0
        issues.append(CriticIssue(code="quiz_missing", detail="the verified bank has questions for this cut"))
    score = CriticScore(
        safety=round(safety, 3),
        coherence=round(coherence, 3),
        factuality=round(factuality, 3),
        completeness=completeness,
    )
    return score, issues


# ---------------------------------------------------------------- Verifier loop (FR-VER-01, 06, 07)


@dataclass
class LoopResult:
    cut: VerifiedCut
    trace: list[dict[str, Any]] = field(default_factory=list)


def to_verified(
    cut: CandidateCut,
    graph: ConceptGraph,
    masks: list[RedactionMask],
    clips: dict[str, ExplainerClip],
    passes: list[LoopPass],
    status: str,
    score: CriticScore,
    reason: str | None = None,
    degraded: list[str] | None = None,
) -> VerifiedCut:
    labels = {c.node_id: c.label for c in graph.concept_nodes}
    bank = {q.question_id: q for q in graph.quiz_bank}
    quiz = []
    for ref in cut.quiz:
        q = bank[ref.question_id]
        order = option_order(cut.session_id, q.question_id)
        quiz.append(PlayerQuizItem(question_id=q.question_id, stem=q.stem, options=[q.options[i] for i in order]))
    taps = [
        TapTarget(object_id=o, concept_node_id=c.node_id)
        for c in graph.concept_nodes
        for o in c.evidence.object_ids
        if c.node_id in {e.concept_node_id for e in cut.explainer_requests}
    ]
    return VerifiedCut(
        session_id=cut.session_id,
        video_id=cut.video_id,
        learner_id=cut.learner_id,
        status=status,  # type: ignore[arg-type]
        fallback_reason=reason,
        pass_count=len(passes),
        critic_score=score,
        final_threads=[
            FinalThread(
                thread_id=t.thread_id,
                start=t.start,
                end=t.end,
                action=t.action,
                label=", ".join(labels[c] for c in t.concept_node_ids if c in labels) or t.role.title(),
                rationale=t.rationale,
                source=t.source,
            )
            for t in cut.threads
        ],
        skipped=[VerifiedSkip(start=s.start, end=s.end, rationale=s.rationale, source=s.source) for s in cut.skipped],
        redaction_masks=masks,
        explainer_clips=[
            clips[e.concept_node_id]
            for e in cut.explainer_requests
            if e.trigger == "auto" and e.concept_node_id in clips
        ],
        tap_targets=taps,
        quiz=quiz,
        loop_trace=passes,
        degraded=degraded or [],
        created_at=utcnow(),
    )
