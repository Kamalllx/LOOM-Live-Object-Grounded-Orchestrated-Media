"""Board & animation understanding: written text, equations and drawn diagrams become clickable objects.

Lab footage is understood through *things* (Grounding DINO + SAM). Blackboard, whiteboard, slide and animated lessons
carry their meaning in *marks*: lines of writing, formulas, grids, trees, arrows. This stage finds those marks.

Per sampled frame (picture area, ANALYSIS_W px wide):
  1. local background = per-channel median blur much wider than a stroke; ink = |frame - background| > INK_T.
     Solid regions (a presenter, an illustration) survive the blur, so they are background, not ink.
  2. board colour = dominant background colour; pixels whose background is far from it are *occluders* (presenter,
     illustration); they are dilated and never update the board.
  3. **board memory**: a pixel's ink state only changes where it is visible, and only after two agreeing samples.
     Writing accumulates, erasing clears it, and a presenter standing in front of the board changes nothing.
  4. memory → grouped strokes (anisotropic dilation joins letters into lines and lines into blocks) → elements.
  5. elements are tracked through time by overlap (they grow while being written) and become instances with an
     ink-shaped mask per sample (only when the shape changes, plus a keep-alive), and a presenter-free crop taken
     from the colour memory for the VLM to read.
Memory resets at shot cuts, when the board colour changes, or when most of the board changes at once (a new slide).
Pure OpenCV/numpy: no GPU, so it never competes with Ollama for VRAM.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

ANALYSIS_W = 640
MASK_W = 480  # same picture-relative mask width as the SAM 2.1 tier
INK_T = 42  # min |pixel - local background| (0-255) to count as ink
BOARD_T = 38  # max |background - board colour| to count as board
BOARD_MIN = 0.2  # a frame is board-like when at least this fraction of it is board (a phone filming a board: ~0.3)
BOARD_AREA = 0.08  # a background colour must cover this share of the picture to be a board candidate
BOARD_PART = 0.25  # a board-coloured patch smaller than this share of the largest one is not board
BRIDGE_PX = 25  # board-coloured strips thinner than this (analysis px) do not join a patch to the board
OCCLUDER_PAD = 15  # px (analysis width) around a presenter / illustration that never updates the board
DRAWN_MAX = 0.08  # an enclosed solid larger than this share of the picture is not a drawing
DRAWN_MAX_SAT = 70  # ...nor is a saturated one (skin, clothing)
JITTER_PX = 2  # strokes this close in two samples are the same stroke (handheld shake after alignment)
RESET_CHANGE = 0.6  # a sample that changes this fraction of remembered ink starts a new board (slide change)
MIN_INK_PX = 70
MIN_AREA = 0.002  # element bbox area / picture area
MAX_AREA = 0.6
WAVE_PX = 21  # a hand-drawn line may wander this far (analysis px) across its direction
LINE_LEN = 0.3  # a stroke at least this share of the picture's short side, straight or wavy, is a line element
SPLIT_AREA = 0.14  # a block bigger than this share of the picture is re-split more finely
MATCH_MIN = 0.3  # _match score below which a group starts a new element
GAP_S = 6.0  # an element that is gone for longer than this has been erased
MIN_LIFE_S = 2.0
KEEPALIVE_S = 10.0
MIN_SAMPLE_GAP_S = 2.0
MAX_ELEMENTS = 60
OVERLAY_T = 40  # max colour change of a burned-in overlay pixel between samples (compression flicker)
OVERLAY_STEADY = 0.9  # share of samples an overlay pixel keeps its first colour
OVERLAY_MIN_N = 6  # samples needed before anything is called an overlay
OVERLAY_DROP = 0.6  # a board track whose mask lies this much inside the overlay is a piece of it


@dataclass
class ElementTrack:
    track_id: int
    box: tuple[int, int, int, int]  # x, y, w, h at analysis resolution
    first_t: float
    last_t: float
    epoch: int  # board-memory epoch (resets split elements)
    samples: list[tuple[float, str, tuple[float, float, float, float]]] = field(default_factory=list)
    best_ink: int = 0
    best_t: float = 0.0
    crop: Any = None  # BGR, presenter-free
    parts: list[Any] = field(default_factory=list)  # [(RLE, normalized box)] of its parts at best_t
    parts_crop: Any = None  # numbered set-of-marks picture of the parts
    clean: Any = None  # presenter-free colour picture (analysis size) and the element's mask, at best_t:
    clean_mask: Any = None  # SAM splits drawings into parts from these (`everything.board_parts`)
    _last_mask: Any = None
    _first_mask: Any = None

    @property
    def life(self) -> float:
        return self.last_t - self.first_t


@dataclass
class BoardScan:
    elements: list[ElementTrack]
    board_ratio: float  # fraction of sampled frames that looked like a board / slide / flat animation
    samples: int
    picture_hw: tuple[int, int]


def _odd(n: int) -> int:
    return n if n % 2 else n + 1


def board_colour(bg: np.ndarray, ink: np.ndarray | None = None) -> np.ndarray:
    """The board's colour: among the large background colours (coarse 3-D histogram, >= BOARD_AREA of the picture),
    the one that carries the most writing. The *largest* region is often not the board: a phone filming a chalkboard
    sees more wall than board. Without ink, or when no region clearly holds more writing, the dominant colour wins."""
    sb = bg[::4, ::4].reshape(-1, 3)
    q = (sb // 32).astype(np.int32)
    keys = q[:, 0] * 64 + q[:, 1] * 8 + q[:, 2]
    counts = np.bincount(keys, minlength=512)

    def centre(k: int) -> np.ndarray:
        sel = sb[keys == k]
        return sel.mean(axis=0) if len(sel) else sb.mean(axis=0)

    dominant = int(counts.argmax())
    if ink is None:
        return centre(dominant)
    si = ink[::4, ::4].ravel()
    best, best_ink, dom_ink = dominant, -1.0, 0.0
    for k in np.argsort(counts)[::-1][:6]:
        if counts[k] < BOARD_AREA * len(keys):
            break
        c = centre(int(k))
        region = np.abs(sb.astype(np.int16) - c.astype(np.int16)).max(axis=1) < BOARD_T
        written = float(si[region].sum())
        if k == dominant:
            dom_ink = written
        if written > best_ink:
            best, best_ink = int(k), written
    if best != dominant and best_ink >= max(30.0, 1.5 * dom_ink):
        return centre(best)
    return centre(dominant)


def analyse_frame(img: np.ndarray, aux: dict[str, Any] | None = None) -> tuple[np.ndarray, np.ndarray, float, np.ndarray]:
    """BGR picture at analysis width → (ink mask, visible mask, board fraction, board colour). `aux`, when given,
    receives the raw ink (anywhere, not only on visible board) and the solid non-board regions (undilated)."""
    import cv2

    h, w = img.shape[:2]
    half = cv2.resize(img, (w // 2, h // 2), interpolation=cv2.INTER_AREA)  # background is smooth: half res is enough
    bg = cv2.resize(cv2.medianBlur(half, _odd(max(9, w // 42))), (w, h), interpolation=cv2.INTER_LINEAR)
    diff = cv2.absdiff(img, bg).max(axis=2)
    ink = diff > INK_T
    colour = board_colour(bg, ink)
    c16 = colour.astype(np.int16)
    board = np.abs(bg.astype(np.int16) - c16).max(axis=2) < BOARD_T
    # A non-board region is an occluder (presenter, illustration) only if it is solid. Dense writing also lifts the
    # blurred background off the board colour, but between its strokes the *pixels* are still board-coloured.
    near = np.abs(img.astype(np.int16) - c16).max(axis=2) < BOARD_T
    n, lab = cv2.connectedComponents((~board).astype(np.uint8), connectivity=8)
    if n > 1:
        tot = np.bincount(lab.ravel(), minlength=n)
        share = np.bincount(lab.ravel(), weights=near.ravel(), minlength=n) / np.maximum(tot, 1)
        writing = np.where(share > 0.35)[0]
        writing = writing[writing > 0]
        if len(writing):
            board |= np.isin(lab, writing)
    # The board is one big surface (two, if the presenter splits it): patches that merely share its colour (dark
    # jeans in front of a green chalkboard, a shadow) are not board, so they never produce ink. Opening first breaks
    # the thin bridges (the edge of a trouser leg) that would join such a patch to the board.
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (BRIDGE_PX, BRIDGE_PX))
    opened = cv2.morphologyEx(board.astype(np.uint8), cv2.MORPH_OPEN, k)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)
    if n > 1:
        areas = stats[1:, cv2.CC_STAT_AREA]
        main = np.isin(lab, np.where(areas >= BOARD_PART * areas.max())[0] + 1).astype(np.uint8)
        board &= cv2.dilate(main, k) > 0
    # A solid region the board surrounds on every side is *drawn* content (a chalk diagram coloured in, a filled
    # shape): the teacher always runs off the board or the frame edge, a drawing does not.
    drawn = np.zeros_like(board)
    sat = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[..., 1]
    n, lab, stats, _ = cv2.connectedComponentsWithStats((~board).astype(np.uint8), connectivity=8)
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if x > 0 and y > 0 and x + bw < w and y + bh < h and area <= DRAWN_MAX * w * h:
            region = lab == i
            # chalk and marker fills are pale or plain; a hand or a shirt cuff enclosed by board is not drawn content
            if float(sat[region].mean()) < DRAWN_MAX_SAT:
                drawn |= region
    board |= drawn
    if aux is not None:
        aux["raw_ink"], aux["solid"] = ink.copy(), ~board
    occluder = cv2.dilate((~board).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * OCCLUDER_PAD + 1,) * 2))
    visible = occluder == 0
    ink = (ink | drawn) & visible
    # drop specks (noise, compression artefacts)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    small = np.where(stats[:, cv2.CC_STAT_AREA] < 6)[0]
    if len(small) > 1:
        ink[np.isin(lab, small[small > 0])] = False
    return ink, visible, float(board.mean()), colour


def _line_len(h: int, w: int) -> int:
    return max(40, int(LINE_LEN * min(h, w)))


def long_strokes(mem: np.ndarray) -> np.ndarray:
    """Ink of long horizontal or vertical strokes, straight or wavy (a board border, the soil line under a plant, a long
    rule). Waves are fattened across the stroke first, then a LINE_LEN opening keeps only runs that long; words
    survive neither way (the gaps between letters and words break the run)."""
    import cv2

    h, w = mem.shape
    m8 = mem.astype(np.uint8)
    n = _line_len(h, w)
    rect = cv2.MORPH_RECT
    hl = cv2.morphologyEx(cv2.dilate(m8, cv2.getStructuringElement(rect, (3, WAVE_PX))), cv2.MORPH_OPEN,
                          cv2.getStructuringElement(rect, (n, 1)))
    vl = cv2.morphologyEx(cv2.dilate(m8, cv2.getStructuringElement(rect, (WAVE_PX, 3))), cv2.MORPH_OPEN,
                          cv2.getStructuringElement(rect, (1, n)))
    both = np.maximum(np.asarray(hl, np.uint8), np.asarray(vl, np.uint8))
    lines: np.ndarray = np.asarray(cv2.dilate(both, np.ones((3, 3), np.uint8)) > 0) & mem
    return lines


def group_elements(mem: np.ndarray, _fine: bool = False) -> list[tuple[tuple[int, int, int, int], np.ndarray, int]]:
    """Board memory → [(box, ink-shaped mask, ink px)]. Letters join into lines, lines into blocks. A block that grows
    over a large share of the board (a dense, fully labelled board) is re-split with half the joining distance, so
    each drawing with its labels, and each separate line, stays its own element."""
    import cv2

    h, w = mem.shape
    out = []
    if not _fine:
        lines = long_strokes(mem)
        if lines.any():
            # a border, the ground line under a drawing or a long rule would chain everything it touches into one
            # block: each long stroke is its own element and the rest is grouped without it
            n, lab, stats, _ = cv2.connectedComponentsWithStats(
                cv2.dilate(lines.astype(np.uint8), np.ones((9, 9), np.uint8)), connectivity=8)
            taken = np.zeros_like(mem)
            for i in range(1, n):
                x, y, bw, bh, _ = stats[i]
                comp = (lab == i) & lines
                if max(bw, bh) >= _line_len(h, w) and int(comp.sum()) >= MIN_INK_PX:
                    shape = cv2.dilate(comp.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
                    out.append(((int(x), int(y), int(bw), int(bh)), shape, int(comp.sum())))
                    taken |= comp
            mem = mem & ~taken  # only accepted lines leave the grouping; shorter pieces stay with their neighbours
    m8 = mem.astype(np.uint8)
    kx, ky = (max(9, w // 28), max(7, w // 48)) if not _fine else (max(5, w // 64), max(4, w // 110))
    joined = cv2.dilate(m8, cv2.getStructuringElement(cv2.MORPH_RECT, (kx, ky)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
    shape_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    for i in range(1, n):
        x, y, bw, bh, _ = stats[i]
        share = bw * bh / (w * h)
        if share < MIN_AREA:
            continue
        comp = (lab[y:y + bh, x:x + bw] == i) & mem[y:y + bh, x:x + bw]
        if not _fine and (share > SPLIT_AREA or bw > 0.55 * w):
            sub = np.zeros_like(mem)
            sub[y:y + bh, x:x + bw] = comp
            out += join_lines(group_elements(sub, _fine=True))
            continue
        if share > MAX_AREA:
            continue
        ink = int(comp.sum())
        if ink < MIN_INK_PX:
            continue
        full = np.zeros_like(m8)
        full[y:y + bh, x:x + bw] = comp
        out.append(((int(x), int(y), int(bw), int(bh)), cv2.dilate(full, shape_k) > 0, ink))
        if not _fine and bh >= 3 * ky:
            # a multi-line block or a diagram: its parts too (the sun beside the title, one label of a diagram) as
            # nested elements, so hovering picks the smallest thing under the pointer and the block is one click away
            # (a single line of big letters is not a block: its pieces would only be its letters)
            parts = [g for g in join_lines(group_elements(full > 0, _fine=True)) if g[2] >= 2 * MIN_INK_PX]
            if len(parts) >= 2:
                out += parts
    return out


LINE_GAP = 0.8  # glyphs closer than this share of the taller one's height, on one baseline, are one line of text
LINE_HEIGHT_RATIO = 2.2  # ...when their heights are this similar (x-height letters beside capitals and descenders)


def join_lines(groups: list[tuple[tuple[int, int, int, int], np.ndarray, int]]) -> list[tuple[tuple[int, int, int, int], np.ndarray, int]]:
    """Re-join the pieces of a fine re-split that are one line of text. The fine split joins only a few pixels, so the
    big, widely spaced letters of a caption ("Bisect angle!" across a portrait Short) fall apart into letters; letters
    of one line sit on one baseline, have similar heights and are spaced relative to their height, not in pixels."""
    n = len(groups)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        ax, ay, aw, ah = groups[i][0]
        for j in range(i + 1, n):
            bx, by, bw, bh = groups[j][0]
            lo, hi = min(ah, bh), max(ah, bh)
            if hi > LINE_HEIGHT_RATIO * lo:
                continue
            if min(ay + ah, by + bh) - max(ay, by) < 0.5 * lo:
                continue
            if max(bx - (ax + aw), ax - (bx + bw)) > LINE_GAP * hi:
                continue
            parent[find(i)] = find(j)
    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)
    out = []
    for members in clusters.values():
        if len(members) == 1:
            out.append(groups[members[0]])
            continue
        x0 = min(groups[i][0][0] for i in members)
        y0 = min(groups[i][0][1] for i in members)
        x1 = max(groups[i][0][0] + groups[i][0][2] for i in members)
        y1 = max(groups[i][0][1] + groups[i][0][3] for i in members)
        mask = np.logical_or.reduce([groups[i][1] for i in members])
        out.append(((x0, y0, x1 - x0, y1 - y0), mask, sum(groups[i][2] for i in members)))
    return out


def _overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    iw = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    ih = max(0, min(ay + ah, by + bh) - max(ay, by))
    return iw * ih / max(1, min(aw * ah, bw * bh))


def _match(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    """How likely box b is the next sample of the element at box a: overlap of the smaller box (an element grows while
    it is written), weighted toward similar sizes (a block and a label inside it are different elements)."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    iw = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    ih = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = iw * ih
    iou = inter / max(1, aw * ah + bw * bh - inter)
    return _overlap(a, b) * (0.5 + 0.5 * iou)


