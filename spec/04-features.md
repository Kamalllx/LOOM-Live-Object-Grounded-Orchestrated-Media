# 04 — Features: requirements, old → new implementation, acceptance

Each feature has an ID, a priority (**M**ust / **S**hould / **C**ould), what the old build did, how the remake
implements it, and acceptance criteria that a test or demo step can check. Stage numbers refer to
`06-build-stages.md`.

Legend for "Old": ✅ worked · ⚠️ partly / fragile · ❌ broken or missing.

---

## A. Ingest & perception (Stage 1)

### FR-ING-01 · Ingest a video from upload, local path or YouTube link · M
- **Old ⚠️** Upload or link via the library page; `yt-dlp` download (not installed on this machine); perception
  run as a subprocess under a global lock; first 10 min only (`LOOM_MAX_SECONDS`).
- **New**
  - Sources: multipart upload, local file path (CLI), YouTube/HTTP link via `yt-dlp` **Python API** (pinned
    dependency; link ingest disabled when `LOOM_OFFLINE=1`, with a clear message).
  - Normalize with FFmpeg: H.264 + AAC MP4, `+faststart`, trim to `LOOM_MAX_SECONDS` (default 600), keep native
    resolution ≤ 1080p; detect letterbox (`cropdetect`) and store `content_rect` so overlays align to the picture.
  - Identity: `video_id = slug(title) + "_" + sha256(normalized file)[:6]`; the same file or the same canonical
    YouTube id returns the existing video/job instead of re-ingesting.
  - The ingest is a persisted **job** (`jobs` table) with stages
    `probe → shots → asr → ocr → vocab → detect → segment → verify → fuse → safety → quiz → [prerender] → commit`.
- **Accept** Uploading the demo lesson twice yields one video. A YouTube link with the network off returns
  `409 offline`. A 15-min file is trimmed to 10 min and the UI says so.

### FR-ING-02 · Live ingest progress, resume, cancel, re-process · M
- **Old ⚠️** stdout lines prefixed `asr:`/`ocr:`… relayed as events; lost on restart; no resume.
- **New** Each stage publishes `ingest_stage {stage, status, progress 0..1, eta_s, detail}` events (persisted).
  Stage outputs are content-addressed blobs, so a restarted job resumes at the first stage whose output is
  missing. `POST /api/jobs/{id}/cancel` kills the worker. `POST /api/videos/{id}/reprocess {from_stage}`.
- **Accept** Kill the gateway during `segment`; restart; the job resumes at `segment` (ASR/OCR not recomputed).

### FR-PER-01 · Speech transcription with sentence and word timing · M
- **Old ⚠️** Groq Whisper (cloud) in the eval; openai-whisper locally; segments re-split on punctuation.
- **New** faster-whisper `large-v3-turbo`, CUDA fp16 (int8_float16 fallback), Silero VAD, `word_timestamps=True`,
  language auto-detect (v1 accepts English). Post-process into **sentences** with stable ids `s_001…`
  (split on terminal punctuation; max 12 s; merge < 1.2 s fragments). Store words for later caption-safe cuts.
  Silent videos produce an empty transcript and a `degraded: no_speech` flag (fusion then relies on OCR/objects).
- **Accept** WER ≤ 0.03 on the demo lesson (193 ref words); every sentence has `start < end` and ids are
  contiguous; runtime ≤ 15 s for 75 s audio on the target GPU.

### FR-PER-02 · On-screen text (OCR) with time spans and boxes · M
- **Old ⚠️** Tesseract (missing here) or RapidOCR; 1 fps; recall 1.0 / temporal IoU 0.925 on the demo.
- **New** RapidOCR on frames sampled at 2 fps within each shot, plus every keyframe; boxes normalized to the
  picture. Track identical/similar strings across frames (embedding + edit distance) into **spans** `x_001…` with
  start/end/bbox. Low-confidence or math-like crops are re-read by `glm-ocr`; result normalized to Unicode.
- **Accept** On the demo lesson: all 4 ground-truth captions found with char-similarity ≥ 0.95 and temporal
  IoU ≥ 0.9; "NaOH + HCl → NaCl + H₂O" read exactly (arrow and subscript).

### FR-PER-03 · Shot detection and keyframes · M
- **Old ⚠️** colour-histogram cut detection inside the tracker.
- **New** PySceneDetect `ContentDetector` → shots `sh_01…`; keyframes = first, middle and any frame with a large
  OCR change. Tracks never cross a shot boundary (SAM 2.1 re-prompted per shot).
- **Accept** Synthetic test video with 3 hard cuts → exactly 3 boundaries ± 1 frame.

### FR-PER-04 · Object vocabulary (what to look for) · M
- **Old ⚠️** LLM chooses phrases from the transcript + always-on hazards `broken glass, knife, open flame`.
- **New** Union of (a) `brain` VLM `vocab_propose` over ≤ 8 keyframes + transcript + OCR (concrete, visible,
  teachable objects, ≤ 12), (b) transcript noun phrases that match a lab/classroom lexicon, (c) **always-on hazard
  classes** from config (`broken glass, knife, blade, scissors, needle, open flame, fire, blood, gun, cigarette,
  pills, syringe`), each with a curated **look-alike list** (e.g. broken glass ↔ glass beaker, ice, plastic wrap).
