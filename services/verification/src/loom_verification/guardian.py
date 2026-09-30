"""Guardian agent: object-level safety redaction.

1. tag_objects(): every tracked object gets safety tags + a severity, from the LLM (judged in lesson context)
   or, without one, from a hazard lexicon. Cached per video.
2. decide(): per viewer, the learner's family_safety_profile picks what is redacted. The mesh's
   redaction_requests are honoured (over-masking is the safe side) but the Guardian reviews every object,
   so a hazard the mesh missed is still caught.
3. build_masks(): one Contract C mask per visible instance inside the final threads: padded in time by one
   perception sample (an object seen at t may be on screen anywhere in (t - dt, t + dt)), a fallback_bbox
   covering every tracked box of that instance, and a matte video.
"""

from __future__ import annotations

import json
import logging
import re

from .config import Config
from .llm import LLM, LLMError
from .matte import render_matte
from .sources import GraphSource

log = logging.getLogger(__name__)

TAXONOMY = ["sharp_object", "injury_risk", "fire_or_explosion", "weapon", "blood_or_gore", "nudity",
            "drugs_or_alcohol", "hazardous_chemical", "disturbing", "none"]

# (pattern, tags, severity, child_unsafe) - used when no LLM is configured, and as a floor under the LLM.
LEXICON = [
    (r"broken glass|glass shards?|shards?|shattered", ["sharp_object", "injury_risk"], 0.8, True),
    (r"\bknife|knives|blade|razor|scalpel|scissors", ["sharp_object", "weapon"], 0.7, True),
    (r"needle|syringe", ["sharp_object", "injury_risk"], 0.7, True),
    (r"\bgun\b|pistol|rifle|firearm|weapon", ["weapon"], 0.9, True),
    (r"open flame|fire\b|flames?|explosion|burning", ["fire_or_explosion"], 0.6, True),
    (r"blood|wound|gore|injur", ["blood_or_gore", "disturbing"], 0.8, True),
    (r"beer|wine|alcohol|cigarette|vape|drug", ["drugs_or_alcohol"], 0.7, True),
    (r"nude|naked", ["nudity"], 0.95, True),
]

POLICY = {"off": None, "standard": 0.5, "strict": 0.2}

SAFETY_SYSTEM = f"""You are a child-safety reviewer for educational video. For each object seen in the video, decide
whether showing it could be unsuitable or upsetting for a young child watching with a parent. Judge the object
itself in the lesson context, not the lesson topic; ordinary lesson equipment is safe.
Tags must come from: {TAXONOMY}. severity: 0 (harmless) to 1 (clearly unsuitable).
Return JSON: {{"objects": [{{"object_id": str, "tags": [str], "severity": number, "child_unsafe": bool, "reason": str}}]}}"""


def lexicon_tags(label: str) -> dict:
    for pat, tags, sev, unsafe in LEXICON:
        if re.search(pat, label.lower()):
            return {"tags": tags, "severity": sev, "child_unsafe": unsafe, "reason": f"'{label}' matches {tags[0]}",
                    "source": "lexicon"}
    return {"tags": ["none"], "severity": 0.0, "child_unsafe": False, "reason": "no hazard", "source": "lexicon"}


