# LOOM demo guide

## 30 minutes before presenting

1. Close heavy apps. On macOS the first load of each native library is security-scanned and can stall
   for minutes; warm up the demo libraries once (add `--all` only if you will ingest a new video live):
   ```bash
   .venv/bin/python scripts/warmup.py
   ```
2. Start the backend, the player and (optionally) the third-party agent — each in its own terminal:
   ```bash
   .venv/bin/python -m uvicorn server:app --app-dir services/delivery/api --port 8000
   npm run dev --prefix services/delivery/web
   .venv/bin/python -m uvicorn school_policy_agent:app --app-dir services/agent-mesh/plugins --port 8100
   ```
3. Check `curl localhost:8000/api/health` returns `{"ok": true ...}` and open http://localhost:3000.
4. Warm the caches (so the live demo never waits on the LLM):
   ```bash
   for l in learner_alex learner_priya learner_family; do .venv/bin/python scripts/run_session.py vid_demo_neutralization $l; done
   ```
5. Reset mastery so the quiz demo starts clean: `curl -X POST localhost:8000/api/learners/reset`

## Demo script (follows the film, ~6 minutes)

| Film scene | What to click | What to say |
|---|---|---|
| One lesson, three viewers | Library page, point at the three personas | Same 75 s chemistry lesson, three very different viewers. |
| 01 Perceive | Open `data/graphs/vid_demo_neutralization.json` or the graph panel | Whisper transcript, OCR cards, objects grounded from phrases the lesson itself chose, plus always-on hazard phrases. |
| 02 Orchestrate | **Agents** page | Every agent is an A2A Agent Card. Register `http://127.0.0.1:8100` live — a school's own agent joins with no rebuild. |
| 03 Verify | Watch as **Priya**; point at the right-hand loop panel | Every agent call streams live; the Critic scores factuality / coherence / safety; nothing plays until approved. |
| Tap anything | Toggle **Show tappable objects**, click the beaker | Animator writes Manim code, AST gate, render, Critic fact-check, cached for the next learner. |
| Auto explainer | Let Priya's cut reach the end of a core thread | Beginner gets a generated explainer exactly where she needs it. |
| Redact one object | Watch as **Parent + child**, click the weave near 0:58 | Only the broken glass is blurred; the rest of the lesson plays. |
| Different weave | **Compare weaves** | Alex 78% condensed, Priya full + 4 explainers, Parent full + 1 mask. |
| Mastery | Finish Priya's quiz → **Save to my mastery graph** → **Watch again** | Next session's Curator and Pedagogy start from the updated graph. |
| Any video | Library → Add a video (upload or link) | Perception runs once per video; the same pipeline works on any lesson. |

If anything misbehaves live, the evaluation numbers and figures in `data/eval/` and `docs/figures/` are the fallback.

## Member 3 — Verification, Safety & Generation (questions to expect)

- **Why a loop and not one LLM call?** One pass shipped unsupported claims in 5 of 12 fresh explainers; the loop
  caught all of them. The budget (3) prevents thrashing; the fallback is the last verified cut or a strict-mask baseline.
- **How is safety scored?** Deterministically: share of flagged-object screen time inside the cut covered by a mask
  (0.1 s sampling). Must be exactly 1.0.
- **Why block on any issue instead of thresholds?** Averages hide individual failures: an explainer with one false
  sentence averaged 0.93 factuality and would have shipped.
- **Can generated Manim code do harm?** It passes an AST allow-list (no file/OS/network access, no dunder tricks)
  before it runs, in a subprocess with a timeout.
- **What can the Critic NOT catch?** Hazards perception never detected (1.3 s of shards unmasked), visual layout of
  animations, and possible self-preference of a same-family LLM judge.
- **Fault-injection result:** 13/13 planted faults flagged and blocked, 0/6 correct items rejected.
