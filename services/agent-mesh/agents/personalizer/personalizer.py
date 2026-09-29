"""Personalizer agent: assemble the viewer's candidate cut from planned threads.

- skip     -> dropped
- condense -> trimmed to its first ~half, ending on a sentence boundary (and never before an
              on-screen formula/caption has been shown for 3 s)
- keep     -> as is
- expand   -> kept + an automatic Manim explainer anchored at the thread's end
Every concept with a tracked object also gets a tap-to-explain request (click-to-learn).
When the Critic rejects a pass, `revise()` applies its structured issues.
"""
import copy

CONDENSE_RATIO = 0.5
CONDENSE_MIN_S = 6.0


def _sentence_ends(graph, start, end):
    return [s["end"] for s in graph["transcript"] if start < s["end"] <= end + 0.05]


def _condensed_end(t, graph):
    target = t["start"] + max(CONDENSE_MIN_S, CONDENSE_RATIO * (t["end"] - t["start"]))
    for node in graph["concept_nodes"]:
        if node["node_id"] in t["concept_node_ids"]:
            for r in node.get("on_screen_text_refs", []):
                if t["start"] <= r["start"] < t["end"]:
                    target = max(target, r["start"] + 3.0)
    ends = [e for e in _sentence_ends(graph, t["start"], t["end"]) if e >= target]
    return round(min(ends[0] if ends else t["end"], t["end"]), 2)


def _level_for(threads):
    levels = [t.get("level", "intermediate") for t in threads if t["action"] != "skip"]
    return max(set(levels), key=levels.count) if levels else "intermediate"


def assemble(planned, graph, profile, plugin_requests=()):
    kept = []
    explainers = []
    for t in planned:
        if t["action"] == "skip":
            continue
        cut = {"thread_id": t["thread_id"], "concept_node_ids": t["concept_node_ids"], "action": t["action"],
               "start": t["start"], "end": _condensed_end(t, graph) if t["action"] == "condense" else t["end"],
               "note": t.get("rationale", "")}
        kept.append(cut)
        if t["action"] == "expand":
            for cid in t["concept_node_ids"][:1]:
                explainers.append({"concept_node_id": cid, "trigger": "auto", "anchor_time": cut["end"],
                                   "level": t.get("level", "beginner")})

    auto_ids = {e["concept_node_id"] for e in explainers}
    level = _level_for(planned)
    shown = [(c["start"], c["end"]) for c in kept]
    for node in graph["concept_nodes"]:
        if node["object_ids"] and node["node_id"] not in auto_ids:
            explainers.append({"concept_node_id": node["node_id"], "trigger": "tap", "level": level})

    redactions = []
    safety = profile.get("family_safety_profile", {})
    if safety.get("redaction_level", "standard") != "off":
        for obj in graph["objects"]:
            if any(i["start"] < e and s < i["end"] for i in obj["instances"] for s, e in shown):
                redactions.append({"object_id": obj["object_id"],
                                   "reason": f"review under family_safety_profile ({safety.get('redaction_level', 'standard')})"})
    known = {r["object_id"] for r in redactions}
    for r in plugin_requests:
        if r["object_id"] not in known:
            redactions.append(r)
            known.add(r["object_id"])
    return {"threads": kept, "explainer_requests": explainers, "redaction_requests": redactions}


def revise(candidate, planned, graph, issues):
    """Apply the Critic's structured issues to produce the next pass."""
    cut = copy.deepcopy(candidate)
    by_id = {t["thread_id"]: t for t in planned}
    notes = []
    for issue in issues:
        code = issue.get("code")
        if code == "cut_mid_sentence":
            for t in cut["threads"]:
                if t["thread_id"] == issue.get("thread_id"):
                    ends = [e for e in _sentence_ends(graph, t["start"], by_id[t["thread_id"]]["end"]) if e >= t["end"]]
                    t["end"] = round(ends[0] if ends else by_id[t["thread_id"]]["end"], 2)
                    notes.append(f"extended {t['thread_id']} to sentence end")
        elif code == "missing_prerequisite":
            cid = issue.get("concept_node_id")
            src = next((t for t in planned if cid in t["concept_node_ids"]), None)
            if src and all(t["thread_id"] != src["thread_id"] for t in cut["threads"]):
                cut["threads"].append({"thread_id": src["thread_id"], "concept_node_ids": src["concept_node_ids"],
                                       "action": "condense", "start": src["start"],
                                       "end": _condensed_end(src, graph), "note": "re-added as prerequisite"})
                notes.append(f"re-added prerequisite {cid}")
        elif code == "explainer_unavailable":
            cut["explainer_requests"] = [e for e in cut["explainer_requests"]
                                         if e["concept_node_id"] != issue.get("concept_node_id")]
            notes.append(f"dropped explainer for {issue.get('concept_node_id')}")
        elif code in ("overlapping_threads", "out_of_order"):
            cut["threads"].sort(key=lambda t: t["start"])
            for a, b in zip(cut["threads"], cut["threads"][1:]):
                if b["start"] < a["end"]:
                    a["end"] = b["start"]
            notes.append("re-ordered threads")
        elif code == "empty_cut":
            cut["threads"] = [{"thread_id": t["thread_id"], "concept_node_ids": t["concept_node_ids"],
                               "action": "condense", "start": t["start"], "end": _condensed_end(t, graph),
                               "note": "fallback: condensed full lesson"} for t in planned]
            notes.append("restored condensed lesson")
    cut["threads"].sort(key=lambda t: t["start"])
    return cut, notes


def handle(skill, data):
    if skill == "revise_cut":
        cut, notes = revise(data["candidate_cut"], data["planned_threads"], data["concept_graph"], data["issues"])
        return {"candidate_cut": cut, "notes": notes}
    return assemble(data["planned_threads"], data["concept_graph"], data["learner_profile"],
                    data.get("plugin_redaction_requests", []))