- **Accept** On the demo lesson the vocabulary contains every ground-truth object label (or a synonym) and all
  hazard classes; the vocab stage works with the `brain` model stopped (heuristic fallback, `degraded` flag).

### FR-PER-05 · Open-vocabulary detection · M
- **Old ⚠️** Grounding DINO *tiny*, box threshold low; hazard detection confidence 0.33.
- **New** Grounding DINO **base** on frames at `sample_fps` (default 2, 4 within hazard candidate windows),
  phrases batched ≤ 8 per pass, box threshold 0.30 / text threshold 0.25 (config), NMS per phrase.
  Detections are *proposals* for segmentation, not final objects.
- **Accept** Recall of ground-truth object instances ≥ 0.9 at IoU 0.5 on annotated keyframes.

### FR-PER-06 · Segmentation and tracking with pixel masks · M
- **Old ❌** Boxes only, IoU tracker at 1 fps, SAM 3.1 promised but not run.
- **New** Tier T1 (`02-architecture.md` §10): per shot, the highest-scoring detection of each phrase seeds SAM 2.1
  video propagation (box prompt) forward and backward through the shot at `sample_fps`; new detections that do not
  overlap an existing track (mask IoU < 0.3) seed new tracks. Output per object instance: per-sample `bbox` and
  **mask RLE** (COCO), start/end, mean score. Long lessons processed in 60 s chunks with 1 s overlap, stitched by
  mask IoU. Optional T2 (`sam3`) behind the same interface.
- **Accept** Mask IoU ≥ 0.7 vs ground-truth masks on 20 annotated frames; track continuity: no ground-truth object
  split into > 2 tracks within a shot; peak VRAM ≤ 7.5 GB.

### FR-PER-07 · Detection verification with look-alikes · M
- **Old ✅** CLIP check where a hazard must beat its look-alikes → hazard precision 0.13 → 1.00.
- **New** Two-step: (1) SigLIP2 zero-shot on the track's best 3 crops: phrase vs its look-alikes vs "background";
  keep if the phrase wins by margin ≥ 0.1. (2) For **hazard** tracks only, `brain` `hazard_crop_check` on the same
  crops. A hazard is kept if *either* step confirms it (recall over precision); a hazard rejected by both is
  dropped but logged; any step failing to run ⇒ the track is kept as `unverified` (counts as hazard).
- **Accept** On the demo lesson: hazard precision ≥ 0.95, recall ≥ 0.9, false-block ≤ 2 s, missed ≤ 0.5 s (the
  ablation table of `07-evaluation.md` is regenerated).

### FR-PER-08 · Concept graph fusion with evidence IDs and prerequisites · M
- **Old ⚠️** Embedding topic segmentation + LLM labelling; evidence linked by float timestamps; prerequisites from
  an LLM "enrich" step.
- **New**
  1. Topic segmentation: embeddings of 3-sentence windows → change points (cosine drop > config) → segments.
  2. `brain` `concept_fuse` labels each segment (may merge adjacent segments) and **cites** `segment_ids`,
     `text_ids` (OCR spans overlapping in time) and `object_ids` (objects visible during the segment whose
     label embedding is relevant to the segment text, threshold from config).
  3. `concept_prereqs` proposes edges; LOOM keeps only edges from earlier to later concepts and verifies
     acyclicity.
  4. Validation: every concept cites ≥ 1 sentence or OCR span; every cited id exists; every sentence belongs to
     at most one *primary* concept.
- **Accept** On the demo lesson: 5–7 concepts covering ≥ 95 % of transcript time; PPE → acid/base dissociation →
  neutralization → indicator chain present; all evidence ids resolve.

### FR-PER-09 · Ingest-time safety review of every object · M
- **Old ❌** Per session; single cloud model; failures tagged *safe* and cached (`00-audit.md` B3/B4).
- **New** For each object: `safety` (Granite Guardian) per-tag criteria with lesson context **and** `brain`
  visual per-tag check on crops; union rule; record `{status reviewed|partial|unreviewed, tags, severity,
  child_unsafe, reasons, models, disagreement}` in `safety_reviews`. Never cached on failure; a background retry
  re-reviews `unreviewed/partial` objects when models become available.
- **Accept** Broken glass tagged `sharp_object`/`injury_risk` with severity ≥ 0.5; lab coat, gloves, goggles not
  child-unsafe; with Ollama stopped the review yields `unreviewed` for every object (not "none").

### FR-PER-10 · Ingest-time verified quiz bank · M
- **Old ⚠️** Quiz written per session by an LLM, verified by the Critic's LLM judge in the loop.
- **New** For each concept × level (`beginner`, `intermediate`, `expert`): `brain` writes 3 candidate MCQs, each
  citing `evidence_segment_ids`; `judge` `quiz_verify` checks answerable / unique answer / marked answer correct;
  deterministic checks: 4 distinct options, no "all/none of the above", answer text not verbatim the longest
  option > 60 % of the time across the bank. Only verified questions enter the bank.
- **Accept** ≥ 1 verified question per concept per level on the demo lesson; planted wrong-answer question
  rejected.

