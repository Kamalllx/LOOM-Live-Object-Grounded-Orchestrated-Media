# LOOM remake — instructions for Claude Code

LOOM (Live, Object-grounded, Orchestrated Media): one source video, a different **verified** cut per viewer.
This folder is a ground-up rebuild. The spec pack in `spec/` is the source of truth — read the relevant spec file
before working on any component, and keep code and spec in agreement (update the spec in the same change when
reality differs, e.g. after the Stage 0 model spike).

## Non-negotiable rules

1. **Local only.** All AI runs through Ollama at `http://127.0.0.1:11434` or locally cached open weights. Never add a
   cloud API, API key, GCP/Vertex/Groq/Gemini/OpenAI client, or cloud TTS. Only explicit YouTube link ingest may use
   the network, and it is disabled when `LOOM_OFFLINE=1`.
2. **Fail closed** (`spec/03-local-ai.md` §6). A model failure on a safety or verification path must make the output
   more conservative (more masking, artifact dropped, fallback cut) — never silently pass. Never cache a degraded or
   failed result.
3. **One implementation per component.** No `legacy/`, no parallel versions, no dead code.
4. **Contracts first.** Pydantic v2 models in `loom/core/contracts/` are the single source of truth; JSON Schema and
   TS types are generated from them; every hop validates.
5. **Roles, not model names.** Code asks for `brain`/`judge`/`safety`/`embed`/`ocr`; tags live in `loom.toml`.
6. **8 GB VRAM.** One heavy model resident at a time; all GPU work goes through the GPU arbiter
   (`spec/02-architecture.md` §3). Perception (torch) never runs while an Ollama model is loaded.

## Environment

- Windows 11, PowerShell 5.1 + Git Bash; Python 3.12 via **uv**; Node 24; FFmpeg 8 (NVENC); MiKTeX (LaTeX);
  RTX 5070 Laptop 8 GB (CUDA 12.8, torch cu128); 32 GB RAM; ~215 GB free on C:.
- Ollama 0.40.x with `qwen3.5:9b` (brain), `gemma4:e4b` (judge), `granite4.1-guardian:8b-q4_K_M` (safety; the Q6_K `:8b` tag spills to CPU),
  `qwen3-embedding:0.6b` (embed), `glm-ocr:q8_0` (ocr). Verify with `setup/pull-models.ps1 -VerifyOnly`.
- Write Windows-first scripts (PowerShell) with POSIX equivalents where cheap.

## The old build (do not use)

The parent folder `..` is the old implementation. **Do not read, reference or copy anything from it** — no code,
fixtures, ground truth or videos (decision 2026-10-29, Stage 0 kickoff). `spec/00-audit.md` already records what was
learned from it; that document is the only bridge. Fixtures are authored fresh in `remake/tests/fixtures/`; media
comes from the rebuilt demo lesson (`loom eval make-demo`) and newly sourced lessons in `remake/tests/eval_data/`.
**Never modify, move or delete anything outside `remake/`.**

## Working style

- Work stage by stage (`spec/06-build-stages.md`). Do not start a stage before the previous stage's exit criteria pass,
  unless the stage plan says it can run in parallel on fixtures.
- Every feature lands with tests: unit tests for deterministic logic, contract tests for every endpoint/skill.
  Run `ruff`, `mypy`, `pytest` (and `eslint`/`tsc` for TS) before declaring anything done.
- Report honestly: if a target in the spec is not met, say so with the measured number; do not soften results.
- Ask before: deleting files, installing system-wide software, changing user/system environment variables,
  making a git commit or push, or deviating from the spec in a way that changes a requirement.
- Keep `prompts/` versioned (front matter `id`, `version`, `model_role`); record model spike findings in
  `prompts/README.md`.
