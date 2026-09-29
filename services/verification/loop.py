"""Verification service: the bounded Perceive -> Plan -> Act -> Verify loop.  [Member 3 - Verification, Safety & Generation]

Input : candidate-cut.json (Contract B) + concept graph + learner profile.
Output: verified-cut.json (Contract C), status "approved" or "fallback".

Each pass:
  PERCEIVE  Guardian reviews every visible object and builds masks; Animator renders the cut's
            automatic explainers (from cache when possible).
  PLAN      Critic scores factuality / coherence / safety and lists structured issues.
  VERIFY    approved -> deliver.  Otherwise, if budget remains:
  ACT       fix what verification owns locally (re-render an unfaithful explainer with the Critic's
            feedback; force masks on an unmasked hazard) and send the rest back to the agent mesh
            (A2A `revise_cut` on the orchestrator) for the next candidate pass.
When the budget (LOOM_LOOP_BUDGET, default 3) is spent, the viewer gets the last verified cut for this
video + learner, or a conservative baseline - never an unchecked cut.
"""
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

from loom_shared import a2a, contracts, events
from loom_shared.config import LOOP_BUDGET, MEDIA_DIR, SESSIONS_DIR

REGISTRY = a2a.Registry()
LAST_VERIFIED = SESSIONS_DIR / "_last_verified"
LAST_VERIFIED.mkdir(parents=True, exist_ok=True)
RENDER_WORKERS = 3
MESH_ISSUES = {"cut_mid_sentence", "missing_prerequisite", "overlapping_threads", "out_of_order", "empty_cut",
               "quiz_unsupported", "explainer_unavailable"}


def _call(skill, data, session_id):
    card = REGISTRY.with_skill(skill)[0]
    events.publish(session_id, "agent_call", agent=card["name"], skill=skill)
    out, meta = a2a.send(card["url"], data, skill=skill)
    events.publish(session_id, "agent_done", agent=card["name"], skill=skill, latency_ms=meta["latency_ms"])
    return out


def _perceive(candidate, graph, profile, extra_redactions, explainer_feedback, session_id):
    guard = _call("review_objects", {"concept_graph": graph, "learner_profile": profile,
                                     "threads": candidate["threads"],
                                     "redaction_requests": candidate.get("redaction_requests", []) + extra_redactions},
                  session_id)
    explainers, failures = {}, {}

    def render(req):
        cid = req["concept_node_id"]
        try:
            explainers[cid] = dict(_call("render_explainer", {
                "concept_graph": graph, "concept_node_id": cid, "level": req.get("level", "beginner"),
                "feedback": explainer_feedback.get(cid)}, session_id), anchor_time=req.get("anchor_time"))
        except Exception as e:
            failures[cid] = str(e)

    auto = [r for r in candidate.get("explainer_requests", []) if r.get("trigger") == "auto"]
    with ThreadPoolExecutor(max_workers=RENDER_WORKERS) as pool:
        list(pool.map(render, auto))
    return guard, explainers, failures


def _clip_seconds(clip_url):
    path = MEDIA_DIR / clip_url.removeprefix("/media/")
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        return round(float(out), 2)
    except (ValueError, OSError, subprocess.SubprocessError):
        return None


def _verified_cut(candidate, graph, status, pass_count, verdict, masks, explainers, trace):
    labels = {n["node_id"]: n["label"] for n in graph["concept_nodes"]}
    threads = []
    for t in candidate["threads"]:
        th = {k: t[k] for k in ("thread_id", "start", "end", "concept_node_ids", "action") if k in t}
        th["label"] = ", ".join(labels[c] for c in t.get("concept_node_ids", []) if c in labels) or t["thread_id"]
        threads.append(th)
    # Additive fields requested by the delivery web app (services/delivery/web/CONTRACT-NOTES.md):
    # masks carry fallback_bbox, explainers carry anchor_seconds / title / duration_seconds.
    masks = [dict(m, fallback_bbox=m["bbox"]) if "bbox" in m else m for m in masks]
    clips = [{"concept_node_id": cid, "clip_url": ex["clip_url"], "cached": ex.get("cached", False), "trigger": "auto",
              "anchor_time": ex.get("anchor_time"), "anchor_seconds": ex.get("anchor_time"),
              "title": labels.get(cid, cid), "duration_seconds": _clip_seconds(ex["clip_url"])}
             for cid, ex in explainers.items()]
    doc = {
        "schema_version": "1.0", "session_id": candidate["session_id"], "video_id": candidate["video_id"],
        "video_url": graph.get("video_url"), "learner_id": candidate["learner_id"], "status": status,
        "pass_count": pass_count, "critic_score": verdict["scores"],
        "final_threads": threads,
        "redaction_masks": masks,
        "explainer_clips": [{k: v for k, v in c.items() if v is not None} for c in clips],
        "quiz": candidate.get("quiz", []),
        "loop_trace": trace,
    }
    return contracts.validate("verified-cut", doc)


