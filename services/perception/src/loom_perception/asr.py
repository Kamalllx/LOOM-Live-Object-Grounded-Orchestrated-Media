"""Speech → timestamped transcript segments (faster-whisper), optionally with speaker turns (pyannote)."""

from __future__ import annotations

import logging
import math
import os
import re
from pathlib import Path

from .config import AsrConfig
from .types import TranscriptSegment

log = logging.getLogger(__name__)
_SENTENCE_END = re.compile(r"[.!?…]$")


def _ensure_cuda_dlls() -> None:
    """On Windows, CTranslate2 needs cuBLAS/cuDNN DLLs; the CUDA build of torch ships them."""
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


def _resolve_device(cfg: AsrConfig) -> tuple[str, str]:
    device = cfg.device
    if device == "auto":
        try:
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
    compute = cfg.compute_type
    if compute == "auto":
        compute = "float16" if device == "cuda" else "int8"
    return device, compute


class WhisperTranscriber:
    def __init__(self, cfg: AsrConfig):
        self.cfg = cfg
        _ensure_cuda_dlls()
        from faster_whisper import WhisperModel

        device, compute = _resolve_device(cfg)
        log.info("loading faster-whisper %s on %s (%s)", cfg.model, device, compute)
        self.model = WhisperModel(cfg.model, device=device, compute_type=compute)

    def transcribe(self, wav: str | Path) -> tuple[list[TranscriptSegment], str | None]:
        segments, info = self.model.transcribe(
            str(wav),
            language=self.cfg.language,
            vad_filter=self.cfg.vad,
            word_timestamps=True,
            beam_size=5,
            condition_on_previous_text=False,
        )
        out: list[TranscriptSegment] = []
        for seg in segments:
            conf = math.exp(seg.avg_logprob) if seg.avg_logprob is not None else None
            words = [(w.start, w.end, w.word) for w in (seg.words or [])]
            for start, end, text in split_sentences(words, seg.start, seg.end, seg.text, self.cfg.max_segment_seconds):
                if text:
                    out.append(TranscriptSegment(start=start, end=end, text=text, speaker=self.cfg.default_speaker, confidence=conf))
        return out, getattr(info, "language", None)


def split_sentences(
    words: list[tuple[float, float, str]], seg_start: float, seg_end: float, seg_text: str, max_seconds: float
) -> list[tuple[float, float, str]]:
    """Splits one Whisper segment into sentence-sized pieces using word timestamps.

    Short segments pass through unchanged; long ones break at sentence punctuation,
    or at the longest inter-word pause if a sentence itself is too long.
    """
    text = " ".join(seg_text.split())
    if not words or seg_end - seg_start <= max_seconds and not _has_inner_sentence_end(text):
        return [(seg_start, seg_end, text)]

    pieces: list[list[tuple[float, float, str]]] = [[]]
    for w in words:
        pieces[-1].append(w)
        if _SENTENCE_END.search(w[2].strip()):
            pieces.append([])
    pieces = [p for p in pieces if p]

    result: list[tuple[float, float, str]] = []
    for p in pieces:
        result.extend(_split_long(p, max_seconds))
    return result


def _has_inner_sentence_end(text: str) -> bool:
    return bool(re.search(r"[.!?…]\s+\S", text))


def _split_long(words: list[tuple[float, float, str]], max_seconds: float) -> list[tuple[float, float, str]]:
    if words[-1][1] - words[0][0] <= max_seconds or len(words) < 4:
        return [(words[0][0], words[-1][1], "".join(w[2] for w in words).strip())]
    gaps = [(words[i + 1][0] - words[i][1], i) for i in range(1, len(words) - 2)]
    _, cut = max(gaps)
    return _split_long(words[: cut + 1], max_seconds) + _split_long(words[cut + 1 :], max_seconds)


def diarize(wav: str | Path, segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """Assigns speaker_0, speaker_1… by overlap with pyannote turns. Leaves segments untouched if unavailable."""
    try:
        from pyannote.audio import Pipeline
    except ImportError:
        log.warning("diarization requested but pyannote.audio is not installed; keeping default speaker")
        return segments
    try:
        pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")
        try:
            import torch

            if torch.cuda.is_available():
                pipe.to(torch.device("cuda"))
        except ImportError:
            pass
        annotation = pipe(str(wav))
    except Exception as e:  # gated model, no token, etc.
        log.warning("diarization failed (%s); keeping default speaker", e)
        return segments
    turns = [(t.start, t.end, spk) for t, _, spk in annotation.itertracks(yield_label=True)]
    names: dict[str, str] = {}
    for seg in segments:
        best, best_overlap = None, 0.0
        for s, e, spk in turns:
            ov = min(e, seg.end) - max(s, seg.start)
            if ov > best_overlap:
                best, best_overlap = spk, ov
        if best is not None:
            seg.speaker = names.setdefault(best, f"speaker_{len(names)}")
    return segments
