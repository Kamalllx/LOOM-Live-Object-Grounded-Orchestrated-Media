"""End-to-end orchestration: video → concept-graph.json (+ mask sidecars and a run report).

Output layout (out_dir):
  concept-graph.json       the contract output
  masks/obj_001.json       per-object, per-frame COCO RLE masks (for the Guardian and client compositing)
  stages/*.json            cached stage outputs; reused on re-runs unless --force or the inputs changed
  run.json                 timings, versions, config, prompt source, warnings
  work/                    scratch (audio, sampled frames); safe to delete
"""

from __future__ import annotations

import hashlib
import json
import logging
import platform
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import SCHEMA_VERSION, __version__
from .config import PipelineConfig
from .media import Frame, VideoInfo, extract_audio, extract_frames, plan_chunks, probe
from .schema import validate
from .types import FrameDetection, ObjectInstance, ObjectTrack, TextSpan, TranscriptSegment

log = logging.getLogger(__name__)
STAGES = ("asr", "ocr", "prompts", "sam", "fusion")
Progress = Callable[[str, float, str], None]


class PipelineError(RuntimeError):
    pass


@dataclass
class Components:
    """Factories for the heavy models. Tests replace these with fakes."""

    transcriber: Callable | None = None  # cfg.asr -> object with .transcribe(wav) -> (segments, language)
    ocr_reader: Callable | None = None  # () -> object with .read(ndarray) -> [Line]
    segmenter: Callable | None = None  # cfg.sam -> object with .segment_chunk(i, frames, prompts)
    embedder: Callable | None = None  # cfg.fusion -> Embedder
    gemini: Callable | None = None  # cfg.llm -> Gemini | None


@dataclass
class RunReport:
    video_id: str
    video: str
    pipeline_version: str = __version__
    schema_version: str = SCHEMA_VERSION
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    timings: dict[str, float] = field(default_factory=dict)
    cached: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    prompt_source: str | None = None
    prompts: dict[str, list[str]] = field(default_factory=dict)
    language: str | None = None
    counts: dict[str, int] = field(default_factory=dict)
    host: str = field(default_factory=platform.node)


