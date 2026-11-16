"""Print-resolution figures for the paper (PNG, >= 1600 px wide, page content only - no browser chrome), captured
from the running gateway in headless Edge at 2-4x device pixel ratio.

    uv run python -m loom.eval.paper_figures [name ...]     # -> docs/paper/*.png

Figures: map, graph, loom (side panels after a question), compare (three viewers' cuts), hazard-before /
hazard-after (Parent + child, the mask applied), explainer frames (a concept scene and a construction scene),
narration-checks (the fact-checked narration panel), extension (the overlay on a real YouTube watch page),
fail-gloves (safe gloves masked for the child profile), fail-shards (shards outside the mask).
"""

from __future__ import annotations

import asyncio
import json
import sys

from loom.eval.batch import BASE, ROOT, SEEK_JS, Edge, ready

OUT = ROOT / "docs" / "paper"
DEMO, GLASS, SQL = (
    "acid_base_neutralization_d752a6",
    "water_sciences_laboratory_tutorial_glass_a98109",
    "sql_explained_in_100_seconds_4462e4",
)
CONCEPT_SCENE, CONSTRUCT_SCENE = "96acc047616c9efda8bc170b", "1d1bad4d9a82aca791562e79"
EXTENSION = ROOT / "extension"


async def clip(e: Edge, sel: str, pad: int = 0) -> dict[str, float]:
    r: dict[str, float] = await e.js(
        f"(() => {{ const r = document.querySelector({json.dumps(sel)}).getBoundingClientRect(); "
        f"return {{x: r.left + scrollX - {pad}, y: r.top + scrollY - {pad}, width: r.width + {2 * pad}, "
        f"height: r.height + {2 * pad}}}; }})()"
    )
    return r


async def go(e: Edge, url: str, wait: float = 3.0) -> None:
    await e.send("Page.navigate", {"url": url})
    await asyncio.sleep(wait)


async def watch(e: Edge, vid: str, viewer: str, showall: bool = False) -> None:
    await go(e, f"{BASE}/#/runs", 2)
    await e.js(
        f"localStorage.setItem('loom.viewer', '{viewer}'); localStorage.setItem('loom.showall', '{int(showall)}'); true"
    )
    # a full page load: the app reads the viewer once, when it starts
    await go(e, f"{BASE}/?v={viewer}&t={asyncio.get_running_loop().time():.0f}#/watch/{vid}", 1)
    await ready(e)
    await e.js("document.querySelectorAll('.toast, .readychip, .nudge').forEach((x) => x.remove()); true")


async def seek(e: Edge, t: float) -> None:
    for _ in range(10):
        if await e.js(SEEK_JS % t):
            break
        await asyncio.sleep(1)
    await asyncio.sleep(1.5)


async def tab(e: Edge, name: str, wait: float = 2.5) -> None:
    await e.js(f"document.querySelector('.tab[data-tab=\"{name}\"]').click(); true")
    await asyncio.sleep(wait)


async def side_panels(e: Edge) -> None:
    await watch(e, DEMO, "learner_priya")
    await e.js(
        "document.querySelector('#q').value = 'Why does the indicator turn green at pH 7?'; "
        "document.querySelector('#doAnswer').click(); true"
    )
    for _ in range(90):
        await asyncio.sleep(1)
        if await e.js(
            "!!document.querySelector('#results') && document.querySelector('#results').innerText.length > 80 "
            "&& !/Thinking|Searching|Answering/i.test(document.querySelector('#results').innerText.slice(0, 60))"
        ):
            break
    await asyncio.sleep(2)
    await e.shot(OUT / "ask-answer.png", await clip(e, "aside.side"))
    for name, file in (("Map", "map.png"), ("Graph", "graph.png"), ("Loom", "loom.png")):
        await tab(e, name, 4)
        await e.shot(OUT / file, await clip(e, "aside.side"))


async def compare(e: Edge) -> None:
    await go(e, f"{BASE}/#/weave/{DEMO}", 12)
    await e.js("scrollTo(0, 0); true")
    await asyncio.sleep(2)
    await e.shot(OUT / "compare-cuts.png", await clip(e, "main", 0))


async def hazard(e: Edge) -> None:
    await watch(e, DEMO, "learner_family")
    for t in (52.0, 54.5):
        await seek(e, t)
        tag = f"{t:.1f}".replace(".", "_")
        await e.js(
            "document.querySelector('#ov').style.visibility = 'hidden'; document.querySelector('#mb').style.visibility = 'hidden'; true"
        )
        await asyncio.sleep(0.6)
        await e.shot(OUT / f"hazard-before-{tag}.png", await clip(e, ".stagewrap"))
        await e.js(
            "document.querySelector('#ov').style.visibility = 'visible'; document.querySelector('#mb').style.visibility = 'visible'; true"
        )
        await asyncio.sleep(0.8)
        await e.shot(OUT / f"hazard-after-{tag}.png", await clip(e, ".stagewrap"))


