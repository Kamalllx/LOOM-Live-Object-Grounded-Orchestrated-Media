"""README screenshots of every feature, captured from the running gateway in headless Edge (no model calls).

    uv run python -m loom.eval.readme_shots      # writes docs/img/1x-*.jpg .. 2x-*.jpg
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from loom.eval.batch import BASE, ROOT, Edge

OUT = ROOT / "docs" / "img"
SQL, BOARD = "sql_foreign_keys_clip_8f527f", "the_process_of_photosynthesis_b5be68"


async def wait_watch(e: Edge) -> None:
    for _ in range(120):
        await asyncio.sleep(1)
        if await e.js("!!document.querySelector('#play') && !document.querySelector('#play').disabled"):
            return


async def seek(e: Edge, t: float) -> None:
    await e.js(f"(async () => {{ const v = document.querySelector('#vid'); v.muted = true; v.currentTime = {t}; "
               "await v.play().catch(() => {}); await new Promise(r => setTimeout(r, 600)); v.pause(); "
               "document.querySelector('.stagewrap').scrollIntoView({block: 'center'}); return true; })()")
    await asyncio.sleep(1.4)


async def clip(e: Edge, sel: str, pad: int = 0) -> dict[str, float]:
    r: dict[str, float] = await e.js(f"(() => {{ const r = document.querySelector({json.dumps(sel)}).getBoundingClientRect(); "
                                     f"return {{x: r.left + scrollX - {pad}, y: r.top + scrollY - {pad}, width: r.width + {2 * pad}, "
                                     f"height: r.height + {2 * pad}}}; }})()")
    return r


async def go(e: Edge, url: str, wait: float = 3.5) -> None:
    await e.send("Page.navigate", {"url": url})
    await asyncio.sleep(wait)


async def lift_biggest(e: Edge, vid: str, t: float, want_parts: bool = True) -> None:
    target: Any = await e.js(f"""(async () => {{
      const g = await (await fetch('/api/videos/{vid}/graph')).json(), t = {t};
      const st = document.querySelector('#stage').getBoundingClientRect(), v = document.querySelector('#vid');
      const s = Math.min(st.width / v.videoWidth, st.height / v.videoHeight), fw = v.videoWidth * s, fh = v.videoHeight * s;
      const fx = st.left + (st.width - fw) / 2, fy = st.top + (st.height - fh) / 2, [rx, ry, rw, rh] = g.frame.content_rect;
      let best = null;
      for (const o of g.objects) for (const i of o.instances) {{
        if (t < i.start || t > i.end || !i.track.length) continue;
        const smp = i.track.reduce((a, b) => Math.abs(b.t - t) < Math.abs(a.t - t) ? b : a), [x, y, w, h] = smp.bbox;
        const score = ({'true' if want_parts else 'false'} ? (o.parts || []).length * 10 : 0) + w * h;
        if (!best || score > best.score) best = {{ score, x: fx + (rx + (x + w / 2) * rw) * fw, y: fy + (ry + (y + h / 2) * rh) * fh }};
      }}
      return best; }})()""")
    if target:
        await e.click(target["x"], target["y"])
        await asyncio.sleep(1.6)
        if not await e.js("document.querySelectorAll('.li-chip').length") and await e.js("!!document.querySelector('.li-parent')"):
            await e.js("document.querySelector('.li-parent').click(); true")
            await asyncio.sleep(1.6)


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    e = Edge(port=9361)
    await e.connect()
    try:
        # landing: the 3-D thread sculpture, the journey, the palette, upload
        await go(e, f"{BASE}/#/", 2)
        for _ in range(30):  # the library loads its lessons first; shooting earlier captured an empty page
            if await e.js("!!document.querySelector('#journey') && document.querySelectorAll('.lesson').length > 0"):
                break
            await asyncio.sleep(1)
        await asyncio.sleep(3)  # the curtain lifts and the sculpture weaves in
        await e.shot(OUT / "11-hero-3d.jpg")
        top, h = await e.js("document.querySelector('#journey').offsetTop"), await e.js("document.querySelector('#journey').offsetHeight")
        for name, f in (("12-journey-loom.jpg", 0.08), ("13-journey-lift.jpg", 0.5), ("14-journey-agents.jpg", 0.72)):
            await e.js(f"scrollTo(0, {top + (h - 900) * f}); true")
            await asyncio.sleep(2)
            await e.shot(OUT / name)
        await e.js("scrollTo(0, 0); true")
        await asyncio.sleep(1)
        await e.js("window.loomPalette(); true")
        await asyncio.sleep(0.8)
        await e.send("Input.insertText", {"text": "photo"})
        await asyncio.sleep(0.6)
        await e.shot(OUT / "15-command-palette.jpg")
        await e.js("document.querySelector('.palette').click(); document.querySelector('.addlesson').scrollIntoView({block: 'center'}); true")
        await asyncio.sleep(2)
        await e.shot(OUT / "16-add-lesson.jpg", await clip(e, ".addlesson", 12))
        # agent runs
        await go(e, f"{BASE}/#/runs", 4)
        await e.shot(OUT / "17-agent-runs.jpg")
        async with httpx.AsyncClient(timeout=30) as c:
            runs = (await c.get(f"{BASE}/api/runs", params={"limit": 300})).json()
        sess = next((r for r in runs if r["kind"] == "session" and r["calls"] >= 9), None)
        ing = next((r for r in runs if r["kind"] == "ingest" and r["status"] == "done" and r["video_id"] == BOARD), None)
        for name, r in (("18-run-session.jpg", sess), ("19-run-ingest.jpg", ing)):
            if r:
                await go(e, f"{BASE}/#/run/{r['run_id']}", 11)
                await e.shot(OUT / name)
        # the watch page on an animation: every element outlined, one lifted with its parts, a part chosen
        await go(e, f"{BASE}/#/runs", 2)
        await e.js("localStorage.setItem('loom.showall','1'); true")
        await go(e, f"{BASE}/#/watch/{SQL}", 2)
        await wait_watch(e)
        await seek(e, 17)
        await e.shot(OUT / "20-show-all-animation.jpg", await clip(e, ".stagewrap", 8))
        await lift_biggest(e, SQL, 17)
        await e.shot(OUT / "21-lift-parts.jpg")
        chip = await e.js("(() => { const c = document.querySelectorAll('.li-chip')[1] || document.querySelector('.li-chip'); "
                          "if (!c) return null; const b = c.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; })()")
        if chip:
            await e.click(chip[0], chip[1])
            await asyncio.sleep(1.2)
            await e.shot(OUT / "22-ask-about-a-part.jpg")
        # the filmed chalkboard: elements, the teacher made transparent, a lifted board element
        await go(e, f"{BASE}/#/watch/{BOARD}", 2)
        await wait_watch(e)
        await seek(e, 50)
        await e.shot(OUT / "23-chalkboard-elements.jpg", await clip(e, ".stagewrap", 8))
        await e.js("localStorage.setItem('loom.showall','0'); document.querySelector('#showall').click(); true")
        await asyncio.sleep(0.8)
        await e.shot(OUT / "24-teacher-present.jpg", await clip(e, ".stagewrap", 8))
        await e.js("document.querySelector('#seethru').click(); true")
        await asyncio.sleep(1.5)
        await e.shot(OUT / "25-see-through-teacher.jpg", await clip(e, ".stagewrap", 8))
        # a 3-D explainer, mid-scene
        scenes = sorted((ROOT / "data" / "media" / "scenes").glob("*/scene.json"), key=lambda p: p.stat().st_mtime)
        best = next((p for p in reversed(scenes) if json.loads(p.read_text(encoding="utf-8")).get("version") == 3), None)
        if best:
            url = f"/media/scenes/{best.parent.name}/scene.json"
            await go(e, f"{BASE}/#/runs", 2)
            await e.js("(async () => { document.body.style.overflow = 'hidden'; const host = document.createElement('div'); "
                       "Object.assign(host.style, {position: 'fixed', inset: '0', zIndex: 200, background: '#03090d', display: 'grid', "
                       "placeItems: 'center', padding: '20px'}); const inner = document.createElement('div'); inner.style.width = '1320px'; "
                       f"host.appendChild(inner); document.body.appendChild(host); const s = await (await fetch('{url}')).json(); "
                       "window.LoomScene.mount(inner, s); return true; })()")
            for name, wait in (("26-explainer-intro.jpg", 1.2), ("27-explainer-3d.jpg", 16.5), ("28-explainer-3d-b.jpg", 9)):
                await asyncio.sleep(wait)
                await e.shot(OUT / name)
    finally:
        await e.close()
    print("shots written to", OUT)


if __name__ == "__main__":
    asyncio.run(main())
