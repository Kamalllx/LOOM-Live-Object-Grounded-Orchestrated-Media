"""Build the golden fixtures (spec/06 S0) from the demo lesson's ground truth + hand-authored content.

    uv run python -m tests.fixtures.build_fixtures

Timings come from `tests/eval_data/groundtruth_demo.json` (the real built video), so fixtures line up with the media.
Everything else below — concepts, prerequisites, roles, quiz bank, safety records, object boxes, sample cuts — is
authored by hand and must be reviewed (see `tests/fixtures/README.md`). Masks are box-only here: real RLE masks
arrive with Stage 1 perception output, which replaces this graph.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loom.core.contracts.common import sha256_of
from loom.core.contracts.cuts import CandidateCut, VerifiedCut
from loom.core.contracts.graph import ConceptGraph
from loom.core.contracts.learner import LearnerProfile

HERE = Path(__file__).parent
GT = json.loads((HERE.parent / "eval_data" / "groundtruth_demo.json").read_text(encoding="utf-8"))
VIDEO = GT["video_id"]
NOW = datetime(2026, 10, 29, 0, 0, tzinfo=UTC).isoformat()
FIXTURE_JUDGE = "fixture:hand-authored"

SENT = {f"s_{i + 1:03d}": n for i, n in enumerate(GT["narration"])}
SEG = {s["id"]: s for s in GT["segments"]}


def sent_ids(segment: str) -> list[str]:
    return [sid for sid, n in SENT.items() if n["segment"] == segment]


def end_of(sid: str) -> float:
    return float(SENT[sid]["end"])


# ------------------------------------------------------------------------------------------------ graph content

SHOTS = {seg["id"]: f"sh_{i + 1:02d}" for i, seg in enumerate(GT["segments"])}

# (object_id, label, phrase_source, segment, box per instance) — boxes read off frames of the built video
OBJECTS: list[tuple[str, str, str, list[tuple[str, tuple[float, float, float, float]]]]] = [
    ("o_001", "gloves", "vlm", [("ppe", (0.27, 0.28, 0.48, 0.36))]),
    ("o_002", "lab coat", "vlm", [("acid_base", (0.55, 0.0, 0.45, 0.75))]),
    ("o_003", "microscope", "vlm", [("acid_base", (0.0, 0.05, 0.35, 0.80))]),
    (
        "o_004",
        "beaker",
        "transcript",
        [("reaction", (0.16, 0.02, 0.39, 0.96)), ("indicator", (0.42, 0.27, 0.23, 0.68))],
    ),
    ("o_005", "measuring cylinder", "vlm", [("reaction", (0.62, 0.0, 0.36, 1.0))]),
    ("o_006", "volumetric flask", "vlm", [("indicator", (0.0, 0.0, 0.22, 0.97))]),
    ("o_007", "broken glass", "hazard_class", [("hazard", (0.30, 0.05, 0.47, 0.80))]),
]

CONCEPTS: list[dict[str, Any]] = [
    {
        "node_id": "c_01",
        "label": "Personal Protective Equipment",
        "summary": "Wear a lab coat, gloves and safety goggles because acids and bases can damage skin and eyes.",
        "segments": sent_ids("ppe"),
        "text_ids": [],
        "object_ids": ["o_001", "o_002"],
        "prerequisites": [],
        "difficulty": "beginner",
        "canonical_key": "concept:lab_ppe",
    },
    {
        "node_id": "c_02",
        "label": "Acid Dissociation",
        "summary": "An acid such as hydrochloric acid releases hydrogen ions when it dissolves in water.",
        "segments": ["s_004", "s_005"],
        "text_ids": [],
        "object_ids": ["o_003"],
        "prerequisites": ["c_01"],
        "difficulty": "intermediate",
        "canonical_key": "concept:acid_dissociation",
    },
    {
        "node_id": "c_03",
        "label": "Base Dissociation",
        "summary": "A base such as sodium hydroxide releases hydroxide ions in water.",
        "segments": ["s_006"],
        "text_ids": [],
        "object_ids": [],
        "prerequisites": ["c_01"],
        "difficulty": "intermediate",
        "canonical_key": "concept:base_dissociation",
    },
    {
        "node_id": "c_04",
        "label": "Neutralization Reaction",
        "summary": "Hydrogen ions and hydroxide ions combine to form water; the remaining ions form a dissolved salt.",
        "segments": sent_ids("reaction") + sent_ids("summary"),
        "text_ids": ["x_002", "x_004"],
        "object_ids": ["o_004", "o_005"],
        "prerequisites": ["c_02", "c_03"],
        "difficulty": "intermediate",
        "canonical_key": "concept:neutralization",
    },
    {
        "node_id": "c_05",
        "label": "Indicator and Neutral pH",
        "summary": "Universal indicator shows when neutralization is complete by turning green at pH 7.",
        "segments": sent_ids("indicator"),
        "text_ids": ["x_003"],
        "object_ids": ["o_004", "o_006"],
        "prerequisites": ["c_04"],
        "difficulty": "beginner",
        "canonical_key": "concept:ph_indicator",
    },
    {
        "node_id": "c_06",
        "label": "Safe Handling of Broken Glass",
        "summary": "Never pick up broken glass by hand; tell the teacher and use a brush and dustpan.",
        "segments": sent_ids("hazard"),
        "text_ids": [],
        "object_ids": ["o_007"],
        "prerequisites": ["c_01"],
        "difficulty": "beginner",
        "canonical_key": "concept:broken_glass_safety",
    },
]

THREAD_ROLES = [
    (sent_ids("title"), "intro", "Lesson overview"),
    (sent_ids("ppe"), "safety", "Protective equipment before the experiment"),
    (sent_ids("acid_base"), "setup", "What acids and bases release in water"),
    (sent_ids("reaction"), "core", "Hydrogen and hydroxide ions form water and salt"),
    (sent_ids("indicator"), "core", "Indicator shows the neutral point"),
    (sent_ids("hazard"), "safety", "What to do when glassware breaks"),
    (sent_ids("summary"), "summary", "Acid plus base gives salt plus water"),
]

# (concept, level, stem, options, answer_index, evidence, rationale)
QUIZ: list[tuple[str, str, str, list[str], int, list[str], str]] = [
    (
        "c_01",
        "beginner",
        "Which items should you put on before an acid-base experiment?",
        ["A lab coat, gloves and safety goggles", "Only a lab coat", "A face mask only", "Nothing for small amounts"],
        0,
        ["s_002"],
        "The lesson lists a lab coat, gloves and safety goggles.",
    ),
    (
        "c_01",
        "intermediate",
        "Why does the lesson say protective equipment is needed?",
        [
            "Acids and bases can damage skin and eyes",
            "The beaker is heavy",
            "The lab is cold",
            "To keep the solution clean",
        ],
        0,
        ["s_003"],
        "Acids and bases can damage your skin and eyes.",
    ),
    (
        "c_01",
        "expert",
        "Which hazard of acids and bases do goggles specifically protect against?",
        ["Damage to the eyes", "Breathing in fumes", "Burns to the feet", "Electric shock"],
        0,
        ["s_002", "s_003"],
        "Goggles protect the eyes, which acids and bases can damage.",
    ),
    (
        "c_02",
        "beginner",
        "What does hydrochloric acid release in water?",
        ["Hydrogen ions", "Hydroxide ions", "Sodium ions", "Oxygen gas"],
        0,
        ["s_005"],
        "An acid such as hydrochloric acid releases hydrogen ions in water.",
    ),
    (
        "c_02",
        "intermediate",
        "Which ion makes a solution acidic, according to the lesson?",
        ["Hydrogen ion", "Chloride ion", "Hydroxide ion", "Sodium ion"],
        0,
        ["s_005"],
        "Acids release hydrogen ions.",
    ),
    (
        "c_02",
        "expert",
        "Hydrochloric acid dissolves in water. Which particle does the lesson say it releases?",
        ["H⁺ (hydrogen ion)", "OH⁻ (hydroxide ion)", "Na⁺ (sodium ion)", "H₂O (water molecule)"],
        0,
        ["s_005"],
        "The acid releases hydrogen ions (H⁺).",
    ),
    (
        "c_03",
        "beginner",
        "What does sodium hydroxide release in water?",
        ["Hydroxide ions", "Hydrogen ions", "Chloride ions", "Carbon dioxide"],
        0,
        ["s_006"],
        "A base such as sodium hydroxide releases hydroxide ions.",
    ),
    (
        "c_03",
        "intermediate",
        "Sodium hydroxide is an example of which kind of substance?",
        ["A base", "An acid", "A salt", "An indicator"],
        0,
        ["s_006"],
        "The lesson names sodium hydroxide as a base.",
    ),
    (
        "c_03",
        "expert",
        "Which ion released by sodium hydroxide later combines with hydrogen ions?",
        ["Hydroxide ion", "Sodium ion", "Chloride ion", "Oxide ion"],
        0,
        ["s_006", "s_007"],
        "Hydroxide ions from the base join hydrogen ions to form water.",
    ),
    (
        "c_04",
        "beginner",
        "What two products form when an acid neutralizes a base?",
        ["Salt and water", "Gas and heat", "Acid and oxygen", "Only water"],
        0,
        ["s_014"],
        "An acid plus a base gives a salt plus water.",
    ),
    (
        "c_04",
        "intermediate",
        "What forms when a hydrogen ion joins a hydroxide ion?",
        ["Water", "Table salt", "Hydrochloric acid", "Sodium hydroxide"],
        0,
        ["s_007"],
        "Each hydrogen ion joins a hydroxide ion to form water.",
    ),
    (
        "c_04",
        "expert",
        "After neutralizing hydrochloric acid with sodium hydroxide, what happens to the salt formed?",
        [
            "It stays dissolved in the water",
            "It falls out as a solid",
            "It escapes as a gas",
            "It turns back into acid",
        ],
        0,
        ["s_008"],
        "The sodium and chloride ions make table salt, which stays dissolved.",
    ),
    (
        "c_05",
        "beginner",
        "What colour does universal indicator turn at pH 7?",
        ["Green", "Red", "Purple", "Yellow"],
        0,
        ["s_010"],
        "Universal indicator turns green at pH seven.",
    ),
    (
        "c_05",
        "intermediate",
        "What does pH 7 mean, according to the lesson?",
        [
            "The solution is neutral",
            "The solution is strongly acidic",
            "The solution is strongly basic",
            "The reaction has not started",
        ],
        0,
        ["s_010"],
        "pH seven is neutral.",
    ),
    (
        "c_05",
        "expert",
        "Why is an indicator used during neutralization?",
        [
            "To show when the reaction is complete",
            "To speed up the reaction",
            "To make the salt dissolve",
            "To cool the solution",
        ],
        0,
        ["s_009"],
        "An indicator shows when the reaction is complete.",
    ),
    (
        "c_06",
        "beginner",
        "What should you do if glassware breaks?",
        [
            "Tell your teacher and use a brush and dustpan",
            "Pick up the pieces with your hands",
            "Leave it on the floor",
            "Wash it down the sink",
        ],
        0,
        ["s_012", "s_013"],
        "Never pick up the pieces by hand; tell your teacher and sweep them up.",
    ),
    (
        "c_06",
        "intermediate",
        "Why should broken glass never be picked up by hand?",
        ["The pieces are sharp", "The glass is hot", "The glass is acidic", "It is too heavy"],
        0,
        ["s_012"],
        "The lesson calls the broken pieces sharp.",
    ),
    (
        "c_06",
        "expert",
        "Which tools does the lesson recommend for cleaning up broken glass?",
        ["A brush and dustpan", "Gloves and tweezers", "A wet cloth", "A vacuum and mop"],
        0,
        ["s_013"],
        "Sweep them up with a brush and dustpan.",
    ),
]

LEVEL_CODE = {"beginner": "b", "intermediate": "i", "expert": "e"}


def build_graph() -> ConceptGraph:
    shots = [
        {
            "shot_id": SHOTS[s["id"]],
            "start": s["start"],
            "end": s["end"],
            "keyframes": [round(s["start"] + 0.5, 2), round((s["start"] + s["end"]) / 2, 2)],
        }
        for s in GT["segments"]
    ]
    transcript = [
        {"seg_id": sid, "start": n["start"], "end": n["end"], "text": n["text"], "words": [], "speaker": "narrator"}
        for sid, n in SENT.items()
    ]
    ocr = []
    for i, cap in enumerate(GT["on_screen_text"]):
        ocr.append(
            {
                "text_id": f"x_{i + 1:03d}",
                "start": cap["start"],
                "end": cap["end"],
                "text": cap["text"],
                "bbox": cap["bbox"],
                "confidence": 0.95,
                "reader": "glm-ocr" if "→" in cap["text"] else "rapidocr",
            }
        )
    objects = []
    for oid, label, source, instances in OBJECTS:
        insts = []
        for k, (segment, box) in enumerate(instances):
            s = SEG[segment]
            t0, t1 = float(s["start"]), float(s["end"])
            samples = [round(t0 + 0.5 * j, 2) for j in range(int((t1 - t0) / 0.5) + 1) if t0 + 0.5 * j <= t1]
            insts.append(
                {
                    "instance_id": f"{oid}_{k}",
                    "shot_id": SHOTS[segment],
                    "start": t0,
                    "end": t1,
                    "score": 0.8,
                    "track": [{"t": t, "bbox": box, "mask": None} for t in samples],
                    "verification": {
                        "siglip_margin": 0.3,
                        "vlm": "confirmed" if source == "hazard_class" else "not_run",
                        "status": "verified",
                    },
                }
            )
        labels = GT["safety_labels"][label]
        unsafe = bool(labels["child_unsafe"])
        objects.append(
            {
                "object_id": oid,
                "label": label,
                "phrase_source": source,
                "is_hazard_class": source == "hazard_class",
                "instances": insts,
                "safety": {
                    "status": "reviewed",
                    "tags": labels["tags"],
                    "severity": 0.9 if unsafe else 0.0,
                    "child_unsafe": unsafe,
                    "disagreement": False,
                    "reasons": {
                        "guardian": "fixture: sharp shards could cut a child"
                        if unsafe
                        else "fixture: ordinary lab equipment",
                        "vlm": "fixture",
                    },
                    "models": {"safety": FIXTURE_JUDGE, "vlm": FIXTURE_JUDGE},
                },
            }
        )
    concepts = [
        {
            "node_id": c["node_id"],
            "label": c["label"],
            "summary": c["summary"],
            "evidence": {"segment_ids": c["segments"], "text_ids": c["text_ids"], "object_ids": c["object_ids"]},
            "prerequisites": c["prerequisites"],
            "difficulty": c["difficulty"],
            "canonical_key": c["canonical_key"],
        }
        for c in CONCEPTS
    ]
    roles = [{"segment_ids": ids, "role": role, "gist": gist} for ids, role, gist in THREAD_ROLES]
    quiz = [
        {
            "question_id": f"q_{c.replace('_', '')}_{LEVEL_CODE[lvl]}_1",
            "concept_node_id": c,
            "level": lvl,
            "stem": stem,
            "options": opts,
            "answer_index": ans,
            "rationale": why,
            "evidence_segment_ids": ev,
            "verified_by": FIXTURE_JUDGE,
        }
        for c, lvl, stem, opts, ans, ev, why in QUIZ
    ]
    graph = ConceptGraph.model_validate(
        {
            "video_id": VIDEO,
            "title": GT["title"],
            "source": {"kind": "path", "ref": f"tests/eval_data/build/{VIDEO}.mp4"},
            "video_url": f"/media/videos/{VIDEO}.mp4",
            "duration_seconds": GT["duration_seconds"],
            "frame": {**GT["frame"], "content_rect": (0.0, 0.0, 1.0, 1.0)},
            "shots": shots,
            "transcript": transcript,
            "on_screen_text": ocr,
            "objects": objects,
            "concept_nodes": concepts,
            "thread_roles": roles,
            "quiz_bank": quiz,
            "perception_meta": {
                "pipeline_version": "fixture-0",
                "segmentation_tier": "fixture",
                "models": {"all": FIXTURE_JUDGE},
                "timings_s": {},
                "degraded": [],
                "stage_hashes": {"ground_truth": sha256_of(GT)},
            },
        }
    )
    return graph.sealed()


# ------------------------------------------------------------------------------------------------ learners

LEARNERS = {
    "learner_alex": {
        "display_name": "Alex",
        "persona": "Expert - wants the new idea without the setup",
        "preferences": {"pace": "condensed", "prior_knowledge": 0.85, "explainers": "tap_only"},
        "safety_profile": {"redaction_level": "off"},
    },
    "learner_priya": {
        "display_name": "Priya",
        "persona": "Beginner - new to this topic",
        "preferences": {"pace": "detailed", "prior_knowledge": 0.20, "explainers": "auto"},
        "safety_profile": {"redaction_level": "off"},
    },
    "learner_family": {
        "display_name": "Parent + child",
        "persona": "Co-viewing with a young child",
        "preferences": {"pace": "standard", "prior_knowledge": 0.40, "explainers": "tap_only"},
        "safety_profile": {
            "redaction_level": "standard",
            "blocked_tags": ["sharp_object", "injury_risk"],
            "parent_lock": True,
        },
    },
}


def build_learners() -> dict[str, LearnerProfile]:
    return {
        lid: LearnerProfile.model_validate({"learner_id": lid, **body}).with_state_sha()
        for lid, body in LEARNERS.items()
    }


# ------------------------------------------------------------------------------------------------ sample cuts

THREADS = [  # (thread_id, segment, concepts)
    ("t1", "title", []),
    ("t2", "ppe", ["c_01"]),
    ("t3", "acid_base", ["c_02", "c_03"]),
    ("t4", "reaction", ["c_04"]),
    ("t5", "indicator", ["c_05"]),
    ("t6", "hazard", ["c_06"]),
    ("t7", "summary", ["c_04"]),
]
ROLE = {tid: role for (tid, _, _), (_, role, _) in zip(THREADS, THREAD_ROLES, strict=True)}


def _span(segment: str) -> tuple[float, float]:
    return float(SEG[segment]["start"]), float(SEG[segment]["end"])


def build_candidate(
    graph: ConceptGraph,
    learner: LearnerProfile,
    plan: dict[str, tuple[str, str]],
    explainers: list[tuple[str, str]],
    redactions: list[str],
    quiz: list[str],
) -> CandidateCut:
    """plan: thread_id -> (action | 'skip', rationale). Condensed threads end at the sentence end listed in CONDENSE."""
    threads, skipped = [], []
    for tid, segment, concepts in THREADS:
        start, end = _span(segment)
        action, why = plan[tid]
        if action == "skip":
            skipped.append({"thread_id": tid, "start": start, "end": end, "rationale": why, "source": "pedagogy"})
            continue
        cut_end = round(end_of(CONDENSE[tid]) + 0.3, 2) if action == "condense" else end
        threads.append(
            {
                "thread_id": tid,
                "concept_node_ids": concepts,
                "role": ROLE[tid],
                "action": action,
                "start": start,
                "end": cut_end,
                "source_end": end,
                "rationale": why,
                "source": "pedagogy",
            }
        )
    ends = {tid: next(t["end"] for t in threads if t["thread_id"] == tid) for tid in {t["thread_id"] for t in threads}}
    by_concept = {c: tid for tid, _, cs in THREADS for c in cs}
    return CandidateCut.model_validate(
        {
            "session_id": f"sess_fixture{learner.learner_id.removeprefix('learner_')}",
            "video_id": graph.video_id,
            "graph_sha": graph.graph_sha,
            "learner_id": learner.learner_id,
            "learner_state_sha": learner.learner_state_sha,
            "pass_number": 1,
            "threads": threads,
            "skipped": skipped,
            "explainer_requests": [
                {"concept_node_id": c, "trigger": "auto", "level": lvl, "anchor_time": ends[by_concept[c]]}
                for c, lvl in explainers
            ],
            "redaction_requests": [
                {"object_id": o, "reason": "redaction level standard: object may be unsafe", "source": "personalizer"}
                for o in redactions
            ],
            "quiz": [{"question_id": q} for q in quiz],
            "agent_trace": [
                {"agent": "loom-curator", "version": "2.0", "skill": "build_threads", "latency_ms": 12, "status": "ok"},
                {"agent": "loom-pedagogy", "version": "2.0", "skill": "plan_threads", "latency_ms": 3, "status": "ok"},
                {
                    "agent": "loom-personalizer",
                    "version": "2.0",
                    "skill": "assemble_cut",
                    "latency_ms": 4,
                    "status": "ok",
                },
                {"agent": "loom-assessment", "version": "2.0", "skill": "select_quiz", "latency_ms": 2, "status": "ok"},
            ],
        }
    )


CONDENSE = {"t4": "s_007", "t5": "s_010"}


def build_verified(
    graph: ConceptGraph, cand: CandidateCut, status: str = "approved", mask_all: bool = False, reason: str | None = None
) -> VerifiedCut:
    labels = {c.node_id: c.label for c in graph.concept_nodes}
    objects = {o.object_id: o for o in graph.objects}
    bank = {q.question_id: q for q in graph.quiz_bank}
    masked = [o.object_id for o in graph.objects] if mask_all else [r.object_id for r in cand.redaction_requests]
    masks = []
    for oid in masked:
        obj = objects[oid]
        for inst in obj.instances:
            x, y, w, h = inst.track[0].bbox
            pad = 0.04
            box = (
                max(0.0, x - pad),
                max(0.0, y - pad),
                min(1.0 - max(0.0, x - pad), w + 2 * pad),
                min(1.0 - max(0.0, y - pad), h + 2 * pad),
            )
            masks.append(
                {
                    "mask_id": f"m_{inst.instance_id}",
                    "object_id": oid,
                    "label": obj.label,
                    "start": max(0.0, inst.start - 0.5),
                    "end": min(graph.duration_seconds, inst.end + 0.5),
                    "track_url": f"/media/masks/{graph.video_id}/{inst.instance_id}.json",
                    "fallback_bbox": box,
                    "style": "blur",
                    "reason": "safety review incomplete - extra masking applied"
                    if mask_all
                    else "blocked tag sharp_object",
                    "source": "guardian",
                    "enforced": True,
                }
            )
    clips = []
    if status == "approved":
        for req in cand.explainer_requests:
            storyboard = [f"{labels[req.concept_node_id]}: fixture storyboard line {i}." for i in (1, 2, 3)]
            h = sha256_of({"storyboard": storyboard, "concept": req.concept_node_id, "level": req.level})
            clips.append(
                {
                    "concept_node_id": req.concept_node_id,
                    "trigger": req.trigger,
                    "anchor_seconds": req.anchor_time,
                    "clip_url": f"/media/clips/{h.removeprefix('sha256:')}.mp4",
                    "content_hash": h,
                    "title": labels[req.concept_node_id],
                    "duration_seconds": 14.0,
                    "storyboard": storyboard,
                    "verified_by": FIXTURE_JUDGE,
                }
            )
    final = [
        {
            "thread_id": t.thread_id,
            "start": t.start,
            "end": t.end,
            "action": t.action,
            "label": labels[t.concept_node_ids[0]] if t.concept_node_ids else "Introduction",
            "rationale": t.rationale,
            "source": t.source,
        }
        for t in cand.threads
    ]
    score = {"safety": 1.0, "coherence": 1.0, "factuality": 1.0, "completeness": 1.0}
    return VerifiedCut.model_validate(
        {
            "session_id": cand.session_id,
            "video_id": cand.video_id,
            "learner_id": cand.learner_id,
            "status": status,
            "fallback_reason": reason,
            "pass_count": 1 if status == "approved" else 3,
            "cache_hit": False,
            "critic_score": score,
            "final_threads": final,
            "skipped": [
                {"start": s.start, "end": s.end, "rationale": s.rationale, "source": s.source} for s in cand.skipped
            ],
            "redaction_masks": masks,
            "explainer_clips": clips,
            "tap_targets": [
                {"object_id": c.evidence.object_ids[0], "concept_node_id": c.node_id}
                for c in graph.concept_nodes
                if c.evidence.object_ids
            ]
            if status == "approved"
            else [],
            "quiz": [
                {"question_id": q.question_id, "stem": bank[q.question_id].stem, "options": bank[q.question_id].options}
                for q in cand.quiz
            ]
            if status == "approved"
            else [],
            "loop_trace": [
                {
                    "pass_number": 1,
                    "approved": status == "approved",
                    "scores": score,
                    "issues": [],
                    "actions": [],
                    "latency_ms": 820,
                }
            ],
            "degraded": [] if status == "approved" else ["fallback: " + (reason or "")],
            "created_at": NOW,
        }
    )


def main() -> None:
    graph = build_graph()
    learners = build_learners()
    alex, priya, family = learners["learner_alex"], learners["learner_priya"], learners["learner_family"]
    keep = "mastery {m:.2f} (prior knowledge): keep at standard pace"
    cands = {
        "alex": build_candidate(
            graph,
            alex,
            {
                "t1": ("skip", "intro skipped: prior knowledge 0.85 >= 0.80 (condensed pace)"),
                "t2": ("keep", "safety threads are never skipped"),
                "t3": ("skip", "setup skipped: prior knowledge 0.85 >= 0.80; prerequisites of c_04 assumed known"),
                "t4": ("condense", "core never skipped: condensed (0.85 >= 0.60)"),
                "t5": ("condense", "core never skipped: condensed (0.85 >= 0.60)"),
                "t6": ("keep", "safety threads are never skipped"),
                "t7": ("skip", "summary skipped: prior knowledge 0.85 >= 0.80"),
            },
            [],
            [],
            ["q_c04_e_1", "q_c05_e_1"],
        ),
        "priya": build_candidate(
            graph,
            priya,
            {
                tid: ("expand", "mastery 0.20 < 0.35: expand with an explainer")
                if tid in ("t4", "t5")
                else ("keep", keep.format(m=0.20))
                for tid, _, _ in THREADS
            },
            [("c_04", "beginner"), ("c_05", "beginner")],
            [],
            ["q_c04_b_1", "q_c05_b_1", "q_c02_b_1"],
        ),
        "family": build_candidate(
            graph,
            family,
            {tid: ("keep", keep.format(m=0.40)) for tid, _, _ in THREADS},
            [],
            ["o_007"],
            ["q_c04_i_1", "q_c06_b_1"],
        ),
    }
    verified = {name: build_verified(graph, c) for name, c in cands.items()}
    verified["family_fallback"] = build_verified(
        graph,
        cands["family"],
        status="fallback",
        mask_all=True,
        reason="judge and safety models unavailable: conservative full-lesson cut, every object masked",
    )

    def dump(name: str, obj: Any) -> None:
        (HERE / name).write_text(
            json.dumps(obj.model_dump(mode="json", by_alias=True), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    dump("graph_demo_v2.json", graph)
    for lid, prof in learners.items():
        dump(f"{lid}.json", prof)
    for name, cand in cands.items():
        dump(f"candidate_cut_{name}.json", cand)
    for name, cut in verified.items():
        dump(f"verified_cut_{name}.json", cut)
    print(f"fixtures written for {graph.video_id} ({graph.graph_sha})")


if __name__ == "__main__":
    main()
