# Verification, Safety & Generation

Owner: Person 3
Consumes: [/contracts/candidate-cut.schema.json](../../contracts/candidate-cut.schema.json) (Contract B), in the shape of [/fixtures/candidate-cut.sample.json](../../fixtures/candidate-cut.sample.json)
Produces: [/contracts/verified-cut.schema.json](../../contracts/verified-cut.schema.json) (Contract C), in the shape of [/fixtures/verified-cut.sample.json](../../fixtures/verified-cut.sample.json)

Turns a candidate cut into a verified cut. Nothing reaches a viewer without passing the Critic:

```
candidate-cut.json ─┐
concept graph (P1) ─┼─► PERCEIVE  Guardian: safety tags → per-viewer masks (+ matte videos)
learner profile (P4)┘            Animator: explainer_requests → Manim clips (cached)
                         PLAN      Critic: safety · coherence · factuality → structured issues
                         VERIFY    approved ─────────────────────────────► verified-cut.json
                         ACT       re-render / drop explainer, force mask, drop wrong quiz item,
                                   thread issues → agent mesh (P2) or local repair; next pass
                         budget spent → last verified cut for this video + learner, else a strict baseline
```

| Component | Module | What it does |
|---|---|---|
| Critic + loop | `critic.py`, `loop.py` | Scores **safety** (share of flagged-object screen time inside the cut covered by a mask, must be 1.0), **coherence** (ordered, non-overlapping, inside the video, no mid-sentence cut, known concepts, prerequisites present, explainers available) and **factuality** (every quiz answer and explainer sentence supported by the lesson). Any single issue blocks approval: averages hide individual failures. Up to `LOOM_LOOP_BUDGET` (3) passes, then fallback. |
| Guardian | `guardian.py`, `matte.py` | Tags each object (LLM in lesson context, with a hazard lexicon as a floor and as the offline fallback), applies the learner's `family_safety_profile` (`off` / `standard` / `strict`, `blocked_tags`) and honours the mesh's `redaction_requests`. Reviews every object, so a hazard the mesh missed is still caught. One mask per visible instance, padded in time by one perception sample, with a `fallback_bbox` covering every tracked box and a matte video built from Person 1's per-frame masks. |
| Animator | `animator.py` | LLM writes a storyboard + Manim code → AST allow-list (no file/OS/network access) → render in a subprocess with a timeout → up to 2 repairs from the error → narration (macOS `say`, Windows SAPI, `espeak`; silent if none) → cached per concept + level. Without an LLM, or if every draft fails, a template scene made only of the lesson's own sentences is rendered. |

## Contract C output

Everything in the fixture, field for field, plus the **additive** fields the delivery client asked for in [`services/delivery/web/CONTRACT-NOTES.md`](../delivery/web/CONTRACT-NOTES.md). All optional; consumers that ignore them are unaffected:

- `final_threads[]`: `concept_node_ids`, `label` (concept labels), `action`
- `redaction_masks[]`: `reason`, `fallback_bbox` `[x, y, w, h]` normalized 0–1
- `explainer_clips[]`: `title`, `anchor_seconds`, `duration_seconds`
- `quiz[]`: `options` / `answer_index` passed through from the mesh when present (an item whose marked answer fails the fact-check is dropped, never shipped)
- top level: `video_id`, `learner_id`, `loop_trace` (one entry per pass: scores, issues, latency)

Media URLs use the contract's `s3://<bucket>/<key>` form (`loom-masks`, `loom-clips`); files are written to `data/media/<bucket>/<key>`. The delivery client maps `s3://<bucket>/<key>` to `/media/<key>`, so copying `data/media/loom-*/*` into `services/delivery/web/public/media/` makes them playable. Alternatively set `LOOM_PUBLIC_MEDIA_BASE=http://localhost:8003/media` and URLs point at this service instead.

Every output is validated before it is returned (`contracts.py`): against the shared schema, against the sample's item shapes and the delivery client's required fields, and against the concept graph (masks and clips only reference real objects and concepts). The shared contract files are never modified.

## Inputs beyond Contract B

Contract B names the video and learner; the Guardian and Critic also need the concept graph and learner profile. They are looked up, files first:

