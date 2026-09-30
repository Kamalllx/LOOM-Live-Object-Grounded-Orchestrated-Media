"""On-screen text: OCR sampled frames (RapidOCR), then merge per-frame lines into continuous spans."""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

import numpy as np

from .config import OcrConfig
from .media import Frame
from .types import TextSpan

log = logging.getLogger(__name__)


@dataclass
class Line:
    text: str
    box: list[float]  # normalized [x, y, w, h]
    score: float


class RapidOcrReader:
    def __init__(self) -> None:
        from rapidocr import RapidOCR

        self.engine = RapidOCR()

    def read(self, image: np.ndarray) -> list[Line]:
        h, w = image.shape[:2]
        res = self.engine(image)
        boxes, txts, scores = getattr(res, "boxes", None), getattr(res, "txts", None), getattr(res, "scores", None)
        if boxes is None or txts is None:
            return []
        lines = []
        for box, text, score in zip(boxes, txts, scores):
            pts = np.asarray(box, dtype=float)
            x0, y0 = pts[:, 0].min() / w, pts[:, 1].min() / h
            x1, y1 = pts[:, 0].max() / w, pts[:, 1].max() / h
            lines.append(Line(text=str(text).strip(), box=[x0, y0, x1 - x0, y1 - y0], score=float(score)))
        return lines


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def _key(text: str) -> str:
    return re.sub(r"[^0-9a-z+\-=→>]", "", normalize(text).lower())


def similar(a: str, b: str) -> float:
    ka, kb = _key(a), _key(b)
    if not ka or not kb:
        return 0.0
    return SequenceMatcher(None, ka, kb).ratio()


def _box_iou(a: list[float], b: list[float]) -> float:
    ax1, ay1, bx1, by1 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw, ih = max(0.0, min(ax1, bx1) - max(a[0], b[0])), max(0.0, min(ay1, by1) - max(a[1], b[1]))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


@dataclass
class _Open:
    first: float
    last: float
    best: Line
    seen: int


def merge_spans(frames: list[tuple[float, list[Line]]], cfg: OcrConfig, step: float) -> list[TextSpan]:
    """Turns per-frame OCR lines into spans of continuously visible text.

    A line continues an open span when its text is similar enough (OCR jitter tolerated)
    and it sits roughly in the same place; the most confident reading wins.
    """
    open_spans: list[_Open] = []
    done: list[_Open] = []
    for t, lines in frames:
        lines = [ln for ln in lines if ln.score >= cfg.min_confidence and len(_key(ln.text)) >= cfg.min_chars]
        matched: set[int] = set()
        for ln in lines:
            best_i, best_s = None, 0.0
            for i, sp in enumerate(open_spans):
                if i in matched:
                    continue
                s = similar(ln.text, sp.best.text)
                if s >= cfg.merge_similarity and (_box_iou(ln.box, sp.best.box) > 0.1 or s > 0.97) and s > best_s:
                    best_i, best_s = i, s
            if best_i is None:
                open_spans.append(_Open(first=t, last=t, best=ln, seen=1))
                matched.add(len(open_spans) - 1)
            else:
                sp = open_spans[best_i]
                sp.last, sp.seen = t, sp.seen + 1
                if ln.score > sp.best.score:
                    sp.best = ln
                matched.add(best_i)
        still = []
        for i, sp in enumerate(open_spans):
            (still if i in matched or t - sp.last <= cfg.max_gap_seconds else done).append(sp)
        open_spans = still
    done.extend(open_spans)

    spans = []
    for sp in done:
        start, end = sp.first, sp.last + step
        if end - start < cfg.min_duration_seconds or sp.seen < cfg.min_frames:
            continue
        if sum(ch.isalpha() for ch in sp.best.text) < cfg.min_letters:
            continue
        spans.append(TextSpan(start=start, end=end, text=normalize(sp.best.text), bbox=sp.best.box, confidence=sp.best.score))
    spans.sort(key=lambda s: (s.start, s.bbox[1] if s.bbox else 0))
    return spans


def run_ocr(frames: list[Frame], cfg: OcrConfig, reader: RapidOcrReader | None = None) -> list[TextSpan]:
    import cv2

    reader = reader or RapidOcrReader()
    step = frames[1].t - frames[0].t if len(frames) > 1 else 1.0 / cfg.sample_fps
    results: list[tuple[float, list[Line]]] = []
    prev_small, prev_lines, reused = None, [], 0
    for f in frames:
        img = cv2.imread(str(f.path))
        if img is None:
            continue
        small = cv2.cvtColor(cv2.resize(img, (160, 90)), cv2.COLOR_BGR2GRAY).astype(np.int16)
        if prev_small is not None and np.abs(small - prev_small).mean() < cfg.change_threshold:
            lines, reused = prev_lines, reused + 1
        else:
            lines = reader.read(img)
            prev_small, prev_lines = small, lines
        results.append((f.t, lines))
    log.info("OCR: %d frames, %d reused unchanged results", len(frames), reused)
    return merge_spans(results, cfg, step)
