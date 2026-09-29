"""Pedagogy agent: map each knowledge thread to this learner's level.

Deterministic, explainable policy (so a teacher can audit why a viewer saw what they saw):
    mastery >= 0.80 -> skip      (already known)
    mastery >= 0.60 -> condense  (quick refresher)
    mastery >= 0.35 -> keep
    otherwise       -> expand    (keep + auto explainer)
Pace shifts the thresholds. Role rules (roles come from the Curator): intro/setup can be skipped;
core ideas and safety are only ever condensed, never skipped; a concept whose prerequisite the learner
has not mastered is never skipped; explainers are spent on core/setup threads only.
"""

THRESHOLDS = {"skip": 0.80, "condense": 0.60, "keep": 0.35}
PACE_SHIFT = {"condensed": -0.10, "standard": 0.0, "detailed": +0.10}


def mastery_lookup(profile, video_id):
    table = {}
    for m in profile.get("mastery_graph", []):
        cid = m["concept_id"]
        table[cid] = m["level"]
        if "/" in cid and cid.split("/", 1)[0] == video_id:
            table[cid.split("/", 1)[1]] = m["level"]
    return table


def level_of(concept_ids, mastery, prior):
    vals = [mastery.get(c, prior) for c in concept_ids] or [prior]
    return sum(vals) / len(vals)


def learner_level(m):
    return "expert" if m >= 0.75 else "intermediate" if m >= 0.45 else "beginner"


def plan(threads, graph, profile):
    prefs = profile.get("preferences", {})
    shift = PACE_SHIFT.get(prefs.get("pace", "standard"), 0.0)
    prior = float(prefs.get("prior_knowledge", 0.3))
    mastery = mastery_lookup(profile, graph["video_id"])
    prereqs = {n["node_id"]: n.get("prerequisites", []) for n in graph["concept_nodes"]}

    planned = []
    for t in threads:
        m = level_of(t["concept_node_ids"], mastery, prior)
        if m >= THRESHOLDS["skip"] + shift:
            action, why = "skip", f"mastery {m:.2f} >= {THRESHOLDS['skip'] + shift:.2f}"
        elif m >= THRESHOLDS["condense"] + shift:
            action, why = "condense", f"mastery {m:.2f}: refresher only"
        elif m >= THRESHOLDS["keep"] + shift:
            action, why = "keep", f"mastery {m:.2f}: standard pacing"
        else:
            action, why = "expand", f"mastery {m:.2f}: needs an explainer"

        role = t.get("role", "core")
        if action == "skip" and role == "safety":
            action, why = "condense", "safety content is never skipped"
        if action == "skip" and role == "core":
            action, why = "condense", f"mastery {m:.2f}: core idea kept as a quick refresher"
        missing = [p for c in t["concept_node_ids"] for p in prereqs.get(c, [])
                   if mastery.get(p, prior) < THRESHOLDS["keep"]]
        if action == "skip" and missing:
            action, why = "condense", f"prerequisite {missing[0]} not yet mastered"
        if action == "skip" and role == "summary" and m < 0.9:
            action, why = "condense", "keep a short recap"
        if action == "expand" and role not in ("core", "setup"):
            action, why = "keep", f"mastery {m:.2f}: {role} segment kept, explainers go to core ideas"
        planned.append(dict(t, action=action, mastery=round(m, 2), level=learner_level(m), rationale=why))
    return planned


def handle(skill, data):
    return {"threads": plan(data["threads"], data["concept_graph"], data["learner_profile"])}
