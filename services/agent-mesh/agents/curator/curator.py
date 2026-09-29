"""Curator agent: concept graph -> ordered, self-contained knowledge threads.

Threads partition the video timeline at sentence boundaries, so a thread never starts or ends
mid-sentence. Each transcript sentence belongs to the first concept that cites it; consecutive
sentences with the same owner form one thread. The LLM then labels each thread's teaching role.
"""
from loom_shared import llm

ROLE_SYSTEM = """You label segments of an instructional video by their teaching role.
Roles: "intro" (welcome/overview), "setup" (preparation, context), "core" (the main idea being taught),
"safety" (hazards or precautions), "summary" (recap).
Return JSON: {"roles": [{"thread_id": str, "role": str, "gist": one short sentence}]}"""

ROLES = {"intro", "setup", "core", "safety", "summary"}


def _owner_of_sentences(graph):
    owner = {}
    for node in graph["concept_nodes"]:
        for ref in node.get("transcript_refs", []):
            for i, s in enumerate(graph["transcript"]):
                if abs(s["start"] - ref["start"]) < 0.05 and i not in owner:
                    owner[i] = node["node_id"]
    return owner


def build_threads(graph):
    transcript = graph["transcript"]
    duration = graph.get("duration_seconds") or (transcript[-1]["end"] if transcript else 0)
    owner = _owner_of_sentences(graph)

    groups = []  # [(node_id or None, [sentence indexes])]
    for i in range(len(transcript)):
        nid = owner.get(i)
        if groups and groups[-1][0] == nid:
            groups[-1][1].append(i)
        else:
            groups.append((nid, [i]))

    threads = []
    for k, (nid, idxs) in enumerate(groups):
        start = 0.0 if k == 0 else transcript[idxs[0]]["start"]
        end = duration if k == len(groups) - 1 else transcript[groups[k + 1][1][0]]["start"]
        concept_ids = [nid] if nid else []
        # Pull in concepts evidenced only by on-screen text / objects inside this window.
        for node in graph["concept_nodes"]:
            refs = node.get("on_screen_text_refs", [])
            if node["node_id"] not in concept_ids and any(start <= r["start"] < end for r in refs) \
                    and not node.get("transcript_refs"):
                concept_ids.append(node["node_id"])
        threads.append({"thread_id": f"t{k + 1}", "concept_node_ids": concept_ids,
                        "start": round(start, 2), "end": round(end, 2),
                        "text": " ".join(transcript[i]["text"] for i in idxs)})

    if not threads:  # silent video: one thread per concept node, by its evidence window
        for k, node in enumerate(graph["concept_nodes"]):
            refs = node.get("on_screen_text_refs", [])
            if refs:
                threads.append({"thread_id": f"t{k + 1}", "concept_node_ids": [node["node_id"]],
                                "start": min(r["start"] for r in refs), "end": max(r["end"] for r in refs),
                                "text": node.get("summary", "")})

    _label_roles(threads, graph)
    return threads


def _label_roles(threads, graph):
    labels = {n["node_id"]: n["label"] for n in graph["concept_nodes"]}
    lines = [f"{t['thread_id']} ({t['start']:.0f}-{t['end']:.0f}s) concepts={[labels.get(c) for c in t['concept_node_ids']]}: "
             f"{t['text']}" for t in threads]
    try:
        roles = {r["thread_id"]: r for r in llm.complete(ROLE_SYSTEM, "\n".join(lines))["roles"]}
    except Exception as e:
        print(f"[curator] role labelling failed ({e}); defaulting to core")
        roles = {}
    for i, t in enumerate(threads):
        r = roles.get(t["thread_id"], {})
        role = r.get("role") if r.get("role") in ROLES else ("intro" if i == 0 else "core")
        t["role"], t["gist"] = role, r.get("gist", "")


def handle(skill, data):
    return {"threads": build_threads(data["concept_graph"])}
