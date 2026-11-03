We are rebuilding LOOM from scratch in this folder (`remake/`). Everything you need is in `CLAUDE.md`, `README.md` and the spec pack in `spec/` (00-audit through 07-evaluation). Your job in this session is **Stage 0 — Foundation and model spike** only, exactly as defined in `spec/06-build-stages.md`.

**Step 1 — Read before you plan.** Read `CLAUDE.md`, `README.md`, `loom.example.toml` and all eight files in `spec/` in full. Skim the old build in `..` only where the spec points to it (`spec/00-audit.md` §D lists what to keep). Do not modify anything outside `remake/`.

**Step 2 — Plan and ask, then wait for my answers.** Give me a short Stage 0 plan (ordered tasks, files you will create, what each exit criterion will be tested with) and ask me these before writing code:
1. Git: `remake/` currently sits inside the old repo's working tree (branch `integration/end-to-end`, with uncommitted changes). Should I `git init` a separate repo in `remake/`, or create a new branch in the parent repo?
2. `uv` is not on PATH — may I install it (user-level), and how (winget or `pip install --user uv`)?
3. May I run `setup/pull-models.ps1 -Fallbacks -OpenWeights` (~13 GB of downloads) and `-ConfigureServer` (sets user env vars for Ollama; I will need to restart Ollama)?
4. The demo lesson must be rebuilt (`spec/07-evaluation.md` §1): may I download the royalty-free source clips once?
Also flag anything in the spec that is contradictory, under-specified or infeasible on this machine.

**Step 3 — Build Stage 0** after I answer, in this order, with tests for each piece:
1. uv workspace, `pyproject.toml`, `loom.toml` (from `loom.example.toml`), `loom` CLI skeleton, ruff/mypy/pytest config, prompt-file loader (`prompts/` with versioned front matter).
2. `loom.core.contracts`: all v2 Pydantic models from `spec/05-contracts.md` + `loom contracts export` (JSON Schema + TS types in `packages/contracts-ts/`).
3. `loom.core.config`, `offline`, `store` (SQLite schema + migrations from `spec/02-architecture.md` §6), `blobs` (content-addressed), `events` (persisted + SSE with `Last-Event-ID`), `jobs` (persisted queue), `a2a` (server router + client per §5), `gpu` (arbiter per §3).
4. `loom.core.llm`: the Ollama client per `spec/03-local-ai.md` §4 — roles from config, structured output via `format` JSON Schema, one repair attempt, typed errors, cache that never stores failures, per-role metrics.
5. Gateway skeleton: `/api/health`, `/api/ready` (real per-role readiness — must report missing roles within 30 s of Ollama stopping), `/api/models`, `/api/events/{channel}`, `/media` with range requests.
6. `loom doctor` (FR-OPS-02).
7. Golden fixtures in `tests/fixtures/`: convert the old v1 graph `../data/graphs/vid_demo_neutralization.json` (+ ground truth and the three learner profiles) to v2 contracts, hand-check them, and add sample candidate/verified cuts.
8. **Model spike** (the most important deliverable): for each role and fallback, measure schema-valid structured-output rate over 50 calls on a toy schema, image input (brain, judge, ocr), latency, peak VRAM at the configured `num_ctx` (via `nvidia-smi`), thinking on/off behaviour, and the exact Granite Guardian prompt format + parsing. Write the results as a table in `prompts/README.md`, choose fallbacks from the data, and update `spec/03-local-ai.md` where findings differ from its assumptions.
9. Demo lesson rebuild (`loom eval make-demo`) if I approved the download.

**Step 4 — Prove it and stop.** Run every Stage 0 exit criterion from `spec/06-build-stages.md` and report a table: criterion → pass/fail → evidence (command + key output). Include lint/type/test results and the spike table. If something misses its target, say so with the number. Then stop — do not start Stage 1 until I say so.

Throughout: local only (no cloud APIs or keys), fail closed, one implementation per component, roles not model names, ask before deleting files, changing environment variables, installing system-wide software or committing.
