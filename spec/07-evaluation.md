# 07 — Evaluation

Every number the report or paper states must be produced by `loom eval <suite>` on the local stack and written to
`data/eval/<suite>.json`, with the model tags + digests, segmentation tier, git commit and machine info embedded.
No number is typed by hand.

## 1. Test sets

| Set | Content | Ground truth |
|---|---|---|
| `demo` | Acid-Base Neutralization (~75 s, synthetic), built by `loom eval make-demo` from the script in `loom/eval/demo_script.py`: royalty-free clips downloaded once (URLs + licences in `tests/eval_data/demo_sources.json`), Kokoro narration, captions burned with Pillow (Windows fonts) | Generated `groundtruth_demo.json` (narration, captions, segment times, hazard window, safety labels per object); object boxes and masks on 20 keyframes annotated by hand in S1 |
| `real_a`, `real_b` | Two newly sourced CC-licensed real lab lessons (S1), stored in `tests/eval_data/` (the old build's videos are not used) | Transcript, concept list, object boxes on 8–10 keyframes, hazard labels |
| `youtube` | One CC-licensed YouTube lab lesson (≤ 10 min), stored locally after first download | Concept list, hazard intervals (if any) |
| `safety` | 30 short clips/crops: 15 hazards (glass, blades, flame, needle…), 15 look-alikes (beaker, ice, plastic, pens, lamps) | Per-item hazard tags |
| `animator12` | 6 concepts × 2 levels from `demo` | Factual reference sentences per concept |
| `faults` | Planted faults (§4) | Expected issue codes |

Ground-truth files live in `tests/eval_data/` with a README describing how they were annotated.

## 2. Suites and targets

| Suite | Metric | Old | Target |
|---|---|---|---|
| `asr` | WER (`jiwer`, normalized) | 0.0155 (cloud) | ≤ 0.03 (local) |
| `ocr` | recall@char-sim 0.8 · mean temporal IoU · formula exact match | 1.0 · 0.925 · — | 1.0 · ≥ 0.90 · 100 % |
| `grounding` | object instance recall @IoU 0.5 · mask IoU · hazard precision/recall · false-block s · missed s | boxes only; hazard 1.0/0.60, 0 s / 3.3 s | ≥ 0.9 · ≥ 0.7 · ≥ 0.95/≥ 0.90 · ≤ 2 s · ≤ 0.5 s |
| `grounding_ablation` | detector only → +SigLIP generic → +SigLIP look-alikes → +VLM crop check | 3 rows | 4 rows, same metrics |
| `fusion` | concept coverage of transcript time · evidence id validity · prerequisite chain match | — | ≥ 95 % · 100 % · expected chain present |
| `safety` | hazard item recall · false-flag rate on look-alikes · judge agreement (Cohen's κ Guardian vs VLM) | — | 1.0 · ≤ 0.1 · reported |
| `redaction` | per-viewer redaction precision / recall of hazard pixel-time · safe content blocked (s) | 1.00 / 0.84 · 0 s | ≥ 0.95 / ≥ 0.95 · 0 s |
| `critic_faults` | detection rate · false rejection on controls · per-family | 13/13 · 0/6 | 100 % on ≥ 20 faults · 0 on ≥ 8 controls |
| `animator` | render success · first-attempt compile · first-draft Critic pass · layout pass · median render s · cache hit latency | 1.0 · 1.0 · 0.583 · — · 14.1 s · — | ≥ 0.95 · ≥ 0.95 · ≥ 0.70 · ≥ 0.90 · ≤ 20 s · ≤ 1 s |
| `quiz` | verified questions per concept per level · planted-wrong rejection | — | ≥ 1 · 100 % |
| `loop` | passes-to-approval distribution · fallback rate on clean inputs | all 1-pass | report; fallback 0 on clean inputs |
| `personalization` | per persona: kept source %, explainers, masks, quiz count; mastery change after "watch again" | Alex 78 %, Priya full + 4, Parent full + 1 mask | report; ≥ 1 changed thread after correct quiz |
| `latency` | ingest time per minute of video · session cold/warm · tap cold/warm · model swap times | — | NFR-PERF targets |
| `outage` | behaviour with each role's model stopped (see §5) | fail-open observed | all fail-closed |
| `offline` | end-to-end demo with outbound network blocked | — | pass |

## 3. Procedures (abridged)

- **ASR**: normalize case/punctuation, `jiwer.wer` against the reference script.
- **OCR**: for each ground-truth caption, best-matching span by char similarity; temporal IoU of spans.
- **Grounding**: hazard intervals = union of verified hazard-class instance times (after time padding); precision
  and recall in seconds against ground-truth hazard windows at 0.1 s resolution; false-block = seconds masked
  outside any hazard window; missed = hazard seconds unmasked.
- **Mask IoU**: decode RLE at keyframes, IoU with annotated masks (polygon → mask).
- **Redaction**: run a session for Parent + child and strict profiles; pixel-time coverage of hazard masks by
  delivered masks (dilated) frame by frame at 10 fps.
- **Critic faults**: inject into a clean candidate/verified state, run `score_cut`, compare issue codes.
- **Animator**: fresh cache, render each of `animator12`; record attempts, compile, layout, Critic verdicts.
- **Latency**: 3 runs each, report median and max; cold = after `ollama stop` and gateway restart.

## 4. Fault-injection families

| Family | Faults (≥ 1 each) | Expected codes |
|---|---|---|
| F1 Structure | overlapping threads; out-of-order; empty cut | `overlapping_threads`, `out_of_order`, `empty_cut` |
| F2 Sentence | condensed thread ends mid-sentence (×3 positions) | `cut_mid_sentence` |
| F3 Factuality | explainer line with wrong indicator colour; "always"; dissolved salt called solid; wrong quiz answer; unanswerable quiz | `explainer_unfaithful`, `quiz_unsupported` |
| F4 Prerequisite | skip a prerequisite of a kept concept for a learner below mastery | `missing_prerequisite` |
| F5 Safety | Guardian returns no masks; mask ends 1 s early; mask on the wrong object | `unmasked_hazard` |
| F6 Explainer | render failure | `explainer_unavailable` |
| **F7 Outage (new)** | safety model down at ingest; judge down at session; brain down during tap | objects `unreviewed` → masked; `judge_unavailable` → artifact dropped; tap returns "unavailable" |
| **F8 Completeness (new)** | Assessment returns empty quiz with a non-empty bank; required plug-in down | `quiz_missing`, `plugin_unavailable` |
| **F9 Plug-in (new)** | plug-in asks to unmask; malformed plug-in payload | no effect; `forbidden_effect` logged |
| **F10 Cache (new)** | verified clip replaced on disk; stale guardian cache with older digest | content hash mismatch → re-verify; stale cache ignored |

Controls (must be approved): clean cut per persona (3), true explainer claims (3), correct quiz (2).

## 5. Outage matrix (fail-closed proof)

| Stopped | Ingest result | Parent + child session | Alex session | Tap |
|---|---|---|---|---|
| `brain` | heuristic vocab/fusion, objects still reviewed by `safety` (status `partial`) | masks for partial objects | normal cut, no new explainers | "unavailable" |
| `safety` | VLM-only reviews (`partial`) | masks for partial objects | unchanged | unchanged |
| `judge` | quiz bank empty (`degraded`) | no quiz, `quiz_missing` resolved as degraded; no new explainers | same | "unavailable" |
| Ollama entirely | all objects `unreviewed`, no quiz bank | **fallback, all visible objects masked** | fallback, no masks | "unavailable" |

Each cell is an automated test in `loom eval outage`.

## 6. Reporting

`loom eval report` renders `data/eval/results.md` and figures (`docs/figures/`): grounding ablation bar chart,
redaction timeline for the demo lesson, loop pass distribution, animator funnel (draft → gate → render → layout →
verified), latency box plots. Limitations section must state: synthetic demo lesson, small test sets, no user
study, segmentation tier used, LLM judges are local mid-size models.
