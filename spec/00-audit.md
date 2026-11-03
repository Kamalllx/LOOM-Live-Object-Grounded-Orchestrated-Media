# 00 — Audit of the old build

Basis: a full read of the parent repository on branch `integration/end-to-end` (commit `9ce95b7` plus uncommitted
work) and a live run on 2026-10-28: gateway on `:8000`, player on `:3001`, session `sess_cad495a3`
(*Acid-Base Neutralization* × *Parent + child*).

## A. What the old build does (the flow we keep)

```
video ─► PERCEIVE (once per video) ─► concept-graph.json        Contract A
           Whisper · Tesseract/RapidOCR · Grounding DINO + IoU tracking · CLIP check · LLM fusion
      ─► ORCHESTRATE (per viewer)   ─► candidate-cut.json       Contract B
           Curator → Pedagogy → [plug-in policy_review] → Personalizer → Assessment   (A2A JSON-RPC)
      ─► VERIFY (≤3 passes)         ─► verified-cut.json        Contract C
           Guardian (masks) · Animator (Manim) · Critic (safety/coherence/factuality) · revise_cut
      ─► DELIVER                    ─► session-log.json         Contract D → mastery graph
           Next.js player: verified threads, client-side blur, tap-to-learn, quiz, live loop panel
```

Observed timings in the live run: Curator 11.8 s, Pedagogy 0.5 s, Personalizer 0.3 s, Assessment 6.7 s,
Guardian 9.0 s, Critic 0.2 s → approved on pass 1 in ≈ 29 s end to end.

## B. Critical defects (must not recur)

| # | Defect | Evidence | Consequence | Remake rule |
|---|---|---|---|---|
| B1 | **All AI depends on one cloud project.** `LLM_PROVIDER=vertex` on GCP project `curiora-studios`; billing disabled → every LLM call returns `403 BILLING_DISABLED`. | gateway log; `packages/shared-types/loom_shared/llm.py` | Role labels, quiz, safety review, explainers, fact-check all silently off. | Local Ollama only (`03-local-ai.md`). |
| B2 | **Health lies.** `/api/health` returned `{"ok": true}` while 3/3 LLM calls had failed. | `services/delivery/api/server.py` `health()` | Operators and the UI believe the system is fine. | Health = readiness of every required model; `ok:false` when degraded (FR-OPS-01). |
| B3 | **Guardian fails open.** On model failure every object becomes `{"tags":["none"],"severity":0}`. | `services/verification/guardian/guardian.py:53-58` | Parent + child cut shipped with **0 masks**; broken glass (58–63 s) unblurred. | Unreviewed ⇒ treated as unsafe for any viewer with redaction on (FR-SAF-04). |
| B4 | **Failures are cached as truth.** The fail-open tags are written to `data/cache/guardian/<video>.json` and reused forever. | `guardian.py:59` (`path.write_text` after the except) | Fixing the model later does not fix the video. | Never cache a degraded result; caches keyed by content hash + model version (NFR-REL-03). |
| B5 | **Critic safety only checks what Guardian flagged.** Coverage is computed over `flagged` objects; nothing flagged ⇒ safety = 1.0. | `services/verification/critic/critic.py` `safety()` | The independent check is not independent. Approved with safety 1.0 and 0 masks. | Critic re-derives the hazard set itself from ingest-time safety review + always-on hazard classes (FR-VER-03). |
| B6 | **Empty quiz passes factuality.** No claims ⇒ factuality 1.0; a failed Assessment is invisible. | `critic.py` `factuality()` | Viewers silently lose the quiz. | Missing required artifact is a structured issue (`quiz_missing`) (FR-VER-05). |
| B7 | **Explainer verification cache keyed by URL**, while the clip file name ignores feedback; a re-render overwrites the same path. | `animator.py` `_key()`, `critic.py` `VERIFIED_CLIPS` | A clip can change content under a "verified" URL. | Clips are content-addressed: `sha256(storyboard+code+model+version)` (FR-GEN-07). |
| B8 | **Generated code runs with full user rights.** The AST allow-list is the only boundary; the render subprocess inherits the user's environment, filesystem and network. Manim's `config` object is reachable from generated code. | `animator.py` `check_code()`, `_render()` | A prompt-injected concept label could reach the host. | Layered sandbox: AST gate + restricted env + temp working dir + no network + Windows Job Object limits (FR-GEN-04). |
| B9 | **Mastery trusts the browser.** The client posts `quiz_answered {correct: true}`; the server folds it into mastery without grading. `answer_index` is shipped to the client. | `server.py` `log_session()`, `assessment.py` `update_mastery()` | Mastery graph is forgeable; answers are visible in devtools. | Server-side grading; client sends the chosen option only (FR-MEM-03). |

## C. Structural problems

