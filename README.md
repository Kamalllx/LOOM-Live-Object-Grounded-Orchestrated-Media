# LOOM — Live, Object-grounded, Orchestrated Media

Personalization *inside* the frame: one source video, a different **verified** cut for every viewer.
LOOM grounds and tracks objects in an instructional video, lets a mesh of A2A agents build a personalized
cut, and checks every cut in a bounded Critic loop before it plays — with per-object redaction and
Manim explainers written on demand.

Generative AI project · Dept. of CSE, Ramaiah Institute of Technology · supervised by Dr. J Sangeetha
Manya Ravishankar · Rana Adiba · Kamal Karteek U · Jeevika R

## Repository map (mirrors the work split)

| Stage | Folder | Owner | Produces |
|---|---|---|---|
| Perception & concept graph | `services/perception/` (`asr/`, `ocr/`, `sam/`, `graph-fusion/`, `pipeline.py`) | Member 1 | Contract A `concept-graph.json` |
| Agent mesh & personalization | `services/agent-mesh/` (`orchestrator/`, `agents/*`, `plugins/`) | Member 2 | Contract B `candidate-cut.json` |
| Verification, safety & generation | `services/verification/` (`guardian/`, `animator/`, `critic/`, `loop.py`) | Member 3 | Contract C `verified-cut.json` |
| Delivery, memory & infra | `services/delivery/` (`api/server.py`, `memory/`, `player/` integrated player, `web/` delivery web app) | Member 4 | Contract D `session-log.json` |
| Shared | `packages/shared-types/loom_shared/` (LLM client, A2A, contracts, events) · `contracts/` · `fixtures/` | all | |

Scripts: `scripts/make_demo_video.py` (demo lesson + ground truth), `scripts/run_session.py`,
`scripts/evaluate.py` (all paper numbers), `scripts/make_figures.py`, `scripts/render_frame.py`,
`scripts/validate_contracts.py`, `scripts/warmup.py`. Paper: `docs/paper/` (`node docs/paper/build_paper.js`).

## Setup (macOS)

```bash
brew install ffmpeg tesseract pango pkg-config
python3.11 -m venv .venv && .venv/bin/pip install jsonschema pydantic fastapi "uvicorn[standard]" httpx python-dotenv \
  opencv-python-headless numpy pillow pytesseract openai-whisper transformers accelerate google-genai groq \
  python-multipart yt-dlp manim
(cd services/delivery/player && npm install)
cp .env.example .env    # then paste GROQ_API_KEY (and/or GEMINI_API_KEY); LLM_PROVIDER=groq
.venv/bin/python scripts/warmup.py   # once after reboot; add --all before ingesting new videos (slow the first time)
```

## Run

```bash
.venv/bin/python -m uvicorn server:app --app-dir services/delivery/api --port 8000      # all agents + API
npm run dev --prefix services/delivery/player                                           # player on :3001
.venv/bin/python -m uvicorn school_policy_agent:app --app-dir services/agent-mesh/plugins --port 8100   # optional 3rd-party agent
```

Open http://localhost:3001, pick a viewer (Alex / Priya / Parent + child), press **Watch**.
Add any video from the library page (upload or link); perception runs once per video.

Ingest from the command line: `.venv/bin/python services/perception/pipeline.py --source <file|url> --video-id vid_x`.

## How it works

1. **Perceive** – Whisper transcript, Tesseract OCR, LLM-chosen object phrases + always-on hazard phrases,
   Grounding DINO + IoU tracking, CLIP verification (hazards must beat look-alikes), LLM fusion into concept nodes.
2. **Orchestrate** – the orchestrator discovers agents by A2A Agent Card and tasks them over JSON-RPC:
   Curator (threads + roles) → Pedagogy (mastery policy) → plug-in `policy_review` agents → Personalizer → Assessment.
3. **Verify** – Guardian (safety model, per-viewer masks) and Animator (LLM → Manim, AST gate, render, repair,
   narrate, cache) perceive the cut; the Critic scores safety / coherence / factuality and emits structured issues;
   the loop fixes locally or asks the mesh to `revise_cut`, within a budget of 3, falling back to the last verified cut.
4. **Deliver** – the player plays only verified threads, composites blur masks client-side, offers tap-to-learn on
   tracked objects, streams the loop live, and posts the quiz back to the learner's mastery graph.

## Results (demo lesson, `data/eval/`)

| Measure | Value |
|---|---|
| Critic fault injection (13 planted faults, 6 families) | 13/13 caught and blocked, 0/6 controls rejected |
| Per-object redaction vs ground truth | precision 1.00, recall 0.84, 0 s of safe content blocked |
| Hazard false alarms, detector only → with look-alike verification | see `data/eval/perception.json` |
| Loop repair example | pass 1 rejected an explainer inventing indicator colours → re-rendered → pass 2 approved |

Known limitations are listed in the paper (SAM 3.1 not run on laptop hardware, box masks, same-family LLM judge,
layout of generated animations not verified, one demo lesson, no user study).
