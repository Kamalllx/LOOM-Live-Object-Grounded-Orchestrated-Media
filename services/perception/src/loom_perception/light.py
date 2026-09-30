"""Lightweight segmenter ("Grounded SAM 2"): Grounding DINO tiny + SAM 2.1 tiny, tracked by box overlap.

For machines where SAM 3.1 (~850M params, custom Triton kernels) is too heavy. Per sampled frame:
1. Grounding DINO finds boxes for all text prompts in one pass,
2. duplicate boxes are suppressed per prompt, and boxes covering most of the frame are dropped,
3. SAM 2.1 draws a mask inside every box,
4. boxes are linked to the previous frame's boxes of the same prompt by IoU, which gives the
   per-chunk object ids that tracks.py stitches and de-duplicates exactly as for SAM 3.1.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np

from .config import SamConfig
from .media import Frame
from .sam import RawDetection, encode_mask
from .tracks import box_iou

log = logging.getLogger(__name__)


def match_prompt(label: str, prompts: list[str]) -> str | None:
    """Grounding DINO returns the matched span of the query ('flask', 'beaker flask'); map it to one prompt."""
    words = set(re.findall(r"[a-z0-9\-]+", label.lower()))
    if not words:
        return None
    best, best_score = None, 0.0
    for p in prompts:
        pw = set(re.findall(r"[a-z0-9\-]+", p.lower()))
        overlap = len(words & pw)
        if not overlap:
            continue
        score = overlap / len(pw) + overlap / len(words)
        if score > best_score:
            best, best_score = p, score
    return best


def _affinity(a: list[float], b: list[float]) -> float:
    """Box IoU, or — for objects that moved too far between samples to overlap — closeness of centres
    for boxes of similar size (a hand moving across the bench is still the same hand)."""
    iou = box_iou(a, b)
    if iou > 0:
        return iou
    ca, cb = (a[0] + a[2] / 2, a[1] + a[3] / 2), (b[0] + b[2] / 2, b[1] + b[3] / 2)
    dist = ((ca[0] - cb[0]) ** 2 + (ca[1] - cb[1]) ** 2) ** 0.5
    size = max(a[2], a[3], b[2], b[3])
    area_a, area_b = a[2] * a[3], b[2] * b[3]
    similar = min(area_a, area_b) / max(area_a, area_b, 1e-9) > 0.4
    return 0.3 * max(0.0, 1 - dist / size) if similar and size > 0 else 0.0


@dataclass
class _Track:
    obj_id: int
    box: list[float]
    t: float


class IouTracker:
    """Links each prompt's boxes frame to frame; a box that overlaps no recent box starts a new object."""

    def __init__(self, max_gap: float, min_iou: float):
        self.max_gap, self.min_iou = max_gap, min_iou
        self.tracks: dict[str, list[_Track]] = {}
        self.next_id = 1

    def assign(self, prompt: str, t: float, boxes: list[list[float]]) -> list[int]:
        live = [tr for tr in self.tracks.setdefault(prompt, []) if t - tr.t <= self.max_gap + 1e-6]
        pairs = sorted(
            ((_affinity(b, tr.box), bi, ti) for bi, b in enumerate(boxes) for ti, tr in enumerate(live)),
            reverse=True,
        )
        ids: list[int | None] = [None] * len(boxes)
        used: set[int] = set()
        for iou, bi, ti in pairs:
            if iou < self.min_iou:
                break
            if ids[bi] is None and ti not in used:
                ids[bi], live[ti].box, live[ti].t = live[ti].obj_id, boxes[bi], t
                used.add(ti)
        for bi, b in enumerate(boxes):
            if ids[bi] is None:
                tr = _Track(self.next_id, b, t)
                self.next_id += 1
                self.tracks[prompt].append(tr)
                ids[bi] = tr.obj_id
        return ids  # type: ignore[return-value]


def _xyxy_to_norm_xywh(b, w: int, h: int) -> list[float]:
    x0, y0, x1, y1 = (float(v) for v in b)
    x0, y0, x1, y1 = max(0.0, x0), max(0.0, y0), min(float(w), x1), min(float(h), y1)
    return [x0 / w, y0 / h, max(0.0, x1 - x0) / w, max(0.0, y1 - y0) / h]


def _mask_box(mask: np.ndarray) -> list[float] | None:
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    h, w = mask.shape
    return [xs.min() / w, ys.min() / h, (xs.max() + 1 - xs.min()) / w, (ys.max() + 1 - ys.min()) / h]


