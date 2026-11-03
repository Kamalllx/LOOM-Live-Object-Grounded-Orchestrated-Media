# 01 — Product: vision, goals, users, scope, non-functional requirements

## 1. Vision

Every instructional video today is one fixed sequence of pixels. Players can speed it up, slow it down or seek,
but nothing reaches **inside a frame** to change what is shown, to whom, or in what order.

LOOM keeps one set of source material — footage, transcript, on-screen text, tracked objects — and re-weaves a
different, **verified** arrangement for every viewer: threads condensed or expanded to their level, explainer
animations written on demand when they tap an object, unsafe objects masked for that viewer alone, and a short
check that updates a persistent mastery graph. Nothing reaches a viewer until a Critic approves it inside a
bounded Perceive → Plan → Act → Verify loop.

> **Weaving metaphor.** A loom does not create new thread; it re-arranges the same threads into a different,
> structurally sound cloth each time. Same source, different verified weave, every session.

## 2. Goals and success criteria

| ID | Goal | Measured by (see `07-evaluation.md`) |
|---|---|---|
| G1 | **Object-level personalization**: act on individual objects inside the frame, not just chapters | Tap-to-learn works on every tracked concept object; per-object masks |
| G2 | **Spatial safety as a dial**: mask the one unsafe object instead of blocking the video | Redaction precision/recall ≥ 0.95; 0 s safe content blocked; fail-closed under model outage |
| G3 | **Open agent mesh**: specialists discover each other via A2A Agent Cards; third-party agents plug in without a rebuild | A plug-in agent registers live and its output reaches the cut (and is verified) |
| G4 | **Self-checked delivery**: every cut, mask, quiz and animation is verified before it plays; budgeted loop; fallback | Fault-injection detection 100 %, 0 false rejects; loop convergence ≤ 3 passes |
| G5 | **Agent-authored, verifiable animation**: Manim explainers written on demand, fact-checked, layout-checked, cached | Render success ≥ 0.95; first-draft pass ≥ 0.70; cache hit instant |
| G6 | **Mastery graph, not a score**: assessment updates a per-learner concept graph that changes the next cut | Watch → quiz → watch again yields a measurably different cut |
| G7 | **Fully local**: no cloud AI; runs on one 8 GB-VRAM laptop | `LOOM_OFFLINE=1` end-to-end demo passes with network disabled |
| G8 | **Works on any lesson**: upload a file or paste a link; perception runs once | ≥ 3 different lessons (chemistry, physics, one YouTube video) processed end to end |

### Non-goals (explicitly out of scope)

- Re-encoding a personalized video per viewer (composition stays client-side).
- Multi-tenant hosting, accounts, payments; deployment beyond localhost / LAN (may be designed for, not built).
- A user study claim. No engagement or learning-outcome claims without a study.
- Languages other than English for v1 (contracts carry `language` so it can be added).

## 3. Users and personas

| Persona | Profile | Starting cut | Mid-video | Safety | Outcome |
|---|---|---|---|---|---|
| **Alex** (expert) | `prior_knowledge 0.85`, `pace condensed`, redaction `off` | ≈ 75–80 % of source, setup condensed/skipped | Rarely taps | None | Reaches the new idea without the setup |
| **Priya** (beginner) | `prior_knowledge 0.20`, `pace detailed`, redaction `off` | Full lesson + auto explainers on core threads | Taps objects, watches explainers | None | Doesn't fall behind |
| **Parent + child** | `prior_knowledge 0.40`, `pace standard`, redaction `standard`, blocked tags `sharp_object`, `injury_risk` | Standard cut | May not interact | Hazards blurred per object | Keeps the other 95 % of the lesson |
| **Teacher / school** | Operates a plug-in policy agent | — | — | Adds school rules (e.g. mask brand logos) | Policy enforced, still verified |
| **Evaluator / team** | Runs the demo, reads the trace | — | Opens the loop panel, agents page | — | Sees the mechanism working |

Learners beyond the three seeded personas can be created from the UI (FR-MEM-05).

## 4. Product principles (from `PRODUCT.md`, kept)

1. **Show the mechanism working**: live agent calls, Critic scores, masks following objects. Never decorate.
2. **Trust is visible**: what changed for this viewer, and why, is always one glance away.
3. **The viewer stays in control**: every skip, mask and explainer can be seen and opted out of (except masks
   enforced by a guardian profile, which show *that* something is masked and why).
4. **The video is the hero**: the interface recedes while playing and speaks only when it has something verified to say.
5. **Honest degradation**: when something is unavailable, say so in the UI ("Quiz unavailable — model offline"),
   never hide it.

