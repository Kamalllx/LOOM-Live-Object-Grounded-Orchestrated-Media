"""`python -m loom.eval.latency_eval` — interactive latency as distributions, against the running gateway.

Every request is a *different* question / topic so the LLM cache never answers (a cache hit is reported separately,
once). Per-stage ingest times come from the stored graphs (`perception_meta.timings_s`) of the three corpus lessons
and of every batch-evaluated short. Writes `data/eval/latency.json`.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from typing import Any

import httpx

from loom.core.config import load_config
from loom.eval.batch import BASE
from loom.eval.common import machine_info

ASKS = [
    ("acid_base_neutralization_d752a6", "What happens when an acid and a base react?"),
    ("acid_base_neutralization_d752a6", "Why does the indicator change colour at pH 7?"),
    ("acid_base_neutralization_d752a6", "What protective equipment should I wear in this experiment?"),
    ("acid_base_neutralization_d752a6", "What salt is formed from sodium hydroxide and hydrochloric acid?"),
    ("water_sciences_laboratory_tutorial_glass_a98109", "Where should broken glass be thrown away?"),
    ("water_sciences_laboratory_tutorial_glass_a98109", "How do I clean up small pieces of glass?"),
    ("water_sciences_laboratory_tutorial_glass_a98109", "Who should I tell when the glass box is full?"),
    ("sql_explained_in_100_seconds_4462e4", "What is a relational database?"),
    ("sql_explained_in_100_seconds_4462e4", "What does a SELECT statement do?"),
    ("sql_explained_in_100_seconds_4462e4", "What is a primary key used for?"),
]
QUIZZES = [
    ("acid_base_neutralization_d752a6", "Neutralization Reaction"),
    ("acid_base_neutralization_d752a6", "Indicator and Neutral pH"),
    ("water_sciences_laboratory_tutorial_glass_a98109", "Step-by-Step Broken Glass Cleanup Procedure"),
    ("water_sciences_laboratory_tutorial_glass_a98109", "Safety Precautions for the Disposal Box"),
    ("sql_explained_in_100_seconds_4462e4", "SQL Explained in 100 Seconds"),
]
SESSIONS = [
    (v, learner)
    for v in ("acid_base_neutralization_d752a6", "water_sciences_laboratory_tutorial_glass_a98109")
    for learner in ("learner_alex", "learner_priya", "learner_family")
] * 2


def stats(xs: list[float]) -> dict[str, Any]:
    if not xs:
        return {"n": 0}
    s = sorted(xs)
    q = statistics.quantiles(s, n=4) if len(s) >= 4 else [s[0], statistics.median(s), s[-1]]
    return {
        "n": len(s),
        "median": round(statistics.median(s), 2),
        "p25": round(q[0], 2),
        "p75": round(q[-1], 2),
        "min": round(s[0], 2),
        "max": round(s[-1], 2),
        "mean": round(statistics.fmean(s), 2),
        "stdev": round(statistics.stdev(s), 2) if len(s) > 1 else 0.0,
    }


async def _wait_delivered(c: httpx.AsyncClient, channel: str, after: int, timeout: float = 600) -> dict[str, Any]:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        ev = (await c.get(f"{BASE}/api/channels/{channel}/latest", params={"limit": 80})).json()["events"]
        end = next((e for e in ev if e["id"] > after and e["kind"] in ("delivered", "error")), None)
        if end:
            return end
        await asyncio.sleep(0.25)
    return {"kind": "timeout"}


async def run() -> dict[str, Any]:
    out: dict[str, Any] = {"suite": "latency", "machine": machine_info(), "asks": [], "quizzes": [], "sessions": []}
    async with httpx.AsyncClient(timeout=900) as c:
        for vid, q in ASKS:
            t0 = time.perf_counter()
            r = (await c.post(f"{BASE}/api/videos/{vid}/ask", json={"question": q})).json()
            out["asks"].append(
                {
                    "video_id": vid,
                    "question": q,
                    "seconds": round(time.perf_counter() - t0, 2),
                    "found_in_video": r.get("found_in_video"),
                    "citations": len(r.get("citations") or []),
                }
            )
            print("ask", out["asks"][-1], flush=True)
        vid, q = ASKS[0]
        t0 = time.perf_counter()
        await c.post(f"{BASE}/api/videos/{vid}/ask", json={"question": q})
        out["ask_cache_hit_s"] = round(time.perf_counter() - t0, 3)
        for vid, topic in QUIZZES:
            t0 = time.perf_counter()
            r = (await c.post(f"{BASE}/api/videos/{vid}/quiz", json={"topic": topic})).json()
            out["quizzes"].append(
                {
                    "video_id": vid,
                    "topic": topic,
                    "seconds": round(time.perf_counter() - t0, 2),
                    "questions": len(r.get("questions") or []),
                }
            )
            print("quiz", out["quizzes"][-1], flush=True)
        for vid, learner in SESSIONS:
            t0 = time.perf_counter()
            sid = (await c.post(f"{BASE}/api/sessions", json={"video_id": vid, "learner_id": learner})).json()[
                "session_id"
            ]
            end = await _wait_delivered(c, sid, 0)
            out["sessions"].append(
                {
                    "video_id": vid,
                    "learner_id": learner,
                    "seconds": round(time.perf_counter() - t0, 3),
                    "status": end.get("data", {}).get("status"),
                    "passes": end.get("data", {}).get("pass_count"),
                }
            )
            print("session", out["sessions"][-1], flush=True)
    out["summary"] = {
        "ask_s": stats([a["seconds"] for a in out["asks"]]),
        "quiz_s": stats([q["seconds"] for q in out["quizzes"]]),
        "session_s": stats([s["seconds"] for s in out["sessions"]]),
    }
    return out


def ingest_stages() -> dict[str, Any]:
    cfg = load_config()
    rows = []
    for p in sorted((cfg.data_dir / "graphs").glob("*.json")):
        g = json.loads(p.read_text(encoding="utf-8"))
        t = (g.get("perception_meta") or {}).get("timings_s") or {}
        if t.get("total"):
            rows.append({"video_id": g["video_id"], "duration_s": g["duration_seconds"], "timings_s": t})
    stages = sorted({k for r in rows for k in r["timings_s"] if k != "total"})
    per_stage = {k: stats([r["timings_s"][k] for r in rows if k in r["timings_s"]]) for k in stages}
    per_min = stats([r["timings_s"]["total"] / max(0.1, r["duration_s"] / 60) for r in rows])
    return {
        "lessons": len(rows),
        "per_stage_s": per_stage,
        "total_s": stats([r["timings_s"]["total"] for r in rows]),
        "seconds_per_minute_of_video": per_min,
        "rows": rows,
    }


def main() -> None:
    cfg = load_config()
    body = asyncio.run(run())
    body["ingest"] = ingest_stages()
    (cfg.data_dir / "eval" / "latency.json").write_text(json.dumps(body, indent=1), encoding="utf-8")
    print(json.dumps(body["summary"], indent=1))
    print(json.dumps({k: v for k, v in body["ingest"].items() if k != "rows"}, indent=1)[:3000])


if __name__ == "__main__":
    main()