### FR-PER-11 · Background pre-render of likely explainers · S
- **New** After commit, a low-priority `prerender` job renders explainers for concepts whose role is `core`/
  `setup`, at `beginner` level, through the full Animator + Critic path. Pausable; yields the GPU to any
  interactive lease.
- **Accept** After prerender, Priya's session has all auto explainers as cache hits (time to cut ≤ 2 s).

### FR-PER-12 · Perception inspector · S
- **Old ⚠️** `scripts/render_frame.py`, `overlay.py` produce static images.
- **New** Web page `/videos/{id}/inspect`: video with toggleable overlays (object masks with labels and
  verification status, OCR boxes, current sentence, current concept), side lists of concepts with evidence chips,
  safety review table with both judges' verdicts. Export a frame with overlays as PNG (for the paper).
- **Accept** Every object/OCR span in the graph is visible at its time in the inspector.

---

## B. Agent mesh (Stage 2)

### FR-MESH-01 · A2A Agent Cards and JSON-RPC tasking · M
- **Old ✅⚠️** Minimal A2A: card at `/.well-known/agent.json`, `message/send` with a `data` part; whole graph sent
  every call.
- **New** A2A 0.3 subset (`02-architecture.md` §5): `agent-card.json` (+ legacy path), `message/send`,
  `tasks/get` for long tasks, LOOM `x-loom` card extension (contracts, trust), artifact references instead of
  inline graphs, JSON-RPC error codes. Shared helper `loom.core.a2a` (server router + client with timeout,
  retries for idempotent skills, latency metrics, event publishing).
- **Accept** Contract test: each first-party agent's card validates against the card schema; a raw `curl`
  JSON-RPC call to any skill returns a schema-valid result; payload for Curator < 50 KB on the demo lesson.

### FR-MESH-02 · Agent registry and live registration · M
- **Old ✅** Register a third-party agent by URL from the Agents page; discovered by skill.
- **New** Registry in SQLite; `POST /api/agents/register {url, required}` fetches and validates the card, checks
  the URL is localhost/LAN (configurable allow-list), stores trust `plugin`. Enable/disable/remove. Health
  ping every 30 s; failures counted. Agents page shows cards, skills, last latency, failures.
- **Accept** Register `http://127.0.0.1:8100` live; the next session's trace contains `policy_review` from it;
  disable it and the next trace does not.

### FR-MESH-03 · Orchestrator · M
- **Old ✅** Fixed sequence Curator → Pedagogy → plug-ins → Personalizer → Assessment; `revise_cut` callback.
- **New** Same sequence, expressed as a small declarative plan in config (skills, order, fan-out, timeouts,
  required flags). Responsibilities: resolve learner + graph refs, call skills, merge plug-in outputs, build
  candidate pass N, expose `revise_cut` (A2A skill) that routes Critic issues to the right agent (Personalizer
  for structure, Assessment for quiz), keep an `agent_trace` (agent, version, skill, latency, status). Session
  cut cache lookup happens before the plan runs (FR-VER-08).
- **Accept** Trace for a demo session lists every call with latency; a plug-in timeout produces
  `degraded: plugin_timeout` and the session still completes.

### FR-MESH-04 · Curator: knowledge threads · M
- **Old ✅⚠️** Sentence-aligned threads by concept ownership; LLM role labels (failed → all `core`).
- **New** Same algorithm on **ids** (sentence ownership from concept `segment_ids`); threads `t1…` partition the
  timeline at sentence boundaries; OCR-only concepts attached by span time; silent videos fall back to
  concept evidence windows. Roles from the **ingest-time** `thread_roles` (computed once per graph, cached with the
  graph) — no LLM on the session path. Role failure ⇒ `core` (never skipped).
- **Accept** Threads partition [0, duration] with no gaps/overlaps; no thread boundary falls inside a sentence;
  identical output for identical graph (deterministic).

### FR-MESH-05 · Pedagogy: per-thread action for this learner · M
- **Old ✅** Deterministic thresholds skip ≥ 0.80 / condense ≥ 0.60 / keep ≥ 0.35 / else expand, pace shift ±0.10,
  role rules, prerequisite guard.
- **New** Same policy, thresholds in config, every decision carries a human-readable `rationale` and the inputs
  used (mastery value, source: `mastery_graph` vs `prior_knowledge`). Adds: a learner's *explicit* preference
  overrides (e.g. "never skip", "always explain").
- **Accept** Table-driven unit tests for each rule; Alex (0.85, condensed) never skips a `core` or `safety`
  thread; Priya gets `expand` on core threads; changing mastery of one concept changes only its thread's action.

### FR-MESH-06 · Personalizer: assemble and revise the cut · M
- **Old ✅** Condense to ~half ending on a sentence boundary (≥ 6 s, ≥ 3 s after an on-screen formula appears);
  auto explainers for `expand`; tap explainers for concepts with objects; redaction *requests* for every visible
  object when redaction ≠ off; `revise()` handles 5 issue codes.
