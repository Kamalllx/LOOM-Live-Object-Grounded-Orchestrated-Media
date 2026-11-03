"""`loom eval asr` (spec/07 §2-3): WER of the local ASR against the demo lesson's narration script.

Normalization (applied to both sides): lowercase, punctuation removed, numbers 0-99 spelled out (so "pH 7" and
"pH seven" are the same words), whitespace collapsed. Target WER ≤ 0.03; runtime ≤ 15 s per 75 s of audio.
"""

from __future__ import annotations

import re
import time
from typing import Any

from loom.core.config import LoomConfig
from loom.eval.common import demo_video, free_gpu_for_torch, load_ground_truth, write_result

_ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_TENS = ["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _number(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + ("" if ones == 0 else " " + _ONES[ones])


def normalize(text: str) -> str:
    t = text.lower().replace("-", " ")
    t = re.sub(r"\b(\d{1,2})\b", lambda m: _number(int(m.group(1))), t)
    t = re.sub(r"[^\w\s']", " ", t)
    t = t.replace("'", "")
    return re.sub(r"\s+", " ", t).strip()


def wer(reference: str, hypothesis: str) -> dict[str, Any]:
    import jiwer

    ref, hyp = normalize(reference), normalize(hypothesis)
    out = jiwer.process_words(ref, hyp)
    return {
        "wer": round(out.wer, 4),
        "ref_words": len(ref.split()),
        "substitutions": out.substitutions,
        "deletions": out.deletions,
        "insertions": out.insertions,
    }


def run_asr_eval(cfg: LoomConfig) -> dict[str, Any]:
    from loom.perception.asr import transcribe
    from loom.perception.probe import media_info

    gt = load_ground_truth()
    video = demo_video(cfg, gt)
    info = media_info(video)
    free_gpu_for_torch(cfg)
    t0 = time.perf_counter()
    result = transcribe(video, info.has_audio, cfg.perception.asr_model)
    seconds = time.perf_counter() - t0
    reference = " ".join(n["text"] for n in gt["narration"])
    hypothesis = " ".join(s.text for s in result.sentences)
    score = wer(reference, hypothesis)
    body = {
        "video_id": gt["video_id"],
        "model": result.model,
        "device": result.device,
        "compute_type": result.compute_type,
        "audio_seconds": round(info.duration_s, 2),
        "runtime_s": round(seconds, 2),
        "runtime_per_75s": round(seconds * 75 / info.duration_s, 2),
        **score,
        "target_wer": 0.03,
        "pass": score["wer"] <= 0.03,
        "sentences": len(result.sentences),
        "ids_contiguous": [s.seg_id for s in result.sentences]
        == [f"s_{i + 1:03d}" for i in range(len(result.sentences))],
        "all_start_lt_end": all(s.start < s.end for s in result.sentences),
        "degraded": result.degraded,
        "hypothesis": hypothesis,
        "reference": reference,
    }
    write_result(cfg, "asr", body)
    return body
