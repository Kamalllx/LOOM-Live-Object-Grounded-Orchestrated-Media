"""Review video: masks, object labels, transcript, OCR boxes and the active concept drawn over the source."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

PALETTE = [(32, 176, 255), (199, 212, 45), (250, 139, 167), (132, 101, 255), (237, 243, 245), (60, 200, 120)]  # BGR


def _decode(rle: dict, shape: tuple[int, int]) -> np.ndarray:
    import cv2
    from pycocotools import mask as mask_utils

    m = mask_utils.decode({"size": rle["size"], "counts": rle["counts"].encode("ascii")})
    if m.shape[:2] != shape:
        m = cv2.resize(m, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
    return m.astype(bool)


def render_overlay(video: Path, result_dir: Path, out: Path) -> Path:
    import cv2

    graph = json.loads((result_dir / "concept-graph.json").read_text(encoding="utf-8"))
    ocr_path = result_dir / "stages" / "ocr.json"
    ocr = json.loads(ocr_path.read_text(encoding="utf-8"))["payload"] if ocr_path.is_file() else []
    masks = {}
    for o in graph["objects"]:
        ref = o.get("mask_ref")
        if ref and (result_dir / ref).is_file():
            masks[o["object_id"]] = json.loads((result_dir / ref).read_text(encoding="utf-8"))

    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    tmp = Path(tempfile.mkdtemp()) / "overlay.mp4"
    writer = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    colors = {o["object_id"]: PALETTE[i % len(PALETTE)] for i, o in enumerate(graph["objects"])}
    font, i = cv2.FONT_HERSHEY_SIMPLEX, 0
    scale = max(0.5, h / 1080)

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = i / fps
        i += 1
        layer = frame.copy()
        for oid, m in masks.items():
            step = 1.0 / m.get("sample_fps", 2.0)
            near = min(m["frames"], key=lambda f: abs(f["t"] - t), default=None)
            if not near or abs(near["t"] - t) > step:
                continue
            mask = _decode(near["rle"], (h, w))
            layer[mask] = (0.45 * np.array(colors[oid]) + 0.55 * layer[mask]).astype(np.uint8)
            x, y = int(near["box"][0] * w), int(near["box"][1] * h)
            label = next(o["label"] for o in graph["objects"] if o["object_id"] == oid)
            _chip(layer, f"{oid} {label} {near['score']:.2f}", (x, max(0, y - int(8 * scale))), colors[oid], scale)
        for span in ocr:
            if span["start"] <= t < span["end"] and span.get("bbox"):
                bx, by, bw, bh = span["bbox"]
                pad = int(8 * scale)
                p0, p1 = (int(bx * w) - pad, int(by * h) - pad), (int((bx + bw) * w) + pad, int((by + bh) * h) + pad)
                cv2.rectangle(layer, p0, p1, (199, 212, 45), max(2, int(3 * scale)))
                _chip(layer, "OCR", (p0[0], p1[1] + int(26 * scale)), (199, 212, 45), scale)
        said = next((s for s in graph["transcript"] if s["start"] <= t < s["end"]), None)
        if said:
            _caption(layer, said["text"], scale)
        node = next((n for n in graph["concept_nodes"] if n.get("start", 0) <= t < n.get("end", 0)), None)
        if node:
            _chip(layer, f"CONCEPT {node['node_id']} | {node['label']}", (int(16 * scale), h - int(110 * scale)), (237, 243, 245), scale)
        writer.write(layer)
    cap.release()
    writer.release()

    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(tmp), "-i", str(video), "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)],
            check=True,
        )
    else:
        shutil.move(str(tmp), out)
    return out


def _chip(img, text: str, org: tuple[int, int], color, scale: float) -> None:
    import cv2

    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), base = cv2.getTextSize(text, font, 0.6 * scale, 1)
    x, y = org
    y = max(th + 6, y)
    cv2.rectangle(img, (x, y - th - 6), (x + tw + 10, y + base), color, -1)
    cv2.putText(img, text, (x + 5, y - 3), font, 0.6 * scale, (16, 12, 11), max(1, int(scale)), cv2.LINE_AA)


def _caption(img, text: str, scale: float) -> None:
    import cv2

    font = cv2.FONT_HERSHEY_SIMPLEX
    h, w = img.shape[:2]
    (tw, th), _ = cv2.getTextSize(text, font, 0.8 * scale, 2)
    x, y = max(10, (w - tw) // 2), h - int(40 * scale)
    cv2.rectangle(img, (x - 10, y - th - 12), (x + tw + 10, y + 10), (16, 12, 11), -1)
    cv2.putText(img, text, (x, y), font, 0.8 * scale, (237, 243, 245), max(1, int(2 * scale)), cv2.LINE_AA)