- **New** Same rules, plus: condensing uses **word** timestamps to pick the latest sentence end ≤ target + 2 s;
  explainer requests carry `anchor_time` and `level`; redaction requests are only *hints* (Guardian reviews
  every object anyway); `revise` handles `cut_mid_sentence`, `missing_prerequisite`, `explainer_unavailable`,
  `overlapping_threads`, `out_of_order`, `empty_cut`, `too_short` (cut < 30 % of source for a non-expert).
- **Accept** Golden-file tests per persona on the demo graph; each revise code has a unit test turning a faulty
  cut into one the Critic approves.

### FR-MESH-07 · Plug-in trust boundary · M
- **Old ⚠️** Plug-in redaction requests honoured; output not schema-checked; full graph shared.
- **New** Plug-ins receive only their declared view (e.g. `safety` view: object ids, labels, times — no
  transcript unless declared). Their outputs are schema-validated; a plug-in can only **add** restrictions
  (masks, a skip of a thread it names with a reason) — it cannot remove masks, add content, or change quiz. Every
  plug-in effect is labelled in the verified cut (`source: plugin:<name>`) and shown in the weave timeline.
  `required` plug-ins that fail block delivery (`plugin_unavailable`); optional ones degrade.
- **Accept** A malicious test plug-in that returns a request to *unmask* an object or a malformed payload has no
  effect and is reported.

### FR-MESH-08 · Assessment: select quiz, update mastery · M
- **Old ⚠️** LLM writes ≤ 3 questions per session (failed silently → empty quiz); mastery update rule from
  client-reported correctness.
- **New** `select_quiz`: up to 3 questions from the **verified bank**, targeting the lowest-mastery concepts that
  are in the cut, at the learner's level, avoiding questions this learner saw in the last 2 sessions.
  `update_mastery`: applies the EMA rule to **server-recorded** events only (graded answers, explainer views
  confirmed by server events, thread completion from telemetry):
  correct `m ← m + 0.35(1−m)`, wrong `m ← 0.75 m`, explainer watched `m ← m + 0.05(1−m)`, thread completed
  `m ← m + 0.03(1−m)`.
- **Accept** Quiz never empty when the bank has questions for in-cut concepts (else `quiz_missing` issue);
  answering via devtools with a forged `correct:true` has no effect.

### FR-MESH-09 · Example third-party agent: school policy · M
- **Old ✅** Separate FastAPI app on :8100, `policy_review`, masks labels listed in `POLICY_MASK_LABELS`.
- **New** Same idea as a standalone package in `plugins/school_policy_agent/` (own pyproject, no import of
  `loom`), config file with label rules and thread-skip rules, its own card with `x-loom.trust: plugin`.
- **Accept** Starting it and registering it live changes the Parent + child cut (e.g. masks "safety goggles" if
  configured) and the change is attributed to the plug-in in the UI.

---

## C. Safety, verification and generation (Stages 3–4)

### FR-SAF-01 · Viewer safety profiles · M
- **Old ✅** `redaction_level` off / standard (child_unsafe & severity ≥ 0.5) / strict (severity ≥ 0.2) +
  `blocked_tags`.
- **New** Same three levels plus `blocked_tags`, `allowed_tags` (explicit exceptions a parent sets), and
  `parent_lock` (viewer cannot reveal enforced masks without the parent PIN set on the profile).
- **Accept** Unit tests for every level × tag combination.

### FR-SAF-02 · Guardian: per-viewer redaction decision · M
- **Old ⚠️** LLM tags per session + decision; fail-open.
- **New** Deterministic `review_objects` over the ingest-time `safety_reviews` + viewer profile + plug-in
  requests: redact if (a) any blocked tag, or (b) level threshold met, or (c) a plug-in requested it, or
  (d) **status ∈ {unreviewed, partial} and level ≠ off**. Returns decisions with reasons.
- **Accept** Parent + child on the demo lesson masks broken glass; with all safety reviews forced to
  `unreviewed`, every visible object is masked for Parent + child and nothing for Alex.

### FR-SAF-03 · Masks: pixel-accurate, padded in space and time · M
- **Old ⚠️** Box masks padded 0.04, time-padded 1 s, one JSON track per instance.
- **New** Mask track per redacted instance: per-sample RLE mask **dilated** by 3 % of frame diagonal plus a box
  fallback padded 0.04; time padding = one sampling interval each side (0.5 s at 2 fps). Served as compact JSON
  (`/media/masks/<video>/<object>_<k>.json`) with RLE strings; client interpolates boxes between samples and uses
  the nearest mask (or its union with the neighbouring sample during motion).
- **Accept** Redaction recall ≥ 0.95 of ground-truth hazard pixel-time; 0 s of safe content fully blocked.

### FR-SAF-04 · Fail-closed safety under model failure · M (new)
- **Old ❌** Model failure ⇒ every object tagged `none`/severity 0 ⇒ no masks, and the result cached
  (`00-audit.md` B3/B4).
- **New** Safety state is three-valued per object (`reviewed`, `partial`, `unreviewed`); anything not `reviewed`
  is treated as unsafe for every viewer whose redaction level is not `off` (Guardian, FR-SAF-02 rule d) **and** is
  counted in the Critic's independent hazard set (FR-VER-03). Degraded reviews are never cached; a background job
  re-reviews them when `/api/ready` reports the safety roles healthy, and invalidates affected cut-cache entries.
  The UI shows "Safety review incomplete — extra masking applied" (FR-DEL-13).
