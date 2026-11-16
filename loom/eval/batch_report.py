"""Batch results -> markdown: headline numbers, a per-style summary, a per-video table and a screenshot gallery.

Writes `docs/RESULTS.md` (everything) and the section between `<!-- BATCH:START -->` and `<!-- BATCH:END -->` in the
README (summary + tables, gallery linked). Re-run after more videos are processed.

    uv run python -m loom.eval.batch_report
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from loom.core.config import load_config
from loom.eval.batch import ROOT

IMG = "docs/img/batch"


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _ingest_s(r: dict[str, Any]) -> float:
    return float(r["metrics"]["timings_s"].get("total", r.get("seconds", 0)))


def _md_link(r: dict[str, Any]) -> str:
    t = r["metrics"]["title"].replace("|", "/")
    return f"[{t[:58] + ('…' if len(t) > 58 else '')}]({r['url']})"


def build(rows: list[dict[str, Any]], img_prefix: str) -> tuple[str, str]:
    ok = [r for r in rows if r.get("status") == "ok"]
    failed = [r for r in rows if r.get("status") != "ok"]
    styles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in ok:
        styles[r["category"]].append(r)
    mins = sum(r["metrics"]["duration_s"] for r in ok) / 60
    tot = lambda k: sum(r["metrics"][k] for r in ok)  # noqa: E731
    asks = [r["ask"] for r in ok if "seconds" in r.get("ask", {})]
    head = [
        f"**{len(ok)} short lessons in {len(styles)} styles** ({mins:.1f} minutes of video) went through the full pipeline "
        f"on one laptop GPU; {len(failed)} failed{' (listed below)' if failed else ''}.",
        "",
        "| | Total | Per video (mean) |", "|---|---:|---:|",
        f"| Elements found and tracked (board, drawn, detected) | {tot('objects')} | {_mean([r['metrics']['objects'] for r in ok]):.1f} |",
        f"| Named parts inside elements | {tot('parts')} | {_mean([r['metrics']['parts'] for r in ok]):.1f} |",
        f"| Concepts in the knowledge graph | {sum(len(r['metrics']['concepts']) for r in ok)} | {_mean([len(r['metrics']['concepts']) for r in ok]):.1f} |",
        f"| Quiz questions written and verified | {tot('quiz_questions')} | {_mean([r['metrics']['quiz_questions'] for r in ok]):.1f} |",
        f"| Perception time | {sum(_ingest_s(r) for r in ok) / 60:.0f} min | {_mean([_ingest_s(r) for r in ok]):.0f} s |",
        f"| Answer agent: \"{asks[0]['question'] if asks else ''}\" | {sum(1 for a in asks if a.get('found_in_video'))}/{len(asks)} answered from the video | {_mean([a['seconds'] for a in asks]):.1f} s |",
    ]
    by_style = ["| Style | Videos | Mean length | Elements | Parts | Concepts | Quiz | Perception |",
                "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for s, rs in sorted(styles.items(), key=lambda kv: -len(kv[1])):
        by_style.append(f"| {s} | {len(rs)} | {_mean([r['metrics']['duration_s'] for r in rs]):.0f} s | "
                        f"{_mean([r['metrics']['objects'] for r in rs]):.1f} | {_mean([r['metrics']['parts'] for r in rs]):.1f} | "
                        f"{_mean([len(r['metrics']['concepts']) for r in rs]):.1f} | {_mean([r['metrics']['quiz_questions'] for r in rs]):.1f} | "
                        f"{_mean([_ingest_s(r) for r in rs]):.0f} s |")
    per = ["| # | Style | Lesson | Length | Elements (drawn / detected) | Parts | Concepts | Quiz | Perception | Answer |",
           "|---:|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for n, r in enumerate(ok, 1):
        m, a = r["metrics"], r.get("ask", {})
        ans = (f"{a['seconds']:.0f} s, {'from video' if a.get('found_in_video') else 'general'}" if "seconds" in a else "n/a")
        per.append(f"| {n} | {r['category']} | {_md_link(r)} | {m['duration_s']:.0f} s | {m['objects']} "
                   f"({m['board_or_scene_elements']} / {m['detected_objects']}) | {m['parts']} | {len(m['concepts'])} | "
                   f"{m['quiz_questions']} | {_ingest_s(r):.0f} s | {ans} |")
    fails = [f"- {r['category']}: {r['url']} — {r.get('error', r.get('status'))}" for r in failed]
    gallery = []
    for s, rs in styles.items():
        gallery.append(f"<details><summary><b>{s}</b> ({len(rs)})</summary>\n")
        gallery.append("| Every element outlined | One lifted, with its parts | The agent run |\n|---|---|---|")
        for r in rs:
            sc = r.get("screens", {})
            cells = [f'<img src="{img_prefix}/{sc[k]}" width="280"/>' if sc.get(k) else "" for k in ("overlay", "lift", "run")]
            gallery.append(f"| {' | '.join(cells)} |")
            gallery.append(f"| {_md_link(r)} | {sc.get('lifted') or ''} ({sc.get('lift_chips', 0)} parts) | "
                           f"{r['metrics']['timings_s'].get('total', 0):.0f} s perception |")
        gallery.append("\n</details>\n")
    concepts = ["| Lesson | Concepts LOOM built | A few element and part names |", "|---|---|---|"]
    for r in ok:
        m = r["metrics"]
        names = "; ".join(dict.fromkeys([*m["element_labels"][:5], *m["part_labels"][:4]]))
        concepts.append(f"| {_md_link(r)} | {'; '.join(m['concepts'][:5])} | {names[:220]} |")
    core = "\n".join([*head, "", "**By lesson style**", "", *by_style, "", "**Every video**", "", *per,
                      *(["", "**Failures**", "", *fails] if fails else [])])
    full = "\n".join(["# LOOM batch results", "", core, "", "## What LOOM understood", "", *concepts, "",
                      "## Screenshots", "", *gallery])
    return core, full


def main() -> None:
    data = load_config().data_dir
    rows = json.loads((data / "eval" / "batch" / "summary.json").read_text(encoding="utf-8"))
    _, full = build(rows, "img/batch")
    (ROOT / "docs" / "RESULTS.md").write_text(full + "\n", encoding="utf-8")
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    section = (f"<!-- BATCH:START -->\n{build(rows, IMG)[0]}\n\nScreenshots of every video, the concepts and names LOOM built "
               f"for each, and failures: [docs/RESULTS.md](docs/RESULTS.md).\n<!-- BATCH:END -->")
    if "<!-- BATCH:START -->" in text:
        text = re.sub(r"<!-- BATCH:START -->.*?<!-- BATCH:END -->", lambda _: section, text, flags=re.S)
        readme.write_text(text, encoding="utf-8")
    print(f"{len(rows)} rows -> docs/RESULTS.md" + (" + README" if "<!-- BATCH:START -->" in text else ""))


if __name__ == "__main__":
    main()
