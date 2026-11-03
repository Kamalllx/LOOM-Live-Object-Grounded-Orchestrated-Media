"""`loom` command line (FR-OPS-05). Commands land with the stage that implements them."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

from loom import __version__

if TYPE_CHECKING:
    from loom.core.config import LoomConfig

app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="LOOM - one source video, a verified cut per viewer."
)
contracts_app = typer.Typer(no_args_is_help=True, help="Data contracts v2 (spec/05).")
eval_app = typer.Typer(no_args_is_help=True, help="Evaluation suites (spec/07).")
app.add_typer(contracts_app, name="contracts")
app.add_typer(eval_app, name="eval")

ConfigOpt = typer.Option(None, "--config", help="path to loom.toml (default: $LOOM_CONFIG or ./loom.toml)")


def _cfg(path: Path | None) -> LoomConfig:
    from loom.core.config import load_config

    return load_config(path)


@app.command()
def version() -> None:
    """Print the LOOM version."""
    typer.echo(__version__)


@app.command()
def doctor(
    config: Path | None = ConfigOpt,
    smoke: bool = typer.Option(True, "--smoke/--no-smoke", help="run a short call against every model"),
    as_json: bool = typer.Option(False, "--json", help="machine-readable output"),
) -> None:
    """Check the machine (Python, CUDA, FFmpeg, LaTeX, Ollama, models, weights, ports, disk) and print fixes."""
    from loom.ops.doctor import doctor_main

    raise typer.Exit(doctor_main(_cfg(config), smoke, as_json))


@app.command()
def gateway(
    config: Path | None = ConfigOpt,
    host: str = typer.Option("127.0.0.1", help="bind address (loopback by default)"),
    port: int | None = typer.Option(None, help="default: [runtime].gateway_port"),
) -> None:
    """Run the gateway (REST + SSE + A2A host)."""
    import uvicorn

    from loom.core.logging import configure_logging
    from loom.gateway.app import create_app

    cfg = _cfg(config)
    configure_logging()
    uvicorn.run(create_app(cfg), host=host, port=port or cfg.runtime.gateway_port, log_config=None)


@app.command()
def worker(selftest: bool = typer.Option(False, "--selftest")) -> None:
    """Run the subprocess stage runner (normally spawned by the gateway)."""
    from loom.worker.main import main

    raise typer.Exit(main(["--selftest"] if selftest else []))


@app.command()
def prompts() -> None:
    """Validate every prompt file and list id@version and role."""
    from loom.core.prompts import PromptLibrary

    for p in PromptLibrary().all():
        typer.echo(f"{p.ref:28} {p.model_role:7} output={p.output} think={p.think}")


@eval_app.command("spike")
def eval_spike(
    config: Path | None = ConfigOpt,
    calls: int = typer.Option(50, help="structured calls per model on the toy schema"),
    think_calls: int = typer.Option(10, help="calls with thinking on (brain/judge)"),
    only: list[str] | None = typer.Option(None, "--only", help="role, label or tag to run (repeatable)"),
    tag: list[str] | None = typer.Option(None, "--tag", help="extra candidate as role:tag (repeatable)"),
) -> None:
    """Stage 0 model spike: structured output, thinking, images, latency, VRAM, Guardian format."""
    from loom.eval.spike import spike_main

    raise typer.Exit(spike_main(_cfg(config), calls, think_calls, only, tag))


@eval_app.command("make-demo")
def eval_make_demo(config: Path | None = ConfigOpt) -> None:
    """Build the demo lesson video + ground truth (downloads royalty-free clips once; Kokoro narration)."""
    from loom.eval.make_demo import make_demo

    make_demo(_cfg(config))


@eval_app.command("asr")
def eval_asr(config: Path | None = ConfigOpt) -> None:
    """WER of local ASR on the demo lesson (target <= 0.03)."""
    import json

    from loom.eval.asr_eval import run_asr_eval

    body = run_asr_eval(_cfg(config))
    typer.echo(json.dumps({k: v for k, v in body.items() if k not in ("hypothesis", "reference")}, indent=2))
    raise typer.Exit(0 if body["pass"] else 1)


@eval_app.command("ocr")
def eval_ocr(
    config: Path | None = ConfigOpt,
    reread: bool = typer.Option(True, "--reread/--no-reread", help="re-read math/low-confidence spans with glm-ocr"),
) -> None:
    """On-screen text recall / temporal IoU / formula exactness on the demo lesson."""
    import json

    from loom.eval.ocr_eval import run_ocr_eval

    body = run_ocr_eval(_cfg(config), reread)
    typer.echo(json.dumps({k: v for k, v in body.items() if k != "all_spans"}, indent=2, ensure_ascii=False))
    raise typer.Exit(0 if body["pass"] else 1)


@eval_app.command("vocab")
def eval_vocab(config: Path | None = ConfigOpt) -> None:
    """Object vocabulary on the demo lesson: every ground-truth object and every hazard class present."""
    import json

    from loom.eval.vocab_eval import run_vocab_eval

    body = run_vocab_eval(_cfg(config))
    typer.echo(json.dumps(body, indent=2, ensure_ascii=False))
    raise typer.Exit(0 if body["pass"] else 1)


@app.command()
def ingest(
    source: str = typer.Argument(..., help="video file path or YouTube/HTTP link"),
    title: str | None = typer.Option(None, help="title (default: from the file / link)"),
    config: Path | None = ConfigOpt,
) -> None:
    """Perceive a video once: concept graph with objects, safety review and verified quiz bank."""
    import asyncio

    from loom.perception.pipeline import ingest_source

    cfg = _cfg(config)
    graph = asyncio.run(
        ingest_source(cfg, source, title, lambda st, status, p, d: typer.echo(f"  {st:10} {status:8} {d}"))
    )
    typer.echo(f"OK {graph.video_id}: {len(graph.transcript)} sentences, {len(graph.on_screen_text)} text spans, "
               f"{len(graph.objects)} objects, {len(graph.concept_nodes)} concepts, {len(graph.quiz_bank)} questions, "
               f"{graph.perception_meta.timings_s.get('total')} s, degraded={graph.perception_meta.degraded}")


@app.command()
def masks(video_id: list[str], config: Path | None = ConfigOpt) -> None:
    """Exact-shape masks: re-segment every object of a processed video with SAM 2.1 (tier sam2)."""
    from loom.agents import session as S
    from loom.eval.common import free_gpu_for_torch
    from loom.perception.refine_masks import refine

    cfg = _cfg(config)
    for vid in video_id:
        free_gpu_for_torch(cfg)
        g = refine(cfg, S.load_graph(cfg.data_dir, vid), lambda m: typer.echo(f"  {vid} {m}"))
        S.save_graph(cfg.data_dir, g)
        typer.echo(f"OK {vid}: {g.perception_meta.models.get('sam2_masked_instances')} instances masked, "
                   f"{g.perception_meta.timings_s.get('segment_sam2')} s, peak {g.perception_meta.models.get('sam2_peak_vram_gb')} GB")


@app.command()
def explain(
    video_id: str,
    concept: list[str] | None = typer.Option(None, "--concept", help="concept id (repeatable); default: --auto set"),
    level: str = typer.Option("beginner", help="learner level"),
    auto: bool = typer.Option(False, "--auto", help="prerender every core/setup concept (FR-PER-11)"),
    config: Path | None = ConfigOpt,
) -> None:
    """Render + fact-check Manim explainers (Animator) and store the verified ones."""
    import asyncio

    from loom.agents import session as S
    from loom.agents.animator import make_explainer
    from loom.core.llm import LLMClient
    from loom.core.ollama import OllamaHttp
    from loom.core.store import Store

    cfg = _cfg(config)
    store = Store(cfg.data_dir / "loom.db")
    store.migrate()
    graph = S.load_graph(cfg.data_dir, video_id)
    ids = list(concept or [])
    if auto or not ids:
        roles = {s: r.role for r in graph.thread_roles for s in r.segment_ids}
        ids = [
            c.node_id
            for c in graph.concept_nodes
            if any(roles.get(s) in ("core", "setup") for s in c.evidence.segment_ids)
        ]

    async def run() -> int:
        http = OllamaHttp(cfg)
        llm = LLMClient(cfg, http, store=store)
        failed = 0
        try:
            for cid in ids:
                try:
                    row = await make_explainer(
                        cfg,
                        llm,
                        store,
                        cfg.data_dir,
                        graph,
                        cid,
                        level,
                        lambda step, n, cid=cid: typer.echo(f"  {cid} {step} (attempt {n})"),
                    )
                    typer.echo(f"OK {cid} -> {row['clip_ref']}")
                except RuntimeError as e:
                    failed += 1
                    typer.echo(f"FAILED {cid}: {e}")
        finally:
            await http.aclose()
        return failed

    raise typer.Exit(1 if asyncio.run(run()) else 0)


@eval_app.command("grounding")
def eval_grounding(config: Path | None = ConfigOpt) -> None:
    """Detection + tracking + verification ablation on the demo lesson (hazard P/R in seconds)."""
    import json

    from loom.eval.grounding_eval import run_grounding_eval

    body = run_grounding_eval(_cfg(config))
    keep = ("tier", "vocab", "samples", "proposals", "ablation", "pass", "timings_s")
    summary = {k: body[k] for k in keep}
    for row in summary["ablation"].values():
        row.pop("hazard_intervals", None)
    typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))
    raise typer.Exit(0 if body["pass"] else 1)


@contracts_app.command("export")
def contracts_export(
    check: bool = typer.Option(False, "--check", help="fail if generated files are stale; write nothing"),
) -> None:
    """Write JSON Schema to contracts/ and TypeScript types to packages/contracts-ts/."""
    from loom.core.contracts.export import export

    changed = export(check=check)
    if check and changed:
        typer.echo("stale generated contract files:\n  " + "\n  ".join(changed), err=True)
        raise typer.Exit(1)
    typer.echo("\n".join(f"wrote {c}" for c in changed) if changed else "contracts up to date")