class Guardian:
    def __init__(self, cfg: Config, llm: LLM | None):
        self.cfg, self.llm = cfg, llm

    def tag_objects(self, src: GraphSource) -> dict[str, dict]:
        graph = src.graph
        path = self.cfg.cache_dir / "guardian" / f"{src.video_id}.json"
        sig = [bool(self.llm)] + [(o["object_id"], o["label"]) for o in graph.get("objects", [])]
        if path.exists():
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("sig") == sig:
                return cached["tags"]
        tags = {o["object_id"]: lexicon_tags(o["label"]) for o in graph.get("objects", [])}
        judged_ok = True
        if self.llm and tags:
            context = " ".join(s["text"] for s in graph.get("transcript", []))[:1500]
            lines = [f"{o['object_id']}: '{o['label']}' (visible " +
                     ", ".join(f"{i['start']:.0f}-{i['end']:.0f}s" for i in o.get("instances", [])) + ")"
                     for o in graph["objects"]]
            try:
                out = self.llm.json(SAFETY_SYSTEM, f"LESSON CONTEXT: {context}\n\nOBJECTS:\n" + "\n".join(lines), role="safety")
                for o in out.get("objects", []):
                    oid = o.get("object_id")
                    if oid not in tags:
                        continue
                    judged = {"tags": [t for t in o.get("tags", []) if t in TAXONOMY] or ["none"],
                              "severity": float(o.get("severity", 0)), "child_unsafe": bool(o.get("child_unsafe")),
                              "reason": o.get("reason", ""), "source": self.llm.name}
                    # The lexicon is a floor: the model may add hazards, never talk one away.
                    if judged["severity"] >= tags[oid]["severity"] or "none" in tags[oid]["tags"]:
                        tags[oid] = judged
            except LLMError as e:
                judged_ok = False
                log.warning("Guardian LLM unavailable (%s); using the hazard lexicon", e)
        if judged_ok:   # a lexicon-only result from a failed LLM call is not cached, so the next run retries
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"sig": sig, "tags": tags}, indent=2), encoding="utf-8")
        return tags

    @staticmethod
    def decide(graph: dict, profile: dict, redaction_requests: list[dict], tags: dict[str, dict]) -> dict[str, str]:
        """{object_id: reason} for every object redacted for this viewer."""
        safety = profile.get("family_safety_profile") or {}
        level = safety.get("redaction_level", "standard")
        blocked = set(safety.get("blocked_tags", []))
        threshold = POLICY.get(level, POLICY["standard"])
        known = {o["object_id"] for o in graph.get("objects", [])}
        out: dict[str, str] = {}
        for oid in known:
            t = tags.get(oid, {})
            hit = blocked & set(t.get("tags", []))
            if hit:
                out[oid] = f"blocked tag {sorted(hit)[0]}"
            elif threshold is not None and t.get("severity", 0) >= threshold and (level == "strict" or t.get("child_unsafe")):
                out[oid] = f"family_safety_profile: {level} ({', '.join(x for x in t.get('tags', []) if x != 'none')})"
        if level != "off":
            for r in redaction_requests:
                if r.get("object_id") in known and r["object_id"] not in out:
                    out[r["object_id"]] = r.get("reason") or f"family_safety_profile: {level}"
        return out

    def build_masks(self, src: GraphSource, threads: list[dict], decisions: dict[str, str], *,
                    extra_pad_s: float = 0.0, render: bool = True) -> list[dict]:
        cfg = self.cfg
        masks = []
        for obj in src.graph.get("objects", []):
            if obj["object_id"] not in decisions:
                continue
            frames, sample_fps = src.mask_frames(obj)
            tpad = (1.0 / sample_fps if sample_fps else cfg.default_time_pad_s) + extra_pad_s
            for k, inst in enumerate(obj.get("instances", [])):
                start, end = max(0.0, inst["start"] - tpad), inst["end"] + tpad
                if not any(start < t["end"] and t["start"] < end for t in threads):
                    continue
                inst_frames = [f for f in frames if inst["start"] - 1e-6 <= f["t"] <= inst["end"] + 1e-6] or \
                              [{"t": inst["start"], "box": inst["bbox"]}]
                key = f"{src.video_id}/{obj['object_id']}_{k}.mp4"
                if render:
                    try:
                        render_matte(inst_frames, start, end, cfg.media_path(cfg.mask_bucket, key), fps=cfg.matte_fps,
                                     max_width=cfg.matte_max_width, pad=cfg.mask_pad)
                    except (RuntimeError, OSError) as e:
                        src.warnings.append(f"matte for {obj['object_id']} not rendered ({e}); fallback_bbox still applies")
                masks.append({
                    "object_id": obj["object_id"], "mask_url": cfg.media_url(cfg.mask_bucket, key),
                    "start": round(start, 2), "end": round(end, 2), "reason": decisions[obj["object_id"]],
                    "fallback_bbox": _union_box([f["box"] for f in inst_frames], cfg.mask_pad),
                })
        return sorted(masks, key=lambda m: m["start"])


def _union_box(boxes: list[list[float]], pad: float) -> list[float]:
    """Smallest box covering every tracked box of the instance, padded: a static CSS blur must cover the
    object wherever it moves during the mask window."""
    x0 = max(0.0, min(b[0] for b in boxes) - pad)
    y0 = max(0.0, min(b[1] for b in boxes) - pad)
    x1 = min(1.0, max(b[0] + b[2] for b in boxes) + pad)
    y1 = min(1.0, max(b[1] + b[3] for b in boxes) + pad)
    return [round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4)]
