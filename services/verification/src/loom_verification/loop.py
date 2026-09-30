"""The bounded Perceive -> Plan -> Act -> Verify loop: candidate-cut.json (Contract B) -> verified-cut.json (Contract C).

Each pass:
  PERCEIVE  the Guardian reviews every object and builds masks for the current threads; the Animator renders the
            requested explainers (in parallel, from cache when possible).
  PLAN      the Critic scores safety / coherence / factuality and lists structured issues.
  VERIFY    approved -> deliver and remember it as the last verified cut for this video + learner.
  ACT       otherwise fix what verification owns (re-render an unfaithful explainer once with the Critic's reasons,
            then drop it; force a mask on an unmasked hazard; drop an unsupported quiz item) and send thread-level
            issues to the agent mesh (Person 2) when LOOM_MESH_REVISE_URL is set, else repair them locally.
When the budget (default 3 passes) is spent, the viewer gets the last verified cut for this video + learner, or a
conservative baseline (full lesson, every safety-tagged object masked, nothing generated) - never an unchecked cut.
"""

from __future__ import annotations

import copy
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from .animator import Animator, AnimatorError, Explainer
from .config import Config
from .contracts import validate_candidate, validate_verified
from .critic import Critic
from .guardian import Guardian
from .llm import LLM
from .sources import GraphSource, load_concept_graph, load_learner_profile

log = logging.getLogger(__name__)

THREAD_ISSUES = {"cut_mid_sentence", "overlapping_threads", "thread_out_of_bounds", "unknown_concept",
                 "missing_prerequisite", "empty_cut"}


class CandidateError(ValueError):
    pass


def learner_level(profile: dict, cid: str) -> str:
    m = {e["concept_id"].split("/")[-1]: e.get("level", 0) for e in profile.get("mastery_graph", [])}.get(cid, 0.3)
    return "expert" if m >= 0.75 else "intermediate" if m >= 0.45 else "beginner"


def node_span(node: dict) -> tuple[float, float] | None:
    if "start" in node and "end" in node:        # Person 1 adds these (additive field)
        return node["start"], node["end"]
    refs = node.get("transcript_refs", []) + node.get("on_screen_text_refs", [])
    return (min(r["start"] for r in refs), max(r["end"] for r in refs)) if refs else None