- **Accept** Outage matrix in `07-evaluation.md` §5 passes; after Ollama returns, re-review runs and the next
  Parent + child session masks only the genuinely unsafe objects.

### FR-VER-01 · Bounded Perceive → Plan → Act → Verify loop · M
- **Old ✅** Budget 3; local fixes for `unmasked_hazard`/`explainer_unfaithful`; other codes to `revise_cut`;
  fallback.
- **New** Same structure in `loom/agents/verifier.py`, as an A2A agent (`verify_cut`). Every phase publishes
  `loop_phase` events; every pass writes `critic_pass{n}` to the session record; the loop never returns a cut
  the Critic has not approved except through FR-VER-07.
- **Accept** Fault-injection suite (`07-evaluation.md` §4) passes; trace for a forced 2-pass session shows pass 1 issues and
  pass 2 approval.

### FR-VER-02 · Critic coherence (deterministic) · M
- **Old ✅** ordering/overlap, mid-sentence ends, missing prerequisites, explainer failures.
- **New** Same plus `too_short`, threads outside [0, duration], explainer anchor outside the cut, quiz concept not
  in the cut. Score = 1 − Σ penalties; **any** issue blocks.
- **Accept** One unit test per issue code.

### FR-VER-03 · Critic safety: independent hazard set · M
- **Old ❌** Coverage measured only over Guardian-flagged objects.
- **New** The Critic computes its *own* hazard set for this viewer from (a) ingest safety reviews with the
  viewer's profile, (b) any object with status `unreviewed/partial` when redaction ≠ off, (c) any object whose
  label matches an always-on hazard class, (d) plug-in requests. Coverage of that set's screen time inside the cut
  (0.1 s sampling, pixel masks via their padded boxes) must be exactly 1.0; uncovered objects produce
  `unmasked_hazard`.
- **Accept** Fault family F-SAF: Guardian returns no masks for Parent + child → Critic blocks with
  `unmasked_hazard obj_broken_glass`.

### FR-VER-04 · Critic factuality with retrieved evidence · M
- **Old ✅⚠️** LLM judge (same family) over quiz + storyboard lines vs whole transcript; judge failure ⇒ 0.
- **New** Claims = quiz items not already bank-verified (normally none) + explainer storyboard lines not already
  verified (by content hash). For each claim, retrieve top-5 evidence items (sentences + OCR) by embedding plus
  cited ids; `judge` `claims_verify`; unsupported claims → `explainer_unfaithful` (with feedback) or
  `quiz_unsupported`. Judge unavailable ⇒ affected artifacts dropped (`judge_unavailable`), never passed.
- **Accept** 12-explainer run reproduces the old "pass 1 rejects an invented indicator colour → re-render → pass 2
  approves" example.

### FR-VER-05 · Critic completeness · M
- **New** Required artifacts per learner (config): quiz (≥ 1 question if the bank has in-cut concepts), auto
  explainers for `expand` threads (or an `explainer_unavailable` resolution), required plug-ins. Missing ⇒
  `quiz_missing`, `explainer_missing`, `plugin_unavailable`.
- **Accept** Assessment returning `[]` while the bank has questions → session blocked on pass 1, fixed on pass 2.

### FR-VER-06 · Act: local fixes and mesh revisions · M
- **Old ✅** As described in `00-audit.md` D.
- **New** Local: `unmasked_hazard` → add a forced mask; `explainer_unfaithful` → one re-render with feedback, then
  drop; `layout_failed` → one re-draft. Mesh: structural and quiz codes → `Orchestrator.revise_cut`.
  Every action is recorded in the loop trace with the issue that caused it.
- **Accept** Trace shows issue → action → result for each pass.

### FR-VER-07 · Fallback when the budget is spent · M
- **Old ✅** Last verified cut for (video, learner), else whole lesson with strict masks, no generated content.
- **New** Same; the fallback cut is itself run through the Critic's safety and coherence checks (no LLM) and is
  labelled `status: fallback` with the reason; the UI shows "Showing a safe default cut (why)".
- **Accept** With the judge model stopped and an explainer-only cut, the viewer receives a fallback with no
  generated content and all hazards masked.

### FR-VER-08 · Verified cut cache · S
- **New** Key `(graph_sha, learner_state_sha, agent_set_sha, policy_version)`; learner-state hash covers mastery
  values rounded to 0.05 and preferences; any change produces a new cut. Hit ⇒ deliver in < 1 s with
  `cache_hit: true` in the trace.
- **Accept** Second identical session is a cache hit; after a quiz changes mastery, the next session is a miss.

### FR-GEN-01 · Animator: storyboard + Manim code drafting · M
- **Old ✅** LLM returns `{storyboard, code}` under detailed style rules; LaTeX disabled when absent.
- **New** `brain` `manim_draft` with: concept, summary, learner level, cited lesson sentences, and a **style
  pack** (frame 16:9, title zone, large shapes, ≤ 5 beats, 10–18 s, colour palette, takeaway line). LaTeX is
  available on the target (MiKTeX) → `MathTex` allowed when `latex` is on PATH (checked at startup).
  Storyboard lines must each map to a beat; code comments `# beat k` delimit beats.
