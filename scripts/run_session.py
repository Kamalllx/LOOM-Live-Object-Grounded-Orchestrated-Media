"""Start a personalization session against the running backend and print its live event stream.

    .venv/bin/python scripts/run_session.py vid_demo_neutralization learner_family
"""
import json
import sys

import httpx

API = "http://127.0.0.1:8000"


def run(video_id, learner_id, quiet=False):
    sid = httpx.post(f"{API}/api/sessions", json={"video_id": video_id, "learner_id": learner_id}).json()["session_id"]
    if not quiet:
        print(f"session {sid}")
    with httpx.stream("GET", f"{API}/api/events/{sid}", timeout=None) as r:
        for line in r.iter_lines():
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            if not quiet:
                if ev["kind"] == "agent_done":
                    print(f"  {ev['agent']:>20s}.{ev['skill']:<16s} {ev['latency_ms']:>6d} ms")
                elif ev["kind"] == "loop_phase":
                    extra = f" approved={ev['approved']} scores={ev['scores']}" if ev["phase"] == "verify" else ""
                    print(f"  -- pass {ev['pass_number']} {ev['phase'].upper()}{extra}")
                    for issue in ev.get("issues", []):
                        print(f"       issue: {issue}")
                elif ev["kind"] not in ("agent_call",):
                    print("  ", {k: v for k, v in ev.items() if k != "t"})
            if ev["kind"] in ("delivered", "error"):
                break
    try:
        return httpx.get(f"{API}/api/sessions/{sid}").json()
    except Exception:
        return None


if __name__ == "__main__":
    cut = run(sys.argv[1], sys.argv[2])
    if cut:
        print(json.dumps({k: cut[k] for k in ("status", "pass_count", "critic_score")}, indent=1))
        print("threads:", [(t["thread_id"], t.get("action"), t["start"], t["end"]) for t in cut["final_threads"]])
        print("masks:", [(m["object_id"], m["start"], m["end"], m["reason"]) for m in cut["redaction_masks"]])
        print("explainers:", [(c["concept_node_id"], c["clip_url"], c.get("cached")) for c in cut["explainer_clips"]])
        print("quiz:", [q["question"] for q in cut["quiz"]])