| # | Problem | Evidence |
|---|---|---|
| C1 | Three perception implementations: `services/perception/legacy/`, `src/loom_perception/` (3 038 lines), and top-level `pipeline.py` + `ingest.py`; the README describes Tesseract, the driver uses RapidOCR. | `services/perception/` |
| C2 | Two agent-mesh implementations: `services/agent-mesh/app/` (FastAPI skeleton with tests) and `services/agent-mesh/agents/` (the one the gateway actually imports). | `services/agent-mesh/` |
| C3 | Two web front ends: `services/delivery/player/` (JSX, used) and `services/delivery/web/` (TSX + Mongo store, unused); plus unused `docker-compose.yml` for Mongo/Redis. | `services/delivery/` |
| C4 | Agents are "separate A2A services" but run in one process and receive the **entire concept graph** on every call (tracks included). | `server.py`, `loop.py` `_call()` |
| C5 | Evidence links are matched by float timestamps (`abs(s["start"] - ref["start"]) < 0.05`), not by IDs. | `curator.py`, `assessment.py`, `pipeline.py` |
| C6 | Events are in-memory and polled; the extension long-polls `/since/{idx}` (hundreds of requests in `gateway.log`); all events are lost on restart. | `loom_shared/events.py`, `gateway.log` |
| C7 | Setup is macOS-only (`brew`, `.venv/bin/python`), Windows is the real target; `tesseract` and `yt_dlp` missing on this machine. | `README.md` |
| C8 | File-backed JSON store without locking; concurrent sessions can race on learner files. | `services/delivery/memory/store.py` |
| C9 | Ingest holds a global lock and shells out to a subprocess; GPU memory between Ollama/torch is not coordinated. | `server.py` `_ingest_job()` |
| C10 | Perception masks are **boxes**, sampled at 1 fps, Grounding DINO *tiny*; the hazard object scored confidence 0.33 and 3.3 s of hazard went unmasked (recall 0.60). | `data/eval/results.md`, `data/graphs/vid_demo_neutralization.json` |
| C11 | Repeated model families: the Critic's LLM judge was the same family as the generator (paper limitation). | `docs/DEMO.md` |
| C13 | Media referenced by graphs is missing: `vid_demo_neutralization.mp4` and `vid_newtons_3_laws_27c8.mp4` are not in `media/videos/`; `media/source/` (demo footage) is absent; the demo generator needs macOS `say`. The headline demo cannot be rebuilt on this machine. | `scripts/make_demo_video.py`, `media/videos/` |
| C12 | Docs promise SAM 3.1, WebGPU compositing, Socket.io, vector + graph DB, S3, Redis — none exist. | `docs/LOOM-Project-Document.md` §10 |

## D. What proved itself (re-implement, don't discard)

| Keep | Why | Old location |
|---|---|---|
| Sentence-aligned threads (a thread never starts/ends mid-sentence) | Simple, auditable, Critic can check it | `curator.py` |
| Deterministic, explainable Pedagogy policy (skip/condense/keep/expand + role rules + prerequisite guard) | A teacher can audit *why* | `pedagogy.py` |
| Condense to a sentence boundary, never before an on-screen formula has shown 3 s | Good UX detail | `personalizer.py` |
| Structured Critic issues `{code, …}` routed either to local fixes or to `revise_cut` | Clean loop design | `loop.py`, `personalizer.revise()` |
| "Block on any issue, don't average" | One false sentence averaged 0.93 and would have shipped | `critic.py` |
| Hazard look-alike negatives in CLIP verification | Raised hazard precision 0.13 → 1.00, false-block 41 s → 0 s | `data/eval/results.md` |
| Always-on hazard phrases independent of the narration | Redaction must not depend on the narrator | `pipeline.py` `HAZARD_PHRASES` |
| Time padding of masks by one sampling interval | Safety errs toward covering | `guardian.py` `TIME_PAD_S` |
| AST gate + bounded repair loop for Manim (12/12 rendered, 100% first-attempt compile) | Works; needs a stronger sandbox around it | `animator.py` |
| Fault-injection evaluation of the Critic (13/13 caught, 0/6 false rejects) | Strong paper result; extend it | `scripts/evaluate.py` |
| Shared pure playback engine for web + extension (`boxAt`, `containRect`, `activeMasks`, `visibleTaps`, `reduceLoop`) | Same rules on both surfaces, testable under `node --test` | `packages/loom-engine/` |
| Mastery update rule (EMA on correct/wrong/explainer/exposure) | Simple, explainable | `assessment.py` |
| Fallback to last verified cut, else conservative baseline | Never an unchecked cut | `loop.py` `_fallback()` |
| Brand system (amber perception, teal mesh, violet verification, rose redaction; Instrument Serif / Inter Tight / JetBrains Mono) | Established by the product film | `PRODUCT.md`, `video/` |

## E. Measured results to beat (from `data/eval/`)

| Measure | Old value | Remake target |
|---|---|---|
| ASR WER (demo lesson) | 0.0155 (Groq whisper-large-v3-turbo, cloud) | ≤ 0.03 locally (faster-whisper large-v3-turbo) |
| OCR recall@0.8 / temporal IoU | 1.00 / 0.925 | ≥ 1.00 / ≥ 0.90 |
| Hazard grounding precision / recall | 1.00 / 0.60, 3.3 s missed | ≥ 0.95 / **≥ 0.90**, ≤ 0.5 s missed |
| Redaction precision / recall vs ground truth | 1.00 / 0.84 | ≥ 0.95 / ≥ 0.95 with pixel masks |
| Critic fault injection | 13/13 caught, 0/6 false rejects | ≥ 20 faults incl. *model-outage* family; 100 % caught, 0 false rejects |
| Animator render success / first-draft Critic pass | 1.00 / 0.58 | ≥ 0.95 / ≥ 0.70, plus layout check pass ≥ 0.90 |
| Session time to first frame (warm) | 0.1–0.3 s | ≤ 1 s warm, ≤ 15 s cold (no cached cut) |