- **Accept** First-attempt compile ≥ 0.95 on the 12-concept set (6 concepts × 2 levels).

### FR-GEN-02 · Static code gate · M
- **Old ✅** AST allow-list: imports only manim/math/numpy; forbidden builtins; no dunder attributes; no
  ImageMobject/SVG/sound; class `Explainer(Scene)` required.
- **New** Same allow-list plus: forbid any reference to `config`, `os`, `sys`, `subprocess`, `Path`, `open`,
  `tempconfig`, attribute access on modules other than `math`/`np`, `while True`, recursion depth > 1; limit
  source to 250 lines; limit loop ranges to literal bounds ≤ 200.
- **Accept** A corpus of 25 hostile snippets (file write, `config.media_dir`, `__class__` tricks, infinite loops)
  is rejected; the 12 good drafts pass.

### FR-GEN-03 · Rendering · M
- **Old ✅** `manim render -qm` subprocess, 120 s timeout, bounded repair (2) with the error tail.
- **New** Render in the worker at `-qm` (720p30) with `--disable_caching`, 120 s timeout; on failure, `manim_repair`
  with the last 40 lines of stderr; ≤ 2 repairs. Encode with NVENC when available, libx264 otherwise.
- **Accept** Render success ≥ 0.95; median render ≤ 20 s on the target.

### FR-GEN-04 · Sandbox for generated code · M
- **Old ❌** Subprocess with the user's full environment and network.
- **New** Layers: (1) AST gate (FR-GEN-02); (2) a fresh temp dir as CWD containing only `scene.py`; (3) minimal
  environment (`PATH` to Python/FFmpeg/LaTeX only, no user tokens, `HOME`/`USERPROFILE` → temp dir);
  (4) a **Windows Job Object** (via `pywin32`) limiting memory (2 GB), CPU time, and child processes, killed on
  timeout; (5) no network — the subprocess gets `LOOM_SANDBOX=1` and a `sitecustomize.py` that disables
  `socket` creation; (6) outputs copied out only if they are a single MP4 within size limits. POSIX equivalent:
  `prlimit` + `unshare -n` when available.
- **Accept** A snippet that bypasses the AST gate in a test build (gate disabled) still cannot write outside the
  temp dir, open a socket, or exceed memory.

### FR-GEN-05 · Layout check of rendered explainers · S (new)
- **Old ❌** Not verified (paper limitation).
- **New** Two checks: (a) **geometric**: the scene runs with a LOOM `Scene` mixin that, after each `play`, records
  every mobject's bounding box and flags off-frame (> 2 % outside), overlaps between text mobjects (IoU > 0.1),
  and text height < 3 % of frame; (b) **visual**: `brain` `layout_check` on a 3×3 grid of frames. Failure → one
  re-draft with the problems listed.
- **Accept** On the 12-concept set ≥ 90 % pass layout on first or second draft; a planted overlapping-text scene is
  caught.

### FR-GEN-06 · Narration · M
- **Old ⚠️** Google Cloud TTS → OS speech; narration muxed, last frame held if audio is longer.
- **New** Kokoro-82M (ONNX, CPU, voice configurable) → Piper → Windows SAPI → silent with captions. Per-beat
  narration aligned to beats: the render records beat start times; audio for beat k is placed at its start;
  burned-in captions (optional) from the storyboard. Loudness normalized (EBU R128, −16 LUFS).
- **Accept** Narrated clip has audio, duration within ±1 s of max(video, audio), captions match storyboard.

### FR-GEN-07 · Content-addressed explainer cache · M
- **Old ⚠️** Clip name from (concept label, summary, level); verification cache by URL (`00-audit.md` B7).
- **New** `content_hash = sha256(storyboard, code, voice, animator_version, brain digest)`; clip stored at
  `/media/clips/<content_hash>.mp4`; the `explainers` table maps `(graph_sha, concept_id, level)` → latest
  **verified** content hash. Re-renders create new hashes; nothing is overwritten.
- **Accept** Re-render with feedback produces a new URL; the old unverified clip is never served.

### FR-GEN-08 · Tap-to-learn · M
- **Old ✅⚠️** Click a tracked object → render (or fetch) explainer → fact-check (budget 2) → show; ~70 s cold.
- **New** `POST /api/sessions/{id}/explain {concept_id}` returns immediately with a cached verified clip or a
  `job_id`; the job runs draft → gate → render → layout → narrate → verify (budget 2) under the `tap_explainer`
  GPU priority and streams progress events; the player shows a progress chip on the tapped object and keeps
  playing. Level = learner's level for that concept.
- **Accept** Cached tap ≤ 1 s; uncached ≤ 120 s with ≥ 5 progress events; an unverified clip is never shown.

---

## D. Delivery (Stage 5)

### FR-DEL-01 · Library · M
- **Old ✅** Video cards; add a video (upload or link); viewer picker; Watch.
- **New** Next.js + TS. Cards show title, duration, objects/concepts counts, ingest status, degraded flags.
  Add-video dialog with upload (drag-drop), path (dev only) or link; live ingest progress per stage (SSE).
  Readiness banner from `/api/ready`.
