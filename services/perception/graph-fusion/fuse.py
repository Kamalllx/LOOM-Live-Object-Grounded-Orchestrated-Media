"""Graph fusion: merge objects + transcript + on-screen text into concept nodes (concept-graph.json).

Two LLM steps:
  1. object_vocabulary(): read the lesson (transcript + OCR) and list the physical things worth
     grounding - these phrases prompt the detector, so perception adapts to any video.
  2. fuse(): group evidence into concept nodes; every node points at real transcript/OCR time
     ranges and object ids. A deterministic fallback keeps ingest working without an LLM.
"""
import json

from loom_shared import llm

VOCAB_SYSTEM = """You help a video-understanding system decide which physical objects to look for.
Given a lesson transcript and on-screen text, list short noun phrases (1-3 words) for VISIBLE, physical,
solid objects that a camera would show and that matter for teaching. No abstract ideas, no people's
names, no text/diagrams, no liquids or chemicals (a camera sees the container, not the substance).
Use the narrator's own words for objects, and never list two phrases for the same kind of thing
(e.g. not both "beaker" and "glass container"); prefer the more specific term.
Return JSON: {"phrases": ["...", ...]} with at most 8 phrases, most important first."""

FUSE_SYSTEM = """You build a spatio-temporal concept graph for an instructional video.
Input: numbered transcript sentences (with times), numbered on-screen text items, and detected objects
(with the time ranges they are visible). Group the evidence into 3-8 teachable concepts.
Rules:
- Each concept must cite at least one transcript index.
- Cite an object only if it is visible during that concept's transcript/on-screen times and relevant.
- Hazard objects (e.g. broken glass) belong to a safety concept.
- "prerequisites" lists labels of other concepts in this graph that should be understood first.
- Fix obvious OCR errors when you write "clean_text" (e.g. HCI -> HCl, H20 -> H2O).
Return JSON: {"concepts": [{"label": str, "summary": one sentence, "transcript_idx": [int],
"ocr_idx": [int], "object_ids": [str], "prerequisites": [str]}], "clean_text": {"<ocr index>": str}}"""


HAZARD_PHRASES = ["broken glass", "knife", "open flame"]
MAX_LESSON_PHRASES = 6


def object_vocabulary(transcript, on_screen_text):
    """Lesson objects chosen by the LLM + safety hazards that are ALWAYS searched for, so redaction
    never depends on the narration happening to mention a hazard."""
    lesson = "\n".join(s["text"] for s in transcript)
    screen = "\n".join(o["text"] for o in on_screen_text)
    try:
        phrases = llm.complete(VOCAB_SYSTEM, f"TRANSCRIPT:\n{lesson}\n\nON-SCREEN TEXT:\n{screen}",
                               temperature=0)["phrases"]
        phrases = [p.lower().strip() for p in phrases if isinstance(p, str) and 0 < len(p.split()) <= 3]
    except Exception as e:
        print(f"[fusion] vocabulary LLM failed ({e}); using generic phrases")
        phrases = []
    hazard_words = {w for h in HAZARD_PHRASES for w in h.split()}
    lesson_phrases = [p for p in phrases if not set(p.split()) & hazard_words and p not in HAZARD_PHRASES]
    lesson_phrases = (lesson_phrases or ["person", "tool", "container"])[:MAX_LESSON_PHRASES]
    return lesson_phrases + HAZARD_PHRASES


def _overlaps(a_start, a_end, b_start, b_end, slack=1.0):
    return a_start < b_end + slack and b_start < a_end + slack


def _fallback_nodes(transcript, objects):
    nodes = []
    for i, s in enumerate(transcript):
        objs = [o["object_id"] for o in objects if any(_overlaps(s["start"], s["end"], x["start"], x["end"], 0)
                                                        for x in o["instances"])]
        nodes.append({"label": " ".join(s["text"].split()[:5]), "summary": s["text"], "transcript_idx": [i],
                      "ocr_idx": [], "object_ids": objs, "prerequisites": []})
    return nodes


def fuse(transcript, on_screen_text, objects):
    lines = ["TRANSCRIPT:"] + [f"[{i}] {s['start']:.1f}-{s['end']:.1f}s: {s['text']}" for i, s in enumerate(transcript)]
    lines += ["", "ON-SCREEN TEXT:"] + [f"[{i}] {o['start']:.1f}-{o['end']:.1f}s: {o['text']}"
                                        for i, o in enumerate(on_screen_text)]
    lines += ["", "OBJECTS:"] + [f"{o['object_id']} '{o['label']}' visible " +
                                 ", ".join(f"{x['start']:.0f}-{x['end']:.0f}s" for x in o["instances"])
                                 for o in objects]
    try:
        result = llm.complete(FUSE_SYSTEM, "\n".join(lines))
        concepts = result["concepts"]
        clean = result.get("clean_text") or {}
    except Exception as e:
        print(f"[fusion] LLM failed ({e}); using one node per sentence")
        concepts, clean = _fallback_nodes(transcript, objects), {}

    for idx, text in clean.items():
        if str(idx).isdigit() and int(idx) < len(on_screen_text) and isinstance(text, str) and text.strip():
            on_screen_text[int(idx)]["text"] = text.strip()

    valid_objects = {o["object_id"]: o for o in objects}
    nodes, labels = [], {}
    for c in concepts:
        t_idx = [i for i in c.get("transcript_idx", []) if isinstance(i, int) and 0 <= i < len(transcript)]
        o_idx = [i for i in c.get("ocr_idx", []) if isinstance(i, int) and 0 <= i < len(on_screen_text)]
        if not t_idx and not o_idx:
            continue
        refs = [transcript[i] for i in t_idx] + [on_screen_text[i] for i in o_idx]
        start, end = min(r["start"] for r in refs), max(r["end"] for r in refs)
        # Keep only objects actually visible while this concept is on screen (grounding check).
        obj_ids = [oid for oid in c.get("object_ids", []) if oid in valid_objects and any(
            _overlaps(start, end, x["start"], x["end"]) for x in valid_objects[oid]["instances"])]
        node_id = f"c_{len(nodes) + 1:02d}"
        labels[c["label"].lower()] = node_id
        nodes.append({
            "node_id": node_id, "label": c["label"], "summary": c.get("summary", ""),
            "object_ids": obj_ids,
            "transcript_refs": [{"start": transcript[i]["start"], "end": transcript[i]["end"]} for i in t_idx],
            "on_screen_text_refs": [{"start": on_screen_text[i]["start"], "end": on_screen_text[i]["end"]} for i in o_idx],
            "_prereq_labels": c.get("prerequisites", []),
        })
    for n in nodes:
        n["prerequisites"] = [labels[p.lower()] for p in n.pop("_prereq_labels") if p.lower() in labels
                              and labels[p.lower()] != n["node_id"]]
    nodes.sort(key=lambda n: min([r["start"] for r in n["transcript_refs"] + n["on_screen_text_refs"]]))
    renumber = {n["node_id"]: f"c_{i:02d}" for i, n in enumerate(nodes, 1)}
    for n in nodes:
        n["node_id"] = renumber[n["node_id"]]
        n["prerequisites"] = [renumber[p] for p in n["prerequisites"]]
    return nodes
