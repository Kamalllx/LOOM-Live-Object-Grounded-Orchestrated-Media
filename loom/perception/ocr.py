"""On-screen text with time spans and boxes (spec/04 FR-PER-02).

1. Frames sampled at `sample_fps` within each shot, plus every keyframe; RapidOCR (PP-OCR ONNX, CPU) reads boxes +
   text + confidence per frame.
2. Detections are tracked across frames into spans `x_001…`: same or similar text (char similarity ≥ 0.8, whitespace
   insensitive) at an overlapping position, consecutive in time (gap ≤ 1.5 sampling intervals). A span's text is its
   most confident reading; its box the median box; start/end padded by half a sampling interval.
3. Spans that are low-confidence (< `ocr.reread_below_confidence`) or math-like are re-read by the `ocr` role
   (glm-ocr) on a crop of their best frame; the reply is normalized LaTeX → Unicode (`ocr_text.py`).
Boxes are normalized `[x, y, w, h]` relative to the picture (`content_rect` removed).
"""

from __future__ import annotations

import difflib
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loom.core.contracts.common import BBox, Contract
from loom.perception.ocr_text import compact

if TYPE_CHECKING:
    import numpy as np

STAGE_VERSION = "ocr@1"
SIM_THRESHOLD = 0.8
MIN_IOU = 0.2
# operators and letter/digit mixes (H2O, 2HCl); a plain hyphen ("Acid-Base") is not math, a minus sign (−) is
_MATH = re.compile(r"[=+−→⇌^_()]|\d[A-Za-z]|[A-Za-z]\d|\d\s*-\s*\d")
REREAD_KEEP_CONFIDENCE = 0.6


@dataclass(frozen=True)
class Detection:
    t: float
    text: str
    box: tuple[float, float, float, float]  # normalized to the picture
    confidence: float


@dataclass
class SpanDraft:
    detections: list[Detection] = field(default_factory=list)

    @property
    def start(self) -> float:
        return self.detections[0].t

    @property
    def end(self) -> float:
        return self.detections[-1].t

    @property
    def best(self) -> Detection:
        return max(self.detections, key=lambda d: (d.confidence, len(d.text)))

    @property
    def box(self) -> tuple[float, float, float, float]:
        cols = list(zip(*(d.box for d in self.detections), strict=True))
        return (
            round(statistics.median(cols[0]), 4),
            round(statistics.median(cols[1]), 4),
            round(statistics.median(cols[2]), 4),
            round(statistics.median(cols[3]), 4),
        )

    @property
    def confidence(self) -> float:
        return round(statistics.mean(d.confidence for d in self.detections), 3)


def text_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, compact(a).lower(), compact(b).lower()).ratio()


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a[0], a[1], a[0] + a[2], a[1] + a[3]
    bx1, by1, bx2, by2 = b[0], b[1], b[0] + b[2], b[1] + b[3]
    iw, ih = max(0.0, min(ax2, bx2) - max(ax1, bx1)), max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def is_math_like(text: str) -> bool:
    return bool(_MATH.search(text))


def to_picture_box(
    quad: list[list[float]], frame_w: int, frame_h: int, content_rect: tuple[float, float, float, float]
) -> tuple[float, float, float, float] | None:
    """Pixel quadrilateral → normalized [x, y, w, h] inside the picture; None if it lies outside the picture."""
    xs, ys = [p[0] for p in quad], [p[1] for p in quad]
    cx, cy, cw, ch = content_rect
    px0, py0, pw, ph = cx * frame_w, cy * frame_h, cw * frame_w, ch * frame_h
    x0 = max(0.0, (min(xs) - px0) / pw)
    y0 = max(0.0, (min(ys) - py0) / ph)
    x1 = min(1.0, (max(xs) - px0) / pw)
    y1 = min(1.0, (max(ys) - py0) / ph)
    if x1 <= x0 or y1 <= y0:
        return None
    return (round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4))


def group_spans(detections: list[Detection], interval: float) -> list[SpanDraft]:
    """Track detections over time into spans (greedy, in time order)."""
    open_spans: list[SpanDraft] = []
    closed: list[SpanDraft] = []
    for d in sorted(detections, key=lambda d: (d.t, d.box[1], d.box[0])):
        still_open: list[SpanDraft] = []
        for s in open_spans:
            (still_open if d.t - s.end <= 1.5 * interval + 1e-6 else closed).append(s)
        open_spans = still_open
        match = None
        for s in open_spans:
            last = s.detections[-1]
            if last.t == d.t:
                continue
            if iou(last.box, d.box) >= MIN_IOU and text_similarity(last.text, d.text) >= SIM_THRESHOLD:
                match = s
                break
        if match is None:
            open_spans.append(SpanDraft([d]))
        else:
            match.detections.append(d)
    return sorted(closed + open_spans, key=lambda s: (s.start, s.box[1], s.box[0]))