- **Accept** E2E: upload → see stage-by-stage progress → card becomes "Ready" → Watch.

### FR-DEL-02 · Viewer picker and learner cards · M
- **Old ✅** Alex / Priya / Parent + child cards.
- **New** Same three seeded; "New learner" form (name, prior knowledge slider, pace, safety level, blocked tags,
  parent PIN); edit and reset.
- **Accept** Creating a learner and watching produces a cut consistent with its settings.

### FR-DEL-03 · Player: plays only the verified cut · M
- **Old ✅** Plays kept threads, skips the rest, condensed threads end early.
- **New** `@loom/engine` computes the playback plan; the player seeks across skipped ranges with a short
  cross-fade and a toast "Skipped: setup (you know this)"; seeking by the user into a skipped range is allowed
  (viewer control) and logged; masks still apply everywhere.
- **Accept** For Alex the played time equals the cut length ± 0.5 s; user seek into skipped area works.

### FR-DEL-04 · Mask compositing · M
- **Old ⚠️** CSS blur boxes following interpolated per-second tracks.
- **New** A `<canvas>` overlay synced with `requestVideoFrameCallback`: draws a blurred copy of the current frame
  (`ctx.filter = "blur(24px)"` or a WebGL2 Gaussian) clipped by the decoded RLE mask (cached as `ImageBitmap`
  per sample) with box fallback. Masks are aligned to the picture via `content_rect` and `containRect`. A small
  rose badge "masked · broken glass · why?" opens the reason.
- **Accept** No visible unblurred hazard frames in a frame-by-frame capture of the 56–65 s window; ≤ 1 frame lag.

### FR-DEL-05 · Tap targets · M
- **Old ✅** "Show tappable objects" toggle; click an object with a concept.
- **New** Hit-testing against the current mask (not just the box); focusable list of current tappable objects
  for keyboard users; hover outline in amber.
- **Accept** Keyboard-only user can open an explainer.

### FR-DEL-06 · Explainer overlay · M
- **Old ✅** Auto explainer at thread end for beginners; tap explainer overlay.
- **New** Auto explainers pause the lesson at `anchor_time` and play in a modal (skip / replay / "less of these");
  tap explainers play picture-in-picture without pausing unless the viewer chooses. Storyboard shown as captions.
- **Accept** Priya sees auto explainers at the anchors; "less of these" lowers the expand threshold in her
  preferences.

### FR-DEL-07 · Live loop panel · M
- **Old ✅** Streams agent calls and loop phases while the cut is woven.
- **New** Timeline of A2A calls (agent, skill, latency, status), loop passes with the three scores and issues,
  actions taken, cache hits, GPU waits, degraded flags — all from SSE. Collapsible; "export trace" (JSON).
- **Accept** Every event in the session trace appears in the panel in order.

### FR-DEL-08 · Weave timeline with reasons · M
- **Old ✅** Weave bar showing kept/condensed/skipped segments and masks.
- **New** Under the video: source timeline with coloured segments (kept, condensed, skipped), mask spans (rose),
  explainer anchors (violet), plug-in effects (teal outline); clicking any element explains *why* (rationale
  from Pedagogy/Guardian/plug-in) and offers the opt-out.
- **Accept** Every change in the verified cut has a clickable reason.

### FR-DEL-09 · Compare weaves · S
- **Old ✅** Alex 78 % condensed, Priya full + explainers, Parent full + masks.
- **New** `/weave/{videoId}`: side-by-side timelines for all learners with summary stats (kept %, explainers,
  masks, quiz count, pass count).
- **Accept** Matches the per-learner verified cuts.

### FR-DEL-10 · Agents page · M
- **Old ✅** List agents; register by URL.
- **New** Cards, skills, trust, required flag, enable/disable, live latency/failures; "register" dialog validates
  the card and shows it before adding.
- **Accept** Live registration demo works without reload.

### FR-DEL-11 · Quiz panel · M
- **Old ⚠️** Questions with answers in the client; "Save to my mastery graph".
- **New** Questions arrive without answers; each answer is graded by the server and shows rationale + the lesson
  moment (seek link to the evidence sentence); "Finish" posts `/finish` and shows mastery deltas per concept.
- **Accept** Network tab shows no `answer_index` before answering.

### FR-DEL-12 · Mastery view · S
- **New** Per learner: concept graph (nodes coloured by mastery, prerequisite edges), history per concept, "watch
  again" with a preview of how the cut will change.
- **Accept** After Priya's quiz, the view shows the updated levels; "watch again" produces a different cut.

