"""`python -m loom.eval.factcheck_history` — what the explainer fact-checker did, from the persisted event log.

Every custom explainer run publishes the Critic's verdict per narrated line ("ok"/"cut" + the judge's reason) as an
`agent_note`. From those this reports, per explainer run: first-draft line support, whether the first draft was
accepted (the planner's thresholds), drafts needed, and outcome; and it exports a labelling sheet of narration lines
with the judge's verdicts (`data/eval/factcheck_lines.csv`) for a human to label supported / unsupported, so judge
agreement with a human can be measured (`--score` once the `human` column is filled).
"""

from __future__ import annotations

import csv
import json
import random
import re
import sqlite3
import sys
from collections import defaultdict
from typing import Any

from loom.core.config import load_config

LINE = re.compile(r"^(ok|cut)\s+(.*?)(?:\s+\((.*)\))?$", re.S)


def history(db: str) -> dict[str, Any]:
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT id, channel, payload, ts FROM events WHERE kind = 'agent_note' AND "
        "(payload LIKE '%loom-critic%' OR payload LIKE '%loom-animator%' OR payload LIKE '%loom-retriever%') "
        "ORDER BY id"
    ).fetchall()
    runs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        d = json.loads(r["payload"])
        runs[r["channel"]].append({"id": r["id"], "ts": r["ts"], **d})
    out = []
    for ch, notes in runs.items():
        # one channel can hold several runs of the same question: a run starts at "Planning the" / "Planned"
        run: list[dict[str, Any]] = []
        sessions: list[list[dict[str, Any]]] = []
        for n in notes:
            if n.get("agent") == "loom-retriever" and n.get("text", "").startswith("Searching") and run:
                sessions.append(run)
                run = []
            run.append(n)
        if run:
            sessions.append(run)
        for s in sessions:
            checks = [
                n
                for n in s
                if n.get("agent") == "loom-critic" and re.match(r"\d+ of \d+ lines are supported", n.get("text", ""))
            ]
            if not checks:
                continue
            drafts = []
            for n in checks:
                m = re.match(r"(\d+) of (\d+)", n["text"])
                items = []
                for it in n.get("items", []):
                    lm = LINE.match(it.strip())
                    if lm:
                        items.append(
                            {"verdict": lm.group(1), "line": lm.group(2).strip(), "reason": (lm.group(3) or "").strip()}
                        )
                drafts.append({"supported": int(m.group(1)), "lines": int(m.group(2)), "items": items})
            delivered = any("Scene ready" in n.get("text", "") or "Rendered" in n.get("text", "") for n in s)
            first = drafts[0]
            bad = first["lines"] - first["supported"]
            accepted_first = bad == 0 or (first["supported"] >= 3 and bad <= max(2, first["lines"] // 3))
            out.append(
                {
                    "channel": ch,
                    "started": s[0]["ts"],
                    "drafts": len(drafts),
                    "first_draft": first,
                    "first_fully_supported": bad == 0,
                    "first_accepted": accepted_first,
                    "delivered": delivered,
                    "construction": any("geometric construction" in n.get("text", "") for n in s),
                }
            )
    return {"runs": out}


def summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(runs)
    lines = sum(r["first_draft"]["lines"] for r in runs)
    sup = sum(r["first_draft"]["supported"] for r in runs)
    return {
        "explainer_runs": n,
        "first_draft_line_support": round(sup / max(1, lines), 3),
        "first_draft_lines": lines,
        "first_draft_fully_supported": sum(r["first_fully_supported"] for r in runs),
        "first_draft_accepted": sum(r["first_accepted"] for r in runs),
        "delivered": sum(r["delivered"] for r in runs),
        "drafts_histogram": {k: sum(1 for r in runs if r["drafts"] == k) for k in sorted({r["drafts"] for r in runs})},
    }


def sheet(runs: list[dict[str, Any]], path: str, n: int = 40, seed: int = 7) -> int:
    """A balanced sample of judged narration lines (unique), shuffled, for a human to label."""
    seen, ok, cut = set(), [], []
    for r in runs:
        for d in [r["first_draft"]]:
            for it in d["items"]:
                key = it["line"].lower()
                if key in seen or len(it["line"]) < 20:
                    continue
                seen.add(key)
                (ok if it["verdict"] == "ok" else cut).append({**it, "channel": r["channel"]})
    rnd = random.Random(seed)  # noqa: S311 - a reproducible sample, not security
    take = rnd.sample(cut, min(len(cut), n // 2))
    take += rnd.sample(ok, min(len(ok), n - len(take)))
    rnd.shuffle(take)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["n", "lesson", "line", "judge", "judge_reason", "human"])
        for i, t in enumerate(take, 1):
            lesson = re.sub(r"^tap_|_[0-9a-f]{16,}$", "", t["channel"])
            w.writerow([i, lesson, t["line"], "supported" if t["verdict"] == "ok" else "unsupported", t["reason"], ""])
    return len(take)


def _split(r: dict[str, str]) -> tuple[str, str]:
    """(line, judge reason); a long item was cut at 240 characters in the event, its "(reason" left inside the line."""
    line, reason = r["line"], r["judge_reason"]
    if not reason and " (" in line:
        k = line.rfind(" (")
        if line[k + 2 : k + 3].isupper():
            line, reason = line[:k], line[k + 2 :]
    return line, reason


def loom_final(rows: list[dict[str, str]]) -> list[bool]:
    """LOOM's delivered verdict per line: the judge, then the absence-only overrule, then the not-teaching guard (its
    video-narration test; the repeat test only makes sense within one explainer, so each line is checked alone)."""
    from loom.agents.animator import absence_only, not_teaching

    out = []
    for r in rows:
        line, reason = _split(r)
        v = r["judge"] == "supported" or absence_only(reason)
        if not_teaching([line]):
            v = False
        out.append(v)
    return out


def score(path: str, label_col: str = "human", final: bool = False) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get(label_col, "").strip()]
    judge = loom_final(rows) if final else [r["judge"] == "supported" for r in rows]
    human = [r[label_col].strip().lower().startswith("s") for r in rows]
    n = len(rows)
    agree = sum(a == b for a, b in zip(judge, human, strict=True))
    po = agree / max(1, n)
    pj, ph = sum(judge) / max(1, n), sum(human) / max(1, n)
    pe = pj * ph + (1 - pj) * (1 - ph)
    tp = sum(j and h for j, h in zip(judge, human, strict=True))
    fp = sum(j and not h for j, h in zip(judge, human, strict=True))
    fn = sum(h and not j for j, h in zip(judge, human, strict=True))
    tn = n - tp - fp - fn
    return {
        "labelled_by": label_col,
        "verdict": "LOOM final (judge + overrule + guard)" if final else "judge alone",
        "n": n,
        "agreement": round(po, 3),
        "cohens_kappa": round((po - pe) / (1 - pe), 3) if pe < 1 else None,
        "verdict_supported_label_supported": tp,
        "verdict_supported_label_unsupported": fp,
        "verdict_unsupported_label_supported": fn,
        "verdict_unsupported_label_unsupported": tn,
        "false_accept_rate": round(fp / max(1, fp + tn), 3),
        "false_reject_rate": round(fn / max(1, fn + tp), 3),
    }


def main() -> None:
    cfg = load_config()
    out = cfg.data_dir / "eval"
    if "--score" in sys.argv:
        col = sys.argv[sys.argv.index("--score") + 1] if len(sys.argv) > sys.argv.index("--score") + 1 else "human"
        res = {
            "judge_alone": score(str(out / "factcheck_lines.csv"), col),
            "loom_final": score(str(out / "factcheck_lines.csv"), col, final=True),
        }
        (out / f"factcheck_agreement_{col}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
        print(json.dumps(res, indent=1))
        return
    h = history(str(cfg.data_dir / "loom.db"))
    body = {"suite": "factcheck_history", "summary": summary(h["runs"]), **h}
    (out / "factcheck_history.json").write_text(json.dumps(body, indent=1), encoding="utf-8")
    n = sheet(h["runs"], str(out / "factcheck_lines.csv"))
    print(json.dumps(body["summary"], indent=1), "\nlabelling sheet:", n, "lines")


if __name__ == "__main__":
    main()
