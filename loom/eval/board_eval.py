"""Board-lesson report: what the board/animation stage contributed to a processed graph (no ground truth needed).

    uv run python -m loom.eval.board_eval <video_id> [<video_id> ...]

Writes data/eval/board.json: per video, board-like share, board elements by kind, instances, mask samples, concepts
citing board elements, verified quiz questions, timings, and graph size. Compared against the same lesson processed
before the stage existed when that graph is given as `old=<path>`.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from loom.core.contracts.graph import ConceptGraph


def report(path: Path) -> dict[str, Any]:
    g = ConceptGraph.model_validate_json(path.read_text(encoding="utf-8"))
    board = [o for o in g.objects if o.phrase_source == "board"]
    things = [o for o in g.objects if o.phrase_source != "board"]
    board_ids = {o.object_id for o in board}
    cited = [c for c in g.concept_nodes if board_ids & set(c.evidence.object_ids)]
    return {
        "video_id": g.video_id, "title": g.title, "duration_s": g.duration_seconds,
        "board": g.perception_meta.models.get("board", "n/a"),
        "board_elements": len(board), "by_kind": dict(Counter(o.element_kind or "text" for o in board)),
        "board_instances": sum(len(o.instances) for o in board),
        "board_mask_samples": sum(len(i.track) for o in board for i in o.instances),
        "scene_objects": len(things),
        "on_screen_text_spans": len(g.on_screen_text), "concepts": len(g.concept_nodes),
        "concepts_citing_board": len(cited), "quiz_questions": len(g.quiz_bank),
        "labels": [f"{o.element_kind}: {o.label}" for o in board],
        "timings_s": g.perception_meta.timings_s, "degraded": g.perception_meta.degraded,
        "graph_kb": round(path.stat().st_size / 1024),
    }


def main(argv: list[str]) -> int:
    data = Path("data")
    out: dict[str, Any] = {"suite": "board", "videos": []}
    for arg in argv:
        if arg.startswith("old="):
            out.setdefault("before", []).append(report(Path(arg[4:])))
            continue
        out["videos"].append(report(data / "graphs" / f"{arg}.json"))
    (data / "eval").mkdir(parents=True, exist_ok=True)
    (data / "eval" / "board.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
