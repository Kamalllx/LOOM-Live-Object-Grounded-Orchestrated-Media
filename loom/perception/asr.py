"""Speech transcription with sentence and word timing (spec/04 FR-PER-01).

faster-whisper `large-v3-turbo` (CTranslate2) on CUDA fp16 (int8_float16 fallback, CPU int8 as a last resort,
flagged `degraded`), Silero VAD, word timestamps. Words are regrouped into **sentences** with stable ids `s_001…`:
split on terminal punctuation, at most 12 s per sentence (split at the nearest pause/comma), fragments shorter than
1.2 s merged into a neighbour. A video without speech yields an empty transcript and `degraded: no_speech`.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

import numpy as np

from loom.core.weights import cached_snapshot
from loom.perception.models import AsrResult, SentenceTiming, WordTiming

STAGE_VERSION = "asr@1"
REPO = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
MAX_SENTENCE_S = 12.0
MIN_SENTENCE_S = 1.2
_TERMINAL = re.compile(r"[.!?…][\"')\]]*$")


def _text(words: list[WordTiming]) -> str:
    return re.sub(r"\s+", " ", "".join(w.w if w.w.startswith(" ") else " " + w.w for w in words)).strip()


def _split_long(words: list[WordTiming]) -> list[list[WordTiming]]:
    """Split a run of words longer than MAX_SENTENCE_S at the best break (comma, then largest pause)."""
    if not words or words[-1].end - words[0].start <= MAX_SENTENCE_S or len(words) < 2:
        return [words]
    best, best_score = None, -1.0
    for i in range(1, len(words)):
        left = words[i - 1].end - words[0].start
        right = words[-1].end - words[i].start
        if left < MIN_SENTENCE_S or right < MIN_SENTENCE_S:
            continue
        gap = words[i].start - words[i - 1].end
        score = gap + (1.0 if words[i - 1].w.rstrip().endswith((",", ";", ":")) else 0.0)
        score -= abs(left - right) / 100  # prefer balanced halves on ties
        if score > best_score:
            best, best_score = i, score
    if best is None:
        best = len(words) // 2
    return _split_long(words[:best]) + _split_long(words[best:])


def words_to_sentences(words: Iterable[WordTiming]) -> list[SentenceTiming]:
    groups: list[list[WordTiming]] = []
    current: list[WordTiming] = []
    for w in words:
        if not w.w.strip():
            continue
        current.append(w)
        if _TERMINAL.search(w.w.strip()):
            groups.append(current)
            current = []
    if current:
        groups.append(current)

    pieces = [g for group in groups for g in _split_long(group)]
    merged: list[list[WordTiming]] = []
    for g in pieces:
        dur = g[-1].end - g[0].start
        if merged and dur < MIN_SENTENCE_S and not _TERMINAL.search(merged[-1][-1].w.strip()):
            merged[-1] = merged[-1] + g  # an unfinished previous sentence absorbs the fragment
        elif merged and dur < MIN_SENTENCE_S and (g[-1].end - merged[-1][0].start) <= MAX_SENTENCE_S:
            merged[-1] = merged[-1] + g
        else:
            merged.append(g)
    if len(merged) > 1 and merged[0][-1].end - merged[0][0].start < MIN_SENTENCE_S:
        merged[1] = merged[0] + merged[1]
        merged = merged[1:]

    out: list[SentenceTiming] = []
    for i, g in enumerate(merged):
        start, end = round(g[0].start, 3), round(g[-1].end, 3)
        if end <= start:
            end = round(start + 0.05, 3)
        out.append(SentenceTiming(seg_id=f"s_{i + 1:03d}", start=start, end=end, text=_text(g), words=g))
    return out


SAMPLE_RATE = 16000


def load_audio(path: Path) -> np.ndarray:
    """Decode the first audio stream to 16 kHz mono float32 with FFmpeg (no PyAV dependency)."""
    res = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-",
        ],
        capture_output=True,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg audio decode failed: {res.stderr.decode('utf-8', 'replace')[-500:]}")
    return np.frombuffer(res.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def _prepare_cuda_dlls() -> None:
    """On Windows, CTranslate2 needs cuBLAS/cuDNN DLLs; the CUDA torch wheel ships them in torch/lib."""
    if os.name != "nt":
        return
    try:
        import torch

        lib = Path(torch.__file__).parent / "lib"
        if lib.is_dir():
            os.add_dll_directory(str(lib))
            os.environ["PATH"] = str(lib) + os.pathsep + os.environ.get("PATH", "")
    except ImportError:
        pass


def transcribe(audio_source: Path, has_audio: bool, model_name: str = "large-v3-turbo") -> AsrResult:
    if not has_audio:
        return AsrResult(
            language=None, sentences=[], model=model_name, device="none", compute_type="none", degraded=["no_speech"]
        )
    _prepare_cuda_dlls()
    from faster_whisper import WhisperModel

    audio = load_audio(audio_source)
    snapshot = cached_snapshot(REPO)
    model_ref = str(snapshot) if snapshot is not None else model_name
    degraded: list[str] = []
    attempts = [("cuda", "float16"), ("cuda", "int8_float16"), ("cpu", "int8")]
    last_error: Exception | None = None
    for device, compute_type in attempts:
        try:
            model = WhisperModel(model_ref, device=device, compute_type=compute_type)
            segments, info = model.transcribe(
                audio,
                vad_filter=True,
                word_timestamps=True,
                beam_size=5,
                condition_on_previous_text=False,
            )
            words = [
                WordTiming(
                    w=w.word,
                    start=round(w.start, 3),
                    end=round(max(w.end, w.start), 3),
                    p=round(float(w.probability), 3),
                )
                for seg in segments
                for w in (seg.words or [])
            ]
            break
        except (RuntimeError, ValueError, OSError) as exc:  # CUDA/cuDNN missing or out of memory: next attempt
            last_error = exc
            degraded.append(f"asr_{device}_{compute_type}_failed")
            continue
    else:
        raise RuntimeError(f"ASR failed on every device: {last_error}")
    if device == "cpu":
        degraded.append("asr_cpu")
    sentences = words_to_sentences(words)
    if not sentences:
        degraded.append("no_speech")
    return AsrResult(
        language=info.language,
        language_probability=round(float(info.language_probability), 3),
        sentences=sentences,
        model=f"faster-whisper {model_name}",
        device=device,
        compute_type=compute_type,
        degraded=[d for d in degraded if not d.endswith("_failed")] + [d for d in degraded if d.endswith("_failed")],
    )