### FR-DEL-13 · Honest degradation in the UI · M (new)
- **New** Banners and inline chips for every `degraded` flag and fallback ("Quiz unavailable — judge model
  offline", "Safety review incomplete — extra masking applied").
- **Accept** Stopping Ollama mid-demo produces the banners, not silent omissions.

### FR-DEL-14 · Accessibility, motion and brand · M
- **New** WCAG AA contrast, keyboard paths for every action, focus rings, `prefers-reduced-motion` disables
  cross-fades and orb animations, captions untouched. Brand tokens: amber `#FFB020` perception, teal `#2DD4C7`
  mesh, violet `#A78BFA` verification, rose `#FF6584` redaction; Instrument Serif / Inter Tight / JetBrains Mono;
  light and dark themes.
- **Accept** axe-core: 0 serious violations on library, player, agents pages.

---

## E. Memory (Stage 6)

### FR-MEM-01 · Learner profiles and mastery graph · M
- **Old ⚠️** JSON files per learner; `mastery_graph` list keyed `video_id/concept_id`.
- **New** SQLite `learners` + `mastery`; mastery keyed `video_id/concept_id` **and** optionally a global concept
  key (`concept:acid_dissociation`) when fusion maps a concept to a known canonical label (cross-video transfer:
  C, later).
- **Accept** Concurrent sessions for two learners never corrupt profiles (transactional test).

### FR-MEM-02 · Session logging · M
- **Old ⚠️** Client posts a full log at the end.
- **New** Client batches events every 5 s and on `pagehide` (`navigator.sendBeacon`); server stamps receive time;
  final `session-log` (Contract D) assembled server-side.
- **Accept** Closing the tab mid-session still records events up to the close.

### FR-MEM-03 · Server-side grading · M
- **Old ❌** Client sends `correct`.
- **New** `quiz_attempts` written by the answer endpoint; mastery uses only those.
- **Accept** See FR-MESH-08.

### FR-MEM-04 · Mastery update rule · M
- **Old ✅** EMA rule (kept, FR-MESH-08). **New** Rule parameters in config; each update stores before/after and
  the event that caused it (auditable).

### FR-MEM-05 · Learner editor and reset · S
- **Old ⚠️** Reset all via API. **New** Per-learner reset, edit, delete; reset-all for demos.

### FR-MEM-06 · Next session reflects mastery · M
- **New** Cut cache key includes the learner-state hash (FR-VER-08); "watch again" always re-plans.
- **Accept** Priya: watch → answer all correctly → watch again → at least one thread changes from expand to keep.

---

## F. YouTube extension (Stage 7)

### FR-EXT-01 · Detect the YouTube video and connect to LOOM · S
- **Old ✅⚠️** Content script detects the watch page; looks up / ingests via the gateway; long-polls events.
- **New** Content script handles YouTube SPA navigation (`yt-navigate-finish`); service worker talks to the
  gateway (token from options), streams events via `fetch` streaming; "Process this video with LOOM" button when
  not yet ingested (disabled when the gateway is offline-mode).
- **Accept** Navigating between three videos without reload keeps state correct.

### FR-EXT-02 · Masks over the YouTube player · S
- **Old ✅** Overlay aligned to the letterboxed picture inside `video.html5-main-video`.
- **New** Same `@loom/engine` geometry; canvas compositing as in FR-DEL-04; follows theatre/fullscreen modes.
- **Accept** Masks align in default, theatre and fullscreen modes.

### FR-EXT-03 · Skip to the viewer's cut · S
- **Old ✅** **New** Same engine plan; YouTube ads and user seeks respected; skip toast.

### FR-EXT-04 · Explainers inside the player · S
- **Old ✅** Explainer page inside the player area. **New** Same, using the shared explainer component.

### FR-EXT-05 · Panel · S
- **Old ✅** Preact panel: viewer, mesh calls, weave bar. **New** Same views as the web player's loop panel and
  weave timeline, sharing components where possible (Preact compat).

### FR-EXT-06 · Options · S
- **New** Gateway URL (default `http://127.0.0.1:8000`), token, default learner; host permission request when the
  URL changes.

---

## G. Operations (Stage 0 onward)

### FR-OPS-01 · Health and readiness · M
- **Old ❌** `/api/health` always `ok:true`.
- **New** `/api/health` (liveness) and `/api/ready` (per-role model presence + last smoke-test result, worker
  spawn test, disk free ≥ 5 GB, offline flag). UI banner when not ready.
- **Accept** Stopping Ollama flips `/api/ready` to `ready:false` within 30 s.

### FR-OPS-02 · `loom doctor` · M
- **New** CLI check of: Python/uv, CUDA + VRAM, FFmpeg + NVENC, LaTeX, Ollama env vars, each model (presence +
  smoke call), HF cache for open weights, ports free, disk. Prints fixes.

### FR-OPS-03 · Offline mode · M
- **New** `LOOM_OFFLINE=1` → HF offline env vars, link ingest disabled, Ollama host must be loopback; a CI test
  runs the full demo with outbound network blocked (Windows firewall rule in the test script).

### FR-OPS-04 · Structured logs and traces · M
- **New** JSON logs (structlog) with `session_id`/`job_id`; per-session trace export (all events + agent trace +
  critic passes) used by the paper's figures.

### FR-OPS-05 · CLI · M
- **New** `loom gateway`, `loom worker`, `loom ingest <file|url>`, `loom session <video> <learner>`,
  `loom eval [suite]`, `loom doctor`, `loom warm` (demo warm-up: ingest/prerender/cut cache for all personas).

### FR-OPS-06 · Data management · S
- **New** Delete a video (and its blobs), purge caches by role/model digest, export/import a video bundle
  (graph + media + masks) for sharing a processed lesson between team machines without re-running perception.