def sample_times(shots: list[tuple[float, float, list[float]]], fps: float, duration: float) -> list[float]:
    times: set[float] = set()
    step = 1.0 / fps
    for start, end, keyframes in shots:
        t = start + step / 2
        while t < end:
            times.add(round(t, 3))
            t += step
        times.update(round(k, 3) for k in keyframes)
    return sorted(t for t in times if 0 <= t < duration)


# ------------------------------------------------------------------------------------------------ filtering

# Characters a v1 (English) lesson can legitimately show: Latin, digits, punctuation, math, Greek, sub/superscripts.
_ALLOWED = re.compile(r"[A-Za-z0-9\s.,:;!?'\"()\[\]{}%/\+\-−=<>≤≥≈≠×÷·°±→←↔⇌⇒^_*#&@$€£α-ωΑ-Ω₀-₉⁰-⁹⁺⁻⁼₊₋₌ⁿ]")


def clean_text(text: str) -> str | None:
    """Drop characters outside the v1 (English) repertoire; None when nothing readable remains (e.g. '区')."""
    kept = "".join(ch for ch in text if _ALLOWED.match(ch)).strip()
    if not re.search(r"[A-Za-z0-9α-ωΑ-Ω]", kept):
        return None
    return kept


# ------------------------------------------------------------------------------------------------ engine


def read_frame(path: Path, t: float) -> np.ndarray | None:
    import cv2

    cap = cv2.VideoCapture(str(path))
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        return frame if ok else None
    finally:
        cap.release()


class FrameReader:
    """Sequential frame access (seeking per frame is slow with OpenCV); frames are BGR numpy arrays."""

    def __init__(self, path: Path) -> None:
        import cv2

        self.cap = cv2.VideoCapture(str(path))
        self.fps = float(self.cap.get(cv2.CAP_PROP_FPS)) or 30.0
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._index = -1
        self._frame: Any = None

    def at(self, t: float) -> Any:
        import cv2

        target = round(t * self.fps)
        if target < self._index or target - self._index > self.fps * 5:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, target)
            self._index = target - 1
        while self._index < target:
            ok, frame = self.cap.read()
            if not ok:
                return None
            self._index += 1
            self._frame = frame
        return self._frame

    def close(self) -> None:
        self.cap.release()


DET_LIMIT_SIDE = 960


def rapidocr_engine(use_cuda: bool = True) -> Any:
    """PP-OCR via RapidOCR. On CUDA (torch engine) ~0.1 s per 720p frame vs ~1.9 s with the CPU default (S1 bench).

    The text-orientation classifier is off (lesson captions are upright) and detection runs at ≤ 960 px."""
    from rapidocr import EngineType, RapidOCR

    params: dict[str, Any] = {
        "Global.use_cls": False,
        "Global.log_level": "error",
        "Det.limit_type": "max",
        "Det.limit_side_len": DET_LIMIT_SIDE,
    }
    if use_cuda:
        params |= {
            "Det.engine_type": EngineType.TORCH,
            "Rec.engine_type": EngineType.TORCH,
            "EngineConfig.torch.use_cuda": True,
        }
    return RapidOCR(params=params)


def ocr_frame(engine: Any, frame: Any) -> list[tuple[list[list[float]], str, float]]:
    """Run RapidOCR on one frame → [(quad, text, confidence)]."""
    out = engine(frame)
    boxes = getattr(out, "boxes", None)
    txts = getattr(out, "txts", None)
    scores = getattr(out, "scores", None)
    if boxes is None or txts is None:
        return []
    return [
        ([[float(x), float(y)] for x, y in quad], str(text), float(score))
        for quad, text, score in zip(boxes, txts, scores or [1.0] * len(txts), strict=False)
        if str(text).strip()
    ]


# ------------------------------------------------------------------------------------------------ stage


class OcrSpan(Contract):
    text_id: str
    start: float
    end: float
    text: str
    bbox: BBox
    confidence: float
    reader: str
    best_t: float
    needs_reread: bool


class OcrResult(Contract):
    spans: list[OcrSpan]
    frames_read: int
    sample_fps: float
    engine: str
    keyframes: list[float] = []  # times where new on-screen text appears (added to shot keyframes)
    degraded: list[str] = []


