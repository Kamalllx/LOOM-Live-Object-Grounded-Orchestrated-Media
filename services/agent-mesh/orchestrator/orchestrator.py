"""Orchestrator: the A2A client at the centre of the mesh.

It never calls agent code directly. Agents are discovered through their Agent Cards and tasked over
JSON-RPC `message/send`, so a school's or publisher's own agent can join by publishing a card with a
matching skill (e.g. `policy_review`), with no rebuild.

Flow for one session:
  Curator.build_threads -> Pedagogy.plan_threads -> [plug-ins].policy_review -> Personalizer.assemble_cut
  -> Assessment.write_quiz -> candidate-cut.json -> Verification.verify_cut (bounded Critic loop)
The verification service calls back `revise_cut` on this orchestrator when the Critic rejects a pass.
"""
import json
import uuid

from loom_shared import a2a, contracts, events
from loom_shared.config import GRAPHS_DIR, LEARNERS_DIR, SESSIONS_DIR

REGISTRY = a2a.Registry()


def _agent(skill):
    cards = REGISTRY.with_skill(skill)
    if not cards:
        raise RuntimeError(f"no registered agent offers skill '{skill}'")
    return cards[0]


def call(skill, data, session_id=None, agent_card=None):
    card = agent_card or _agent(skill)
    if session_id:
        events.publish(session_id, "agent_call", agent=card["name"], skill=skill)
    out, meta = a2a.send(card["url"], data, skill=skill)
    if session_id:
        events.publish(session_id, "agent_done", agent=card["name"], skill=skill, latency_ms=meta["latency_ms"])
    return out, {"agent": card["name"], "version": card["version"], "skill": skill, "latency_ms": meta["latency_ms"]}


def _save(session_id, name, doc):
    d = SESSIONS_DIR / session_id
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(doc, indent=2))


def _load(session_id, name):
    return json.loads((SESSIONS_DIR / session_id / name).read_text())


def load_inputs(video_id, learner_id):
    graph = contracts.validate("concept-graph", json.loads((GRAPHS_DIR / f"{video_id}.json").read_text()))
    profile = contracts.validate("learner-profile", json.loads((LEARNERS_DIR / f"{learner_id}.json").read_text()))
    return graph, profile


def personalize(video_id, learner_id, session_id=None):
    """Build pass 1 of the candidate cut, then hand it to verification. Returns the verified cut."""
    session_id = session_id or f"sess_{uuid.uuid4().hex[:8]}"
    graph, profile = load_inputs(video_id, learner_id)
    events.publish(session_id, "session_start", video_id=video_id, learner_id=learner_id)
    trace = []

    out, meta = call("build_threads", {"concept_graph": graph}, session_id)
    trace.append(meta)
    out, meta = call("plan_threads", {"threads": out["threads"], "concept_graph": graph,
                                      "learner_profile": profile}, session_id)
    trace.append(meta)
    planned = out["threads"]

    plugin_requests = []
    for card in REGISTRY.with_skill("policy_review"):
        try:
            res, meta = call("policy_review", {"concept_graph": graph, "learner_profile": profile}, session_id, card)
            plugin_requests += res.get("redaction_requests", [])
            trace.append(meta)
        except Exception as e:  # a third-party agent failing must not break the session
            events.publish(session_id, "agent_error", agent=card["name"], error=str(e))

    cut, meta = call("assemble_cut", {"planned_threads": planned, "concept_graph": graph, "learner_profile": profile,
                                      "plugin_redaction_requests": plugin_requests}, session_id)
    trace.append(meta)
    candidate = {"schema_version": "1.0", "session_id": session_id, "video_id": video_id, "learner_id": learner_id,
                 "pass_number": 1, **cut, "quiz": [], "agent_trace": []}
    quiz, meta = call("write_quiz", {"candidate_cut": candidate, "concept_graph": graph, "learner_profile": profile},
                      session_id)
    trace.append(meta)
    candidate["quiz"] = quiz["quiz"]
    candidate["agent_trace"] = [{"agent": t["agent"], "version": t["version"], "note": t["skill"]} for t in trace]
    contracts.validate("candidate-cut", candidate)

    _save(session_id, "planned_threads.json", planned)
    _save(session_id, "candidate_pass1.json", candidate)
    events.publish(session_id, "candidate_ready", pass_number=1, threads=len(candidate["threads"]))

    verified, _ = call("verify_cut", {"candidate_cut": candidate, "concept_graph": graph, "learner_profile": profile,
                                      "revise_agent_url": REGISTRY.by_name("loom-orchestrator")["url"]}, session_id)
    return verified


def revise(data):
    """A2A skill `revise_cut`: apply Critic issues and return the next candidate pass."""
    candidate, issues = data["candidate_cut"], data["issues"]
    session_id = candidate["session_id"]
    graph, profile = load_inputs(candidate["video_id"], candidate["learner_id"])
    planned = _load(session_id, "planned_threads.json")

    structural = [i for i in issues if i.get("code") != "quiz_unsupported"]
    out, meta = call("revise_cut", {"candidate_cut": candidate, "planned_threads": planned, "concept_graph": graph,
                                    "issues": structural}, session_id)
    new = out["candidate_cut"]
    new["pass_number"] = candidate.get("pass_number", 1) + 1
    new["revision_feedback"] = [i.get("message", i.get("code", "")) for i in issues]
    new["agent_trace"] = candidate.get("agent_trace", []) + [{"agent": meta["agent"], "version": meta["version"],
                                                              "note": "revise_cut: " + "; ".join(out["notes"])}]
    quiz_issues = [i["message"] for i in issues if i.get("code") == "quiz_unsupported"]
    if quiz_issues or any(i.get("code") in ("missing_prerequisite", "empty_cut") for i in issues):
        q, meta = call("write_quiz", {"candidate_cut": new, "concept_graph": graph, "learner_profile": profile,
                                      "feedback": quiz_issues}, session_id)
        new["quiz"] = q["quiz"]
        new["agent_trace"].append({"agent": meta["agent"], "version": meta["version"], "note": "rewrite quiz"})
    contracts.validate("candidate-cut", new)
    _save(session_id, f"candidate_pass{new['pass_number']}.json", new)
    events.publish(session_id, "candidate_ready", pass_number=new["pass_number"], threads=len(new["threads"]))
    return {"candidate_cut": new}


def handle(skill, data):
    if skill == "revise_cut":
        return revise(data)
    if skill == "personalize":
        return personalize(data["video_id"], data["learner_id"], data.get("session_id"))
    raise ValueError(f"unknown skill {skill}")