## 5. Scope summary (feature list — details in `04-features.md`)

| Area | Features |
|---|---|
| Ingest & perception | Upload / link ingest · progress stream · ASR · OCR · shot detection · VLM object vocabulary · open-vocabulary detection · segmentation + tracking (pixel masks) · look-alike verification · concept graph fusion · ingest-time safety review · ingest-time quiz bank · optional explainer pre-render |
| Agent mesh | A2A agent cards & JSON-RPC · registry & live registration · Orchestrator · Curator · Pedagogy · Personalizer · Assessment · plug-in policy agents · trust boundary |
| Verification & generation | Guardian · Animator (Manim + TTS + sandbox + layout check) · Critic (safety, coherence, factuality, completeness) · bounded loop · local fixes · `revise_cut` · fallback · tap-to-learn verification |
| Delivery | Library · viewer picker · player (verified threads, skip, pixel-mask blur, tap-to-learn, auto explainers) · live loop panel · weave timeline · compare weaves · agents page · quiz · mastery view · "why am I seeing this" · accessibility |
| Memory | Learner profiles · mastery graph · session logs · server-side grading · reset · learner editor |
| YouTube extension | Overlay masks, skip to cut, explainers inside the YouTube player, panel with mesh/loop status |
| Ops & evaluation | Health/readiness · model manager · offline mode · structured logs · evaluation harness · figure/paper numbers |

## 6. Non-functional requirements

### Performance (on the target laptop)

| ID | Requirement |
|---|---|
| NFR-PERF-01 | Ingest of a 75 s lesson ≤ 4 min cold (models downloaded, not loaded); a 10 min lesson ≤ 25 min. Progress events at least every 5 s. |
| NFR-PERF-02 | Session (cut ready) ≤ 15 s cold, ≤ 1 s when the same (video, learner-state) cut is cached. |
| NFR-PERF-03 | Tap-to-learn: cached explainer ≤ 1 s; uncached ≤ 120 s with live progress (draft → check → render → narrate → verify). |
| NFR-PERF-04 | Player renders masks at the video frame rate with ≤ 1 frame lag at 1080p; no dropped frames attributable to LOOM on the target laptop. |
| NFR-PERF-05 | Peak VRAM ≤ 7.5 GB at all times (one heavy model resident). |

### Reliability & safety

| ID | Requirement |
|---|---|
| NFR-REL-01 | **Fail closed**: any model failure on a safety path results in more masking or a blocked output, never less. |
| NFR-REL-02 | Every degraded output is labelled `degraded: [reason]` in the contract and shown in the UI. |
| NFR-REL-03 | Caches store only successful, verified results, keyed by content hash + model id + prompt version. |
| NFR-REL-04 | Jobs (ingest, explainer render) survive a gateway restart (persisted job table, resumable stages). |
| NFR-REL-05 | All contract hops are schema-validated; an invalid payload is an error, not a best-effort parse. |
| NFR-REL-06 | Generated code never runs outside the sandbox (FR-GEN-04). |

### Privacy & locality

| ID | Requirement |
|---|---|
| NFR-LOC-01 | No outbound network during ingest/session/playback except an explicit YouTube download. Enforced by `LOOM_OFFLINE=1` (sets `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, refuses non-localhost model hosts). |
| NFR-LOC-02 | Ollama host must be `localhost`/`127.0.0.1` unless `LOOM_ALLOW_REMOTE_OLLAMA=1` is set deliberately. |
| NFR-LOC-03 | Learner data stays in the local SQLite file; nothing is sent to third-party agents beyond the minimum their skill needs (see trust boundary FR-MESH-07). |

### Usability & accessibility

| ID | Requirement |
|---|---|
| NFR-UX-01 | Keyboard operable; visible focus; `prefers-reduced-motion` respected; body text contrast ≥ 4.5:1. |
| NFR-UX-02 | Captions are never altered by LOOM. |
| NFR-UX-03 | Every LOOM change (skip, condense, mask, explainer) is discoverable in the weave timeline with its reason. |

### Maintainability

| ID | Requirement |
|---|---|
| NFR-MNT-01 | One implementation per component; no dead code paths; `ruff` + `mypy --strict` on core, `eslint` + `tsc --noEmit` on web. |
| NFR-MNT-02 | Unit tests for every agent's deterministic logic; contract tests on every endpoint; one end-to-end test per persona. |
| NFR-MNT-03 | Every model, prompt and threshold lives in config (`loom.toml`), versioned; prompt text in `prompts/` files. |
| NFR-MNT-04 | Windows-first scripts (PowerShell) with POSIX equivalents. |
