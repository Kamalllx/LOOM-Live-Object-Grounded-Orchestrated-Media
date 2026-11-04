"""Live ingest previews: what each perception stage is looking at, as pictures + short findings.

Each preview is a small JPEG under data/media/ingest/<video_id>/ (served at /media/ingest/...) announced through the
ordinary `ingest_stage` progress event (`image`, `items`). Rendering is best-effort: a preview that fails to render
is skipped and never affects perception.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import numpy as np

PALETTE = [(255, 199, 124), (196, 242, 110), (255, 166, 195), (138, 179, 255), (122, 92, 255), (110, 220, 255),
           (180, 120, 255), (120, 255, 200)]  # BGR, the player's Silk colours
PREVIEW_W = 960


def colour(i: int) -> tuple[int, int, int]:
    return PALETTE[i % len(PALETTE)]


class Previewer:
    def __init__(self, data: Path, video_id: str, emit: Callable[..., None]) -> None:
        self.dir = data / "media" / "ingest" / video_id
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.url = f"/media/ingest/{video_id}"
        self.emit = emit
        self.n = 0

    def image(self, stage: str, img: Any, detail: str, items: Iterable[str] = (), progress: float = 0.5) -> None:
        import cv2

        try:
            h, w = img.shape[:2]
            if w > PREVIEW_W:
                img = cv2.resize(img, (PREVIEW_W, round(h * PREVIEW_W / w)), interpolation=cv2.INTER_AREA)
            self.n += 1
            name = f"{self.n:03d}_{stage}.jpg"
            cv2.imwrite(str(self.dir / name), img, [cv2.IMWRITE_JPEG_QUALITY, 82])
            self.emit(stage, "progress", progress, detail[:200], image=f"{self.url}/{name}",
                      items=[str(i)[:240] for i in items][:12])
        except Exception:  # noqa: BLE001 - previews are decoration, never a failure
            pass

    def items(self, stage: str, detail: str, items: Iterable[str], progress: float = 0.9) -> None:
        self.emit(stage, "progress", progress, detail[:200], items=[str(i)[:240] for i in items][:12])


# ---------------------------------------------------------------- drawing helpers


def label(img: Any, text: str, x: int, y: int, col: tuple[int, int, int]) -> None:
    import cv2

    text = text[:48]
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    y = max(th + 6, y)
    cv2.rectangle(img, (x, y - th - 6), (x + tw + 8, y + 2), col, -1)
    cv2.putText(img, text, (x + 4, y - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (20, 20, 20), 1, cv2.LINE_AA)


def draw_boxes(img: Any, boxes: list[tuple[tuple[float, float, float, float], str]]) -> Any:
    """Normalized [x, y, w, h] boxes with captions."""
    import cv2

    out = img.copy()
    h, w = out.shape[:2]
    for i, (b, text) in enumerate(boxes):
        x0, y0 = int(b[0] * w), int(b[1] * h)
        x1, y1 = int((b[0] + b[2]) * w), int((b[1] + b[3]) * h)
        cv2.rectangle(out, (x0, y0), (x1, y1), colour(i), 2)
        if text:
            label(out, text, x0, y0, colour(i))
    return out


def draw_masks(img: Any, masks: list[tuple[np.ndarray, str]], fill: float = 0.28) -> Any:
    """Boolean masks (any size; resized to the image) drawn as tinted shapes with outlines and captions."""
    import cv2

    out = img.copy()
    h, w = out.shape[:2]
    tint = out.copy()
    for i, (m, text) in enumerate(masks):
        mm = cv2.resize(m.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)
        tint[mm > 0] = colour(i)
        cnts, _ = cv2.findContours(mm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(out, cnts, -1, colour(i), 2)
        if text and cnts:
            x, y, _, _ = cv2.boundingRect(max(cnts, key=cv2.contourArea))
            label(out, text, x, y, colour(i))
    return cv2.addWeighted(tint, fill, out, 1 - fill, 0)


def tile(images: list[tuple[Any, str]], cols: int = 4, cell_w: int = 320) -> Any:
    """Captioned grid of images."""
    import cv2

    cells = []
    for img, text in images:
        h, w = img.shape[:2]
        c = cv2.resize(img, (cell_w, max(1, round(h * cell_w / w))), interpolation=cv2.INTER_AREA)
        ch = round(cell_w * 9 / 16)
        canvas = np.full((ch, cell_w, 3), 24, np.uint8)
        if c.shape[0] > ch:
            c = c[:ch]
        y = (ch - c.shape[0]) // 2
        canvas[y:y + c.shape[0]] = c
        if text:
            label(canvas, text, 4, ch - 6, (255, 199, 124))
        cells.append(canvas)
    if not cells:
        return np.zeros((10, 10, 3), np.uint8)
    while len(cells) % cols:
        cells.append(np.full_like(cells[0], 24))
    rows = [np.hstack(cells[i:i + cols]) for i in range(0, len(cells), cols)]
    return np.vstack(rows)


def frame_at(video: Path, t: float, rect: tuple[float, float, float, float]) -> Any:
    from loom.perception.board import picture_frames

    for _, f in picture_frames(video, [t], rect):
        return f.copy()
    return None


def mmss(t: float) -> str:
    return f"{int(t) // 60}:{int(t) % 60:02d}"