def _fallback(candidate, graph, profile, trace, session_id):
    key = LAST_VERIFIED / f"{candidate['video_id']}__{candidate['learner_id']}.json"
    if key.exists():
        prev = json.loads(key.read_text())
        prev.update(session_id=candidate["session_id"], status="fallback", pass_count=len(trace), loop_trace=trace)
        events.publish(session_id, "fallback", source="last verified cut")
        return contracts.validate("verified-cut", prev)
    # Conservative baseline: the whole lesson, every safety-tagged object masked, nothing generated.
    guard = _call("review_objects", {"concept_graph": graph,
                                     "learner_profile": dict(profile, family_safety_profile={"redaction_level": "strict"}),
                                     "threads": [{"start": 0, "end": graph["duration_seconds"]}],
                                     "redaction_requests": []}, session_id)
    base = dict(candidate, threads=[{"thread_id": "t_full", "start": 0.0, "end": graph["duration_seconds"],
                                     "concept_node_ids": [n["node_id"] for n in graph["concept_nodes"]],
                                     "action": "keep"}], quiz=[])
    events.publish(session_id, "fallback", source="conservative baseline")
    return _verified_cut(base, graph, "fallback", len(trace),
                         {"scores": trace[-1]["scores"] if trace else {}}, guard["redaction_masks"], {}, trace)


def verify_cut(data):
    candidate, graph, profile = data["candidate_cut"], data["concept_graph"], data["learner_profile"]
    contracts.validate("candidate-cut", candidate)
    session_id = candidate["session_id"]
    revise_url = data.get("revise_agent_url")
    trace, extra_redactions, explainer_feedback, feedback_used = [], [], {}, set()

    for pass_no in range(1, LOOP_BUDGET + 1):
        t0 = time.time()
        events.publish(session_id, "loop_phase", phase="perceive", pass_number=pass_no)
        guard, explainers, failures = _perceive(candidate, graph, profile, extra_redactions, explainer_feedback,
                                                session_id)

        events.publish(session_id, "loop_phase", phase="plan", pass_number=pass_no)
        verdict = _call("score_cut", {"candidate_cut": candidate, "concept_graph": graph, "learner_profile": profile,
                                      "flagged": list(guard["decisions"]), "redaction_masks": guard["redaction_masks"],
                                      "explainers": explainers, "explainer_failures": failures}, session_id)
        trace.append({"pass_number": pass_no, "approved": verdict["approved"], "scores": verdict["scores"],
                      "issues": [i["message"] for i in verdict["issues"]],
                      "latency_ms": round((time.time() - t0) * 1000)})
        events.publish(session_id, "loop_phase", phase="verify", pass_number=pass_no, approved=verdict["approved"],
                       scores=verdict["scores"], issues=[i["message"] for i in verdict["issues"]])
        (SESSIONS_DIR / session_id).mkdir(parents=True, exist_ok=True)
        (SESSIONS_DIR / session_id / f"critic_pass{pass_no}.json").write_text(json.dumps(verdict, indent=2))

        if verdict["approved"]:
            doc = _verified_cut(candidate, graph, "approved", pass_no, verdict, guard["redaction_masks"], explainers,
                                trace)
            (LAST_VERIFIED / f"{candidate['video_id']}__{candidate['learner_id']}.json").write_text(json.dumps(doc))
            (SESSIONS_DIR / session_id / "verified_cut.json").write_text(json.dumps(doc, indent=2))
            events.publish(session_id, "delivered", status="approved", pass_count=pass_no)
            return doc
        if pass_no == LOOP_BUDGET:
            break

        # ACT: local fixes first, then everything else goes back to the mesh.
        events.publish(session_id, "loop_phase", phase="act", pass_number=pass_no)
        mesh_issues = []
        for issue in verdict["issues"]:
            code = issue["code"]
            if code == "unmasked_hazard":
                extra_redactions.append({"object_id": issue["object_id"], "reason": "critic: unmasked hazard"})
            elif code == "explainer_unfaithful":
                cid = issue["concept_node_id"]
                if cid in feedback_used:   # already re-rendered once with feedback: drop it instead
                    mesh_issues.append({"code": "explainer_unavailable", "concept_node_id": cid,
                                        "message": f"explainer {cid} still unfaithful after revision"})
                else:
                    explainer_feedback[cid] = issue["feedback"]
                    feedback_used.add(cid)
            elif code in MESH_ISSUES:
                mesh_issues.append(issue)
        if mesh_issues and revise_url:
            out, _ = a2a.send(revise_url, {"candidate_cut": candidate, "issues": mesh_issues}, skill="revise_cut")
            candidate = out["candidate_cut"]

    doc = _fallback(candidate, graph, profile, trace, session_id)
    (SESSIONS_DIR / session_id / "verified_cut.json").write_text(json.dumps(doc, indent=2))
    events.publish(session_id, "delivered", status="fallback", pass_count=len(trace))
    return doc


def explain_concept(data):
    """Tap-to-learn: render (or fetch) one explainer and fact-check it before it is shown. Budget 2."""
    graph, cid, level = data["concept_graph"], data["concept_node_id"], data.get("level", "intermediate")
    session_id = data.get("session_id", "tap")
    feedback = None
    for attempt in (1, 2):
        ex = _call("render_explainer", {"concept_graph": graph, "concept_node_id": cid, "level": level,
                                        "feedback": feedback}, session_id)
        stub = {"session_id": session_id, "threads": [], "quiz": []}
        verdict = _call("score_cut", {"candidate_cut": stub, "concept_graph": graph, "learner_profile": {},
                                      "explainers": {cid: ex}}, session_id)
        if verdict["scores"]["factuality"] >= 0.8:
            return {"approved": True, "clip_url": ex["clip_url"], "cached": ex.get("cached", False),
                    "storyboard": ex["storyboard"], "factuality": verdict["scores"]["factuality"], "attempts": attempt}
        feedback = [f for i in verdict["issues"] for f in i.get("feedback", [])]
    return {"approved": False, "reason": "explainer did not pass fact-checking", "issues": feedback}


def handle(skill, data):
    if skill == "explain_concept":
        return explain_concept(data)
    return verify_cut(data)
