# Prompts

Every prompt is a versioned Markdown file (`id`, `version`, `model_role` front matter; see `loom/core/prompts.py`).
Code asks for a **role**, never a model name. Bump `version` on any wording change — the version is part of every
LLM cache key. Untrusted material only ever enters through `<data>` blocks.

`spike_*` prompts exist only for the Stage 0 model spike (`loom eval spike`); production prompts arrive with the
stages that use them.

## Stage 0 model spike

Run with `uv run loom eval spike [--only <role|label>] [--tag role:tag]`. Each model is loaded alone (every other model
unloaded first) at its configured `num_ctx`; VRAM is the peak of `nvidia-smi -lms 250` minus the idle baseline (other
desktop apps held 1.0–1.6 GB during the runs; Windows reports no per-process VRAM), cross-checked with Ollama's own
`size` / `size_vram` (`size_vram < size` ⇒ CPU spill). Toy tasks: 50 lab procedure steps → `SpikeExtraction` JSON
(task accuracy = the chemical and its quantity extracted correctly); 5 rendered shape/caption images → `VisionAnswer`;
10 rendered formulas for OCR; 50 labelled objects (25 hazards with their true tag, 25 benign lab/classroom objects)
for safety.

### Findings and decisions

| # | Finding | Decision (applied) |
|---|---|---|
| 1 | `granite4.1-guardian:8b` (Q6_K) loads at 8.13 GB at ctx 8192 — **2.0 GB spills to CPU**, p50 1.2 s; thinking on 37.6 s. The spec's ~6.5 GB estimate was wrong. | **`safety` = `granite4.1-guardian:8b-q4_K_M`**: 5.95 GB fully on GPU, identical accuracy (96 %, recall 92 %, 0 false flags), p50 0.28 s, thinking 5.6 s. |
| 2 | Guardian prompt format: system message = criterion text, last user message = item; reply `<think>\n</think>` + `<score> yes|no </score>`; 100 % parseable. One call = one criterion. | Safety review is one call per object **per tag**; prompts use `output: text`, `data_rule: user` and a `<score>` parser. spec/03 §5.3 updated. |
| 3 | Ollama returns `logprobs` for the score token (P(yes) ≈ 0.97 on broken glass). | Severity = Guardian P(yes) (spec/03 §5.3). |
| 4 | Guardian missed 2/25 hazards with thinking off (both quantizations); thinking on caught 10/10; the `judge` role on the same criteria scored 50/50. | Keep the union with the `brain` visual check (S3); `judge` confirmed as the safety fallback role. S3 should measure think-on Guardian at q4_K_M (5.6 s/call) on the full safety set. |
| 5 | `qwen3.5:9b` at ctx 8192: 6.26 GB, 0.79 GB on CPU. At 6144: 5.58 GB fully on GPU. | **`brain.num_ctx = 6144`**; fusion may raise it per call at ingest only (accepting spill). |
| 6 | `qwen3.5:9b` thinking on: ~6 100 reasoning chars per toy call; at ctx 8192 (CPU spill) p50 63–73 s and 3/10 over the 120 s timeout; at ctx 6144 (all on GPU) p50 52.6 s, 1/10 over. | `think` off on every interactive path; ingest/pre-render prompts with thinking need `timeout_s ≥ 300` and fall back to `think: false` (spec/03 §5.1). |
| 7 | `glm-ocr` answers formulas in LaTeX (raw similarity 0.51); one reply ran away (42.9 s). | `loom/perception/ocr_text.py` normalizes LaTeX → Unicode (10/10 exact afterwards); `ocr.max_tokens = 256`. `Text Recognition:` and `Formula Recognition:` equal — keep the former. |
| 8 | Fallbacks: `qwen3.5:4b` 100 % valid/accurate, images 5/5, 3.24 GB; `gemma4:e4b-it-qat` identical to `gemma4:e4b`, 3.08 GB. | Both kept as configured fallbacks. |
| 9 | `/api/ps` reported `gemma4:e4b` at 0.33 GB at the end of its block while `nvidia-smi` saw +4.65 GB — Ollama's size report is not reliable for this model. | VRAM gate uses the `nvidia-smi` delta. |