class LightSegmenter:
    def __init__(self, cfg: SamConfig):
        import torch
        from transformers import AutoProcessor, GroundingDinoForObjectDetection, Sam2Model, Sam2Processor

        torch.set_num_threads(int(os.environ.get("LOOM_CPU_THREADS", "4")))
        self.cfg = cfg
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        log.info("loading %s + %s on %s", cfg.detector_model, cfg.mask_model, self.device)
        self.det_proc = AutoProcessor.from_pretrained(cfg.detector_model)
        self.det = GroundingDinoForObjectDetection.from_pretrained(cfg.detector_model).to(self.device).eval()
        self.sam_proc = Sam2Processor.from_pretrained(cfg.mask_model)
        self.sam = Sam2Model.from_pretrained(cfg.mask_model).to(self.device).eval()
        self._clip = None
        self.verifier = None  # set by the pipeline to Gemini.name_objects when verify_labels == "gemini"

    def detect(self, image, prompts: list[str]) -> list[tuple[str, list[float], float]]:
        """Returns (prompt, [x0, y0, x1, y1] in pixels, score) after per-prompt NMS and size filtering."""
        import torch
        from torchvision.ops import nms

        w, h = image.size
        query = " . ".join(p.lower() for p in prompts) + " ."
        inputs = self.det_proc(images=image, text=query, return_tensors="pt").to(self.device)
        with torch.inference_mode():
            outputs = self.det(**inputs)
        res = self.det_proc.post_process_grounded_object_detection(
            outputs,
            inputs.input_ids,
            threshold=self.cfg.box_threshold,
            text_threshold=self.cfg.text_threshold,
            target_sizes=[(h, w)],
        )[0]
        labels = res.get("text_labels", res.get("labels"))
        by_prompt: dict[str, list[tuple[list[float], float]]] = {}
        for box, score, label in zip(res["boxes"].tolist(), res["scores"].tolist(), labels):
            prompt = match_prompt(str(label), prompts)
            if prompt is None:
                continue
            x0, y0, x1, y1 = box
            if (x1 - x0) * (y1 - y0) / (w * h) > self.cfg.max_box_area:
                continue  # "the whole frame" is never the object being taught
            by_prompt.setdefault(prompt, []).append((box, score))
        out = []
        for prompt, items in by_prompt.items():
            boxes = torch.tensor([b for b, _ in items], dtype=torch.float32)
            scores = torch.tensor([s for _, s in items], dtype=torch.float32)
            for i in nms(boxes, scores, 0.5).tolist():
                out.append((prompt, items[i][0], items[i][1]))
        if len(out) > 1:
            # One region, one name: when prompts compete for the same box, the most confident one wins.
            boxes = torch.tensor([b for _, b, _ in out], dtype=torch.float32)
            scores = torch.tensor([s for _, _, s in out], dtype=torch.float32)
            out = [out[i] for i in nms(boxes, scores, self.cfg.cross_prompt_iou).tolist()]
        return out

    def masks(self, image, boxes: list[list[float]]) -> np.ndarray:
        import torch

        inputs = self.sam_proc(images=image, input_boxes=[boxes], return_tensors="pt").to(self.device)
        with torch.inference_mode():
            out = self.sam(**inputs, multimask_output=False)
        masks = self.sam_proc.post_process_masks(out.pred_masks.cpu(), inputs["original_sizes"].cpu())[0]
        return np.asarray(masks[:, 0] > 0)

    def segment_chunk(self, chunk_index: int, frames: list[Frame], prompts: list[str]) -> Iterator[RawDetection]:
        from PIL import Image

        if not frames or not prompts:
            return
        # Tracking is label-agnostic: the same region keeps its id even if the detector's preferred
        # name flickers (a beaker that turns clear briefly reads as "glass"). Each track is then named
        # by a confidence-weighted vote over all of its frames.
        tracker = IouTracker(self.cfg.max_gap_seconds, self.cfg.track_iou)
        chunk_dets: list[RawDetection] = []
        best_view: dict[int, tuple[float, Path, list[float]]] = {}  # local id -> (score, frame, box)
        prev_hist = None
        for f in frames:
            image = Image.open(f.path).convert("RGB")
            w, h = image.size
            hist = colour_histogram(np.asarray(image))
            if prev_hist is not None and is_shot_cut(prev_hist, hist, self.cfg.shot_cut_similarity):
                # Nothing is the same object across a cut, however much the boxes happen to overlap.
                next_id = tracker.next_id
                tracker = IouTracker(self.cfg.max_gap_seconds, self.cfg.track_iou)
                tracker.next_id = next_id
            prev_hist = hist
            dets = self.detect(image, prompts)
            if not dets:
                continue
            masks = self.masks(image, [b for _, b, _ in dets])
            norm = [_xyxy_to_norm_xywh(b, w, h) for _, b, _ in dets]
            ids = tracker.assign("*", f.t, norm)
            for i, (prompt, _, score) in enumerate(dets):
                if score > best_view.get(ids[i], (-1.0,))[0]:
                    best_view[ids[i]] = (score, Path(f.path), norm[i])
                mask = masks[i]
                chunk_dets.append(
                    RawDetection(
                        chunk=chunk_index,
                        prompt=prompt,
                        local_id=ids[i],
                        t=f.t,
                        box=_mask_box(mask) or norm[i],
                        score=float(score),
                        rle=encode_mask(mask) if self.cfg.save_masks and mask.any() else None,
                    )
                )
        verified = None
        if best_view and self.cfg.verify_labels != "off":
            try:
                verified = self.verify(best_view, prompts)
            except Exception as e:
                log.warning("label verification failed (%s); using the detector's vote", e)
        yield from vote_labels(chunk_dets, verified, self.cfg.verify_weight)

    def _crops(self, best_view: dict[int, tuple[float, Path, list[float]]]):
        from PIL import Image

        ids, crops = [], []
        for lid, (_, path, (x, y, w, h)) in best_view.items():
            img = Image.open(path).convert("RGB")
            W, H = img.size
            pad = 0.1
            box = (max(0, (x - pad * w) * W), max(0, (y - pad * h) * H), min(W, (x + w + pad * w) * W), min(H, (y + h + pad * h) * H))
            if box[2] - box[0] < 8 or box[3] - box[1] < 8:
                continue
            ids.append(lid)
            crops.append(img.crop(box))
        return ids, crops

    def verify(self, best_view: dict[int, tuple[float, Path, list[float]]], prompts: list[str]) -> dict[int, dict[str, float]]:
        """An independent judgement of each track's name from its clearest crop.

        gemini: a vision LLM picks the name (or 'none') — reliable on fine-grained things like glassware.
        clip:   local CLIP ViT-B/32 zero-shot scores; no network, but weak on fine-grained categories.
        """
        ids, crops = self._crops(best_view)
        if not crops:
            return {}
        if self.cfg.verify_labels == "gemini":
            if self.verifier is None:
                return {}
            names = self.verifier(crops, prompts)
            return {lid: ({name: 1.0, OTHER: 0.0} if name else {OTHER: 1.0, **{p: 0.0 for p in prompts}}) for lid, name in zip(ids, names)}
        return self._clip_scores(ids, crops, prompts)

    def _clip_scores(self, ids: list[int], crops: list, prompts: list[str]) -> dict[int, dict[str, float]]:
        import torch

        if self._clip is None:
            from transformers import CLIPModel, CLIPProcessor

            self._clip_proc = CLIPProcessor.from_pretrained(self.cfg.verify_model)
            self._clip = CLIPModel.from_pretrained(self.cfg.verify_model).to(self.device).eval()
        texts = [f"a photo of {p}" for p in prompts] + [f"a photo of {n}" for n in NONE_OF_THESE]
        inputs = self._clip_proc(text=texts, images=crops, return_tensors="pt", padding=True).to(self.device)
        with torch.inference_mode():
            probs = self._clip(**inputs).logits_per_image.softmax(dim=-1).cpu().numpy()
        out = {}
        for lid, row in zip(ids, probs):
            scores = dict(zip(prompts, map(float, row[: len(prompts)])))
            scores[OTHER] = float(row[len(prompts) :].max())  # the single best alternative, not their sum
            out[lid] = scores
        return out


