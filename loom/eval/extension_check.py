"""`python -m loom.eval.extension_check [youtube_id] [title-substring]` — load the YouTube extension in headless Edge,
open a real watch page, open a library explainer and check that the 3-D player (not the 2-D fallback) plays it.
Screenshots go to the scratch directory given as `--out` (default: data/eval/extension/)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from loom.eval.batch import ROOT, Edge


async def run(yt: str, want: str, out: Path) -> dict[str, object]:
    out.mkdir(parents=True, exist_ok=True)
    e = Edge(port=9399, scale=1, width=1440, height=900, extension=str(ROOT / "extension"))
    await e.connect()
    try:
        await e.send("Page.navigate", {"url": f"https://www.youtube.com/watch?v={yt}"})
        for _ in range(45):
            await asyncio.sleep(1)
            if await e.js("!!document.getElementById('loom-root') && !!document.querySelector('video')"):
                break
        for _ in range(60):  # ads
            if not await e.js("!!document.querySelector('.ad-showing')"):
                break
            await e.js("document.querySelector('.ytp-skip-ad-button, .ytp-ad-skip-button-modern, .ytp-ad-skip-button')?.click(); true")
            await asyncio.sleep(1)
        await e.js("document.querySelector('video')?.pause(); true")
        for _ in range(30):
            if await e.js("!!document.querySelector('[data-act=\"tab\"][data-tab=\"lib\"]:not([disabled])')"):
                break
            await asyncio.sleep(1)
        await e.shot(out / "panel.jpg")
        await e.js("document.querySelector('[data-act=\"tab\"][data-tab=\"lib\"]').click(); true")
        await asyncio.sleep(3)
        await e.shot(out / "library.jpg")
        opened = await e.js(f"(() => {{ const items = [...document.querySelectorAll('[data-act=\"libopen\"]')]; "
                            f"const b = items.find((x) => x.innerText.toLowerCase().includes({want.lower()!r})) || items[0]; "
                            "if (!b) return null; b.click(); return b.innerText.slice(0, 80); })()")
        await asyncio.sleep(14)
        state = await e.js("JSON.stringify({modal: !!document.getElementById('loom-modal'), "
                           "player3d: !!document.querySelector('#loom-modal .lsc3 canvas'), "
                           "player2d: !!document.querySelector('#loom-modal .lsc'), "
                           "checks: document.querySelectorAll('#loom-modal ol.loom-checks li').length})")
        await e.shot(out / "explainer-1.jpg")
        await asyncio.sleep(10)
        await e.shot(out / "explainer-2.jpg")
        await e.js("const d = document.querySelector('#loom-modal details.loom-story'); if (d) d.open = true; "
                   "document.querySelector('#loom-modal .loom-modal-box')?.scrollTo(0, 99999); true")
        await asyncio.sleep(1)
        await e.shot(out / "explainer-checks.jpg")
        return {"opened": opened, "state": state}
    finally:
        await e.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = Path(next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--out=")), ROOT / "data" / "eval" / "extension"))
    print(asyncio.run(run(args[0] if args else "XapGLl0ppD8", args[1] if len(args) > 1 else "bisect", out)))
