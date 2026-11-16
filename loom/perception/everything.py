"""Segment everything (animations, slides, illustrated lessons): every visual element becomes a tracked, exact mask.

Board writing is found by `board.py` (ink on a flat surface). Animated and illustrated lessons carry their meaning in
*drawn things* (a chip, a fan, a cell organelle, an arrow, a formula box) that no phrase list names in advance. This
stage asks SAM 2.1 to segment the whole picture with a grid of point prompts (automatic mask generation), on sampled
frames that look *graphic* (flat colour regions, not camera footage):

  1. one image embedding per frame; a GRID x GRID point grid is decoded in batches, 3 candidate masks per point;
  2. candidates are filtered on the 256 px logits (predicted IoU, stability) before anything is upsampled, then
     de-duplicated by box NMS and mask IoU; the background (huge, touching the frame edges) and specks are dropped;
     words on one line join into one text element and stray single letters go (`tidy_text`);
  3. masks are linked through time by mask IoU (box IoU + area ratio when an element moves or grows), so every element
     keeps one id; an element must be seen on >= 2 samples to count;
  4. per element: a mask + box per sample (COCO RLE at MASK_W, the same picture-relative width as the other tiers) and
     the clearest crop, outlined, for the VLM to name (`prompts/scene_element.md`).

Pure functions are unit-tested; the GPU part runs in the torch phase of ingest (no Ollama model resident).
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from loom.core.weights import cached_snapshot

REPO = "facebook/sam2.1-hiera-base-plus"
GRID = 24  # 576 point prompts per frame (32 x 32 found 2-3 more elements a frame at twice the time)
POINT_BATCH = 96
PRED_IOU = 0.82
STABILITY = 0.90
NMS_IOU = 0.6
DUP_IOU = 0.75  # two masks this similar are the same element
WORK_W = 480  # masks are judged and tracked at this width (= MASK_W)
MIN_AREA = 0.0012  # share of the picture
MAX_AREA = 0.30
BACKGROUND_AREA = 0.12  # a mask this large touching >= 2 frame edges is background, not an element
LINK_IOU = 0.45
LINK_BOX_IOU = 0.5
GAP_SAMPLES = 2  # an element unseen for more than this many samples has gone
MIN_SAMPLES = 2
MAX_ELEMENTS = 60
GRAPHIC = 0.90  # graphic_score at or above this: drawn content, segment everything


# ---------------------------------------------------------------- pure helpers (unit-tested)


def graphic_score(bgr: np.ndarray) -> float:
    """Share of the calmest half of the picture that is *exactly* flat. Drawn content (animation, slide, digital
    board) is flat to the last bit there (0.94-0.98 on the eval lessons); camera footage keeps sensor grain and
    compression noise even on a white wall (0.62-0.80)."""
    import cv2

    g = cv2.cvtColor(cv2.resize(bgr, (640, 360), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.float32)
    smooth = cv2.GaussianBlur(g, (5, 5), 0)
    res = np.abs(g - smooth)
    grad = cv2.GaussianBlur(np.abs(cv2.Laplacian(smooth, cv2.CV_32F)), (9, 9), 0)
    calm = grad <= np.percentile(grad, 50)
    return float((res[calm] < 0.5).mean()) if calm.any() else 1.0


def grid_points(w: int, h: int, n: int = GRID) -> np.ndarray:
    """n x n point prompts at cell centres, in pixel coordinates (x, y)."""
    xs = (np.arange(n) + 0.5) / n * w
    ys = (np.arange(n) + 0.5) / n * h
    return np.stack(np.meshgrid(xs, ys), -1).reshape(-1, 2).astype(np.float32)


def stability(logits: np.ndarray, offset: float = 1.0) -> np.ndarray:
    """SAM's stability score: area(logit > +offset) / area(logit > -offset), per mask ([N, H, W] -> [N])."""
    hi = (logits > offset).reshape(len(logits), -1).sum(1)
    lo = (logits > -offset).reshape(len(logits), -1).sum(1)
    return hi / np.maximum(lo, 1)


def mask_box(m: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(m)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def box_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    iw = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    ih = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = iw * ih
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u else 0.0


def mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    u = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / u) if u else 0.0