async def failures(e: Edge) -> None:
    await watch(e, GLASS, "learner_family")
    for t in (68.9, 69.6):
        await seek(e, t)
        await e.shot(OUT / (f"fail-gloves-masked-{t:.1f}".replace(".", "_") + ".png"), await clip(e, ".stagewrap"))
    await watch(e, DEMO, "learner_family")
    for t in (50.5, 53.0, 56.0):
        await seek(e, t)
        await e.shot(OUT / (f"fail-shards-{t:.1f}".replace(".", "_") + ".png"), await clip(e, ".stagewrap"))


async def scenes(e: Edge) -> None:
    for key, name, times in (
        (CONCEPT_SCENE, "explainer-concept", (2.0, 7.5, 13.0, 19.0, 26.0, 35.0)),
        (CONSTRUCT_SCENE, "explainer-construction", (5.0, 9.4, 17.5, 24.3, 31.0, 39.0)),
    ):
        await go(e, f"{BASE}/#/runs", 2)
        await e.js(
            "(async () => { document.body.style.overflow = 'hidden'; const host = document.createElement('div'); "
            "host.id = 'figscene'; Object.assign(host.style, {position: 'fixed', left: '0', top: '0', width: '1280px', zIndex: 200}); "
            f"document.body.appendChild(host); const s = await (await fetch('/media/scenes/{key}/scene.json')).json(); "
            "window.LoomScene.mount(host, s); return true; })()"
        )
        t = 0.0
        for at in times:
            await asyncio.sleep(at - t)
            t = at
            await e.shot(OUT / f"{name}-{int(at * 10):03d}.png", {"x": 0, "y": 0, "width": 1280, "height": 720})


async def narration(e: Edge) -> None:
    await watch(e, DEMO, "learner_priya")
    await tab(e, "Library", 3)
    await e.js(
        "(() => { const b = [...document.querySelectorAll('.libitem')].find((x) => /salt and water/i.test(x.innerText)) "
        "|| document.querySelector('.libitem'); b.click(); return true; })()"
    )
    await asyncio.sleep(3)
    await e.js(
        "document.querySelector('.modal details.sb').open = true; "
        "document.querySelector('.modal .scenehost')?.remove(); true"
    )
    await asyncio.sleep(1.2)
    await e.shot(OUT / "narration-checks.png", await clip(e, ".modal", 0))


async def extension() -> None:
    """The extension on a real YouTube watch page (Water Sciences lesson): Parent + child viewer, cut woven, paused at
    the pipette on the floor so the overlay and its mask are visible."""
    e = Edge(port=9381, scale=2, width=1440, height=900, extension=str(EXTENSION))
    await e.connect()
    try:
        await go(e, "https://www.youtube.com/watch?v=ZZO-v10h8tc", 6)
        for _ in range(40):
            if await e.js("!!document.querySelector('video') && !!document.getElementById('loom-root')"):
                break
            await asyncio.sleep(1)
        for _ in range(60):  # ads first: skip when possible, else wait them out
            if not await e.js("!!document.querySelector('.ad-showing')"):
                break
            await e.js(
                "document.querySelector('.ytp-skip-ad-button, .ytp-ad-skip-button-modern, .ytp-ad-skip-button')?.click(); true"
            )
            await asyncio.sleep(1)
        await e.js(
            "(() => { const b = [...document.querySelectorAll('.loom-learner')].find((x) => /Parent/.test(x.innerText)); "
            "b?.click(); return !!b; })()"
        )
        await asyncio.sleep(1.5)
        await e.js("document.querySelector('[data-act=\"weave\"]')?.click(); true")
        await asyncio.sleep(14)
        await e.js(
            "(() => { const v = document.querySelector('video'); v.muted = true; v.currentTime = 63.2; v.play(); "
            "return true; })()"
        )
        await asyncio.sleep(2.5)
        await e.js("document.querySelector('video').pause(); true")
        await asyncio.sleep(2)
        await e.shot(OUT / "extension-overlay.png")
        print(
            "extension page:",
            await e.js(
                "JSON.stringify({root: !!document.getElementById('loom-root'), "
                "ad: !!document.querySelector('.ad-showing'), t: document.querySelector('video')?.currentTime})"
            ),
        )
    finally:
        await e.close()


JOBS = {
    "panels": side_panels,
    "compare": compare,
    "hazard": hazard,
    "failures": failures,
    "scenes": scenes,
    "narration": narration,
}


async def main(names: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    todo = names or [*JOBS, "extension"]
    for name in todo:
        if name == "extension":
            await extension()
            continue
        scale = 4.5 if name in ("panels", "narration") else 2
        e = Edge(port=9380, scale=scale)
        await e.connect()
        try:
            await JOBS[name](e)
            print("done", name, flush=True)
        except Exception as exc:
            print("FAILED", name, type(exc).__name__, str(exc)[:300], flush=True)
        finally:
            await e.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