def _mask_iou(a: np.ndarray | None, b: np.ndarray) -> float:
    if a is None:
        return 0.0
    u = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / u) if u else 1.0


class Overlay:
    """Burned-in captions, titles and watermarks: drawn on top of the video, not on the board. Such a pixel keeps its
    colour while what lies *beneath* it changes (the teacher's arm passes under the caption, the camera moves); writing
    on the board is covered by the arm instead. Found over the whole scan; each overlay line becomes one element and
    board tracks made of overlay pieces (a caption cut into letters wherever the arm hid part of it) are dropped."""

    def __init__(self) -> None:
        self.ref: np.ndarray | None = None
        self.ink: np.ndarray | None = None
        self.bad: np.ndarray | None = None
        self.under: np.ndarray | None = None
        self.n, self.t0, self.t1 = 0, 0.0, 0.0

    def add(self, t: float, img: np.ndarray, aux: dict[str, Any]) -> None:
        if self.ref is None or self.ref.shape != img.shape:
            self.ref, self.ink = img.copy(), aux["raw_ink"]
            self.bad = np.zeros(img.shape[:2], np.uint16)
            self.under = np.zeros(img.shape[:2], np.uint16)
            self.n, self.t0 = 0, t
        assert self.bad is not None and self.under is not None
        self.bad += np.abs(img.astype(np.int16) - self.ref.astype(np.int16)).max(axis=2) >= OVERLAY_T
        self.under += aux["solid"]
        self.n, self.t1 = self.n + 1, t

    def mask(self) -> np.ndarray | None:
        if self.ref is None or self.ink is None or self.bad is None or self.under is None or self.n < OVERLAY_MIN_N:
            return None
        # steady, contrasted, and something different lay beneath it at times (not always: a resting arm is steady too)
        m: np.ndarray = (self.bad <= (1 - OVERLAY_STEADY) * self.n) & self.ink & (self.under >= 2) & (self.under <= self.n - 2)
        return m if int(m.sum()) >= MIN_INK_PX else None

    def apply(self, tracks: list[ElementTrack]) -> list[ElementTrack]:
        import cv2

        from loom.perception.everything import outlined_crop
        from loom.perception.segment import encode_rle

        m = self.mask()
        if m is None or self.ref is None:
            return tracks
        h, w = m.shape
        small_h = max(1, round(h * MASK_W / w))
        grown = cv2.dilate(m.astype(np.uint8), np.ones((9, 9), np.uint8))
        small = cv2.resize(grown, (MASK_W, small_h), interpolation=cv2.INTER_NEAREST) > 0

        def inside(mk: Any) -> float:
            return float((mk & small).sum() / max(1, mk.sum())) if mk is not None and mk.shape == small.shape else 0.0

        kept = [tr for tr in tracks if max(inside(tr._last_mask), inside(tr._first_mask)) < OVERLAY_DROP]
        times = [self.t0 + k * KEEPALIVE_S for k in range(int((self.t1 - self.t0) // KEEPALIVE_S) + 1)] + [self.t1]
        for box, gm, inkpx in join_lines(group_elements(m)):
            gsmall = cv2.resize(gm.astype(np.uint8), (MASK_W, small_h), interpolation=cv2.INTER_NEAREST) > 0
            rle, nb = encode_rle(gsmall), _norm_box(box, w, h)
            x, y, bw, bh = box
            tr = ElementTrack(track_id=len(tracks) + len(kept), box=box, first_t=self.t0, last_t=self.t1, epoch=-1,
                              samples=[(round(tt, 2), rle, nb) for tt in dict.fromkeys(times)], best_ink=inkpx,
                              best_t=self.t0)
            tr.crop = outlined_crop(self.ref, gm, (x, y, x + bw, y + bh), pad_ratio=0.6, min_pad=40, grow=6)
            tr.clean, tr.clean_mask, tr._last_mask = self.ref.copy(), gm, gsmall
            kept.append(tr)
        return kept


REID_BOX = 0.7  # box IoU (picture coordinates) for an element that comes back after a board restart
REID_MASK = 0.6  # ...and mask IoU: the same shape, not just the same place (a new slide's title is not the old one)


def _box_iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    iw = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    ih = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    inter = iw * ih
    return inter / max(1e-9, a[2] * a[3] + b[2] * b[3] - inter)


def reidentify(tracks: list[ElementTrack]) -> list[ElementTrack]:
    """Join tracks that are one element seen across board restarts. A restart (a stencil slid over the board, a jump
    cut, a zoom) starts every element again; whatever comes back in the same place with the same shape (a burned-in
    caption, a drawing the cut did not change) continues its old track instead of becoming a copy of itself."""
    out: list[ElementTrack] = []
    for tr in sorted((t for t in tracks if t.samples), key=lambda t: t.first_t):
        prev = next((o for o in out if o.epoch != tr.epoch and o.last_t <= tr.first_t
                     and _box_iou(o.samples[-1][2], tr.samples[0][2]) >= REID_BOX
                     and _mask_iou(o._last_mask, tr._first_mask) >= REID_MASK), None)
        if prev is None:
            out.append(tr)
            continue
        prev.samples += tr.samples
        prev.last_t, prev.epoch, prev._last_mask = tr.last_t, tr.epoch, tr._last_mask
        if tr.best_ink > prev.best_ink:
            prev.best_ink, prev.best_t, prev.crop = tr.best_ink, tr.best_t, tr.crop
            prev.clean, prev.clean_mask = tr.clean, tr.clean_mask
    return out


def _norm_box(box: tuple[int, int, int, int], w: int, h: int) -> tuple[float, float, float, float]:
    x, y, bw, bh = box
    return (round(x / w, 4), round(y / h, 4), round(bw / w, 4), round(bh / h, 4))


PREVIEW_EVERY_S = 30.0


def render_scan(img: np.ndarray, visible: np.ndarray, masks: list[np.ndarray]) -> np.ndarray:
    """What the scanner sees: occluders (presenter, illustrations) dimmed, each tracked element outlined."""
    import cv2

    from loom.perception.preview import colour

    out = img.copy()
    out[~visible] = (out[~visible] * 0.35).astype(np.uint8)
    for i, m in enumerate(masks):
        cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(out, cnts, -1, colour(i), 2)
    return out


def camera_shift(prev: np.ndarray, cur: np.ndarray) -> tuple[float, float, float]:
    """Global translation of the picture content between two grey frames (phase correlation): (dx, dy, confidence).
    A camera panning right moves the board left, i.e. dx < 0."""
    import cv2

    win = cv2.createHanningWindow((cur.shape[1], cur.shape[0]), cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(prev, cur, win)
    return float(dx), float(dy), float(resp)


def scan_board(
    frames: Any, shot_starts: list[float], interval: float, on_preview: Any = None, on_snapshot: Any = None,
    snap_every: float = 2.0,
) -> BoardScan:
    """`frames` yields (t, BGR picture already cropped to the content rect). Returns tracked board elements.

    Memory and tracking live on a board *canvas* (twice the frame size): each frame is placed on it at the camera
    offset found by phase correlation, so a camera that pans to follow the teacher does not look like a new board.
    Masks and boxes are reported in each frame's own coordinates."""
    import cv2

    from loom.perception.segment import encode_rle

    tracks: list[ElementTrack] = []
    mem = count = colour_mem = known = prev_colour = prev_grey = None
    last_snap = -1e9
    ox = oy = 0
    epoch = board_frames = total = 0
    hw = (0, 0)
    cuts = sorted(shot_starts)
    next_cut = 0
    last_preview = -1e9
    jitter_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * JITTER_PX + 1,) * 2)
    ov = Overlay()
    for t, frame in frames:
        total += 1
        h0, w0 = frame.shape[:2]
        img = cv2.resize(frame, (ANALYSIS_W, round(h0 * ANALYSIS_W / w0)), interpolation=cv2.INTER_AREA) if w0 != ANALYSIS_W else frame
        h, w = img.shape[:2]
        hw = (h, w)
        aux: dict[str, Any] = {}
        ink, visible, frac, colour = analyse_frame(img, aux)
        ov.add(t, img, aux)
        grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
        grey[~visible] = float(grey[visible].mean()) if visible.any() else 0.0  # the teacher must not steer the pan
        cut = False
        while next_cut < len(cuts) and cuts[next_cut] <= t:
            cut, next_cut = True, next_cut + 1
        if frac < BOARD_MIN:  # not a board / slide right now (camera on the presenter, a busy scene)
            mem, prev_grey = None, None
            continue
        board_frames += 1
        fresh = mem is None or cut or prev_colour is None or np.abs(colour - prev_colour).max() > 40
        if not fresh and prev_grey is not None:
            dx, dy, resp = camera_shift(prev_grey, grey)
            if resp < 0.04 or abs(dx) > 0.25 * w or abs(dy) > 0.25 * h:
                fresh = True  # a cut or a zoom: start a new board
            else:
                ox, oy = ox - round(dx), oy - round(dy)
                if not (0 <= ox <= w and 0 <= oy <= h):
                    fresh = True  # panned off the canvas
        if fresh or mem is None or count is None or colour_mem is None or known is None:
            mem, count = np.zeros((2 * h, 2 * w), bool), np.zeros((2 * h, 2 * w), np.uint8)
            colour_mem = np.zeros((2 * h, 2 * w, 3), np.uint8)
            known = np.zeros((2 * h, 2 * w), bool)  # board pixels seen unobstructed at least once
            ox, oy = w // 2, h // 2
            epoch += 1
        prev_colour, prev_grey = colour, grey
        sl = (slice(oy, oy + h), slice(ox, ox + w))
        m_r, c_r = mem[sl], count[sl]
        # two agreeing visible samples flip a pixel; occluded pixels keep their state. "Agreeing" tolerates JITTER_PX:
        # a handheld camera shakes by a pixel or two after alignment, and chalk strokes are only 2-3 px wide
        near_prev = cv2.dilate(((c_r >= 1) | m_r).astype(np.uint8), jitter_k) > 0
        hit = visible & ink
        c_r = np.where(hit, np.where(near_prev, 2, np.minimum(c_r + 1, 2)), np.where(visible, 0, c_r)).astype(np.uint8)
        new_r = (c_r >= 2) | (m_r & ~visible)
        if m_r.sum() > 500:
            # a new slide / scene changes most of the writing; a shaken frame only moves it by a pixel or two
            moved_in = new_r & visible & ~(cv2.dilate(m_r.astype(np.uint8), jitter_k) > 0)
            gone = m_r & visible & ~(cv2.dilate(new_r.astype(np.uint8), jitter_k) > 0)
            if int(moved_in.sum() + gone.sum()) > RESET_CHANGE * max(1, int(m_r.sum())):
                epoch += 1  # elements restart
        count[sl], mem[sl] = c_r, new_r
        colour_mem[sl][visible] = img[visible]
        groups = group_elements(new_r)
        if on_preview is not None and t - last_preview >= PREVIEW_EVERY_S:
            last_preview = t
            with contextlib.suppress(Exception):  # a preview never stops the scan
                on_preview(t, render_scan(img, visible, [m for _, m, _ in groups]), len(groups))
        frame_colour = colour_mem[sl]
        known[sl] |= visible
        if on_snapshot is not None and t - last_snap >= snap_every:
            # the board as if the teacher were not there: last unobstructed colour of every board pixel, transparent
            # where the board was never seen; soft edges so it blends into the live picture
            last_snap = t
            alpha = cv2.GaussianBlur(known[sl].astype(np.uint8) * 255, (9, 9), 0)
            with contextlib.suppress(Exception):
                on_snapshot(t, np.dstack([frame_colour, alpha]))
        # one track per group and one group per track: without this a big block (a labelled diagram) whose box covers
        # a neighbour's box steals the neighbour's track, and that element blinks out
        cboxes = [(box[0] + ox, box[1] + oy, box[2], box[3]) for box, _, _ in groups]  # board canvas: stable on pans
        live = [tr for tr in tracks if tr.epoch == epoch and t - tr.last_t <= GAP_S]
        pairs = sorted(((_match(tr.box, cb), gi, ti) for gi, cb in enumerate(cboxes) for ti, tr in enumerate(live)),
                       reverse=True)
        owner: dict[int, ElementTrack] = {}
        taken: set[int] = set()
        for score, gi, ti in pairs:
            if score < MATCH_MIN or gi in owner or ti in taken:
                continue
            owner[gi] = live[ti]
            taken.add(ti)
        for gi, (box, mask, inkpx) in enumerate(groups):
            cbox = cboxes[gi]
            best = owner.get(gi)
            if best is None:
                best = ElementTrack(track_id=len(tracks), box=cbox, first_t=t, last_t=t, epoch=epoch)
                tracks.append(best)
            best.box, best.last_t = cbox, t
            small = cv2.resize(mask.astype(np.uint8), (MASK_W, max(1, round(h * MASK_W / w))),
                               interpolation=cv2.INTER_NEAREST) > 0
            last_t = best.samples[-1][0] if best.samples else -1e9
            changed = _mask_iou(best._last_mask, small) < 0.93
            if (changed and t - last_t >= MIN_SAMPLE_GAP_S) or t - last_t >= KEEPALIVE_S or not best.samples:
                if not best.samples:
                    best._first_mask = small
                best.samples.append((round(t, 2), encode_rle(small), _norm_box(box, w, h)))
                best._last_mask = small
            if inkpx >= best.best_ink:
                from loom.perception.everything import outlined_crop

                x, y, bw, bh = box
                best.best_ink, best.best_t = inkpx, t
                # presenter-free colour memory, the element outlined and its surroundings dimmed: a small part of a
                # dense board (one label, the soil line) is named for what it is, not guessed from the speech
                best.crop = outlined_crop(frame_colour, mask, (x, y, x + bw, y + bh), pad_ratio=0.6, min_pad=40,
                                          grow=6)
                best.clean, best.clean_mask = frame_colour.copy(), mask
    del interval
    tracks = reidentify(tracks)
    tracks = ov.apply(tracks)
    kept = [tr for tr in tracks if tr.life >= MIN_LIFE_S and tr.samples]
    kept.sort(key=lambda tr: tr.best_ink * (tr.life + 1) ** 0.5, reverse=True)
    return BoardScan(elements=kept[:MAX_ELEMENTS], board_ratio=board_frames / max(1, total), samples=total,
                     picture_hw=hw)


def picture_frames(video: Path, times: list[float], rect: tuple[float, float, float, float]) -> Any:
    """Yield (t, BGR picture) for `times`, cropped to the content rect (letterbox removed). Random access; for a full
    scan use `stream_frames` (an ffmpeg pipe is ~10x faster than seeking with OpenCV)."""
    from loom.perception.ocr import FrameReader

    reader = FrameReader(video)
    try:
        for t in times:
            f = reader.at(t)
            if f is None:
                continue
            fh, fw = f.shape[:2]
            rx, ry, rw, rh = rect
            x0, y0 = round(rx * fw), round(ry * fh)
            yield t, f[y0:max(y0 + 1, round((ry + rh) * fh)), x0:max(x0 + 1, round((rx + rw) * fw))]
    finally:
        reader.close()


def stream_frames(video: Path, interval: float, rect: tuple[float, float, float, float], frame_w: int,
                  frame_h: int, limit_s: float | None = None) -> Any:
    """Yield (t, BGR picture at ANALYSIS_W) every `interval` seconds: ffmpeg decodes, crops and scales in one pass."""
    import subprocess

    rx, ry, rw, rh = rect
    cw, ch = max(2, round(rw * frame_w)), max(2, round(rh * frame_h))
    out_h = max(2, round(ch * ANALYSIS_W / cw / 2) * 2)
    vf = f"fps=1/{interval},crop={cw}:{ch}:{round(rx * frame_w)}:{round(ry * frame_h)},scale={ANALYSIS_W}:{out_h}:flags=area"
    cmd = ["ffmpeg", "-loglevel", "error", "-nostdin", "-hwaccel", "auto"]
    if limit_s:
        cmd += ["-t", str(limit_s)]
    cmd += ["-i", str(video), "-vf", vf, "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    size = ANALYSIS_W * out_h * 3
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    try:
        k = 0
        while True:
            buf = proc.stdout.read(size) if proc.stdout else b""
            if len(buf) < size:
                break
            yield round(k * interval, 2), np.frombuffer(buf, np.uint8).reshape(out_h, ANALYSIS_W, 3)
            k += 1
    finally:
        proc.kill()
        proc.wait()


def scan_times(duration: float) -> tuple[list[float], float]:
    """1 sample/s for lessons up to 15 min, sparser beyond (board content changes slowly)."""
    interval = 1.0 if duration <= 900 else 2.0
    return [round(interval / 2 + k * interval, 2) for k in range(int(duration / interval))], interval


def save_crop(crop: np.ndarray, path: Path) -> Path:
    """Upscale small crops so handwriting is legible to the VLM."""
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    h, w = crop.shape[:2]
    scale = max(1.0, 448 / max(1, w), 160 / max(1, h))
    if scale > 1:
        crop = cv2.resize(crop, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_CUBIC)
    cv2.imwrite(str(path), crop)
    return path


# ---------------------------------------------------------------- on-screen text clean-up (pure)

_SCRIBBLE = re.compile(r"^[imnuwo]{2,}$", re.IGNORECASE)  # cursive strokes misread as letters ("imom", "minn")
_REAL = {"mom", "now", "own", "won", "nun", "noun", "union", "mini", "minimum", "onion", "in", "on", "no", "nu", "mu",
         "io", "um", "mm"}


def is_noise(text: str, confidence: float) -> bool:
    s = text.strip()
    if not s:
        return True
    low = s.lower()
    cursive = sum(c in "mnuw" for c in low) >= 0.5 * len(low)
    if _SCRIBBLE.match(s) and low not in _REAL and confidence < 0.97 and cursive:
        return True
    letters = sum(c.isalnum() for c in s)
    return (letters <= 1 and confidence < 0.9) or (confidence < 0.55 and len(s) < 6)


def merge_lines(spans: list[Any], make: Any) -> list[Any]:
    """Word-level OCR spans → line-level spans. Two spans join when they are on screen together, on the same line
    (vertical centres within 60 % of the line height) and close horizontally. `make(first, text, start, end, bbox,
    confidence)` builds the merged span (keeps the first id)."""
    items = sorted(spans, key=lambda s: (round(s.bbox[1] + s.bbox[3] / 2, 2), s.bbox[0]))
    used = [False] * len(items)
    out = []
    for i, a in enumerate(items):
        if used[i]:
            continue
        used[i] = True
        group = [a]
        changed = True
        while changed:
            changed = False
            x0 = min(g.bbox[0] for g in group)
            x1 = max(g.bbox[0] + g.bbox[2] for g in group)
            cy = sum(g.bbox[1] + g.bbox[3] / 2 for g in group) / len(group)
            lh = max(g.bbox[3] for g in group)
            s0, s1 = min(g.start for g in group), max(g.end for g in group)
            for j, b in enumerate(items):
                if used[j]:
                    continue
                bcy = b.bbox[1] + b.bbox[3] / 2
                t_ov = min(s1, b.end) - max(s0, b.start)
                gap = max(b.bbox[0] - x1, x0 - (b.bbox[0] + b.bbox[2]))
                if t_ov > 0.5 * min(s1 - s0, b.end - b.start) and abs(bcy - cy) < 0.6 * max(lh, b.bbox[3]) \
                        and gap < 1.6 * max(lh, b.bbox[3]):
                    used[j] = True
                    group.append(b)
                    changed = True
        if len(group) == 1:
            out.append(a)
            continue
        group.sort(key=lambda g: g.bbox[0])
        gx0 = min(g.bbox[0] for g in group)
        gy0 = min(g.bbox[1] for g in group)
        gx1 = max(g.bbox[0] + g.bbox[2] for g in group)
        gy1 = max(g.bbox[1] + g.bbox[3] for g in group)
        # the longest reading of overlapping duplicates wins, then words join left to right
        words: list[Any] = []
        for g in group:
            if words and _overlap_1d(words[-1].bbox, g.bbox) > 0.6:
                if len(g.text) > len(words[-1].text):
                    words[-1] = g
                continue
            words.append(g)
        out.append(make(group[0], " ".join(w.text.strip() for w in words),
                        min(g.start for g in group), max(g.end for g in group),
                        (round(gx0, 4), round(gy0, 4), round(gx1 - gx0, 4), round(gy1 - gy0, 4)),
                        min(1.0, sum(g.confidence for g in group) / len(group))))
    out.sort(key=lambda s: (s.start, s.bbox[1], s.bbox[0]))
    return out


def _overlap_1d(a: Any, b: Any) -> float:
    iw = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    return iw / max(1e-6, min(a[2], b[2]))


def boxes_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Intersection over the smaller box (normalized boxes)."""
    iw = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    ih = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return iw * ih / max(1e-9, min(a[2] * a[3], b[2] * b[3]))


# ---------------------------------------------------------------- reading elements (VLM) -> graph objects

KINDS = ("text", "equation", "diagram", "table", "code", "chart", "illustration")


PART_KINDS = ("diagram", "illustration", "table", "chart")


def _parts_schema() -> Any:
    from loom.core.contracts.common import Contract

    class PartName(Contract):
        n: int
        label: str
        what: str = ""

    class PartsReading(Contract):
        parts: list[PartName] = []

    return PartsReading


async def name_parts(llm: Any, e: Any, label: str, content: str, speech: str, workdir: Path,
                     priority: Any = "ingest") -> list[Any]:
    """One set-of-marks VLM call names every numbered part of a drawn element -> ObjectParts (unnamed numbers and
    fragments dropped). A failure leaves the element without parts; it never fails the element."""
    from loom.core.contracts.graph import ObjectPart
    from loom.core.llm import LLMError

    if not e.parts or e.parts_crop is None:
        return []
    img = workdir / f"parts_{e.track_id:03d}.png"
    img.parent.mkdir(parents=True, exist_ok=True)
    import cv2

    cv2.imwrite(str(img), e.parts_crop)
    try:
        r = (await llm.call("brain", "element_parts", {"element": f"{label}: {content}"[:500],
                                                       "speech": speech[:500] or "(silent)"},
                            _parts_schema(), images=[img], priority=priority, timeout_s=120)).value
    except LLMError:
        return []
    out: list[ObjectPart] = []
    for p in r.parts:
        name = p.label.strip()
        if not (1 <= p.n <= len(e.parts)) or not name or name.lower() in ("unclear", "background"):
            continue
        if any(x.part_id == f"p_{p.n:02d}" for x in out):
            continue
        rle, box = e.parts[p.n - 1]
        out.append(ObjectPart(part_id=f"p_{p.n:02d}", label=name[:80], description=p.what.strip()[:300] or None,
                              t=round(e.best_t, 2), bbox=box, mask=rle))
    return out


def _reading_schema() -> Any:
    from loom.core.contracts.common import Contract

    from typing import Literal

    class BoardReading(Contract):
        is_content: bool
        kind: Literal["text", "equation", "diagram", "table", "code", "chart", "illustration"]
        label: str
        content: str = ""
        meaning: str = ""

    return BoardReading


async def read_elements(
    llm: Any, scan: BoardScan, texts: list[Any], sentences: list[Any], shots: list[Any], duration: float,
    interval: float, first_object: int, workdir: Path, progress: Any = None, priority: Any = "ingest",
    prompt: str = "board_element",
) -> tuple[list[Any], list[str]]:
    """VLM-read every tracked element from its presenter-free crop → GraphObjects (phrase_source "board").
    Elements the model calls non-content are dropped; if the model is unavailable an element with OCR text is kept
    with that text as its label (never silently lost). `prompt` is `board_element` for ink on a board and
    `scene_element` for segment-everything elements of animations and slides (outlined crops)."""
    from loom.core.contracts.graph import GraphObject, ObjectInstance, SafetyRecord, TrackSample, Verification
    from loom.core.llm import LLMError

    schema = _reading_schema()
    degraded: list[str] = []

    def shot_of(t: float) -> Any:
        return next((s for s in shots if s.start <= t < s.end), shots[-1])

    by_label: dict[str, Any] = {}
    order: list[str] = []
    failures = 0
    for n, e in enumerate(scan.elements):
        box = e.samples[-1][2]
        ocr = list(dict.fromkeys(
            x.text for x in texts
            if min(x.end, e.last_t) - max(x.start, e.first_t) > 0 and boxes_overlap(tuple(x.bbox), box) > 0.3))
        speech = " ".join(s.text for s in sentences if e.first_t - 8 <= s.start <= e.best_t + 8)
        crop = save_crop(e.crop, workdir / f"el_{e.track_id:03d}.png")
        try:
            r = (await llm.call("brain", prompt, {"ocr": " | ".join(ocr)[:500] or "(none)",
                                                           "speech": speech[:700] or "(silent)"},
                                schema, images=[crop], priority=priority, timeout_s=120)).value
            if not r.is_content or not r.label.strip():
                continue
            kind = r.kind if r.kind in KINDS else "text"  # schema enum; kept as a guard
            label, content, meaning = r.label.strip()[:80], r.content.strip()[:600], r.meaning.strip()[:400]
        except LLMError:
            failures += 1
            if not ocr:
                continue
            kind, label, content, meaning = "text", " ".join(ocr)[:80], " ".join(ocr)[:600], ""
        parts = await name_parts(llm, e, label, content, speech, workdir, priority) if kind in PART_KINDS else []
        if progress:
            progress(f"{kind}: {label}" + (f" ({len(parts)} named parts)" if parts else ""), crop,
                     [x for x in (content, meaning) if x] + [f"part: {p.label}" for p in parts][:8])
        base_key = re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()
        # same name = same object only if they are never on screen together in one shot (an object's instances must
        # not overlap); two simultaneous marks with one name ("Q1" twice) become "Q1" and "Q1 (2)"
        sh = shot_of(e.first_t)
        key, k = base_key, 1
        while key in by_label and any(
                shot_of(o.first_t) is sh and o.first_t < e.last_t + interval and e.first_t < o.last_t + interval
                for o in by_label[key]["els"]):
            k += 1
            key = f"{base_key} #{k}"
        if key not in by_label:
            by_label[key] = {"kind": kind, "label": label if k == 1 else f"{label} ({k})", "content": content,
                             "meaning": meaning, "els": [], "parts": []}
            order.append(key)
        by_label[key]["els"].append(e)
        if len(parts) > len(by_label[key]["parts"]):
            by_label[key]["parts"] = parts
        del n
    if failures:
        what = "board" if prompt == "board_element" else "scene"
        degraded.append(f"{what} reading unavailable for {failures} element(s)")

    objects = []
    for key in order:
        g = by_label[key]
        oid = f"o_{first_object + len(objects):03d}"
        insts = []
        for k, e in enumerate(sorted(g["els"], key=lambda e: e.first_t)):
            sh = shot_of(e.first_t)
            start = max(sh.start, e.first_t)
            end = min(duration, sh.end, max(e.last_t + interval, start + 0.5))
            track = [TrackSample(t=min(max(t, start), end), bbox=b, mask=m) for t, m, b in e.samples]
            track = sorted({s.t: s for s in track}.values(), key=lambda s: s.t)
            insts.append(ObjectInstance(
                instance_id=f"{oid}_{k}", shot_id=sh.shot_id, start=round(start, 3), end=round(end, 3), score=0.9,
                track=track, verification=Verification(vlm="confirmed", status="verified")))
        objects.append(GraphObject(
            object_id=oid, label=g["label"], phrase_source="board", instances=insts,
            safety=SafetyRecord(status="unreviewed"), element_kind=g["kind"],  # type: ignore[arg-type]
            content=g["content"] or None, description=g["meaning"] or None, parts=g["parts"]))
    return objects, degraded
