# Evidence for the paper: answers to the review checklist

> For the co-author writing the paper. Each item: whether the request is sound, the answer, the numbers (generated from `data/eval/*.json` by `python -m loom.eval.report`), the files that prove it, and the caveats. Items marked **needs a human** cannot honestly be finished by software. (`data/` is not in git: copies of every evaluation file cited here are in [`docs/eval/`](eval/).)

## Must have

### 1. Hazard ablation: are the last three rows really separate stages?

**Valid question - and the answer is: yes, they were run separately; they coincide for a reason worth reporting.**

`data/eval/grounding.json` stores, for every one of the 30 hazard tracks, its own SigLIP margin against generic negatives, its own margin against curated look-alikes, and the VLM verdict with the VLM's own label (`hazard_tracks[]`: `siglip_generic`, `siglip_lookalike`, `vlm`, `better_label`). The margins differ track by track (e.g. the shard track at 50.75 s: generic 0.937, look-alike 0.891), so the stages ran.

Why the rows matched: the same 3 broken-glass tracks clear the 0.10 SigLIP margin under both negative sets and no other track does, so the two SigLIP rows coincide; and LOOM keeps a hazard if SigLIP passes **or** the VLM confirms, so the VLM row can only differ when the VLM *confirms* something SigLIP dropped. In the first demo run (2026-11-02) the VLM rejected all 30 hazard crops, true ones included, so the three verified rows were identical (precision 1.00, recall 0.583; README at commit 1945562). Re-measured on 2026-11-16, the detector and SigLIP rows are unchanged (deterministic) but the VLM confirmed 2 of 30 crops - one of them a true hazard SigLIP had dropped - so LOOM's row moved from SigLIP's 1.00 / 0.583 to 0.943 / 0.796 (precision / recall). The VLM is rarely decisive and not stable across runs; under the OR-rule its rare confirmations only add recall, while VLM-only or AND rules lose most of the hazard. On Water Sciences it rejected 13 of 13.

Re-measured run, re-scored under every decision rule from the stored per-stage verdicts (`loom/eval/redaction_eval.py`, no new model calls):

| Decision rule | Hazard tracks kept | Precision | Recall | F1 | False-block (s) | Missed (s) |
|---|---:|---:|---:|---:|---:|---:|
| detector only | 30 | 0.240 | 0.922 | 0.381 | 30.1 | 0.8 |
| SigLIP generic only | 3 | 1.000 | 0.583 | 0.736 | 0.0 | 4.3 |
| SigLIP look-alikes only | 3 | 1.000 | 0.583 | 0.736 | 0.0 | 4.3 |
| VLM only | 2 | 0.889 | 0.388 | 0.541 | 0.5 | 6.3 |
| SigLIP AND VLM | 1 | 1.000 | 0.146 | 0.254 | 0.0 | 8.8 |
| SigLIP OR VLM (LOOM) | 4 | 0.943 | 0.796 | 0.863 | 0.5 | 2.1 |

Suggested wording: *"SigLIP2 removes all false blocking at a recall cost; the VLM crop check rarely confirms (it rejected 30/30 crops in one run and 28/30 in another), but because it can only add hazards under LOOM's OR-rule, its rare confirmations recover recall, while a VLM-only or AND-combined verifier would lose most of the hazard."* Report both runs: the VLM's verdicts are not stable across runs.

Figure: `docs/figures/grounding-rules-demo.svg`.

### 2. Fault injection on the new build

**Valid; now run.** `uv run python -m loom.eval.critic_faults` -> `data/eval/critic_faults.json`.

Method: for 3 lessons x 3 viewers the loop-approved state is a control; then one fault at a time is planted (spec/07 §4 families F1-F6, F8) and the Critic must report the expected issue code; the loop's own repair is then applied. **Detection 76/76 (100%); controls approved 9/9 (0 false rejections); repaired in-loop 49; the remaining 27 end in the fallback cut, so 0 faulty cuts are delivered.** (41 fault/state pairs were not applicable, e.g. no prerequisite to drop for an expert.)

| Family | Injected | Detected | Repaired in loop |
|---|---:|---:|---:|
| F1 structure | 27 | 27 | 18 |
| F2 sentence | 18 | 18 | 18 |
| F3 factuality | 9 | 9 | 0 |
| F4 prerequisite | 2 | 2 | 2 |
| F5 safety | 8 | 8 | 8 |
| F6 explainer | 3 | 3 | 3 |
| F8 completeness | 9 | 9 | 0 |

Two honest findings for the discussion: the loop cannot re-select a quiz (F3/F8 always fall back), and the overlap repair (trim the earlier thread) can cut it mid-sentence, whose repair re-creates the overlap - an oscillation that exhausts the budget. F7 (outages), F9 (plug-ins) and F10 (cache) are covered by unit tests, not by this suite. Figure: `docs/figures/critic-faults.svg`.

### 3. Mask quality (IoU)

