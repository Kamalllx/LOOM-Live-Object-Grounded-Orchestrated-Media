"""Crop and resize the captured screenshots (docs/paper, docs/img) into print figures for the paper (paper/fig/)."""

from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).parent / "fig"


def trim(im: Image.Image, thresh: int = 18, pad: int = 6) -> Image.Image:
    """Cut the dark letterbox margins around a video frame."""
    a = np.asarray(im.convert("L"))
    ys, xs = np.nonzero(a > thresh)
    if not len(xs):
        return im
    x0, x1, y0, y1 = max(0, xs.min() - pad), min(a.shape[1], xs.max() + pad), max(0, ys.min() - pad), min(a.shape[0], ys.max() + pad)
    return im.crop((x0, y0, x1, y1))


def save(src: Path, name: str, width: int, crop: tuple[float, float, float, float] | None = None, do_trim: bool = False) -> None:
    im = Image.open(src).convert("RGB")
    if crop:
        w, h = im.size
        im = im.crop((int(crop[0] * w), int(crop[1] * h), int(crop[2] * w), int(crop[3] * h)))
    if do_trim:
        im = trim(im)
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    im.save(OUT / f"{name}.jpg", quality=90)
    print(name, im.size)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    p, d = ROOT / "docs" / "paper", ROOT / "docs" / "img"
    save(d / "20-show-all-animation.jpg", "board-animation", 1100, do_trim=True)
    save(d / "23-chalkboard-elements.jpg", "board-chalk", 700, do_trim=True)
    save(d / "25-see-through-teacher.jpg", "board-seethrough", 700, do_trim=True)
    save(d / "24-teacher-present.jpg", "board-teacher", 700, do_trim=True)
    for t in ("050", "094", "175", "243", "310", "390"):
        save(p / f"explainer-construction-{t}.png", f"construct-{t}", 1000, crop=(0.0, 0.0, 1.0, 1.0))
    for t in ("075", "190"):
        save(p / f"explainer-concept-{t}.png", f"concept-{t}", 1000)
    save(p / "narration-checks.png", "narration-checks", 1500)
    save(p / "extension-overlay.png", "extension", 1600)
    save(p / "map.png", "map", 800)
    save(p / "compare-cuts.png", "compare-cuts", 1600)
    save(p / "hazard-before-52_0.png", "hazard-before", 900, do_trim=True)
    save(p / "hazard-after-52_0.png", "hazard-after", 900, do_trim=True)
    save(p / "fail-shards-53_0.png", "fail-shards", 900, do_trim=True)
    save(p / "fail-gloves-masked-68_9.png", "fail-gloves", 900, do_trim=True)
    save(p / "loom.png", "loom-tab", 800)
    save(p / "graph.png", "graph-tab", 800)


if __name__ == "__main__":
    main()
