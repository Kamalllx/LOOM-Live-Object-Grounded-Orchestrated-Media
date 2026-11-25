"""Render the report's SVG charts (docs/figures) to 3x PNGs for the paper (paper/fig/), in headless Edge."""

import asyncio
from pathlib import Path

from loom.eval.batch import ROOT, Edge

CHARTS = ["grounding-rules-demo", "hazard-timeline-demo", "hazard-timeline-glass", "critic-faults", "latency",
          "batch-stage-share", "batch-elements-by-style", "grounding-rules-glass"]
OUT = Path(__file__).parent / "fig"


async def main() -> None:
    OUT.mkdir(exist_ok=True)
    e = Edge(port=9401, scale=3, width=920, height=900)
    await e.connect()
    try:
        for name in CHARTS:
            svg = ROOT / "docs" / "figures" / f"{name}.svg"
            await e.send("Page.navigate", {"url": svg.resolve().as_uri()})
            await asyncio.sleep(0.8)
            w, h = await e.js("(() => { const s = document.querySelector('svg'); return [s.width.baseVal.value, s.height.baseVal.value]; })()")
            await e.shot(OUT / f"chart-{name}.png", {"x": 0, "y": 0, "width": w, "height": h})
            print(name, w, h)
    finally:
        await e.close()


if __name__ == "__main__":
    asyncio.run(main())
