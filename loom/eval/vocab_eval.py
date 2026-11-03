"""`loom eval vocab` (spec/04 FR-PER-04 accept): the demo vocabulary contains every ground-truth object label (or a
synonym / containing phrase) and every always-on hazard class."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from loom.core.config import LoomConfig
from loom.eval.common import demo_video, load_ground_truth, write_result
from loom.perception.vocab import VocabResult, normalize_phrase

# accepted equivalents when matching ground-truth labels to vocabulary phrases
EQUIVALENT = {
    "beaker": {"glass beaker", "beaker"},
    "glass beaker": {"glass beaker", "beaker"},
    "gloves": {"gloves", "latex gloves", "nitrile gloves", "rubber gloves", "glove"},
    "volumetric flask": {"volumetric flask", "flask", "round bottom flask", "glass flask"},
    "measuring cylinder": {"measuring cylinder", "graduated cylinder", "cylinder"},
    "broken glass": {"broken glass", "shattered glass", "glass shards", "broken bottle", "shattered bottle"},
}


def matches(label: str, phrases: set[str]) -> str | None:
    key = normalize_phrase(label)
    accepted = {normalize_phrase(p) for p in EQUIVALENT.get(key, {key})} | {key}
    for p in sorted(phrases):
        if p in accepted or key in p.split(" ") or (len(key.split()) > 1 and key in p):
            return p
    return None


def score_vocab(result: VocabResult, gt_labels: list[str], hazards: list[str]) -> dict[str, Any]:
    phrases = {v.phrase for v in result.phrases}
    rows = {label: matches(label, phrases) for label in sorted(set(gt_labels))}
    recall = sum(v is not None for v in rows.values()) / len(rows)
    hazards_ok = all(normalize_phrase(h) in phrases for h in hazards)
    return {
        "gt_recall": round(recall, 3),
        "matched": rows,
        "all_hazard_classes": hazards_ok,
        "pass": recall == 1.0 and hazards_ok,
    }


async def _build(
    cfg: LoomConfig,
    video: Any,
    shots: list[tuple[float, float]],
    sentences: list[tuple[float, float, str]],
    ocr: list[tuple[float, float, str]],
) -> VocabResult:
    from loom.core.llm import LLMClient
    from loom.core.ollama import OllamaHttp
    from loom.perception.vocab import build_vocab

    http = OllamaHttp(cfg)
    try:
        return await build_vocab(
            cfg, LLMClient(cfg, http), video, shots, sentences, ocr, cfg.data_dir / "eval" / "vocab"
        )
    finally:
        await http.aclose()


def run_vocab_eval(cfg: LoomConfig) -> dict[str, Any]:
    from loom.perception.probe import media_info
    from loom.perception.shots import detect_shots

    gt = load_ground_truth()
    video = demo_video(cfg, gt)
    info = media_info(video)
    shots = detect_shots(video, info.duration_s)
    # vocab is evaluated on its own: the reference transcript and captions stand in for ASR/OCR output
    sentences = [(n["start"], n["end"], n["text"]) for n in gt["narration"]]
    texts = [(c["start"], c["end"], c["text"]) for c in gt["on_screen_text"]]
    t0 = time.perf_counter()
    result = asyncio.run(_build(cfg, video, [(s.start, s.end) for s in shots.shots], sentences, texts))
    seconds = time.perf_counter() - t0
    gt_labels = [o for seg in gt["segments"] for o in seg["objects"]]
    score = score_vocab(result, gt_labels, list(cfg.perception.hazard_classes))
    body = {
        "video_id": gt["video_id"],
        "seconds": round(seconds, 2),
        "model": result.model,
        "degraded": result.degraded,
        "keyframes": result.keyframes,
        **score,
        "phrases": [v.model_dump() for v in result.phrases],
    }
    write_result(cfg, "vocab", body)
    return body
