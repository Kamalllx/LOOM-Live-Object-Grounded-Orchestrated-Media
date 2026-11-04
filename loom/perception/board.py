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

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

ANALYSIS_W = 640
MASK_W = 480  # same picture-relative mask width as the SAM 2.1 tier
INK_T = 42  # min |pixel - local background| (0-255) to count as ink
BOARD_T = 38  # max |background - board colour| to count as board
BOARD_MIN = 0.35  # a frame is board-like when at least this fraction of it is board
OCCLUDER_PAD = 15  # px (analysis width) around a presenter / illustration that never updates the board
RESET_CHANGE = 0.6  # a sample that changes this fraction of remembered ink starts a new board (slide change)
MIN_INK_PX = 70
MIN_AREA = 0.002  # element bbox area / picture area
MAX_AREA = 0.6
GAP_S = 6.0  # an element that is gone for longer than this has been erased
MIN_LIFE_S = 2.0
KEEPALIVE_S = 10.0
MIN_SAMPLE_GAP_S = 2.0
MAX_ELEMENTS = 40


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
    _last_mask: Any = None

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


def board_colour(bg: np.ndarray) -> np.ndarray:
    """Dominant colour of the (blurred) background, via a coarse 3-D histogram."""
    q = (bg[::4, ::4] // 32).reshape(-1, 3).astype(np.int32)
    keys = q[:, 0] * 64 + q[:, 1] * 8 + q[:, 2]
    k = int(np.bincount(keys, minlength=512).argmax())
    sel = bg[::4, ::4].reshape(-1, 3)[keys == k]
    return sel.mean(axis=0) if len(sel) else bg.reshape(-1, 3).mean(axis=0)


def analyse_frame(img: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, np.ndarray]:
    """BGR picture at analysis width → (ink mask, visible mask, board fraction, board colour)."""
    import cv2

    h, w = img.shape[:2]
    half = cv2.resize(img, (w // 2, h // 2), interpolation=cv2.INTER_AREA)  # background is smooth: half res is enough
    bg = cv2.resize(cv2.medianBlur(half, _odd(max(9, w // 42))), (w, h), interpolation=cv2.INTER_LINEAR)
    diff = cv2.absdiff(img, bg).max(axis=2)
    ink = diff > INK_T
    colour = board_colour(bg)
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
    occluder = cv2.dilate((~board).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * OCCLUDER_PAD + 1,) * 2))
    visible = occluder == 0
    ink &= visible
    # drop specks (noise, compression artefacts)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    small = np.where(stats[:, cv2.CC_STAT_AREA] < 6)[0]
    if len(small) > 1:
        ink[np.isin(lab, small[small > 0])] = False
    return ink, visible, float(board.mean()), colour


def group_elements(mem: np.ndarray) -> list[tuple[tuple[int, int, int, int], np.ndarray, int]]:
    """Board memory → [(box, ink-shaped mask, ink px)]. Letters join into lines, lines into blocks."""
    import cv2

    h, w = mem.shape
    m8 = mem.astype(np.uint8)
    joined = cv2.dilate(m8, cv2.getStructuringElement(cv2.MORPH_RECT, (max(9, w // 28), max(7, w // 48))))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
    shape_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    out = []
    for i in range(1, n):
        x, y, bw, bh, _ = stats[i]
        if not (MIN_AREA <= bw * bh / (w * h) <= MAX_AREA):
            continue
        comp = (lab[y:y + bh, x:x + bw] == i) & mem[y:y + bh, x:x + bw]
        ink = int(comp.sum())
        if ink < MIN_INK_PX:
            continue
        full = np.zeros_like(m8)
        full[y:y + bh, x:x + bw] = comp
        out.append(((int(x), int(y), int(bw), int(bh)), cv2.dilate(full, shape_k) > 0, ink))
    return out


def _overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    iw = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    ih = max(0, min(ay + ah, by + bh) - max(ay, by))
    return iw * ih / max(1, min(aw * ah, bw * bh))


def _mask_iou(a: np.ndarray | None, b: np.ndarray) -> float:
    if a is None:
        return 0.0
    u = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / u) if u else 1.0


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


def scan_board(
    frames: Any, shot_starts: list[float], interval: float, on_preview: Any = None
) -> BoardScan:
    """`frames` yields (t, BGR picture already cropped to the content rect). Returns tracked board elements."""
    import cv2

    from loom.perception.segment import encode_rle

    tracks: list[ElementTrack] = []
    mem = count = colour_mem = prev_colour = None
    epoch = board_frames = total = 0
    hw = (0, 0)
    cuts = sorted(shot_starts)
    next_cut = 0
    last_preview = -1e9
    for t, frame in frames:
        total += 1
        h0, w0 = frame.shape[:2]
        img = cv2.resize(frame, (ANALYSIS_W, round(h0 * ANALYSIS_W / w0)), interpolation=cv2.INTER_AREA) if w0 != ANALYSIS_W else frame
        h, w = img.shape[:2]
        hw = (h, w)
        ink, visible, frac, colour = analyse_frame(img)
        cut = False
        while next_cut < len(cuts) and cuts[next_cut] <= t:
            cut, next_cut = True, next_cut + 1
        if frac < BOARD_MIN:  # not a board / slide right now (camera on the presenter, a busy scene)
            mem = None
            continue
        board_frames += 1
        if mem is None or cut or prev_colour is None or np.abs(colour - prev_colour).max() > 40:
            mem, count, colour_mem = np.zeros((h, w), bool), np.zeros((h, w), np.uint8), img.copy()
            epoch += 1
        prev_colour = colour
        # two agreeing visible samples flip a pixel; occluded pixels keep their state
        count = np.where(visible & ink, np.minimum(count + 1, 2), np.where(visible, 0, count)).astype(np.uint8)
        new_mem = (count >= 2) | (mem & ~visible)
        if mem.sum() > 500 and np.logical_xor(new_mem, mem)[visible].sum() > RESET_CHANGE * max(1, mem.sum()):
            epoch += 1  # a new slide / scene: elements restart
            colour_mem = img.copy()
        mem = new_mem
        colour_mem[visible] = img[visible]
        groups = group_elements(mem)
        if on_preview is not None and t - last_preview >= PREVIEW_EVERY_S:
            last_preview = t
            try:
                on_preview(t, render_scan(img, visible, [m for _, m, _ in groups]), len(groups))
            except Exception:  # noqa: BLE001 - a preview never stops the scan
                pass
        for box, mask, inkpx in groups:
            best: ElementTrack | None = None
            best_o = 0.4
            for tr in tracks:
                if tr.epoch != epoch or t - tr.last_t > GAP_S:
                    continue
                o = _overlap(tr.box, box)
                if o > best_o:
                    best, best_o = tr, o
            if best is None:
                best = ElementTrack(track_id=len(tracks), box=box, first_t=t, last_t=t, epoch=epoch)
                tracks.append(best)
            best.box, best.last_t = box, t
            small = cv2.resize(mask.astype(np.uint8), (MASK_W, max(1, round(h * MASK_W / w))), interpolation=cv2.INTER_NEAREST) > 0
            last_t = best.samples[-1][0] if best.samples else -1e9
            changed = _mask_iou(best._last_mask, small) < 0.93
            if (changed and t - last_t >= MIN_SAMPLE_GAP_S) or t - last_t >= KEEPALIVE_S or not best.samples:
                best.samples.append((round(t, 2), encode_rle(small), _norm_box(box, w, h)))
                best._last_mask = small
            if inkpx >= best.best_ink:
                x, y, bw, bh = box
                p = 8
                best.best_ink, best.best_t = inkpx, t
                best.crop = colour_mem[max(0, y - p):y + bh + p, max(0, x - p):x + bw + p].copy()
    del interval
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
    if _SCRIBBLE.match(s) and low not in _REAL and confidence < 0.97 and             sum(c in "mnuw" for c in low) >= 0.5 * len(low):
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
) -> tuple[list[Any], list[str]]:
    """VLM-read every tracked element from its presenter-free crop → GraphObjects (phrase_source "board").
    Elements the model calls non-content are dropped; if the model is unavailable an element with OCR text is kept
    with that text as its label (never silently lost)."""
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
            r = (await llm.call("brain", "board_element", {"ocr": " | ".join(ocr)[:500] or "(none)",
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
        if progress:
            progress(f"{kind}: {label}", crop, [x for x in (content, meaning) if x])
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
                             "meaning": meaning, "els": []}
            order.append(key)
        by_label[key]["els"].append(e)
        del n
    if failures:
        degraded.append(f"board reading unavailable for {failures} element(s)")

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
            content=g["content"] or None, description=g["meaning"] or None))
    return objects, degraded
