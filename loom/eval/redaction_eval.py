"""`python -m loom.eval.redaction_eval` — per-viewer redaction against ground-truth hazard windows, and the hazard
ablation re-scored under other decision rules from the stored per-stage verdicts. CPU only; no model calls.

Two layers, kept apart on purpose:

* **end-to-end** (perception decides what is a hazard): the hazard tracks the grounding suite stored
  (`data/eval/grounding*.json`, one verdict per stage per track) → masked time with time pad 0 / 0.5 / 1.0 s →
  precision / recall / false-block / missed against the ground-truth windows at 0.1 s.
* **policy** (the Parent + child viewer's actual session masks over a lesson graph): what the Guardian + Critic mask
  for that viewer in the approved cut, as time, against the same windows, and which *safe* objects were masked.

The ablation re-scoring answers "are the stages really separated?": the same tracks, decided by SigLIP generic alone,
SigLIP look-alikes alone, the VLM alone, both (AND), and LOOM's rule (keep if SigLIP passes OR the VLM confirms).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loom.core.config import LoomConfig, load_config
from loom.eval.common import EVAL_DATA, machine_info
from loom.eval.grounding_eval import hazard_seconds, merge

PADS = (0.0, 0.5, 1.0)
LESSONS = {
    "acid_base_neutralization_d752a6": ("grounding.json", EVAL_DATA / "groundtruth_demo.json"),
    "water_sciences_laboratory_tutorial_glass_a98109": (
        "grounding_water_sciences.json",
        EVAL_DATA / "groundtruth_water_sciences.json",
    ),
}


def _rules(margin: float) -> dict[str, Any]:
    def sig(v: float | None) -> bool | None:
        return None if v is None else v >= margin

    return {
        "detector only": lambda t: True,
        "SigLIP generic only": lambda t: sig(t["siglip_generic"]) is not False,
        "SigLIP look-alikes only": lambda t: sig(t["siglip_lookalike"]) is not False,
        "VLM only": lambda t: t["vlm"] != "rejected",
        "SigLIP AND VLM": lambda t: sig(t["siglip_lookalike"]) is not False and t["vlm"] != "rejected",
        "SigLIP OR VLM (LOOM)": lambda t: sig(t["siglip_lookalike"]) is not False or t["vlm"] == "confirmed",
    }


def ablation(g: dict[str, Any], margin: float, duration: float, pad: float) -> dict[str, Any]:
    truth = [tuple(x) for x in g["hazard_truth"]]
    out = {}
    for name, keep in _rules(margin).items():
        kept = [t for t in g["hazard_tracks"] if keep(t)]
        pred = merge((max(0.0, t["start"] - pad), min(duration, t["end"] + pad)) for t in kept)
        out[name] = {"hazard_tracks": len(kept), **hazard_seconds(pred, truth, duration)}
    return out


def policy(cfg: LoomConfig, vid: str, truth: list[tuple[float, float]], safe_labels: set[str]) -> dict[str, Any]:
    from loom.agents.session import load_graph
    from loom.eval.critic_faults import _profile, approved_state

    out = {}
    for pad in PADS:
        c = cfg.model_copy(update={"safety": cfg.safety.model_copy(update={"time_pad_s": pad})})
        graph = load_graph(c.data_dir, vid)
        st, passes = approved_state(c, graph, _profile("family"))
        pred = merge((m.start, m.end) for m in st.masks)
        safe = [m for m in st.masks if m.label in safe_labels]
        out[f"pad {pad:g} s"] = {
            **hazard_seconds(pred, truth, graph.duration_seconds),
            "masks": len(st.masks),
            "masked_labels": sorted({m.label for m in st.masks}),
            "safe_objects_masked": sorted({m.label for m in safe}),
            "safe_object_seconds": round(sum(m.end - m.start for m in safe), 1),
            "passes": passes,
            "graph_source": "hand-authored fixture"
            if any("fixture" in str(o.safety.models) for o in graph.objects)
            else "perception ("
            + ", ".join(sorted({str(v) for o in graph.objects for v in o.safety.models.values()}))
            + ")",
        }
    return out


def run(cfg: LoomConfig) -> dict[str, Any]:
    body: dict[str, Any] = {
        "suite": "redaction",
        "machine": machine_info(),
        "pads_s": list(PADS),
        "configured_pad_s": cfg.safety.time_pad_s,
        "viewer": "Parent + child (learner_family)",
        "lessons": {},
    }
    for vid, (gfile, gt_path) in LESSONS.items():
        gt = json.loads(Path(gt_path).read_text(encoding="utf-8"))
        truth = [(float(h["start"]), float(h["end"])) for h in gt["hazards"]]
        safe = {k for k, v in gt.get("safety_labels", {}).items() if not v.get("child_unsafe")}
        entry: dict[str, Any] = {
            "hazard_truth": truth,
            "hazard_seconds": round(sum(b - a for a, b in truth), 2),
            "ground_truth": str(Path(gt_path).name),
            "annotation": gt.get("annotation", {"by": "generated with the synthetic lesson"}),
        }
        gpath = cfg.data_dir / "eval" / gfile
        if gpath.exists():
            g = json.loads(gpath.read_text(encoding="utf-8"))
            dur = float(gt["duration_seconds"])
            entry["end_to_end"] = {
                f"pad {p:g} s": ablation(g, cfg.perception.siglip_margin, dur, p)["SigLIP OR VLM (LOOM)"] for p in PADS
            }
            entry["ablation_rules"] = ablation(g, cfg.perception.siglip_margin, dur, cfg.safety.time_pad_s)
            entry["ablation_rules_pad0"] = ablation(g, cfg.perception.siglip_margin, dur, 0.0)
            entry["vlm_verdicts"] = {
                v: sum(1 for t in g["hazard_tracks"] if t["vlm"] == v)
                for v in sorted({t["vlm"] for t in g["hazard_tracks"]})
            }
            entry["tracks"] = [
                {
                    k: t[k]
                    for k in ("phrase", "start", "end", "siglip_generic", "siglip_lookalike", "vlm", "better_label")
                }
                for t in g["hazard_tracks"]
            ]
        entry["policy_family"] = policy(cfg, vid, truth, safe)
        body["lessons"][vid] = entry
    return body


def main() -> None:
    cfg = load_config()
    body = run(cfg)
    (cfg.data_dir / "eval" / "redaction.json").write_text(json.dumps(body, indent=1), encoding="utf-8")
    for vid, e in body["lessons"].items():
        print("==", vid, "truth", e["hazard_seconds"], "s")
        for k, v in e.get("end_to_end", {}).items():
            print("  e2e", k, {x: v[x] for x in ("precision", "recall", "false_block_s", "missed_s")})
        for k, v in e.get("ablation_rules", {}).items():
            print("  rule", k, v)
        print("  vlm", e.get("vlm_verdicts"))
        for k, v in e["policy_family"].items():
            print(
                "  policy",
                k,
                {
                    x: v[x]
                    for x in (
                        "precision",
                        "recall",
                        "false_block_s",
                        "missed_s",
                        "masked_labels",
                        "safe_objects_masked",
                        "graph_source",
                    )
                },
            )


if __name__ == "__main__":
    main()