def detect_text(
    video: Path,
    shots: list[tuple[float, float, list[float]]],
    duration: float,
    content_rect: tuple[float, float, float, float],
    sample_fps: float,
    reread_below: float,
    engine: Any | None = None,
) -> OcrResult:
    engine_name = "rapidocr-pp-ocrv6/torch-cuda"
    if engine is None:
        try:
            engine = rapidocr_engine(use_cuda=True)
        except Exception:  # CUDA engine unavailable: CPU is slower but correct
            engine, engine_name = rapidocr_engine(use_cuda=False), "rapidocr-pp-ocrv6/onnx-cpu"
    times = sample_times(shots, sample_fps, duration)
    reader = FrameReader(video)
    detections: list[Detection] = []
    try:
        for t in times:
            frame = reader.at(t)
            if frame is None:
                continue
            for quad, text, conf in ocr_frame(engine, frame):
                cleaned = clean_text(text)
                box = to_picture_box(quad, reader.width, reader.height, content_rect)
                if cleaned and box:
                    detections.append(Detection(t=t, text=cleaned, box=box, confidence=round(conf, 4)))
    finally:
        reader.close()
    interval = 1.0 / sample_fps
    spans = []
    for i, d in enumerate(group_spans(detections, interval)):
        best = d.best
        start = max(0.0, round(d.start - interval / 2, 2))
        end = round(min(duration, d.end + interval / 2), 2)
        spans.append(
            OcrSpan(
                text_id=f"x_{i + 1:03d}",
                start=start,
                end=max(end, round(start + 0.05, 2)),
                text=best.text,
                bbox=d.box,
                confidence=d.confidence,
                reader="rapidocr",
                best_t=best.t,
                needs_reread=d.confidence < reread_below or is_math_like(best.text),
            )
        )
    keyframes = sorted({round(s.best_t, 2) for s in spans})
    return OcrResult(
        spans=spans, frames_read=len(times), sample_fps=sample_fps, engine=engine_name, keyframes=keyframes
    )


def crop_for_reread(video: Path, span: OcrSpan, content_rect: tuple[float, float, float, float], out: Path) -> Path:
    """Save the span's box (padded 15 %) from its best frame as PNG for the `ocr` role."""
    import cv2

    frame = read_frame(video, span.best_t)
    if frame is None:
        raise RuntimeError(f"cannot read frame at {span.best_t}s")
    fh, fw = frame.shape[:2]
    cx, cy, cw, ch = content_rect
    x, y, w, h = span.bbox
    pad_x, pad_y = w * 0.15, h * 0.35
    x0 = int(max(0, (cx + (x - pad_x) * cw) * fw))
    y0 = int(max(0, (cy + (y - pad_y) * ch) * fh))
    x1 = int(min(fw, (cx + (x + w + pad_x) * cw) * fw))
    y1 = int(min(fh, (cy + (y + h + pad_y) * ch) * fh))
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), frame[y0:y1, x0:x1])
    return out


class OcrReading(Contract):
    text: str


def parse_ocr_reply(text: str) -> OcrReading:
    """glm-ocr replies in LaTeX for formulas; normalize to the Unicode a viewer reads (spec/03 §5.5)."""
    from loom.perception.ocr_text import latex_to_unicode

    cleaned = clean_text(latex_to_unicode(text))
    if not cleaned:
        raise ValueError("empty OCR reading")
    return OcrReading(text=cleaned)


async def reread_spans(
    result: OcrResult,
    video: Path,
    content_rect: tuple[float, float, float, float],
    llm: Any,
    workdir: Path,
    priority: Any = "ingest",
) -> OcrResult:
    """Re-read low-confidence / math-like spans with the `ocr` role. Not a safety path: if the model is unavailable
    the RapidOCR reading is kept and the result is flagged `degraded: ocr_reread_unavailable`. An *empty* re-read of a
    low-confidence span means "no text here" (a spurious detection) and drops the span."""
    from loom.core.llm import LLMError, ModelRefused

    spans: list[OcrSpan] = []
    degraded = list(result.degraded)
    for span in result.spans:
        if not span.needs_reread:
            spans.append(span)
            continue
        crop = crop_for_reread(video, span, content_rect, workdir / f"ocr_{span.text_id}.png")
        try:
            res = await llm.call(
                "ocr", "ocr_read", {}, OcrReading, images=[crop], parser=parse_ocr_reply, priority=priority
            )
        except ModelRefused:
            if span.confidence < REREAD_KEEP_CONFIDENCE:
                continue  # the OCR model sees no text: drop the spurious low-confidence detection
            spans.append(span)
            continue
        except LLMError:
            if "ocr_reread_unavailable" not in degraded:
                degraded.append("ocr_reread_unavailable")
            spans.append(span)
            continue
        new_text = res.value.text
        # keep the model's reading unless it is wildly different from what RapidOCR saw (a misplaced crop)
        if text_similarity(new_text, span.text) >= 0.5 or span.confidence < 0.5:
            spans.append(span.model_copy(update={"text": new_text, "reader": "glm-ocr"}))
        else:
            spans.append(span)
    spans = [s.model_copy(update={"text_id": f"x_{i + 1:03d}"}) for i, s in enumerate(spans)]
    return result.model_copy(update={"spans": spans, "degraded": degraded})
