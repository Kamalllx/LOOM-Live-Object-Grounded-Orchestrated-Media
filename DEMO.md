# LOOM demo — run sheet

Everything runs locally: Ollama models + open weights on this laptop, no cloud calls (YouTube download only when you
press "Process with LOOM").

## Before the demo (once)

1. GPU mode **Standard/Ultimate** (not Eco), charger plugged in. Close other heavy apps.
2. Ollama running (tray icon). Check: `uv run loom doctor --no-smoke`.
3. Start the gateway (serves the API, the player and media):
   ```powershell
   cd remake
   uv run loom gateway
   ```
   Open **http://127.0.0.1:8000** — the badge top-right must say **local models ready**.
4. Load the extension: Chrome → `chrome://extensions` → Developer mode → **Load unpacked** → select `remake/extension`.
5. Warm the cuts (optional): watch the demo lesson once as each viewer so "Compare weaves" has data.

## Demo script (~6 min)

| Scene | Click | Say |
|---|---|---|
| One lesson, three viewers | Library: Alex / Priya / Parent + child cards | Same 69 s chemistry lesson; three very different viewers. |
| Orchestrate + verify | Pick **Priya** → Watch; point at the right panel | Curator → Pedagogy → Personalizer → Assessment plan the cut; Guardian and the Critic check it; scores must pass before anything plays. |
| Generated explainers | Let Priya's cut reach the violet marks (or tick **Show tappable objects** and click the beaker) | Qwen plans a scene (shapes, moves, one narrated line per beat); **Gemma fact-checks every line** (a few weak lines are dropped, not the whole explainer); Kokoro narrates; the scene plays live in the browser and an MP4 copy exports in the background. Watch the agents think in the progress box and in the pipeline view while the cut is woven. |
| Object-level safety | Library → **Parent + child** → Watch, jump to ~0:48 | Only the broken glass is blurred; the rest of the lesson plays. Click the weave → reason + which agent decided. |
| Expert cut | **Alex** → Watch | Intro/setup skipped, everything else condensed — never core or safety content. |
| Different weave | **Compare weaves** | Same threads, different cloth per viewer. |
| Mastery | Finish Priya's quiz → **Save to my mastery graph** → **Watch again** | Answers are graded on the server; mastery changes the next cut. |
| YouTube | Open the processed YouTube lesson; LOOM panel top-right → pick viewer → **Weave my cut** | Same mesh + Critic on a real YouTube video: masks over the YouTube player, skip-to-cut, explainers. |
| Any video | On a new YouTube lesson → **Process with LOOM** | Perception runs once, locally (speech, on-screen text, objects, safety review, quiz). |

## What is real vs. simplified (be honest if asked)

- The demo lesson graph and the YouTube lesson graph both come from the local perception pipeline (Grounding DINO + IoU
  tracking + SigLIP2 look-alikes + VLM check). Object outlines are exact SAM 2.1 masks (`loom masks`, wired into ingest).
- Measured hazard grounding (`data/eval/grounding.json`): precision 1.00, recall 0.58 against targets 0.95 / 0.90 (not met).
- The mesh agents are deterministic in-process steps with live events; the interactive agents (retriever, animator,
  assessment) are real A2A services mounted at `/a2a/<name>/` with agent cards.
