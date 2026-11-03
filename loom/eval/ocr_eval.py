"""`loom eval ocr` (spec/07 §2-3): on-screen text against the demo lesson's captions.

For each ground-truth caption: the best-matching span (whitespace-insensitive character similarity) among spans that
overlap the caption's time window; recall@0.8, temporal IoU, and exact match for formula captions.
Targets: recall 1.0, mean temporal IoU ≥ 0.90, formulas 100 % exact.
"""

from __future__ import annotations

import asyncio
import difflib
import statistics
import time
from pathlib import Path
from typing import Any

from loom.core.config import LoomConfig
from loom.eval.common import demo_video, free_gpu_for_torch, load_ground_truth, write_result
from loom.perception.ocr import OcrResult, is_math_like
from loom.perception.ocr_text import compact


def temporal_iou(a: tuple[float, float], b: tuple[float, float]) -> float:
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union > 0 else 0.0


def score_captions(result: OcrResult, captions: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for cap in captions:
        window = (float(cap["start"]), float(cap["end"]))
        best, best_sim = None, 0.0
        for span in result.spans:
            if temporal_iou((span.start, span.end), window) <= 0:
                continue
            sim = difflib.SequenceMatcher(None, compact(span.text), compact(cap["text"])).ratio()
            if sim > best_sim:
                best, best_sim = span, sim
        rows.append(
            {
                "caption": cap["text"],
                "found": best.text if best else None,
                "reader": best.reader if best else None,
                "char_sim": round(best_sim, 3),
                "temporal_iou": round(temporal_iou((best.start, best.end), window), 3) if best else 0.0,
                "formula": is_math_like(cap["text"]),
                "exact": best is not None and compact(best.text) == compact(cap["text"]),
            }
        )
    formulas = [r for r in rows if r["formula"]]
    recall = sum(r["char_sim"] >= 0.8 for r in rows) / len(rows)
    tiou = statistics.mean(r["temporal_iou"] for r in rows)
    exact = sum(r["exact"] for r in formulas) / len(formulas) if formulas else 1.0
    return {
        "recall_at_0_8": round(recall, 3),
        "mean_temporal_iou": round(tiou, 3),
        "formula_exact": round(exact, 3),
        "pass": recall == 1.0 and tiou >= 0.9 and exact == 1.0,
        "captions": rows,
    }


async def _reread(
    cfg: LoomConfig, result: OcrResult, video: Path, rect: tuple[float, float, float, float]
) -> OcrResult:
    from loom.core.llm import LLMClient
    from loom.core.ollama import OllamaHttp
    from loom.perception.ocr import reread_spans

    http = OllamaHttp(cfg)
    try:
        return await reread_spans(result, video, rect, LLMClient(cfg, http), cfg.data_dir / "eval" / "ocr_crops")
    finally:
        await http.aclose()


def release_torch() -> None:
    import gc

    gc.collect()
    try:
        import torch

        torch.cuda.empty_cache()
    except ImportError:
        pass


def run_ocr_eval(cfg: LoomConfig, reread: bool = True) -> dict[str, Any]:
    from loom.perception.ocr import detect_text
    from loom.perception.probe import detect_content_rect, media_info
    from loom.perception.shots import detect_shots

    gt = load_ground_truth()
    video = demo_video(cfg, gt)
    info = media_info(video)
    rect = detect_content_rect(video, info)
    free_gpu_for_torch(cfg)
    t0 = time.perf_counter()
    shots = detect_shots(video, info.duration_s)
    shots_s = time.perf_counter() - t0
    t1 = time.perf_counter()
    result = detect_text(
        video,
        [(s.start, s.end, s.keyframes) for s in shots.shots],
        info.duration_s,
        rect,
        cfg.perception.sample_fps,
        cfg.models.ocr.reread_below_confidence or 0.85,
    )
    ocr_s = time.perf_counter() - t1
    release_torch()
    rapid = score_captions(result, gt["on_screen_text"])
    body: dict[str, Any] = {
        "video_id": gt["video_id"],
        "engine": result.engine,
        "frames_read": result.frames_read,
        "spans": len(result.spans),
        "shots": len(shots.shots),
        "shots_s": round(shots_s, 2),
        "rapidocr_s": round(ocr_s, 2),
        "rapidocr_only": rapid,
    }
    final = rapid
    if reread:
        t2 = time.perf_counter()
        result = asyncio.run(_reread(cfg, result, video, rect))
        body["reread_s"] = round(time.perf_counter() - t2, 2)
        body["reread_spans"] = sum(s.reader == "glm-ocr" for s in result.spans)
        final = score_captions(result, gt["on_screen_text"])
        body["with_reread"] = final
    body.update({k: final[k] for k in ("recall_at_0_8", "mean_temporal_iou", "formula_exact", "pass")})
    body["targets"] = {"recall_at_0_8": 1.0, "mean_temporal_iou": 0.9, "formula_exact": 1.0}
    body["degraded"] = result.degraded
    body["all_spans"] = [s.model_dump() for s in result.spans]
    write_result(cfg, "ocr", body)
    return body