| Input | Where from |
|---|---|
| Concept graph | `LOOM_CONCEPT_GRAPH_DIRS` (default `services/perception/out` then `fixtures`): `<dir>/<video_id>/concept-graph.json` (Person 1's layout) or `<dir>/<video_id>.json`; else Person 1's service `LOOM_PERCEPTION_URL` (`/v1/videos/{id}/concept-graph`) |
| Object masks | Person 1's `objects[].mask_ref` sidecars (`masks/obj_001.json`, COCO RLE per frame) or `/v1/videos/{id}/masks/{object_id}`; without them, the instance boxes |
| Learner profile | Person 4's memory API `LOOM_LEARNER_URL` (`/api/learner/{id}`, header `x-loom-api-key` = `LOOM_API_SECRET`); else `LOOM_LEARNER_DIRS` (default `fixtures`); else the standard safety profile (with a warning) |
| Mesh revisions | Optional `LOOM_MESH_REVISE_URL` (Person 2): `POST {candidate_cut, issues}` → revised candidate-cut. Unset → thread issues are repaired locally (snap to sentence end, clip, de-overlap, add missing prerequisite). |

## LLM

Optional. `LOOM_LLM_PROVIDER=auto` (default) uses every configured provider in order and falls through on auth, unknown-model or rate-limit errors: Vertex Gemini (`GOOGLE_CLOUD_PROJECT`, same setup as perception), `GEMINI_API_KEY`, `GROQ_API_KEY` (read from the environment or the repo's `.env`). `LOOM_LLM_PROVIDER=none` runs fully offline: hazard lexicon, lexical fact-check, template explainers.

## Setup

```bash
cd services/verification
uv venv .venv --python 3.12
uv pip install --python .venv/Scripts/python.exe -e ".[llm,animator,dev]"      # macOS/Linux: .venv/bin/python
```

`ffmpeg`/`ffprobe` must be on `PATH`. Manim needs its system libraries (Cairo, Pango); see the Manim Community install guide. Without Manim, explainer requests are reported unavailable and dropped (the cut still verifies).

## Usage

```bash
# Contract B in → Contract C out
.venv/Scripts/python -m loom_verification verify ../../fixtures/candidate-cut.sample.json -o verified-cut.json
.venv/Scripts/python -m loom_verification --no-llm verify candidate.json --graph out/vid_x/concept-graph.json --profile learner.json

# check any verified cut against Contract C (and optionally its concept graph)
.venv/Scripts/python -m loom_verification validate verified-cut.json --graph concept-graph.json

# one tap-to-learn explainer
.venv/Scripts/python -m loom_verification explain --video-id vid_00123 --concept c_01

# HTTP service on the port the delivery client already points at
.venv/Scripts/python -m loom_verification serve --port 8003
```

### HTTP API

| Method | Path | |
|---|---|---|
| POST | `/v1/verify` | body: candidate-cut.json (or `{"candidate_cut": ...}`) → verified-cut.json |
| GET | `/verified-cut/{session_id}` | the stored verified cut: `VERIFIED_CUT_URL=http://localhost:8003/verified-cut/<session_id>` in the delivery client |
| GET | `/v1/sessions/{session_id}/verified-cut` | same, versioned path |
| GET | `/v1/sessions/{session_id}/report` | per-pass scores, Critic claims and verdicts, actions taken, warnings |
| POST | `/v1/explain` | `{video_id, concept_node_id, level?, learner_id?}` → fact-checked explainer clip |
| GET | `/media/{bucket}/{key}` | rendered masks and clips |
| GET | `/healthz` | version, LLM, Manim/ffmpeg availability |

**A2A** (for the agent mesh): agents at `/a2a/verifier` (`verify_cut`, `explain_concept`), `/a2a/guardian` (`review_objects`), `/a2a/animator` (`render_explainer`), `/a2a/critic` (`score_cut`); Agent Cards at `<agent>/.well-known/agent.json` (the verifier's also at `/.well-known/agent.json`); JSON-RPC `message/send` with the contract JSON as a `data` part.

## Tests

```bash
.venv/Scripts/python -m pytest -m "not manim"   # contracts, Guardian, Critic fault injection, loop, API (no network, no GPU)
.venv/Scripts/python -m pytest -m manim         # renders a real explainer
```

The Critic tests plant one fault per family (unmasked hazard, mask cut short, wrong quiz answer, unfaithful explainer, mid-sentence cut, overlapping threads, out-of-bounds thread, unknown concept, missing prerequisite, empty cut, unavailable explainer) and check each is flagged **and** blocks approval, while a correct cut passes.

## Known limitations

- The Critic checks explainer facts and code safety, not visual layout: an LLM-drawn scene can still overlap labels.
- Safety coverage is measured against the objects perception found; a hazard perception missed cannot be masked.
- The fixtures disagree with each other: `candidate-cut.sample.json` asks to redact `obj_004`, which `concept-graph.sample.json` does not contain, so the fixture pair cannot produce the fixture's mask (the service logs a warning and continues).
