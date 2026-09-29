"""Assessment agent: targeted checks + mastery updates.

write_quiz(): multiple-choice questions grounded in what the viewer actually watched, prioritising
the concepts this learner knows least. Questions must be answerable from the transcript.
update_mastery(): folds a session-log into the learner's mastery graph (Contract D -> A2).
"""
from loom_shared import llm

QUIZ_SYSTEM = """You write short multiple-choice checks for an instructional video.
Only ask about facts stated in the provided transcript excerpts. One question per concept given.
Each question: 4 options, exactly one correct, plausible distractors, no "all of the above".
Match the difficulty to the learner level. Return JSON:
{"quiz": [{"concept_node_id": str, "question": str, "options": [str, str, str, str], "answer_index": int}]}"""

MAX_QUESTIONS = 3

# Mastery update rule (exponential moving estimate):
#   correct answer   : m <- m + 0.35 * (1 - m)
#   wrong answer     : m <- m * 0.75
#   explainer watched: m <- m + 0.05 * (1 - m)
#   thread watched   : m <- m + 0.03 * (1 - m)   (exposure only)


def _excerpt(graph, node):
    refs = node.get("transcript_refs", [])
    lines = [s["text"] for s in graph["transcript"] if any(abs(s["start"] - r["start"]) < 0.05 for r in refs)]
    return " ".join(lines) or node.get("summary", "")


def write_quiz(candidate, graph, profile, feedback=()):
    in_cut = [c for t in candidate["threads"] for c in t["concept_node_ids"]]
    nodes = {n["node_id"]: n for n in graph["concept_nodes"]}
    mastery = {m["concept_id"].split("/")[-1]: m["level"] for m in profile.get("mastery_graph", [])}
    prior = profile.get("preferences", {}).get("prior_knowledge", 0.3)
    targets = sorted(dict.fromkeys(c for c in in_cut if c in nodes), key=lambda c: mastery.get(c, prior))[:MAX_QUESTIONS]
    if not targets:
        return []
    level = "expert" if prior >= 0.75 else "beginner" if prior < 0.45 else "intermediate"
    prompt = [f"Learner level: {level}"]
    for c in targets:
        prompt.append(f"\nconcept_node_id={c} label={nodes[c]['label']}\nTRANSCRIPT: {_excerpt(graph, nodes[c])}")
    if feedback:
        prompt.append("\nA reviewer rejected the previous questions: " + "; ".join(feedback) + ". Fix these problems.")
    try:
        quiz = llm.complete(QUIZ_SYSTEM, "\n".join(prompt), use_cache=not feedback)["quiz"]
    except Exception as e:
        print(f"[assessment] quiz generation failed: {e}")
        return []
    clean = []
    for q in quiz:
        opts = q.get("options") or []
        if q.get("concept_node_id") in targets and len(opts) == 4 and isinstance(q.get("answer_index"), int) \
                and 0 <= q["answer_index"] < 4:
            clean.append({"question": q["question"], "concept_node_id": q["concept_node_id"],
                          "options": [str(o) for o in opts], "answer_index": q["answer_index"]})
    return clean


def update_mastery(profile, session_log, video_id, now_iso):
    table = {m["concept_id"]: dict(m) for m in profile.get("mastery_graph", [])}
    prior = profile.get("preferences", {}).get("prior_knowledge", 0.3)
    updates = {}

    def bump(cid, fn):
        key = f"{video_id}/{cid}"
        cur = updates.get(key, table.get(key, {}).get("level", table.get(cid, {}).get("level", prior)))
        updates[key] = round(min(1.0, max(0.0, fn(cur))), 3)

    for ev in session_log.get("events", []):
        p = ev.get("payload") or {}
        cid = p.get("concept_node_id")
        if not cid:
            continue
        if ev["type"] == "quiz_answered":
            bump(cid, (lambda m: m + 0.35 * (1 - m)) if p.get("correct") else (lambda m: m * 0.75))
        elif ev["type"] == "explainer_shown":
            bump(cid, lambda m: m + 0.05 * (1 - m))
        elif ev["type"] == "play" and p.get("thread_complete"):
            bump(cid, lambda m: m + 0.03 * (1 - m))
    for key, level in updates.items():
        table[key] = {"concept_id": key, "level": level, "last_seen": now_iso}
    profile = dict(profile, mastery_graph=list(table.values()))
    return profile, [{"concept_id": k, "new_level": v} for k, v in updates.items()]


def handle(skill, data):
    if skill == "update_mastery":
        profile, updates = update_mastery(data["learner_profile"], data["session_log"], data["video_id"], data["now"])
        return {"learner_profile": profile, "mastery_updates": updates}
    return {"quiz": write_quiz(data["candidate_cut"], data["concept_graph"], data["learner_profile"],
                               data.get("feedback", []))}
