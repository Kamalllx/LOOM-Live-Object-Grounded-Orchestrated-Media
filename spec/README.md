# LOOM Remake — Specification Pack

**LOOM — Live, Object-Grounded, Orchestrated Media.** One source video, a different *verified* cut for every viewer.

This folder is the blueprint for rebuilding LOOM from scratch, **fully local** (no GCP, no Groq, no Gemini, no
cloud TTS). Every model runs on the developer laptop through **Ollama** (language + vision + safety + embeddings)
or through locally cached open-weight models (speech, OCR, detection, segmentation, TTS).

The old build in the parent repository is used only as a reference for *what we aimed for* and *what went wrong*.
No code is carried over by default; individual algorithms that proved themselves (listed in `spec/00-audit.md`)
are re-implemented against the new contracts.

## How to read this pack

| File | What it answers | Read it when |
|---|---|---|
| [spec/00-audit.md](00-audit.md) | What the old build does, what is broken, what is worth keeping | First — it justifies every change |
| [spec/01-product.md](01-product.md) | Vision, goals, users, personas, scope, non-functional requirements | Before designing anything |
| [spec/02-architecture.md](02-architecture.md) | Components, data flow, process model, GPU scheduling, APIs, repo layout | Before writing code |
| [spec/03-local-ai.md](03-local-ai.md) | Every model, its role, VRAM budget, Ollama config, structured output, failure rules | Before touching any model call |
| [spec/04-features.md](04-features.md) | Every feature: requirement IDs, old implementation → new implementation, acceptance tests | While building each feature |
| [spec/05-contracts.md](05-contracts.md) | Data contracts v2 (concept graph, cuts, learner, session log, events) | While building any interface |
| [spec/06-build-stages.md](06-build-stages.md) | Staged build plan with entry/exit criteria, owners, demo checkpoints | To plan the work |
| [spec/07-evaluation.md](07-evaluation.md) | Metrics, test sets, fault injection, the numbers the paper reports | From Stage 1 onward |
| [setup/pull-models.ps1](setup/pull-models.ps1) | Pulls/verifies the Ollama models and pre-downloads the open-weight models | Once per machine |
| [loom.example.toml](loom.example.toml) | Every model tag, threshold, port and budget named in the spec, in one config | Stage 0 |
| [CLAUDE.md](CLAUDE.md) | Standing rules Claude Code loads automatically in this folder | Always (auto-loaded) |
| [KICKOFF.md](KICKOFF.md) | The prompt that starts Stage 0 in a fresh Claude Code session | Once, to begin |

## The five rules of the remake

1. **Local only.** No network call leaves the machine during ingest, personalization, or playback. The only
   outbound traffic is (a) one-time model downloads during setup and (b) fetching a YouTube video when a user
   explicitly pastes a YouTube link. `LOOM_OFFLINE=1` must make the whole system work with the network cable out.
2. **Fail closed.** If a model is missing, slow, or returns garbage, the affected output is *blocked or made more
   conservative* — never silently passed. A child must never see an unmasked hazard because a model was down.
3. **One implementation per component.** No `legacy/`, no parallel `app/` vs `agents/`, no two web players.
4. **Contracts first.** Pydantic models are the single source of truth; JSON Schema and TypeScript types are
   generated from them. Every hop validates.
5. **Precompute and pre-verify at ingest; assemble and re-verify at session time.** Expensive model work (safety
   review, quiz bank, explainer drafts) happens once per video; a viewer's session is mostly deterministic assembly
   plus verification, so a session takes seconds, not minutes.

## Target machine

Windows 11 · Intel Core Ultra 9 275HX · 32 GB RAM · NVIDIA RTX 5070 Laptop **8 GB VRAM** (CUDA 12.8) ·
Python 3.12 · Node 24 · FFmpeg 8 (NVENC available) · MiKTeX (LaTeX available) · Ollama 0.40.x.
**Disk: C: has ~215 GB free** (after the 2026-10-28 cleanup) — disk is no longer a constraint; **VRAM (8 GB) is**.
The five Ollama models are installed and smoke-tested; fallbacks and open weights are pulled in Stage 0.