**Valid, and the README should not say "exact" without it. Needs a human.** There are no hand-drawn masks yet, and a number computed against another model's masks would not be ground truth. Prepared: `python -m loom.eval.mask_iou export` wrote 15 keyframes of the demo lesson with every visible object (`tests/eval_data/mask_keyframes/`: clean frame, LOOM's mask for reference, an empty LabelMe file listing the object ids). Draw one polygon per object (about an hour in LabelMe), then `python -m loom.eval.mask_iou score` writes mean / median IoU and the share >= 0.5 and >= 0.7 to `data/eval/mask_iou.json`. Until then, describe the masks as "SAM 2.1 instance masks" rather than "exact".

### 4. Redaction for Parent + child, with and without time padding

**Valid; now run** (`python -m loom.eval.redaction_eval` -> `data/eval/redaction.json`). Time-level, 0.1 s resolution, against the ground-truth hazard windows. Two layers are reported separately because they answer different questions:

| Lesson | Layer | Pad | Precision | Recall | False-block (s) | Missed (s) |
|---|---|---|---:|---:|---:|---:|
| Acid-Base demo | perception (verified hazard class) | pad 0 s | 1.000 | 0.505 | 0.0 | 5.1 |
| Acid-Base demo | perception (verified hazard class) | pad 0.5 s | 0.943 | 0.796 | 0.5 | 2.1 |
| Acid-Base demo | perception (verified hazard class) | pad 1 s | 0.897 | 0.845 | 1.0 | 1.6 |
| Acid-Base demo | delivered session masks | pad 0 s | 1.000 | 1.000 | 0.0 | 0.0 |
| Acid-Base demo | delivered session masks | pad 0.5 s | 0.912 | 1.000 | 1.0 | 0.0 |
| Acid-Base demo | delivered session masks | pad 1 s | 0.837 | 1.000 | 2.0 | 0.0 |
| Water Sciences | perception (verified hazard class) | pad 0 s | n/a | 0.000 | 0.0 | 7.4 |
| Water Sciences | perception (verified hazard class) | pad 0.5 s | n/a | 0.000 | 0.0 | 7.4 |
| Water Sciences | perception (verified hazard class) | pad 1 s | n/a | 0.000 | 0.0 | 7.4 |
| Water Sciences | delivered session masks | pad 0 s | 0.514 | 0.730 | 5.1 | 2.0 |
| Water Sciences | delivered session masks | pad 0.5 s | 0.496 | 0.932 | 7.0 | 0.5 |
| Water Sciences | delivered session masks | pad 1 s | 0.451 | 1.000 | 9.0 | 0.0 |

Caveats: the demo lesson's served graph is the hand-authored fixture (its session row is the policy with perfect perception); the end-to-end rows are the honest perception numbers. On Water Sciences the delivered masks also cover safe objects (bottle, gloves, safety goggles: Guardian over-flagging), which is why precision is about 0.50. Pixel-level coverage needs the hand-drawn masks of item 3. Figures: `docs/figures/hazard-timeline-demo.svg`, `docs/figures/hazard-timeline-glass.svg`.

### 5. A second ground-truthed lesson (Water Sciences, 97.5 s)

**Valid; done, with one caveat.** Hazard window annotated in `tests/eval_data/groundtruth_water_sciences.json`: 61.9-66.77 s, 71.46-74 s (7.41 s; a broken glass pipette on the floor). **It was annotated by the AI assistant**, from contact sheets every 2 s, 1 s and 0.25 s and hard cuts from frame differences (method in the file) - a human should confirm it before publication. Grounding suite run on it (`python -m loom.eval.grounding_second` -> `data/eval/grounding_water_sciences.json`):

| Decision rule | Hazard tracks kept | Precision | Recall | F1 | False-block (s) | Missed (s) |
|---|---:|---:|---:|---:|---:|---:|
| detector only | 13 | 0.392 | 1.000 | 0.563 | 11.5 | 0.0 |
| SigLIP generic only | 0 | n/a | 0.000 | 0.000 | 0.0 | 7.4 |
| SigLIP look-alikes only | 0 | n/a | 0.000 | 0.000 | 0.0 | 7.4 |
| VLM only | 0 | n/a | 0.000 | 0.000 | 0.0 | 7.4 |
| SigLIP AND VLM | 0 | n/a | 0.000 | 0.000 | 0.0 | 7.4 |
| SigLIP OR VLM (LOOM) | 0 | n/a | 0.000 | 0.000 | 0.0 | 7.4 |

This is a useful negative result: the detector found the pipette, but as "cigarette", "needle", "syringe" and "open flame"; SigLIP and the VLM correctly rejected those labels (the VLM called it a pipette), so class-level grounding has recall 0 here. The danger is contextual (glass on the floor), and it is the Guardian, judging the tracked "glass pipette" object, that masks it: delivered recall 0.93 at 0.5 s pad.

## Should have

### 6. Animator comparison (free-form Manim vs plan-compiled) and first-draft Critic pass