<!-- spike:begin -->
Measured 2026-10-28T22:09 UTC on NVIDIA GeForce RTX 5070 Laptop GPU, 8151 MiB, 610.88, Ollama 0.40.12, each model at its configured num_ctx (ctx column), 50 structured calls per model (think off), 10 with thinking on. Raw data: `data/eval/spike.json`.

| Role | Model | Load | Schema-valid 1st try | Valid after repair | Task accuracy | p50 / p95 | Thinking on (valid · p50) | Image input (valid · correct) | Peak VRAM (model) | Ollama size / in VRAM @ctx |
|---|---|---|---|---|---|---|---|---|---|---|
| brain | `qwen3.5:9b` | 6.4 s | 100% | 100% | 100% | 3.5 s / 6.6 s | 90% · 52.6 s | 100% · 100% | 6.27 GB | 5.58 GB / 5.58 GB @ctx 6144 |
| brain fallback | `qwen3.5:4b` | 16.1 s | 100% | 100% | 100% | 1.9 s / 5.6 s | 100% · 38.1 s | 100% · 100% | 3.82 GB | 3.20 GB / 3.20 GB @ctx 6144 |
| judge | `gemma4:e4b` | 21.8 s | 100% | 100% | 100% | 1.2 s / 3.5 s | 100% · 4.1 s | 100% · 100% | 4.65 GB | 0.33 GB / 0.33 GB @ctx 8192 |
| judge fallback | `gemma4:e4b-it-qat` | 18.5 s | 100% | 100% | 100% | 1.4 s / 4.4 s | 100% · 7.8 s | 100% · 100% | 4.20 GB | 3.08 GB / 3.08 GB @ctx 8192 |
| safety (native `<score>`) | `granite4.1-guardian:8b` | 21.1 s | 100% | 100% | 96% | 1.2 s / 1.6 s | 100% · 37.6 s | n/a (text-only) | 5.85 GB | 8.13 GB / 6.12 GB @ctx 8192 |
| safety candidate granite4.1-guardian:8b-q4_K_M (native `<score>`) | `granite4.1-guardian:8b-q4_K_M` | 10.1 s | 100% | 100% | 96% | 275 ms / 325 ms | 100% · 5.6 s | n/a (text-only) | 5.67 GB | 5.95 GB / 5.95 GB @ctx 8192 |
| embed | `qwen3-embedding:0.6b` | — | dim 1024, unit-norm True | deterministic (max Δ 0.0e+00) | — | batch 64: 7.48 s cold, 3.54 s warm | n/a | n/a | 1.32 GB | 1.28 GB / 1.28 GB @ctx 8192 |
| ocr (`Text Recognition:`) | `glm-ocr:q8_0` | 6.1 s | 100% (non-empty) | 100% | 100% ≥0.95 sim | 163 ms / 391 ms | n/a | mean sim 1.0 | 2.40 GB | 1.51 GB / 1.51 GB @ctx 8192 |

Safety judgement on 50 labelled objects (25 hazards with their true tag, 25 ordinary lab/classroom objects with a rotating tag):

| Judge | Parse / schema valid | Accuracy | Hazard recall | False-flag rate | p50 |
|---|---|---|---|---|---|
| Guardian native, think off `granite4.1-guardian:8b` | 100% | 96% | 92% | 0% | 1.2 s |
| Guardian native, think on (10) `granite4.1-guardian:8b` | 100% | 100% | 100% | 0% | 37.6 s |
| Guardian JSON `format` (10) `granite4.1-guardian:8b` | 100% | 100% | 100% | 0% | 990 ms |
| Guardian native, think off `granite4.1-guardian:8b-q4_K_M` | 100% | 96% | 92% | 0% | 275 ms |
| Guardian native, think on (10) `granite4.1-guardian:8b-q4_K_M` | 100% | 100% | 100% | 0% | 5.6 s |
| Guardian JSON `format` (10) `granite4.1-guardian:8b-q4_K_M` | 100% | 100% | 100% | 0% | 517 ms |
| Judge `gemma4:e4b` on the same criteria (JSON) | 100% | 100% | 100% | 0% | 699 ms |
<!-- spike:end -->
