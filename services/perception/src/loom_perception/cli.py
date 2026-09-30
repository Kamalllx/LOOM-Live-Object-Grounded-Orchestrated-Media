"""Command line: `loom-perception run|validate|overlay|serve`."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import PipelineConfig


def _csv(s: str | None) -> list[str]:
    return [p.strip() for p in (s or "").split(",") if p.strip()]


def build_config(a: argparse.Namespace) -> PipelineConfig:
    cfg = PipelineConfig()
    cfg.media.sample_fps = a.fps
    cfg.media.chunk_seconds = a.chunk_seconds
    cfg.media.frame_width = a.frame_width
    cfg.asr.model = a.asr_model
    cfg.asr.device = a.device
    cfg.asr.language = a.language
    cfg.asr.diarize = a.diarize
    cfg.sam.backend = a.segmenter
    cfg.sam.box_threshold = a.box_threshold
    cfg.sam.prompts = _csv(a.prompts)
    cfg.sam.discover_prompts = not a.no_discover
    cfg.sam.max_prompts = a.max_prompts
    cfg.sam.score_threshold = a.score_threshold
    cfg.sam.save_masks = not a.no_masks
    cfg.sam.checkpoint = a.sam_checkpoint
    cfg.llm.enabled = not a.no_llm
    cfg.llm.model = a.llm_model
    return cfg


def add_run_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--fps", type=float, default=2.0, help="frames/second sampled for SAM (default 2)")
    p.add_argument("--chunk-seconds", type=float, default=60.0, help="SAM session length (default 60)")
    p.add_argument("--frame-width", type=int, default=960, help="width frames are downscaled to for SAM")
    p.add_argument("--asr-model", default="large-v3-turbo", help="faster-whisper model name")
    p.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"], help="device for ASR")
    p.add_argument("--language", default=None, help="force transcript language (default: detect)")
    p.add_argument("--diarize", action="store_true", help="speaker diarization with pyannote (optional dependency)")
    p.add_argument(
        "--segmenter",
        default="light",
        choices=["light", "sam3"],
        help="light: Grounding DINO tiny + SAM 2.1 tiny (laptops); sam3: SAM 3.1 multiplex (strong GPU)",
    )
    p.add_argument("--box-threshold", type=float, default=0.35, help="light segmenter detection threshold")
    p.add_argument("--prompts", default="", help="comma-separated objects SAM should always look for")
    p.add_argument("--no-discover", action="store_true", help="only use --prompts; don't propose prompts")
    p.add_argument("--max-prompts", type=int, default=12)
    p.add_argument("--score-threshold", type=float, default=0.5)
    p.add_argument("--no-masks", action="store_true", help="don't write per-frame mask sidecars")
    p.add_argument("--sam-checkpoint", default=None, help="local sam3.1_multiplex.pt (default: download from HF)")
    p.add_argument("--no-llm", action="store_true", help="don't call Gemini; use heuristic prompts and labels")
    p.add_argument("--llm-model", default="gemini-2.5-flash")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loom-perception", description="LOOM perception: video → concept-graph.json")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="process one video")
    run.add_argument("video", type=Path)
    run.add_argument("-o", "--out", type=Path, default=None, help="output folder (default: ./out/<video_id>)")
    run.add_argument("--video-id", default=None)
    run.add_argument("--skip", default="", help="comma-separated stages to skip: asr,ocr,prompts,sam,fusion")
    run.add_argument("--force", action="store_true", help="ignore cached stage outputs")
    run.add_argument("--keep-work", action="store_true", help="keep extracted audio/frames")
    add_run_options(run)

    val = sub.add_parser("validate", help="validate a concept-graph.json against the contract")
    val.add_argument("file", type=Path)

    ov = sub.add_parser("overlay", help="render masks, transcript and OCR onto the video for review")
    ov.add_argument("video", type=Path)
    ov.add_argument("result", type=Path, help="output folder of a run")
    ov.add_argument("-o", "--out", type=Path, default=None)

    srv = sub.add_parser("serve", help="run the HTTP service")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8101)
    srv.add_argument("--data-dir", type=Path, default=Path("data"))
    add_run_options(srv)

    a = parser.parse_args(argv)
    # Cap CPU threads before torch/onnxruntime load: saturating every core alongside the GPU
    # has crashed laptops (CLOCK_WATCHDOG_TIMEOUT). Override with LOOM_CPU_THREADS.
    import os

    threads = os.environ.get("LOOM_CPU_THREADS", "4")
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(var, threads)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if a.cmd == "validate":
        from .schema import validate

        problems = validate(json.loads(a.file.read_text(encoding="utf-8-sig")))
        if problems:
            print("\n".join(problems))
            return 1
        print(f"{a.file}: valid")
        return 0

    if a.cmd == "overlay":
        from .overlay import render_overlay

        out = a.out or a.result / "overlay.mp4"
        render_overlay(a.video, a.result, out)
        print(out)
        return 0

    if a.cmd == "serve":
        import uvicorn

        from .service import create_app

        uvicorn.run(create_app(build_config(a), a.data_dir), host=a.host, port=a.port)
        return 0

    from .pipeline import Pipeline, default_video_id

    video_id = a.video_id or default_video_id(a.video)
    out = a.out or Path("out") / video_id
    graph = Pipeline(build_config(a)).run(a.video, out, video_id=video_id, skip=set(_csv(a.skip)), force=a.force, keep_work=a.keep_work)
    counts = {k: len(graph[k]) for k in ("objects", "transcript", "on_screen_text", "concept_nodes")}
    print(json.dumps({"concept_graph": str(out / "concept-graph.json"), **counts}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