def is_element(m: np.ndarray) -> bool:
    """Keep masks that can be an element: not a speck, not the background or a whole panel."""
    h, w = m.shape
    area = m.mean()
    if area < MIN_AREA or area > MAX_AREA:
        return False
    box = mask_box(m)
    if box is None:
        return False
    edges = (box[0] <= 1) + (box[1] <= 1) + (box[2] >= w - 1) + (box[3] >= h - 1)
    return not (edges >= 2 and area > BACKGROUND_AREA)


def dedupe(masks: list[np.ndarray], scores: list[float]) -> list[int]:
    """Indices of masks to keep, best score first; a mask too similar to a kept one is a duplicate."""
    keep: list[int] = []
    for i in sorted(range(len(masks)), key=lambda i: -scores[i]):
        if all(mask_iou(masks[i], masks[k]) < DUP_IOU for k in keep):
            keep.append(i)
    return keep


TEXT_EDGE = 120.0  # mean |Laplacian| inside a mask at or above this: letters (drawn parts measured <= 108)
GLYPH_PX = 18  # a mask smaller than this both ways (at WORK_W) inside a larger element is a single letter


def is_text(m: np.ndarray, edges: np.ndarray) -> bool:
    """Words have sharp glyph edges everywhere inside them; a drawn part (a chip, a cell) is mostly smooth fill."""
    import cv2

    inner = cv2.erode(m.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    return bool(inner.any()) and float(edges[inner].mean()) >= TEXT_EDGE


def tidy_text(masks: list[np.ndarray], scores: list[float], grey: np.ndarray) -> tuple[list[np.ndarray], list[float]]:
    """SAM segments animated text word by word, and sometimes letter by letter. Words on one line (centres within half
    a line height, similar heights, gap under 1.2 line heights) become one line element; letter-sized masks inside a
    larger element are dropped. Drawn parts (smooth fill) are never merged, so a row of capacitors stays three."""
    import cv2

    edges = np.abs(cv2.Laplacian(grey.astype(np.float32), cv2.CV_32F))
    boxes = [mask_box(m) for m in masks]
    keep = []
    for i, bx in enumerate(boxes):
        assert bx is not None
        small = bx[2] - bx[0] < GLYPH_PX and bx[3] - bx[1] < GLYPH_PX
        area = (bx[2] - bx[0]) * (bx[3] - bx[1])
        inside = small and any(j != i and o is not None and o[0] <= bx[0] and o[1] <= bx[1] and o[2] >= bx[2]
                               and o[3] >= bx[3] and (o[2] - o[0]) * (o[3] - o[1]) > 4 * area
                               for j, o in enumerate(boxes))
        if not inside:
            keep.append(i)
    words = [i for i in keep if is_text(masks[i], edges)]
    parent = {i: i for i in words}

    def root(i: int) -> int:
        while parent[i] != i:
            i = parent[i]
        return i

    for a in words:
        for b in words:
            if a >= b:
                continue
            ba, bb = boxes[a], boxes[b]
            assert ba is not None
            assert bb is not None
            ha, hb = ba[3] - ba[1], bb[3] - bb[1]
            same_line = abs((ba[1] + ba[3]) - (bb[1] + bb[3])) / 2 < 0.5 * max(ha, hb) and 0.6 <= ha / max(1, hb) <= 1.7
            gap = max(bb[0] - ba[2], ba[0] - bb[2])
            if same_line and gap < 1.2 * max(ha, hb):
                parent[root(a)] = root(b)
    groups: dict[int, list[int]] = {}
    for i in words:
        groups.setdefault(root(i), []).append(i)
    out_m: list[np.ndarray] = []
    out_s: list[float] = []
    merged = {i for g in groups.values() if len(g) > 1 for i in g}
    for g in groups.values():
        if len(g) > 1:
            out_m.append(np.logical_or.reduce([masks[i] for i in g]))
            out_s.append(max(scores[i] for i in g))
    for i in keep:
        if i not in merged:
            out_m.append(masks[i])
            out_s.append(scores[i])
    k = dedupe(out_m, out_s)
    return [out_m[i] for i in k], [out_s[i] for i in k]


@dataclass
class Element:
    track_id: int
    shot: int
    samples: list[tuple[float, np.ndarray, tuple[int, int, int, int], float]] = field(default_factory=list)
    best: tuple[float, float] = (-1.0, 0.0)  # (quality, t) of the clearest sample
    crop: Any = None
    last_k: int = 0
    parts: list[Any] = field(default_factory=list)  # [(RLE, normalized box)] at the clearest sample
    parts_crop: Any = None  # numbered set-of-marks picture of the parts

    @property
    def first_t(self) -> float:
        return self.samples[0][0]

    @property
    def last_t(self) -> float:
        return self.samples[-1][0]


def link(elements: list[Element], frame_masks: list[tuple[np.ndarray, float]], t: float, k: int, shot: int,
         next_id: int) -> tuple[list[tuple[Element, np.ndarray, float]], int]:
    """Greedy linking of this sample's masks to live elements of the same shot (mask IoU, else box IoU with a similar
    area: an element that slides or grows keeps its id). Returns (pairs, next free id); new elements are appended."""
    live = [e for e in elements if e.shot == shot and k - e.last_k <= GAP_SAMPLES]
    cands = []
    for mi, (m, _) in enumerate(frame_masks):
        mb = mask_box(m)
        area = m.sum()
        for e in live:
            pm, pb = e.samples[-1][1], e.samples[-1][2]
            if mb is None or box_iou(mb, pb) == 0.0:
                continue  # boxes apart: no overlap to measure
            s = mask_iou(m, pm)
            if s < LINK_IOU and mb is not None:
                ratio = area / max(1, pm.sum())
                s = box_iou(mb, pb) * 0.9 if 0.6 <= ratio <= 1.6 and box_iou(mb, pb) >= LINK_BOX_IOU else 0.0
            if s >= min(LINK_IOU, LINK_BOX_IOU * 0.9):
                cands.append((s, mi, e))
    used_m: set[int] = set()
    used_e: set[int] = set()
    pairs: list[tuple[Element, np.ndarray, float]] = []
    for _, mi, e in sorted(cands, key=lambda c: -c[0]):
        if mi in used_m or id(e) in used_e:
            continue
        used_m.add(mi)
        used_e.add(id(e))
        pairs.append((e, frame_masks[mi][0], frame_masks[mi][1]))
    for mi, (m, sc) in enumerate(frame_masks):
        if mi not in used_m:
            e = Element(track_id=next_id, shot=shot)
            next_id += 1
            elements.append(e)
            pairs.append((e, m, sc))
    for e, m, _ in pairs:
        box = mask_box(m)
        assert box is not None
        e.samples.append((t, m, box, float(m.mean())))
        e.last_k = k
    return pairs, next_id


def outlined_crop(img: np.ndarray, m: np.ndarray, box: tuple[int, int, int, int], pad_ratio: float = 0.25,
                  min_pad: int = 12, grow: int = 0) -> np.ndarray:
    """The element with some context, its outline drawn, the rest of the picture dimmed: the VLM names *this* thing.
    `grow` closes thin ink (a line of handwriting) into one region first, so the outline wraps the element, not each
    stroke."""
    import cv2

    h, w = img.shape[:2]
    x0, y0, x1, y1 = box
    pad = max(min_pad, round(pad_ratio * max(x1 - x0, y1 - y0)))
    X0, Y0, X1, Y1 = max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)
    out = img[Y0:Y1, X0:X1].copy()
    mm = m[Y0:Y1, X0:X1].astype(np.uint8)
    if grow:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1,) * 2)
        mm = np.asarray(cv2.morphologyEx(mm, cv2.MORPH_CLOSE, kernel), np.uint8)
    out[mm == 0] = (out[mm == 0] * 0.45).astype(np.uint8)
    cnts, _ = cv2.findContours(mm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(out, cnts, -1, (0, 200, 255), 2)
    return out


PART_COLOURS = [(80, 200, 255), (120, 255, 140), (255, 160, 90), (255, 110, 220), (90, 140, 255), (60, 235, 235),
                (255, 230, 90), (190, 130, 255), (140, 255, 220), (255, 120, 120)]
MAX_PARTS = 10


def pick_parts(element: np.ndarray, cands: list[np.ndarray]) -> list[np.ndarray]:
    """Candidate masks -> the element's parts: inside it (>= 85 %), not the whole of it (<= 70 %), not a speck
    (>= 1.5 % of it), not a near-copy of a bigger part; the largest MAX_PARTS. Fewer than two parts is no split."""
    area = max(1, int(element.sum()))
    keep: list[np.ndarray] = []
    for m in sorted(cands, key=lambda m: -int(m.sum())):
        a = int(m.sum())
        if a < 0.015 * area or a > 0.7 * area or (m & element).sum() < 0.85 * a:
            continue
        if any(mask_iou(m, k) > 0.6 for k in keep):
            continue
        keep.append(m)
        if len(keep) == MAX_PARTS:
            break
    return keep if len(keep) >= 2 else []


def marked_parts(img: np.ndarray, element: np.ndarray, parts: list[np.ndarray],
                 box: tuple[int, int, int, int]) -> np.ndarray:
    """Set-of-marks picture for naming parts in one VLM call: the element with context, each part outlined in its own
    colour with its number on a dark tag, the rest dimmed. Upscaled so numbers stay legible."""
    import cv2

    h, w = img.shape[:2]
    x0, y0, x1, y1 = box
    pad = max(24, round(0.25 * max(x1 - x0, y1 - y0)))
    X0, Y0, X1, Y1 = max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)
    out = img[Y0:Y1, X0:X1].copy()
    near = cv2.dilate(element[Y0:Y1, X0:X1].astype(np.uint8), np.ones((15, 15), np.uint8)) > 0
    out[~near] = (out[~near] * 0.4).astype(np.uint8)
    scale = max(1.0, 640 / max(1, out.shape[1]))
    if scale > 1:
        out = cv2.resize(out, (round(out.shape[1] * scale), round(out.shape[0] * scale)), interpolation=cv2.INTER_CUBIC)
    for n, m in enumerate(parts):
        mm: np.ndarray = m[Y0:Y1, X0:X1].astype(np.uint8)
        if scale > 1:
            mm = np.asarray(cv2.resize(mm, (out.shape[1], out.shape[0]), interpolation=cv2.INTER_NEAREST))
        mm = np.asarray(cv2.morphologyEx(mm, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)))
        col = PART_COLOURS[n % len(PART_COLOURS)]
        cnts, _ = cv2.findContours(mm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(out, cnts, -1, col, 2)
        ys, xs = np.nonzero(mm)
        if len(xs):
            # the number sits just outside the part's top-left corner: it must not hide what the part shows
            label = str(n + 1)
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            cx = max(tw // 2 + 6, int(xs.min()) - tw // 2 - 4)
            cy = max(th // 2 + 7, int(ys.min()) - th // 2 - 4)
            p0, p1 = (cx - tw // 2 - 5, cy - th // 2 - 6), (cx + tw // 2 + 5, cy + th // 2 + 6)
            cv2.rectangle(out, p0, p1, (20, 20, 20), -1)
            cv2.rectangle(out, p0, p1, col, 2)
            cv2.putText(out, label, (cx - tw // 2, cy + th // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2,
                        cv2.LINE_AA)
    return out


def parts_payload(parts: list[np.ndarray]) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Part masks (picture-sized, WORK_W) -> [(RLE, normalized box)]."""
    from loom.perception.segment import encode_rle

    out = []
    for m in parts:
        b = mask_box(m)
        if b is None:
            continue
        mh, mw = m.shape
        out.append((encode_rle(m), (round(b[0] / mw, 4), round(b[1] / mh, 4), round((b[2] - b[0]) / mw, 4),
                                    round((b[3] - b[1]) / mh, 4))))
    return out


# ---------------------------------------------------------------- SAM 2.1 automatic masks (GPU)


class EverythingSegmenter:
    def __init__(self, repo: str = REPO, device: str = "cuda") -> None:
        import torch
        from transformers import Sam2Model, Sam2Processor

        snap = cached_snapshot(repo)
        src = str(snap) if snap else repo
        self.device = device if torch.cuda.is_available() else "cpu"
        self.dtype = torch.bfloat16 if self.device == "cuda" else torch.float32
        self.processor = Sam2Processor.from_pretrained(src)
        model: Any = Sam2Model.from_pretrained(src, dtype=self.dtype)
        self.model = model.to(self.device).eval()

    def segment(self, rgb: np.ndarray, grid: int = GRID, pred_iou: float = PRED_IOU,
                stability: float = STABILITY) -> list[tuple[np.ndarray, float]]:
        """RGB picture -> [(bool mask at WORK_W, score)], de-duplicated elements only. Candidates are filtered, boxed,
        NMS'd and de-duplicated on the GPU; only the survivors are copied back."""
        import torch
        import torch.nn.functional as F
        from torchvision.ops import nms

        h, w = rgb.shape[:2]
        mh = max(2, round(h * WORK_W / w))
        inputs = self.processor(images=rgb, return_tensors="pt").to(self.device)
        sx, sy = 1024 / w, 1024 / h  # SAM 2 resizes the picture to 1024 x 1024
        pts = torch.tensor(grid_points(w, h, grid) * np.array([sx, sy], np.float32), device=self.device)
        keep_m: list[torch.Tensor] = []
        keep_s: list[torch.Tensor] = []
        with torch.inference_mode():
            emb = self.model.get_image_embeddings(inputs["pixel_values"].to(self.dtype))
            for p0 in range(0, len(pts), POINT_BATCH):
                batch = pts[p0:p0 + POINT_BATCH]
                out = self.model(image_embeddings=emb, input_points=batch[None, :, None, :],
                                 input_labels=torch.ones((1, len(batch), 1), dtype=torch.long, device=self.device),
                                 multimask_output=True)
                lg = out.pred_masks[0].float().flatten(0, 1)  # [P*3, 256, 256]
                io = out.iou_scores[0].float().flatten()
                hi = (lg > 1).flatten(1).sum(1).float()
                stab = hi / (lg > -1).flatten(1).sum(1).float().clamp(min=1)
                ok = (io >= pred_iou) & (stab >= stability)
                if bool(ok.any()):
                    up = F.interpolate(lg[ok][:, None], size=(mh, WORK_W), mode="bilinear", align_corners=False)
                    keep_m.append(up[:, 0] > 0)
                    keep_s.append(io[ok] * stab[ok])
            if not keep_m:
                return []
            m = torch.cat(keep_m)
            sc = torch.cat(keep_s)
            area = m.flatten(1).float().mean(1)
            rows, cols = m.any(2), m.any(1)
            ar_h, ar_w = torch.arange(mh, device=m.device), torch.arange(WORK_W, device=m.device)
            y0 = torch.where(rows, ar_h, mh).amin(1)
            y1 = torch.where(rows, ar_h, -1).amax(1) + 1
            x0 = torch.where(cols, ar_w, WORK_W).amin(1)
            x1 = torch.where(cols, ar_w, -1).amax(1) + 1
            edges = (x0 <= 1).int() + (y0 <= 1).int() + (x1 >= WORK_W - 1).int() + (y1 >= mh - 1).int()
            good = (area >= MIN_AREA) & (area <= MAX_AREA) & ~((edges >= 2) & (area > BACKGROUND_AREA))
            if not bool(good.any()):
                return []
            m, sc = m[good], sc[good]
            boxes = torch.stack([x0, y0, x1, y1], 1)[good].float()
            k = nms(boxes, sc, NMS_IOU)
            m, sc = m[k], sc[k]  # sorted by score
            flat = m.flatten(1).half()
            inter = flat @ flat.T
            areas = flat.sum(1)
            iou = inter / (areas[:, None] + areas[None, :] - inter).clamp(min=1)
            keep: list[int] = []
            iou_c = iou.float().cpu().numpy()
            for i in range(len(m)):
                if all(iou_c[i, j] < DUP_IOU for j in keep):
                    keep.append(i)
            kept = m[keep].cpu().numpy()
            sc_l = sc[keep].float().cpu().tolist()
        import cv2

        kernel = np.ones((3, 3), np.uint8)
        grey = cv2.resize(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), (WORK_W, mh), interpolation=cv2.INTER_AREA)
        tm, ts = tidy_text(list(kept), sc_l, grey)
        return [(cv2.morphologyEx(x.astype(np.uint8), cv2.MORPH_CLOSE, kernel) > 0, float(v))
                for x, v in zip(tm, ts, strict=True)]

    def peak_vram_gb(self) -> float:
        import torch

        return round(torch.cuda.max_memory_allocated() / 1e9, 2) if torch.cuda.is_available() else 0.0

    def close(self) -> None:
        import torch

        del self.model
        torch.cuda.empty_cache()


@dataclass
class EverythingScan:
    elements: list[Element]
    graphic_ratio: float  # share of sampled frames that looked graphic (animation, slide, board)
    samples: int
    picture_hw: tuple[int, int]
    seconds: float = 0.0


def scan_interval(duration: float) -> float:
    """Seconds between segmented samples: dense for short clips, sparser for long lessons (0.6 s of GPU per sample)."""
    return 1.0 if duration <= 240 else 2.0 if duration <= 600 else 3.0


def _duplicate(box: tuple[float, float, float, float], others: list[tuple[float, float, float, float]]) -> bool:
    """Is `box` (normalized x, y, w, h) essentially one of `others` (box IoU >= 0.5)? Nested elements are kept: on a
    slide the ink scanner reports a whole table as one block, and its rows, arrows and labels must stay hoverable."""
    x, y, w, h = box
    for ox, oy, ow, oh in others:
        iw = max(0.0, min(x + w, ox + ow) - max(x, ox))
        ih = max(0.0, min(y + h, oy + oh) - max(y, oy))
        inter = iw * ih
        if inter >= 0.5 * (w * h + ow * oh - inter):
            return True
    return False


def to_tracks(scan: EverythingScan, board_tracks: list[Any]) -> list[Any]:
    """Segment-everything elements -> `board.ElementTrack`s (RLE masks, picture-normalized boxes) for the shared
    reader. An element that duplicates a board-ink element on screen at the same time is dropped: the ink grouping
    reads handwriting and text lines better than a grid of point prompts."""
    from loom.perception.board import ElementTrack
    from loom.perception.segment import encode_rle

    out = []
    for e in scan.elements:
        samples = []
        covered = 0
        for t, m, (x0, y0, x1, y1), _ in e.samples:
            mh, mw = m.shape
            box = (round(x0 / mw, 4), round(y0 / mh, 4), round((x1 - x0) / mw, 4), round((y1 - y0) / mh, 4))
            ink = [s[2] for b in board_tracks if b.first_t - 1 <= t <= b.last_t + 1
                   for s in [min(b.samples, key=lambda s: abs(s[0] - t))]]
            covered += _duplicate(box, ink)
            samples.append((round(t, 2), encode_rle(m), box))
        if covered > len(samples) / 2:
            continue
        out.append(ElementTrack(track_id=e.track_id, box=(0, 0, 0, 0), first_t=e.first_t, last_t=e.last_t, epoch=0,
                                samples=samples, best_ink=int(1e6 * e.best[0]), best_t=e.best[1], crop=e.crop,
                                parts=e.parts, parts_crop=e.parts_crop))
    return out


PART_MIN_PX = 64  # a board element smaller than this (analysis px, either side) is not split into parts
PART_GRID, PART_PRED_IOU, PART_STABILITY = 32, 0.7, 0.85


def board_parts(seg: EverythingSegmenter, tracks: list[Any]) -> int:
    """Split drawn board elements into parts with SAM on their presenter-free picture (petals, the flower centre, an
    arrow, the sun): the part masks inside the element become `parts`, numbered on `parts_crop` for naming.
    Ink strokes alone cannot do this: a line drawing is one connected stroke. Returns how many were split."""
    import cv2

    from loom.perception.board import MASK_W

    n = 0
    for tr in tracks:
        if tr.clean is None or tr.clean_mask is None:
            continue
        h, w = tr.clean.shape[:2]
        el = tr.clean_mask.astype(bool)
        box = mask_box(el)
        if box is None or box[2] - box[0] < PART_MIN_PX or box[3] - box[1] < PART_MIN_PX:
            continue
        x0, y0, x1, y1 = box
        pad = 12
        X0, Y0, X1, Y1 = max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)
        crop = cv2.cvtColor(tr.clean[Y0:Y1, X0:X1], cv2.COLOR_BGR2RGB)
        unseen = tr.clean.sum(axis=2) == 0  # board the scanner never saw (where the teacher stood): no parts there
        cands = []
        # one element, so a denser grid and looser thresholds than the whole-frame scan: chalk lines on a dark board
        # give SAM lower-confidence masks than the flat shapes of an animation
        for m, _ in seg.segment(crop, grid=PART_GRID, pred_iou=PART_PRED_IOU, stability=PART_STABILITY):
            full = np.zeros((h, w), bool)
            full[Y0:Y1, X0:X1] = cv2.resize(m.astype(np.uint8), (X1 - X0, Y1 - Y0), interpolation=cv2.INTER_NEAREST) > 0
            if (full & unseen).sum() <= 0.2 * max(1, int(full.sum())):
                cands.append(full)
        # the element's *region*, not its strokes: a part such as the sun's disc lies inside the chalk outline
        close_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31))
        region = np.asarray(cv2.morphologyEx(el.astype(np.uint8), cv2.MORPH_CLOSE, close_k), np.uint8)
        cnts, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(region, cnts, -1, 1, cv2.FILLED)
        hsv = cv2.cvtColor(tr.clean, cv2.COLOR_BGR2HSV)
        skin = (hsv[..., 0] <= 25) & (hsv[..., 1] >= 70) & (hsv[..., 2] >= 60)  # a hand left in the board memory
        cands = [m for m in cands if (m & skin).sum() < 0.3 * max(1, int(m.sum()))]
        parts = pick_parts(region > 0, cands)
        if not parts:
            continue
        mh = max(1, round(h * MASK_W / w))
        tr.parts = parts_payload([cv2.resize(m.astype(np.uint8), (MASK_W, mh), interpolation=cv2.INTER_NEAREST) > 0
                                  for m in parts])
        tr.parts_crop = marked_parts(tr.clean, el, parts, box)
        n += 1
    return n


def scan_everything(frames: Any, shot_starts: list[float], seg: EverythingSegmenter | None = None,
                    on_preview: Any = None) -> EverythingScan:
    """`frames` yields (t, BGR picture). Graphic frames are segmented and linked; camera footage is skipped (the
    detector + SAM 2.1 tier handles real objects there)."""
    import time

    import cv2

    t_start = time.perf_counter()
    own = seg is None
    seg = seg or EverythingSegmenter()
    elements: list[Element] = []
    cuts = sorted(shot_starts)
    shot = k = graphic = total = 0
    next_id = 0
    hw = (0, 0)
    last_preview = -1e9
    try:
        for t, bgr in frames:
            total += 1
            while shot < len(cuts) and cuts[shot] <= t:
                shot += 1
            if graphic_score(bgr) < GRAPHIC:
                continue
            graphic += 1
            k += 1
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            found = seg.segment(rgb)
            h, w = bgr.shape[:2]
            hw = (h, w)
            pairs, next_id = link(elements, found, t, k, shot, next_id)
            small = cv2.resize(bgr, (WORK_W, found[0][0].shape[0]), interpolation=cv2.INTER_AREA) if found else None
            for e, m, sc in pairs:
                q = sc * (m.mean() ** 0.25)  # confident and not tiny
                if q > e.best[0] and small is not None:
                    e.best = (q, t)
                    e.crop = outlined_crop(small, m, e.samples[-1][2])
                    # its parts: the smaller masks of this frame inside it (a chip on a board, a row of a table)
                    parts = pick_parts(m, [o for o, _ in found if o is not m])
                    e.parts = parts_payload(parts)
                    e.parts_crop = marked_parts(small, m, parts, e.samples[-1][2]) if parts else None
            if on_preview is not None and t - last_preview >= 20 and found:
                last_preview = t
                with contextlib.suppress(Exception):  # a preview never stops the scan
                    on_preview(t, bgr, [m for m, _ in found])
    finally:
        if own:
            seg.close()
    kept = [e for e in elements if len(e.samples) >= MIN_SAMPLES and e.crop is not None]
    kept.sort(key=lambda e: e.best[0] * len(e.samples) ** 0.5, reverse=True)
    return EverythingScan(elements=kept[:MAX_ELEMENTS], graphic_ratio=graphic / max(1, total), samples=total,
                          picture_hw=hw, seconds=round(time.perf_counter() - t_start, 1))
