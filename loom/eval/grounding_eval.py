"""`loom eval grounding` (spec/07 §2-3, FR-PER-05/07): detection + tracking + verification on the demo lesson.

Runs the S1 grounding chain - Grounding DINO proposals at `sample_fps` (denser in hazard windows), T0 IoU tracking per
shot, best-3 crops, SigLIP2 margin, `brain` hazard crop check - and scores four ablation rows:

  detector_only          every track kept
  +siglip_generic        SigLIP2 against the other vocabulary phrases + "background" (no curated look-alikes)
  +siglip_lookalikes     SigLIP2 against the curated look-alikes first
  +vlm (LOOM)            the shipped rule `TrackVerdict.decide` (look-alike SigLIP OR VLM; fail closed)

Hazard metrics are in seconds at 0.1 s resolution against the ground-truth hazard windows: hazard intervals are the
union of kept hazard-class instance times, padded by `safety.time_pad_s` (the mask time padding). Targets for the
LOOM row: precision >= 0.95, recall >= 0.90, false-block <= 2 s, missed <= 0.5 s.

Object recall is a *proxy* until keyframe boxes are annotated (ground truth `keyframe_annotations` is pending): a
ground-truth object counts as found in a segment if a kept non-hazard track with a matching phrase overlaps it.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from loom.core.config import LoomConfig
from loom.eval.common import demo_video, free_gpu_for_torch, load_ground_truth, write_result
from loom.eval.vocab_eval import matches
from loom.perception.detect import Box
from loom.perception.track import Track, track_shot
from loom.perception.verify import TrackVerdict

RESOLUTION = 0.1
TARGETS = {"precision": 0.95, "recall": 0.90, "false_block_s": 2.0, "missed_s": 0.5}
ROWS = ("detector_only", "+siglip_generic", "+siglip_lookalikes", "+vlm (LOOM)")

Interval = tuple[float, float]


# ---------------------------------------------------------------- pure scoring (unit-tested)


def sample_times(shots: Iterable[tuple[float, float]], fps: float) -> list[float]:
    """Sample times at `fps` inside each shot, centred in each interval so no sample sits on a cut."""
    step = 1.0 / fps
    out: list[float] = []
    for start, end in shots:
        t = start + step / 2
        while t < end - 1e-6:
            out.append(round(t, 3))
            t += step
    return out


def merge(intervals: Iterable[Interval]) -> list[Interval]:
    out: list[Interval] = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1] + 1e-9:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _ticks(intervals: list[Interval], duration: float) -> set[int]:
    """0.1 s ticks covered by the intervals (tick k covers [k*0.1, (k+1)*0.1), counted by its centre)."""
    covered: set[int] = set()
    for a, b in intervals:
        k = max(0, int(a / RESOLUTION))
        while k * RESOLUTION < min(b, duration):
            centre = (k + 0.5) * RESOLUTION
            if a <= centre < b:
                covered.add(k)
            k += 1
    return covered


def hazard_seconds(predicted: list[Interval], truth: list[Interval], duration: float) -> dict[str, float]:
    p, t = _ticks(merge(predicted), duration), _ticks(merge(truth), duration)
    tp = len(p & t)
    precision = tp / len(p) if p else (1.0 if not t else 0.0)
    recall = tp / len(t) if t else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "false_block_s": round(len(p - t) * RESOLUTION, 1),
        "missed_s": round(len(t - p) * RESOLUTION, 1),
    }


def hazard_intervals(tracks: list[Track], hazards: set[str], pad: float, duration: float) -> list[Interval]:
    return merge((max(0.0, tr.start - pad), min(duration, tr.end + pad)) for tr in tracks if tr.phrase in hazards)


def segment_recall(kept: list[Track], segments: list[dict[str, Any]], hazards: set[str]) -> dict[str, Any]:
    """Proxy object recall: per ground-truth (segment, object), a kept matching non-hazard track overlaps it."""
    rows = []
    for seg in segments:
        for label in seg.get("objects", []):
            phrases = {
                tr.phrase for tr in kept if tr.phrase not in hazards and tr.start < seg["end"] and seg["start"] < tr.end
            }
            rows.append({"segment": seg["id"], "object": label, "matched": matches(label, phrases)})
    found = sum(r["matched"] is not None for r in rows)
    return {"recall": round(found / len(rows), 3) if rows else 1.0, "rows": rows}


def row_keep(row: str, is_hazard: bool, generic: TrackVerdict, lookalike: TrackVerdict) -> bool:
    if row == "detector_only":
        return True
    if row == "+siglip_generic":
        return generic.siglip_pass is not False  # could-not-run keeps the track
    if row == "+siglip_lookalikes":
        return lookalike.siglip_pass is not False
    return lookalike.decide(is_hazard)[0]


def score_rows(
    tracks: list[Track],
    generic: dict[int, TrackVerdict],
    lookalike: dict[int, TrackVerdict],
    hazards: set[str],
    truth: list[Interval],
    segments: list[dict[str, Any]],
    pad: float,
    duration: float,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in ROWS:
        kept = [tr for i, tr in enumerate(tracks) if row_keep(row, tr.phrase in hazards, generic[i], lookalike[i])]
        haz = [tr for tr in kept if tr.phrase in hazards]
        predicted = hazard_intervals(kept, hazards, pad, duration)
        out[row] = {
            "tracks": len(kept),
            "hazard_tracks": len(haz),
            "hazard_labels": sorted({tr.phrase for tr in haz}),
            **hazard_seconds(predicted, truth, duration),
            "hazard_intervals": [[round(a, 2), round(b, 2)] for a, b in predicted],
            "object_recall_proxy": segment_recall(kept, segments, hazards)["recall"],
        }
    return out


def meets_targets(row: dict[str, Any]) -> bool:
    return bool(
        row["precision"] >= TARGETS["precision"]
        and row["recall"] >= TARGETS["recall"]
        and row["false_block_s"] <= TARGETS["false_block_s"]
        and row["missed_s"] <= TARGETS["missed_s"]
    )


# ---------------------------------------------------------------- runner (GPU)


def _frames(video: Path, times: list[float]) -> list[tuple[float, Any]]:
    import cv2
    from PIL import Image

    from loom.perception.ocr import FrameReader

    reader = FrameReader(video)
    out = []
    try:
        for t in sorted(times):
            frame = reader.at(t)
            if frame is not None:
                out.append((t, Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))))
    finally:
        reader.close()
    return out


def _vocab_phrases(cfg: LoomConfig) -> tuple[list[str], str]:
    """The vocabulary from `loom eval vocab` (cached brain output); the always-on hazard classes are always present."""
    import json

    path = cfg.data_dir / "eval" / "vocab.json"
    phrases: list[str] = []
    source = "hazard classes only (run `loom eval vocab` first)"
    if path.exists():
        phrases = [p["phrase"] for p in json.loads(path.read_text(encoding="utf-8"))["phrases"]]
        source = f"{path.name} ({len(phrases)} phrases)"
    for h in cfg.perception.hazard_classes:
        if h not in phrases:
            phrases.append(h)
    return phrases, source


def _timed[T](timings: dict[str, float], name: str, fn: Callable[[], T]) -> T:
    t0 = time.perf_counter()
    try:
        return fn()
    finally:
        timings[name] = round(time.perf_counter() - t0, 1)


async def _vlm(cfg: LoomConfig, tracks: list[Track], verdicts: dict[int, TrackVerdict], hazards: set[str]) -> None:
    from loom.core.llm import LLMClient
    from loom.core.ollama import OllamaHttp
    from loom.perception.verify import vlm_phase

    http = OllamaHttp(cfg)
    try:
        await vlm_phase(LLMClient(cfg, http), tracks, verdicts, hazards, cfg.perception.lookalikes, priority="ingest")
    finally:
        await http.aclose()


def run_grounding_eval(
    cfg: LoomConfig, gt_path: Path | None = None, phrases: list[str] | None = None
) -> dict[str, Any]:
    """`gt_path`: another ground-truth lesson (default: the demo); `phrases`: its vocabulary (default: `loom eval
    vocab`'s cached one, which belongs to the demo)."""
    from loom.perception.detect import Detector, hazard_window_times
    from loom.perception.probe import detect_content_rect, media_info
    from loom.perception.shots import detect_shots
    from loom.perception.verify import SiglipVerifier, crop_boxes, siglip_phase

    gt = load_ground_truth(gt_path) if gt_path else load_ground_truth()
    video = demo_video(cfg, gt)
    info = media_info(video)
    rect = detect_content_rect(video, info)
    shots = detect_shots(video, info.duration_s).shots
    spans = [(s.start, s.end) for s in shots]
    if phrases:
        phrases = [*phrases, *[h for h in cfg.perception.hazard_classes if h not in phrases]]
        vocab_source = f"given ({len(phrases)} phrases incl. hazard classes)"
    else:
        phrases, vocab_source = _vocab_phrases(cfg)
    hazards = set(cfg.perception.hazard_classes) & set(phrases)
    timings: dict[str, float] = {}
    unloaded = free_gpu_for_torch(cfg)

    # detect: base samples for every phrase, then denser samples around hazard proposals (hazard phrases only)
    base = sample_times(spans, cfg.perception.sample_fps)
    detector = Detector(box_threshold=cfg.perception.box_threshold)
    try:
        boxes: list[Box] = _timed(timings, "detect_base", lambda: detector.detect(_frames(video, base), phrases, rect))
        hazard_t = sorted({b.t for b in boxes if b.phrase in hazards})
        extra = hazard_window_times(hazard_t, spans, set(base), cfg.perception.hazard_window_fps)
        if extra:
            dense = _timed(
                timings, "detect_hazard_windows", lambda: detector.detect(_frames(video, extra), sorted(hazards), rect)
            )
            boxes += dense
    finally:
        detector.close()

    # track per shot (T0); linking interval = the base sampling interval
    interval = 1.0 / cfg.perception.sample_fps
    tracks: list[Track] = []
    for s in shots:
        tracks += track_shot([b for b in boxes if s.start <= b.t < s.end], s.shot_id, s.start, s.end, interval, hazards)

    outdir = cfg.data_dir / "eval" / "grounding" / "crops"
    crops = _timed(timings, "crops", lambda: {i: crop_boxes(video, tr, rect, outdir) for i, tr in enumerate(tracks)})

    verifier = SiglipVerifier()
    try:
        margin = cfg.perception.siglip_margin
        generic = _timed(timings, "siglip_generic", lambda: siglip_phase(verifier, tracks, crops, phrases, {}, margin))
        lookalike = _timed(
            timings,
            "siglip_lookalikes",
            lambda: siglip_phase(verifier, tracks, crops, phrases, cfg.perception.lookalikes, margin),
        )
    finally:
        verifier.close()

    t0 = time.perf_counter()
    asyncio.run(_vlm(cfg, tracks, lookalike, hazards))
    timings["vlm_hazard_check"] = round(time.perf_counter() - t0, 1)

    truth = [(float(h["start"]), float(h["end"])) for h in gt["hazards"]]
    rows = score_rows(
        tracks, generic, lookalike, hazards, truth, gt["segments"], cfg.safety.time_pad_s, info.duration_s
    )
    loom_row = rows["+vlm (LOOM)"]
    body = {
        "video_id": gt["video_id"],
        "tier": "boxes (T0)",
        "vocab": vocab_source,
        "hazard_truth": truth,
        "samples": {"base": len(base), "hazard_window": len(extra), "fps": cfg.perception.sample_fps},
        "proposals": len(boxes),
        "ablation": rows,
        "targets": TARGETS,
        "pass": meets_targets(loom_row),
        "timings_s": {**timings, "total": round(sum(timings.values()), 1)},
        "unloaded_before_torch": unloaded,
        "note": "object_recall_proxy = label-level per segment; box/mask IoU waits for keyframe annotation",
        "hazard_tracks": [
            {
                "phrase": tr.phrase,
                "shot": tr.shot_id,
                "start": tr.start,
                "end": tr.end,
                "score": tr.score,
                "samples": len(tr.samples),
                "siglip_generic": generic[i].siglip_margin,
                "siglip_lookalike": lookalike[i].siglip_margin,
                "vlm": lookalike[i].vlm,
                "better_label": lookalike[i].better_label,
                "kept": lookalike[i].decide(True),
            }
            for i, tr in enumerate(tracks)
            if tr.phrase in hazards
        ],
    }
    if gt_path is None:  # the demo's suite file; another lesson's caller writes its own (it once overwrote this one)
        write_result(cfg, "grounding", body)
    return body
