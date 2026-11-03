"""Open-vocabulary detection (spec/04 FR-PER-05): Grounding DINO base on frames sampled within each shot.

Phrases are batched ≤ 8 per text prompt; each box is assigned to the phrase whose token span scores highest (the
library's text-label decoding glues tokens across phrases — S1 finding), kept if that score ≥ `box_threshold`, then
NMS per phrase. Frames are batched for throughput. Detections are *proposals* for tracking/segmentation.
Boxes are normalized `[x, y, w, h]` relative to the picture (`content_rect` removed).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loom.core.weights import cached_snapshot

STAGE_VERSION = "detect@1"
REPO = "IDEA-Research/grounding-dino-base"
PHRASES_PER_PROMPT = 8
FRAME_BATCH = 4
NMS_IOU = 0.5


@dataclass(frozen=True)
class Box:
    t: float
    phrase: str
    box: tuple[float, float, float, float]  # normalized to the picture
    score: float


def prompt_and_spans(phrases: list[str], tokenizer: Any) -> tuple[str, list[tuple[int, int]]]:
    """Build "a . b . c ." and the [start, end) token index range of each phrase in the tokenized prompt."""
    text = ""
    char_spans = []
    for p in phrases:
        start = len(text)
        text += p
        char_spans.append((start, len(text)))
        text += " . "
    text = text.strip()
    enc = tokenizer(text, return_offsets_mapping=True)
    offsets = enc["offset_mapping"]
    spans = []
    for cs, ce in char_spans:
        idx = [i for i, (a, b) in enumerate(offsets) if b > a and a >= cs and b <= ce]
        spans.append((min(idx), max(idx) + 1) if idx else (0, 0))
    return text, spans


def to_picture(
    box_cxcywh: tuple[float, float, float, float], rect: tuple[float, float, float, float]
) -> tuple[float, float, float, float] | None:
    """Model output (normalized cx, cy, w, h over the frame) → normalized [x, y, w, h] over the picture."""
    cx, cy, w, h = box_cxcywh
    rx, ry, rw, rh = rect
    x0 = max(0.0, (cx - w / 2 - rx) / rw)
    y0 = max(0.0, (cy - h / 2 - ry) / rh)
    x1 = min(1.0, (cx + w / 2 - rx) / rw)
    y1 = min(1.0, (cy + h / 2 - ry) / rh)
    if x1 - x0 < 0.005 or y1 - y0 < 0.005:
        return None
    return (round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4))


class Detector:
    def __init__(self, box_threshold: float = 0.30, short_edge: int | None = 540, device: str = "cuda") -> None:
        """short_edge: model input size (default 540 = `perception.frame_width` 960 at 16:9; the library default 800
        costs ~1.5x the time on this GPU — S1 bench)."""
        import torch
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

        snap = cached_snapshot(REPO)
        src = str(snap) if snap else REPO
        self.device = device if torch.cuda.is_available() else "cpu"
        self.dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.processor = AutoProcessor.from_pretrained(src)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(src, dtype=self.dtype).to(self.device).eval()
        self.box_threshold = box_threshold
        if short_edge is not None:
            self.processor.image_processor.size = {"shortest_edge": short_edge, "longest_edge": 1333}

    def detect(
        self, frames: list[tuple[float, Any]], phrases: list[str], rect: tuple[float, float, float, float]
    ) -> list[Box]:
        """frames: [(t, RGB PIL image)]; returns per-phrase NMS'd boxes for every frame."""
        import torch
        from torchvision.ops import nms

        out: list[Box] = []
        for p0 in range(0, len(phrases), PHRASES_PER_PROMPT):
            group = phrases[p0 : p0 + PHRASES_PER_PROMPT]
            text, spans = prompt_and_spans(group, self.processor.tokenizer)
            for f0 in range(0, len(frames), FRAME_BATCH):
                batch = frames[f0 : f0 + FRAME_BATCH]
                inputs = self.processor(images=[img for _, img in batch], text=[text] * len(batch), return_tensors="pt")
                inputs = {
                    k: (v.to(self.device, self.dtype) if v.is_floating_point() else v.to(self.device))
                    for k, v in inputs.items()
                }
                with torch.inference_mode():
                    res = self.model(**inputs)
                probs = res.logits.float().sigmoid()  # (B, Q, T)
                boxes = res.pred_boxes.float()  # (B, Q, 4) cx, cy, w, h normalized to the frame
                per_phrase = torch.stack(
                    [probs[:, :, s:e].amax(dim=-1) if e > s else probs[:, :, 0] * 0 for s, e in spans], dim=-1
                )
                best_score, best_phrase = per_phrase.max(dim=-1)  # (B, Q)
                for b, (t, _) in enumerate(batch):
                    keep = best_score[b] >= self.box_threshold
                    if not bool(keep.any()):
                        continue
                    sc, ph, bx = best_score[b][keep], best_phrase[b][keep], boxes[b][keep]
                    for pi in ph.unique().tolist():
                        sel = ph == pi
                        xyxy = torch.stack(
                            [
                                bx[sel][:, 0] - bx[sel][:, 2] / 2,
                                bx[sel][:, 1] - bx[sel][:, 3] / 2,
                                bx[sel][:, 0] + bx[sel][:, 2] / 2,
                                bx[sel][:, 1] + bx[sel][:, 3] / 2,
                            ],
                            1,
                        )
                        for k in nms(xyxy, sc[sel], NMS_IOU).tolist():
                            pic = to_picture(tuple(float(v) for v in bx[sel][k].tolist()), rect)  # type: ignore[arg-type]
                            if pic is not None:
                                out.append(Box(t=t, phrase=group[pi], box=pic, score=round(float(sc[sel][k]), 4)))
        return out

    def close(self) -> None:
        import torch

        del self.model
        torch.cuda.empty_cache()


def hazard_window_times(
    hazard_times: list[float], shots: list[tuple[float, float]], base: set[float], fps: float, radius: float = 1.0
) -> list[float]:
    """Extra sample times at `fps` within ±radius of every hazard proposal, inside its shot, not already sampled."""
    step = 1.0 / fps
    extra: set[float] = set()
    for t in hazard_times:
        start, end = next(((s, e) for s, e in shots if s <= t <= e), (t, t))
        k = t - radius
        while k <= t + radius:
            if start <= k < end:
                extra.add(round(round(k / step) * step, 3))
            k += step
    return sorted(x for x in extra if x not in base and all(abs(x - b) > 1e-3 for b in base))