def colour_histogram(rgb: np.ndarray) -> np.ndarray:
    import cv2

    hsv = cv2.cvtColor(cv2.resize(rgb, (160, 90)), cv2.COLOR_RGB2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, [8, 8, 8], [0, 180, 0, 256, 0, 256])
    return cv2.normalize(hist, hist).flatten()


def is_shot_cut(a: np.ndarray, b: np.ndarray, min_similarity: float) -> bool:
    import cv2

    return cv2.compareHist(a.astype(np.float32), b.astype(np.float32), cv2.HISTCMP_CORREL) < min_similarity


OTHER = "__other__"
# Generic alternatives CLIP can pick instead of any prompt. An open-vocabulary detector always grounds
# every phrase somewhere; these let the verifier say "that box is none of the things we asked for".
NONE_OF_THESE = ["something else", "a person's hand", "a table surface", "a wall"]


def vote_labels(
    dets: list[RawDetection],
    verified: dict[int, dict[str, float]] | None = None,
    verify_weight: float = 0.7,
) -> list[RawDetection]:
    """Names each track: the detector's confidence-weighted vote across its frames, optionally blended
    with an independent per-track judgement (CLIP probabilities over the prompts plus OTHER).
    Tracks where CLIP prefers a generic alternative over every prompt are dropped."""
    votes: dict[int, dict[str, float]] = {}
    for d in dets:
        votes.setdefault(d.local_id, {}).setdefault(d.prompt, 0.0)
        votes[d.local_id][d.prompt] += d.score
    winner: dict[int, str | None] = {}
    for lid, v in votes.items():
        total = sum(v.values()) or 1.0
        share = {p: s / total for p, s in v.items()}
        clip = dict((verified or {}).get(lid) or {})
        other = clip.pop(OTHER, 0.0)
        if clip and other > max(clip.values()):
            winner[lid] = None
            continue
        if clip:
            score = {p: (1 - verify_weight) * share.get(p, 0.0) + verify_weight * clip.get(p, 0.0) for p in set(share) | set(clip)}
        else:
            score = share
        winner[lid] = max(score, key=score.get)
    kept = []
    for d in dets:
        name = winner[d.local_id]
        if name is not None:
            d.prompt = name
            kept.append(d)
    return kept
