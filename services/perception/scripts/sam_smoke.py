"""Smallest possible SAM 3.1 run: N frames, one prompt. Checks the GPU path before a full pipeline run.

    python scripts/sam_smoke.py samples/lesson.mp4 --prompt beaker --frames 10 --width 640
"""

from __future__ import annotations

import argparse
import os
import tempfile
import time
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", os.environ.get("LOOM_CPU_THREADS", "4"))

from loom_perception.config import SamConfig
from loom_perception.media import extract_frames


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("--prompt", default="beaker")
    ap.add_argument("--frames", type=int, default=10)
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--width", type=int, default=640)
    a = ap.parse_args()

    import torch

    from loom_perception.sam import Sam3Segmenter

    frames = extract_frames(a.video, Path(tempfile.mkdtemp()) / "f", a.fps, width=a.width, end=a.frames / a.fps)
    t0 = time.perf_counter()
    seg = Sam3Segmenter(SamConfig())
    print(f"model loaded in {time.perf_counter() - t0:.1f}s, GPU mem {torch.cuda.memory_allocated() / 2**30:.2f} GiB")
    t1 = time.perf_counter()
    dets = list(seg.segment_chunk(0, frames, [a.prompt]))
    dt = time.perf_counter() - t1
    print(f"{len(frames)} frames in {dt:.1f}s ({len(frames) / dt:.2f} fps), peak GPU mem {torch.cuda.max_memory_allocated() / 2**30:.2f} GiB")
    for d in dets:
        print(f"  t={d.t:5.1f}s id={d.local_id} score={d.score:.2f} box={[round(v, 3) for v in d.box]}")


if __name__ == "__main__":
    main()
