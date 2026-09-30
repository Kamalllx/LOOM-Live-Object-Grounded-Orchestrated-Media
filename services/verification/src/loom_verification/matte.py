"""Matte videos for redaction masks: white where the object is, black elsewhere, starting at the mask's start.

Built from Person 1's per-frame COCO RLE masks when the sidecar has them (pixel-accurate), otherwise from the
tracked boxes. Encoded as H.264 so browsers can play it; the delivery client can use it as a CSS/WebGL mask.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np


def rle_counts_from_string(s: str) -> list[int]:
    """Decode COCO's compressed RLE string (same algorithm as pycocotools' rleFrString)."""
    counts: list[int] = []
    p = 0
    while p < len(s):
        x, k, more = 0, 0, True
        while more:
            c = ord(s[p]) - 48
            x |= (c & 0x1F) << (5 * k)
            more = bool(c & 0x20)
            p += 1
            k += 1
            if not more and (c & 0x10):
                x |= -1 << (5 * k)
        if len(counts) > 2:
            x += counts[-2]
        counts.append(x)
    return counts


def decode_rle(rle: dict) -> np.ndarray:
    """COCO RLE ({"size": [h, w], "counts": str | list}) -> boolean mask of shape (h, w)."""
    h, w = rle["size"]
    counts = rle["counts"]
    if isinstance(counts, str):
        counts = rle_counts_from_string(counts)
    flat = np.zeros(h * w, dtype=bool)
    pos, val = 0, False
    for n in counts:
        if val:
            flat[pos:pos + n] = True
        pos += n
        val = not val
    return flat.reshape((w, h)).T      # COCO masks are column-major


def _even(n: int) -> int:
    return max(2, n - (n % 2))


def matte_size(frames: list[dict], max_width: int) -> tuple[int, int]:
    rle = next((f.get("rle") for f in frames if f.get("rle")), None)
    h, w = (rle["size"] if rle else (720, 1280))
    scale = min(1.0, max_width / w)
    return _even(round(w * scale)), _even(round(h * scale))


def _frame_mask(frame: dict, size: tuple[int, int], pad: float) -> np.ndarray:
    W, H = size
    if frame.get("rle"):
        m = decode_rle(frame["rle"]).astype(np.uint8) * 255
        m = cv2.resize(m, (W, H), interpolation=cv2.INTER_NEAREST)
    else:
        m = np.zeros((H, W), np.uint8)
        x, y, bw, bh = frame["box"]
        m[max(0, int(y * H)):min(H, math.ceil((y + bh) * H)), max(0, int(x * W)):min(W, math.ceil((x + bw) * W))] = 255
    r = max(1, int(pad * max(W, H)))
    return cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))


def render_matte(frames: list[dict], start: float, end: float, out_path: Path, *, fps: int = 10,
                 max_width: int = 640, pad: float = 0.04) -> Path:
    """Render the matte for [start, end). Frames are held until the next sample (no gaps in coverage)."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not on PATH")
    frames = sorted(frames, key=lambda f: f["t"])
    size = matte_size(frames, max_width)
    key = hashlib.sha256(json.dumps([start, end, fps, size, pad, [(f["t"], f.get("box"), bool(f.get("rle"))) for f in frames]],
                                    default=str).encode()).hexdigest()[:16]
    stamp = out_path.with_suffix(".key")
    if out_path.exists() and stamp.exists() and stamp.read_text() == key:
        return out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    W, H = size
    n = max(1, math.ceil((end - start) * fps))
    times = [f["t"] for f in frames]
    cache: dict[int, np.ndarray] = {}
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}", "-r", str(fps),
         "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)],
        stdin=subprocess.PIPE)
    try:
        for i in range(n):
            t = start + i / fps
            j = min(range(len(times)), key=lambda k: abs(times[k] - t))
            if j not in cache:
                cache[j] = _frame_mask(frames[j], size, pad)
            proc.stdin.write(cache[j].tobytes())
    finally:
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed to write {out_path}")
    stamp.write_text(key)
    return out_path
