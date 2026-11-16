"""Grounding ablation on the second ground-truthed lesson (Water Sciences: Glass Disposal).

    uv run python -m loom.eval.grounding_second     # -> data/eval/grounding_water_sciences.json

Vocabulary: the lesson's tracked object labels plus the objects its narration names (its ingest-time vocabulary is
not stored); the always-on hazard classes are added by the suite.
"""

from __future__ import annotations

import json

from loom.core.config import load_config
from loom.eval.common import EVAL_DATA, machine_info
from loom.eval.grounding_eval import run_grounding_eval

GT = EVAL_DATA / "groundtruth_water_sciences.json"
PHRASES = [
    "bottle",
    "glass disposal box",
    "glass pipette",
    "gloves",
    "safety goggles",
    "broom",
    "dustpan",
    "paper towel",
    "lab coat",
    "cardboard box",
]


def main() -> None:
    cfg = load_config()
    body = {
        "suite": "grounding",
        "lesson": "water_sciences",
        "machine": machine_info(),
        **run_grounding_eval(cfg, GT, PHRASES),
    }
    out = cfg.data_dir / "eval" / "grounding_water_sciences.json"
    out.write_text(json.dumps(body, indent=1), encoding="utf-8")
    print(json.dumps(body["ablation"], indent=1))


if __name__ == "__main__":
    main()
