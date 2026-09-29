"""Guardian agent: object-level safety redaction.  [Member 3 - Verification, Safety & Generation]

1. tag_objects(): every tracked object gets safety tags + severity from a dedicated safety model
   (gpt-oss-safeguard on Groq), judged with the lesson context. Cached per video.
2. decide(): per viewer, combine tags with the learner's family_safety_profile. The mesh's
   redaction_requests are hints; the Guardian reviews EVERY visible object, so a hazard the mesh
   missed is still caught. Plug-in (third-party) requests are honoured - over-masking is the safe side.
3. build_masks(): for each redacted object, one mask per visible instance inside the final cut,
   with a padded per-second track the player interpolates for a smooth spatial blur.
"""
import json

from loom_shared import llm
from loom_shared.config import CACHE_DIR, MASKS_DIR

TAXONOMY = ["sharp_object", "injury_risk", "fire_or_explosion", "weapon", "blood_or_gore", "nudity",
            "drugs_or_alcohol", "hazardous_chemical", "disturbing", "none"]

SAFETY_SYSTEM = f"""You are a child-safety reviewer for educational video. For each object seen in the video,
decide whether showing it could be unsuitable or upsetting for a young child watching with a parent.
Judge the object itself in the lesson context, not the lesson topic. Ordinary lab equipment is safe.
Tags must come from: {TAXONOMY}. severity: 0 (harmless) to 1 (clearly unsuitable).
Return JSON: {{"objects": [{{"object_id": str, "tags": [str], "severity": float, "child_unsafe": bool,
"reason": short string}}]}}"""

POLICY = {
    "off": None,
    "standard": 0.5,   # redact child_unsafe objects with severity >= 0.5
    "strict": 0.2,     # redact anything tagged with severity >= 0.2
}
MASK_PAD = 0.04        # pad boxes so edges of the object never peek out
# Perception samples once per second, so an object seen at sample t may be on screen anywhere in
# (t - 1 s, t + 1 s). Masks are padded by one sampling interval on each side: safety errs toward covering.
TIME_PAD_S = 1.0


def tag_objects(graph):
    cache = CACHE_DIR / "guardian"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{graph['video_id']}.json"
    if path.exists():
        return json.loads(path.read_text())
    if not graph["objects"]:
        return {}
    context = " ".join(s["text"] for s in graph["transcript"])[:1500]
    lines = [f"{o['object_id']}: '{o['label']}' (visible "
             + ", ".join(f"{i['start']:.0f}-{i['end']:.0f}s" for i in o["instances"]) + ")" for o in graph["objects"]]
    try:
        out = llm.complete(SAFETY_SYSTEM, f"LESSON CONTEXT: {context}\n\nOBJECTS:\n" + "\n".join(lines), role="safety")
        tags = {o["object_id"]: {"tags": [t for t in o.get("tags", []) if t in TAXONOMY] or ["none"],
                                 "severity": float(o.get("severity", 0)), "child_unsafe": bool(o.get("child_unsafe")),
                                 "reason": o.get("reason", "")} for o in out["objects"]}
    except Exception as e:
        print(f"[guardian] safety model failed ({e}); treating every object as unreviewed")
        tags = {}
    for o in graph["objects"]:  # an object the model skipped is unreviewed, not safe
        tags.setdefault(o["object_id"], {"tags": ["none"], "severity": 0.0, "child_unsafe": False,
                                         "reason": "not reviewed"})
    path.write_text(json.dumps(tags, indent=2))
    return tags


def decide(graph, profile, redaction_requests, tags):
    """Returns {object_id: reason} of objects to redact for this viewer."""
    safety = profile.get("family_safety_profile", {})
    level = safety.get("redaction_level", "standard")
    blocked = set(safety.get("blocked_tags", []))
    threshold = POLICY.get(level)
    decisions = {}
    for obj in graph["objects"]:
        t = tags.get(obj["object_id"], {})
        hit_blocked = blocked & set(t.get("tags", []))
        if hit_blocked:
            decisions[obj["object_id"]] = f"blocked tag {sorted(hit_blocked)[0]}"
        elif threshold is not None and t.get("severity", 0) >= threshold and (level == "strict" or t.get("child_unsafe")):
            decisions[obj["object_id"]] = f"{level} policy: {t.get('reason') or ', '.join(t.get('tags', []))}"
    if level != "off":
        for r in redaction_requests:
            if r["object_id"] not in decisions and "family_safety_profile" not in r.get("reason", "") \
                    and any(o["object_id"] == r["object_id"] for o in graph["objects"]):
                decisions[r["object_id"]] = f"plug-in request: {r.get('reason', '')}"
    return decisions


def _pad(b):
    x, y = max(0.0, b[0] - MASK_PAD), max(0.0, b[1] - MASK_PAD)
    return [round(x, 4), round(y, 4), round(min(1 - x, b[2] + 2 * MASK_PAD), 4), round(min(1 - y, b[3] + 2 * MASK_PAD), 4)]


def build_masks(graph, threads, decisions):
    masks = []
    for obj in graph["objects"]:
        if obj["object_id"] not in decisions:
            continue
        for k, inst in enumerate(obj["instances"]):
            if not any(inst["start"] - TIME_PAD_S < t["end"] and t["start"] < inst["end"] + TIME_PAD_S for t in threads):
                continue
            track = [{"t": p["t"], "bbox": _pad(p["bbox"])} for p in inst.get("track", [])] or \
                    [{"t": inst["start"], "bbox": _pad(inst["bbox"])}]
            name = f"{graph['video_id']}_{obj['object_id']}_{k}.json"
            (MASKS_DIR / name).write_text(json.dumps({"object_id": obj["object_id"], "label": obj["label"],
                                                      "start": inst["start"], "end": inst["end"], "track": track}))
            masks.append({"object_id": obj["object_id"], "mask_url": f"/media/masks/{name}",
                          "start": round(max(0.0, inst["start"] - TIME_PAD_S), 2),
                          "end": round(inst["end"] + TIME_PAD_S, 2), "bbox": _pad(inst["bbox"]),
                          "style": "blur", "reason": decisions[obj["object_id"]]})
    return masks


def handle(skill, data):
    graph = data["concept_graph"]
    tags = tag_objects(graph)
    decisions = decide(graph, data["learner_profile"], data.get("redaction_requests", []), tags)
    return {"decisions": decisions, "tags": tags,
            "redaction_masks": build_masks(graph, data["threads"], decisions)}