**Partly valid.** 0/8 vs 3/3 is too small - agreed. But since S1 the product no longer renders explainers with Manim at request time (scenes play in the browser; the MP4 export is background-only), so a render-success comparison now measures a side path. What matters for the paper is the planning/fact-check funnel, now measured from the event log (`python -m loom.eval.factcheck_history` -> `data/eval/factcheck_history.json`): 12 runs, first-draft line support 72% (82 lines), first draft accepted 9/12, delivered 9/12, drafts needed {'1': 10, '2': 1, '3': 1}. Report the old 0/8 vs 3/3 as an anecdotal S1 observation only.

### 7. Latency: repeated runs, median and spread; per-stage ingest

**Valid; now run** (`python -m loom.eval.latency_eval` -> `data/eval/latency.json`). Every request asks a different question so the LLM cache never answers.

| Interaction | n | Median | IQR | Range |
|---|---:|---:|---:|---:|
| grounded answer | 10 | 22.80 s | 13.84-32.69 s | 11.87-72.74 s |
| topic quiz | 5 | 36.84 s | 19.61-40.74 s | 6.05-42.05 s |
| verified session | 12 | 0.27 s | 0.27-0.28 s | 0.26-0.30 s |

Per-stage ingest times (s) for the corpus lessons (single ingest each; repeating a 5-25 min ingest 10 times was not worth the GPU-hours - the spread across 35 stored lessons is in the testing report). The demo lesson's served graph is the hand-authored fixture, so it has no ingest timings; its perception suites report their own (ASR 10.3 s for 68.7 s of audio, OCR 28.3 s, grounding in `grounding.json` `timings_s`):

| Lesson | Length | ASR | OCR | Detect | Verify | SAM 2.1 | Fuse | Safety | Quiz | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Water Sciences | 97.5 s | 7.7 | 29.8 | 141.5 | 27.8 | 76.6 | 20.4 | 18.0 | 168.0 | 457 |
| SQL in 100 s | 142.4 s | 14.7 | 58.0 | 135.7 | 28.7 | 38.8 | 3.8 | 12.5 | 38.5 | 437 |

Figure: `docs/figures/latency.svg`.

### 8. Unaudited objects in the SQL lesson

**Valid; audited.** Both objects (`fire`, `open flame`, 138.2-140.8 s) are the channel's flame logo on the outro card - false positives, not hazards; the box lingers ~0.5 s into the "Thanks for watching" card. Evidence: `docs/paper/audit-sql-objects.jpg`, record `data/eval/object_audit_sql.json` (audited by the AI assistant from frames). Suggested corpus row: *"2 (both the channel logo; false positives)"*.

### 9. Fact-check accuracy vs a human

**Valid. Needs a human for the final number;** the sheet is ready. 40 narration lines the judge ruled on (balanced accepted / rejected, from 12 real explainer runs) are in `data/eval/factcheck_lines.csv` with an empty `human` column. Provisional result with **labels by the AI assistant** (do not publish as human agreement):

| Verdict | Agreement | Cohen's kappa | False accepts | False rejects |
|---|---:|---:|---:|---:|
| judge alone | 0.60 | 0.05 | 2 | 14 |
| LOOM final (judge + absence-only overrule + not-teaching guard) | 0.93 | 0.69 | 0 | 3 |

The judge mostly errs by rejecting correct lines "because the evidence does not mention it" (which its prompt forbids); LOOM now overrules such absence-only rejections and separately rejects lines that narrate the video. After a human fills the column: `python -m loom.eval.factcheck_history --score human`.

## Figures (PNG, >= 1600 px wide, no browser chrome)

All in `docs/paper/`, captured from the running system in headless Edge at 2-4.5x pixel density (`python -m loom.eval.paper_figures`).

| Requested | File(s) |
|---|---|
| Map tab (similarity map) after a question | `map.png` (and the answer: `ask-answer.png`) |
| Graph and Loom tabs, full size | `graph.png`, `loom.png` |
| Compare cuts: Alex, Priya, Parent + child | `compare-cuts.png` |
| Before / after at the hazard moment (Parent + child) | `hazard-after-52_0.png`, `hazard-after-54_5.png`, `hazard-before-52_0.png`, `hazard-before-54_5.png` |
| 4-6 frames of one scene explainer | `explainer-concept-020.png`, `explainer-concept-075.png`, `explainer-concept-130.png`, `explainer-concept-190.png`, `explainer-concept-260.png`, `explainer-concept-350.png` |
| (new) the exact construction explainer | `explainer-construction-050.png`, `explainer-construction-094.png`, `explainer-construction-175.png`, `explainer-construction-243.png`, `explainer-construction-310.png`, `explainer-construction-390.png` |
| Narration panel with ✓ / ✗ per line | `narration-checks.png` |
| YouTube extension on a real watch page | `extension-overlay.png` |
| Failure: gloves masked for the child profile | `fail-gloves-masked-68_9.png`, `fail-gloves-masked-69_6.png` |
| Failure: shards outside the mask | `fail-shards-50_5.png`, `fail-shards-53_0.png`, `fail-shards-56_0.png` |

Charts (SVG, vector, for print): `docs/figures/`.