class Verifier:
    def __init__(self, cfg: Config, llm: LLM | None):
        self.cfg, self.llm = cfg, llm
        cfg.ensure_dirs()
        self.guardian, self.animator, self.critic = Guardian(cfg, llm), Animator(cfg, llm), Critic(cfg, llm)

    # ------------------------------------------------------------------ public
    def verify(self, candidate: dict, *, graph_source: GraphSource | None = None, profile: dict | None = None) -> dict:
        errs = validate_candidate(candidate)
        if errs:
            raise CandidateError("candidate-cut.json does not match Contract B: " + "; ".join(errs[:6]))
        t_start = time.time()
        src = graph_source or load_concept_graph(candidate["video_id"], self.cfg)
        warnings = list(src.warnings)
        if profile is None:
            profile, w = load_learner_profile(candidate["learner_id"], self.cfg)
            warnings += w
        graph = src.graph
        known = {o["object_id"] for o in graph.get("objects", [])}
        warnings += [f"redaction request for unknown object {r['object_id']} ignored"
                     for r in candidate.get("redaction_requests", []) if r.get("object_id") not in known]
        tags = self.guardian.tag_objects(src)

        cand = copy.deepcopy(candidate)
        threads = sorted(cand["threads"], key=lambda t: t["start"])
        quiz = list(cand.get("quiz", []))
        requests = {r["concept_node_id"]: r for r in cand.get("explainer_requests", [])}
        extra_redactions: list[dict] = []
        extra_pad = 0.0
        feedback: dict[str, list[str]] = {}
        dropped: set[str] = set()
        trace, report_passes = [], []
        session_dir = self.cfg.sessions_dir / cand["session_id"]
        session_dir.mkdir(parents=True, exist_ok=True)

        for pass_no in range(1, self.cfg.loop_budget + 1):
            t0 = time.time()
            # PERCEIVE
            decisions = self.guardian.decide(graph, profile, cand.get("redaction_requests", []) + extra_redactions, tags)
            masks = self.guardian.build_masks(src, threads, decisions, extra_pad_s=extra_pad)
            explainers, failures = self._render_explainers(src, profile, requests, dropped, feedback)
            # PLAN
            verdict = self.critic.score(threads, quiz, graph, profile, set(decisions), masks, explainers, failures)
            entry = {"pass_number": pass_no, "approved": verdict["approved"], "scores": verdict["scores"],
                     "issues": [i["message"] for i in verdict["issues"]], "latency_ms": round((time.time() - t0) * 1000)}
            trace.append(entry)
            report_passes.append({**entry, "judge": verdict["judge"], "claims": verdict["claims"], "decisions": decisions})
            # VERIFY
            if verdict["approved"]:
                doc = self._assemble(cand, graph, "approved", pass_no, verdict["scores"], threads, masks, explainers,
                                     quiz, requests, trace)
                self._store(session_dir, doc, report_passes, warnings, t_start, remember=True)
                return doc
            if pass_no == self.cfg.loop_budget:
                break
            # ACT
            notes = []
            mesh_issues = []
            for issue in verdict["issues"]:
                code = issue["code"]
                if code == "unmasked_hazard":
                    if issue["object_id"] not in decisions:
                        extra_redactions.append({"object_id": issue["object_id"], "reason": "critic: unmasked hazard"})
                    else:
                        extra_pad += 0.5
                    notes.append(f"force mask on {issue['object_id']}")
                elif code == "explainer_unfaithful":
                    cid = issue["concept_node_id"]
                    if cid in feedback:
                        dropped.add(cid)
                        notes.append(f"drop explainer {cid} (still unfaithful after revision)")
                    else:
                        feedback[cid] = issue["feedback"]
                        notes.append(f"re-render explainer {cid} with the Critic's feedback")
                elif code == "explainer_unavailable":
                    dropped.add(issue["concept_node_id"])
                    notes.append(f"drop explainer {issue['concept_node_id']}")
                elif code == "quiz_unsupported":
                    quiz[issue["index"]] = None
                    notes.append(f"drop unsupported quiz item {issue['index']}")
                elif code in THREAD_ISSUES:
                    mesh_issues.append(issue)
            quiz = [q for q in quiz if q is not None]
            if mesh_issues:
                revised = self._ask_mesh(cand, threads, mesh_issues)
                if revised is not None:
                    threads = sorted(revised["threads"], key=lambda t: t["start"])
                    quiz = revised.get("quiz", quiz)
                    requests = {r["concept_node_id"]: r for r in revised.get("explainer_requests", [])} or requests
                    notes.append("threads revised by the agent mesh")
                else:
                    threads, local = self._repair_threads(threads, graph, mesh_issues)
                    notes += local
            report_passes[-1]["act"] = notes
            (session_dir / f"candidate_pass{pass_no + 1}.json").write_text(
                json.dumps({**cand, "pass_number": pass_no + 1, "threads": threads, "quiz": quiz}, indent=2), encoding="utf-8")

        doc = self._fallback(cand, src, profile, tags, trace)
        self._store(session_dir, doc, report_passes, warnings, t_start, remember=False)
        return doc

    def explain(self, video_id: str, concept_node_id: str, level: str | None = None, learner_id: str | None = None) -> dict:
        """Tap-to-learn: render (or fetch) one explainer and fact-check it before it is shown. Budget cfg.tap_budget."""
        src = load_concept_graph(video_id, self.cfg)
        if level is None:
            profile = load_learner_profile(learner_id, self.cfg)[0] if learner_id else {}
            level = learner_level(profile, concept_node_id)
        fb = None
        for attempt in range(1, self.cfg.tap_budget + 1):
            ex = self.animator.render(src, concept_node_id, level, fb)
            s, issues, _, _ = self.critic.factuality([], src.graph, {concept_node_id: ex})
            if not issues:
                return {"approved": True, "concept_node_id": concept_node_id, "clip_url": ex.url, "cached": ex.cached,
                        "title": _label(src.graph, concept_node_id), "duration_seconds": ex.duration_s,
                        "storyboard": ex.storyboard, "factuality": s, "attempts": attempt}
            fb = [f for i in issues for f in i.get("feedback", [])]
        return {"approved": False, "concept_node_id": concept_node_id, "reason": "explainer did not pass fact-checking",
                "issues": fb}

    # ------------------------------------------------------------------ phases
    def _render_explainers(self, src, profile, requests, dropped, feedback):
        explainers: dict[str, Explainer] = {}
        failures: dict[str, str] = {}
        todo = [r for cid, r in requests.items() if cid not in dropped]

        def one(req):
            cid = req["concept_node_id"]
            try:
                explainers[cid] = self.animator.render(src, cid, req.get("level") or learner_level(profile, cid),
                                                       feedback.get(cid))
            except (AnimatorError, OSError) as e:
                failures[cid] = str(e)

        with ThreadPoolExecutor(max_workers=self.cfg.render_workers) as pool:
            list(pool.map(one, todo))
        return explainers, failures

    def _ask_mesh(self, cand: dict, threads: list[dict], issues: list[dict]) -> dict | None:
        """Person 2's revise hook: POST {candidate_cut, issues} -> a revised candidate-cut.json."""
        if not self.cfg.mesh_revise_url:
            return None
        try:
            r = httpx.post(self.cfg.mesh_revise_url, json={"candidate_cut": {**cand, "threads": threads}, "issues": issues},
                           timeout=120)
            r.raise_for_status()
            revised = r.json().get("candidate_cut", r.json())
            if not validate_candidate(revised):
                return revised
            log.warning("agent mesh returned an invalid candidate; repairing locally")
        except (httpx.HTTPError, ValueError) as e:
            log.warning("agent mesh revise failed (%s); repairing locally", e)
        return None

    @staticmethod
    def _repair_threads(threads: list[dict], graph: dict, issues: list[dict]) -> tuple[list[dict], list[str]]:
        threads = [dict(t) for t in threads]
        notes = []
        duration = graph.get("duration_seconds") or max([t["end"] for t in threads] or [0])
        nodes = {n["node_id"]: n for n in graph.get("concept_nodes", [])}
        by_id = {t["thread_id"]: t for t in threads}
        for issue in issues:
            code = issue["code"]
            if code == "cut_mid_sentence" and issue.get("thread_id") in by_id:
                by_id[issue["thread_id"]]["end"] = issue["sentence_end"]
                notes.append(f"extend {issue['thread_id']} to the end of its sentence ({issue['sentence_end']}s)")
            elif code == "unknown_concept":
                for t in threads:
                    t["concept_node_ids"] = [c for c in t.get("concept_node_ids", []) if c != issue["concept_node_id"]]
                notes.append(f"remove unknown concept {issue['concept_node_id']} from threads")
            elif code == "missing_prerequisite" and issue["concept_node_id"] in nodes:
                span = node_span(nodes[issue["concept_node_id"]])
                if span:
                    threads.append({"thread_id": f"t_pre_{issue['concept_node_id']}", "concept_node_ids": [issue["concept_node_id"]],
                                    "action": "condense", "start": span[0], "end": span[1]})
                    notes.append(f"add prerequisite {issue['concept_node_id']}")
        # always leave the threads ordered, inside the video and non-overlapping
        out = []
        for t in sorted(threads, key=lambda t: t["start"]):
            t["start"], t["end"] = max(0.0, t["start"]), min(duration, t["end"])
            if out and t["start"] < out[-1]["end"]:
                t["start"] = out[-1]["end"]
            if t["end"] - t["start"] > 0.05:
                out.append(t)
        if len(out) != len(threads) or any(i["code"] in ("overlapping_threads", "thread_out_of_bounds") for i in issues):
            notes.append("order threads, clip them to the video and remove overlaps")
        return out, notes

    # ------------------------------------------------------------------ output
    def _assemble(self, cand, graph, status, pass_count, scores, threads, masks, explainers, quiz, requests, trace) -> dict:
        labels = {n["node_id"]: n.get("label", n["node_id"]) for n in graph.get("concept_nodes", [])}
        final = []
        for t in threads:
            ft = {"thread_id": t["thread_id"], "start": round(t["start"], 2), "end": round(t["end"], 2),
                  "concept_node_ids": t.get("concept_node_ids", [])}
            ft["label"] = ", ".join(labels[c] for c in ft["concept_node_ids"] if c in labels) or t["thread_id"]
            if t.get("action"):
                ft["action"] = t["action"]
            final.append(ft)
        clips = []
        for cid, ex in explainers.items():
            anchor = requests.get(cid, {}).get("anchor_time")
            if anchor is None:
                anchor = next((t["start"] for t in final if cid in t["concept_node_ids"]), None)
            if anchor is None and cid in {n["node_id"] for n in graph.get("concept_nodes", [])}:
                span = node_span(next(n for n in graph["concept_nodes"] if n["node_id"] == cid))
                anchor = span[0] if span else None
            clip = {"concept_node_id": cid, "clip_url": ex.url, "cached": ex.cached, "title": labels.get(cid, cid),
                    "anchor_seconds": round(anchor, 2) if anchor is not None else None, "duration_seconds": ex.duration_s}
            clips.append({k: v for k, v in clip.items() if v is not None})
        doc = {"schema_version": "1.0", "session_id": cand["session_id"], "video_id": cand["video_id"],
               "learner_id": cand["learner_id"], "status": status, "pass_count": pass_count, "critic_score": scores,
               "final_threads": final, "redaction_masks": masks, "explainer_clips": clips,
               "quiz": [dict(q) for q in quiz], "loop_trace": trace}
        errs = validate_verified(doc, graph)
        if errs:   # never hand an invalid Contract C to delivery
            raise RuntimeError("assembled verified-cut violates Contract C: " + "; ".join(errs[:5]))
        return doc

    def _fallback(self, cand, src: GraphSource, profile, tags, trace) -> dict:
        prev = self.cfg.sessions_dir / "_last_verified" / f"{cand['video_id']}__{cand['learner_id']}.json"
        if prev.exists():
            doc = json.loads(prev.read_text(encoding="utf-8"))
            doc.update(session_id=cand["session_id"], status="fallback", pass_count=len(trace), loop_trace=trace)
            return doc
        graph = src.graph
        duration = graph.get("duration_seconds") or max([s["end"] for s in graph.get("transcript", [])] + [0.0])
        threads = [{"thread_id": "t_full", "start": 0.0, "end": duration,
                    "concept_node_ids": [n["node_id"] for n in graph.get("concept_nodes", [])], "action": "keep"}]
        strict = dict(profile, family_safety_profile={**(profile.get("family_safety_profile") or {}), "redaction_level": "strict"})
        decisions = self.guardian.decide(graph, strict, cand.get("redaction_requests", []), tags)
        masks = self.guardian.build_masks(src, threads, decisions)
        s_saf, _ = self.critic.safety(threads, graph, set(decisions), masks)
        scores = {"factuality": 1.0, "coherence": 1.0, "safety": s_saf}
        return self._assemble(cand, graph, "fallback", len(trace), scores, threads, masks, {}, [], {}, trace)

    def _store(self, session_dir: Path, doc: dict, passes, warnings, t_start, remember: bool) -> None:
        (session_dir / "verified-cut.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
        (session_dir / "report.json").write_text(json.dumps({
            "status": doc["status"], "pass_count": doc["pass_count"], "seconds": round(time.time() - t_start, 1),
            "llm": self.llm.name if self.llm else None, "warnings": warnings, "passes": passes}, indent=2), encoding="utf-8")
        if remember:
            last = self.cfg.sessions_dir / "_last_verified"
            last.mkdir(parents=True, exist_ok=True)
            (last / f"{doc['video_id']}__{doc['learner_id']}.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")


def _label(graph: dict, cid: str) -> str:
    return next((n.get("label", cid) for n in graph.get("concept_nodes", []) if n["node_id"] == cid), cid)