def file_digest(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def default_video_id(path: Path) -> str:
    return "vid_" + file_digest(path)[:10]


def _fingerprint(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _code(*modules: str) -> str:
    """Hash of the stage's source files, so editing the code invalidates that stage's cache."""
    here = Path(__file__).parent
    h = hashlib.sha1()
    for m in modules:
        h.update((here / f"{m}.py").read_bytes())
    return h.hexdigest()[:12]


class Pipeline:
    def __init__(self, cfg: PipelineConfig | None = None, components: Components | None = None):
        self.cfg = cfg or PipelineConfig()
        self.components = components or Components()
        self._embedder = None
        self._gemini = "unset"
        self._models: dict[str, object] = {}

    # ---- model access (lazy, cached across runs for the HTTP service) ----
    def _model(self, name: str, factory: Callable, *args):
        if name not in self._models:
            self._models[name] = factory(*args)
        return self._models[name]

    def _get_embedder(self):
        if self._embedder is None:
            from .fusion import make_embedder

            self._embedder = (self.components.embedder or make_embedder)(self.cfg.fusion)
        return self._embedder

    def _get_gemini(self):
        if self._gemini == "unset":
            from .llm import try_gemini

            self._gemini = (self.components.gemini or try_gemini)(self.cfg.llm)
        return self._gemini

    # ---- stage cache ----
    def _cached(self, stages_dir: Path, name: str, fp: str, force: bool):
        path = stages_dir / f"{name}.json"
        if force or not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data["payload"] if data.get("fingerprint") == fp else None

    def _store(self, stages_dir: Path, name: str, fp: str, payload) -> None:
        stages_dir.mkdir(parents=True, exist_ok=True)
        (stages_dir / f"{name}.json").write_text(json.dumps({"fingerprint": fp, "payload": payload}), encoding="utf-8")

    # ---- the run ----
    def run(
        self,
        video: str | Path,
        out_dir: str | Path,
        video_id: str | None = None,
        skip: set[str] | None = None,
        force: bool = False,
        progress: Progress | None = None,
        keep_work: bool = False,
        prompts: list[str] | None = None,
    ) -> dict:
        """Runs every stage and returns the concept graph. `prompts` adds SAM prompts for this run only."""
        video, out_dir = Path(video), Path(out_dir)
        if prompts:
            from copy import deepcopy

            base, self.cfg = self.cfg, deepcopy(self.cfg)
            self.cfg.sam.prompts = [*base.sam.prompts, *prompts]
            try:
                return self.run(video, out_dir, video_id, skip, force, progress, keep_work)
            finally:
                self.cfg = base
        skip = set(skip or ())
        unknown = skip - set(STAGES)
        if unknown:
            raise PipelineError(f"unknown stage(s) to skip: {sorted(unknown)}")
        progress = progress or (lambda stage, frac, msg: log.info("[%s %3.0f%%] %s", stage, frac * 100, msg))
        cfg = self.cfg

        info = probe(video)
        digest = file_digest(video)
        video_id = video_id or "vid_" + digest[:10]
        out_dir.mkdir(parents=True, exist_ok=True)
        stages_dir, work = out_dir / "stages", out_dir / "work"
        report = RunReport(video_id=video_id, video=str(video))

        def timed(stage: str):
            class _T:
                def __enter__(s):
                    s.t = time.perf_counter()
                    progress(stage, 0.0, "started")

                def __exit__(s, *exc):
                    report.timings[stage] = round(time.perf_counter() - s.t, 2)
                    if not exc[0]:
                        progress(stage, 1.0, "done")

            return _T()

        # ASR
        transcript: list[TranscriptSegment] = []
        fp = _fingerprint(digest, asdict(cfg.asr), _code("asr"))
        if "asr" in skip or not cfg.asr.enabled:
            report.skipped.append("asr")
        elif not info.has_audio:
            report.warnings.append("video has no audio track; transcript is empty")
        else:
            with timed("asr"):
                cached = self._cached(stages_dir, "asr", fp, force)
                if cached is not None:
                    report.cached.append("asr")
                    transcript = [TranscriptSegment(**s) for s in cached["segments"]]
                    report.language = cached.get("language")
                else:
                    wav = extract_audio(video, work / "audio.wav")
                    from .asr import WhisperTranscriber, diarize

                    transcriber = self._model("asr", self.components.transcriber or WhisperTranscriber, cfg.asr)
                    transcript, report.language = transcriber.transcribe(wav)
                    if cfg.asr.diarize:
                        transcript = diarize(wav, transcript)
                    self._store(stages_dir, "asr", fp, {"segments": [asdict(s) for s in transcript], "language": report.language})

        # OCR
        text_spans: list[TextSpan] = []
        fp = _fingerprint(digest, asdict(cfg.ocr), _code("ocr"))
        if "ocr" in skip or not cfg.ocr.enabled:
            report.skipped.append("ocr")
        else:
            with timed("ocr"):
                cached = self._cached(stages_dir, "ocr", fp, force)
                if cached is not None:
                    report.cached.append("ocr")
                    text_spans = [TextSpan(**s) for s in cached]
                else:
                    from .ocr import RapidOcrReader, run_ocr

                    frames = extract_frames(video, work / "ocr_frames", cfg.ocr.sample_fps, width=min(info.width, 1280))
                    reader = self._model("ocr", self.components.ocr_reader or RapidOcrReader)
                    text_spans = run_ocr(frames, cfg.ocr, reader)
                    self._store(stages_dir, "ocr", fp, [asdict(s) for s in text_spans])

        # Prompt selection + SAM
        chunks = plan_chunks(info.duration, cfg.media.chunk_seconds, cfg.media.chunk_overlap_seconds)
        objects: list[ObjectTrack] = []
        run_sam = "sam" not in skip and cfg.sam.enabled
        if not run_sam:
            report.skipped.append("sam")
        prompts_by_chunk: dict[int, list[str]] = {}
        if run_sam and "prompts" not in skip:
            fp = _fingerprint(digest, asdict(cfg.sam), asdict(cfg.llm), asdict(cfg.media), [asdict(s) for s in transcript], [asdict(s) for s in text_spans], _code("vocab", "llm"))
            with timed("prompts"):
                cached = self._cached(stages_dir, "prompts", fp, force)
                if cached is not None:
                    report.cached.append("prompts")
                    prompts_by_chunk = {int(k): v for k, v in cached["by_chunk"].items()}
                    report.prompt_source = cached["source"]
                else:
                    from .vocab import choose_prompts

                    gemini = self._get_gemini() if cfg.sam.discover_prompts else None
                    keyframes = self._keyframes(video, work / "keyframes", chunks) if gemini else {}
                    prompts_by_chunk, report.prompt_source = choose_prompts(
                        cfg.sam.prompts,
                        transcript,
                        text_spans,
                        [(c.start, c.end) for c in chunks],
                        keyframes,
                        gemini,
                        cfg.sam.max_prompts,
                        cfg.sam.discover_prompts,
                    )
                    self._store(stages_dir, "prompts", fp, {"by_chunk": prompts_by_chunk, "source": report.prompt_source})
            report.prompts = {str(k): v for k, v in prompts_by_chunk.items()}
            if not any(prompts_by_chunk.values()):
                report.warnings.append("no SAM prompts found (no transcript, Gemini unavailable, no --prompts); objects will be empty")
        elif run_sam:
            prompts_by_chunk = {c.index: [p.lower() for p in cfg.sam.prompts] for c in chunks}

        if run_sam and any(prompts_by_chunk.values()):
            fp = _fingerprint(digest, asdict(cfg.sam), asdict(cfg.media), prompts_by_chunk, _code("sam", "light", "tracks", "llm"))
            with timed("sam"):
                cached = self._cached(stages_dir, "sam", fp, force)
                if cached is not None:
                    report.cached.append("sam")
                    objects = [_track_from_dict(d) for d in cached]
                else:
                    objects = self._segment(video, info, chunks, prompts_by_chunk, work, progress)
                    self._store(stages_dir, "sam", fp, [asdict(o) for o in objects])

        # Masks sidecars
        masks_dir = out_dir / "masks"
        if masks_dir.exists():
            shutil.rmtree(masks_dir)
        if cfg.sam.save_masks and objects:
            masks_dir.mkdir(parents=True)
            for o in objects:
                if any(d.rle for d in o.detections):
                    o.mask_ref = f"masks/{o.object_id}.json"
                    (out_dir / o.mask_ref).write_text(
                        json.dumps(
                            {
                                "object_id": o.object_id,
                                "label": o.label,
                                "aliases": o.aliases,
                                "sample_fps": cfg.media.sample_fps,
                                "frames": [{"t": d.t, "box": d.box, "score": round(d.score, 3), "rle": d.rle} for d in o.detections],
                            }
                        ),
                        encoding="utf-8",
                    )

        # Fusion
        with timed("fusion"):
            from .fusion import fuse

            gemini = self._get_gemini()
            nodes = fuse(
                info.duration,
                transcript,
                text_spans,
                objects,
                self._get_embedder(),
                cfg.fusion,
                labeler=gemini.label_concepts if gemini else None,
            )

        graph = {
            "schema_version": SCHEMA_VERSION,
            "video_id": video_id,
            "duration_seconds": round(info.duration, 2),
            "objects": [o.to_contract() for o in objects],
            "transcript": [s.to_contract() for s in transcript],
            "on_screen_text": [s.to_contract() for s in text_spans],
            "concept_nodes": [n.to_contract() for n in nodes],
        }
        problems = validate(graph)
        if problems:
            raise PipelineError("output failed validation:\n  " + "\n  ".join(problems))
        (out_dir / "concept-graph.json").write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")

        report.finished_at = time.time()
        report.counts = {k: len(graph[k]) for k in ("objects", "transcript", "on_screen_text", "concept_nodes")}
        (out_dir / "run.json").write_text(
            json.dumps({**asdict(report), "config": cfg.to_dict(), "video_info": {**asdict(info), "path": str(info.path)}}, indent=2),
            encoding="utf-8",
        )
        if not keep_work and work.exists():
            shutil.rmtree(work, ignore_errors=True)
        progress("done", 1.0, f"{report.counts}")
        return graph

    def _keyframes(self, video: Path, folder: Path, chunks) -> dict[int, list[Path]]:
        n = max(1, self.cfg.llm.keyframes_per_chunk)
        out: dict[int, list[Path]] = {}
        for c in chunks:
            length = max(0.5, c.end - c.start)
            frames = extract_frames(video, folder / f"{c.index:03d}", fps=n / length, width=768, start=c.start, end=c.end)
            out[c.index] = [f.path for f in frames[:n]]
        return out

    def _segment(self, video: Path, info: VideoInfo, chunks, prompts_by_chunk, work: Path, progress: Progress) -> list[ObjectTrack]:
        from .tracks import build_tracks

        backend = self.cfg.sam.backend
        if self.components.segmenter:
            factory = self.components.segmenter
        elif backend == "sam3":
            from .sam import Sam3Segmenter as factory
        elif backend == "light":
            from .light import LightSegmenter as factory
        else:
            raise PipelineError(f"unknown segmenter backend {backend!r} (light | sam3)")
        segmenter = self._model(f"seg:{backend}", factory, self.cfg.sam)
        if hasattr(segmenter, "verifier") and self.cfg.sam.verify_labels == "gemini":
            gemini = self._get_gemini()
            segmenter.verifier = gemini.name_objects if gemini else None
        step = 1.0 / self.cfg.media.sample_fps
        dets = []
        for c in chunks:
            prompts = prompts_by_chunk.get(c.index, [])
            if not prompts:
                continue
            frames: list[Frame] = extract_frames(
                video, work / "chunks" / f"{c.index:03d}", self.cfg.media.sample_fps, width=min(info.width, self.cfg.media.frame_width), start=c.start, end=c.end
            )
            progress("sam", c.index / len(chunks), f"chunk {c.index + 1}/{len(chunks)}: {len(frames)} frames × {len(prompts)} prompts")
            dets.extend(segmenter.segment_chunk(c.index, frames, prompts))
            shutil.rmtree(work / "chunks" / f"{c.index:03d}", ignore_errors=True)
        return build_tracks(dets, self.cfg.sam, step)


def _track_from_dict(d: dict) -> ObjectTrack:
    return ObjectTrack(
        object_id=d["object_id"],
        label=d["label"],
        confidence=d["confidence"],
        instances=[ObjectInstance(**i) for i in d["instances"]],
        detections=[FrameDetection(**x) for x in d.get("detections", [])],
        aliases=d.get("aliases", []),
        mask_ref=d.get("mask_ref"),
    )
