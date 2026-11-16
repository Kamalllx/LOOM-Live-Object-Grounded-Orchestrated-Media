"""Batch evaluation on short lessons: every video goes through the running gateway exactly as a user's would.

For each `category | url` line: ingest (POST /api/videos/link, wait for the run to end), read what perception built
from the graph (elements by source, parts, concepts, quiz, timings, degradations), ask the answer agent one question
(latency, grounded or not), and capture three screenshots in headless Edge over the DevTools protocol: every element
outlined and labelled, one element lifted out with its parts, and the agent-run timeline.

Results: `<data>/eval/batch/<video_id>.json`, `<data>/eval/batch/summary.json`; screenshots in `docs/img/batch/`.
Resumable: videos already in the summary with status "ok" are skipped.

    uv run python -m loom.eval.batch tests/eval_data/shorts_batch.txt
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

BASE = "http://127.0.0.1:8000"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
QUESTION = "What is the main idea of this lesson?"
ROOT = Path(__file__).resolve().parents[2]


def load_list(path: Path) -> list[dict[str, str]]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cat, url = (x.strip() for x in line.split("|", 1))
        out.append({"category": cat, "url": url})
    return out


def youtube_id(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
    if not m:
        raise ValueError(url)
    return m.group(1)


def busiest_time(g: dict[str, Any]) -> float:
    """The moment with the most elements on screen (where the overlay screenshot says the most)."""
    spans = [(i["start"], i["end"]) for o in g["objects"] for i in o["instances"]]
    if not spans:
        return g["duration_seconds"] / 2
    cands = sorted({round((a + b) / 2, 2) for a, b in spans} | {round(g["duration_seconds"] * k / 10, 2) for k in range(1, 10)})
    return max(cands, key=lambda t: (sum(1 for a, b in spans if a <= t <= b), -abs(t - g["duration_seconds"] / 2)))


def metrics(g: dict[str, Any]) -> dict[str, Any]:
    objs = g["objects"]
    board = [o for o in objs if o.get("phrase_source") == "board"]
    m = g["perception_meta"]["models"]
    seg = re.search(r"(\d+) segmented", m.get("elements", "") or "")
    return {
        "title": g["title"], "duration_s": round(g["duration_seconds"], 1),
        "frame": f'{g["frame"]["width"]}x{g["frame"]["height"]}', "shots": len(g["shots"]),
        "sentences": len(g["transcript"]), "screen_text": len(g["on_screen_text"]),
        "objects": len(objs), "board_or_scene_elements": len(board), "detected_objects": len(objs) - len(board),
        "segment_everything_tracks": int(seg.group(1)) if seg else 0,
        "board_like": m.get("board", ""), "drawn": m.get("elements", ""),
        "kinds": {k: sum(1 for o in board if o.get("element_kind") == k) for k in
                  sorted({o.get("element_kind") or "text" for o in board})},
        "with_parts": sum(1 for o in objs if o.get("parts")), "parts": sum(len(o.get("parts") or []) for o in objs),
        "part_labels": [p["label"] for o in objs for p in (o.get("parts") or [])][:12],
        "element_labels": [o["label"] for o in objs][:20],
        "concepts": [c["label"] for c in g["concept_nodes"]], "quiz_questions": len(g.get("quiz_bank", [])),
        "child_unsafe": [o["label"] for o in objs if o["safety"]["child_unsafe"]],
        "timings_s": g["perception_meta"]["timings_s"], "degraded": g["perception_meta"]["degraded"],
    }


async def call(c: httpx.AsyncClient, method: str, url: str, **kw: Any) -> Any:
    """One API call, retried through transient network errors (the gateway is busy perceiving meanwhile)."""
    for attempt in range(8):
        try:
            r = await c.request(method, url, **kw)
            return r.json()
        except (httpx.TransportError, ValueError):
            if attempt == 7:
                raise
            await asyncio.sleep(3 * (attempt + 1))
    return None


async def ingest(c: httpx.AsyncClient, url: str, timeout_s: float = 2400) -> dict[str, Any]:
    yid = youtube_id(url)
    t0 = time.perf_counter()
    r = await call(c, "POST", f"{BASE}/api/videos/link", json={"url": url, "max_height": 720})
    run_id = None
    if r.get("status") == "processing":
        ch, after = r["channel"], r.get("after", 0)
        while True:
            if time.perf_counter() - t0 > timeout_s:
                return {"status": "timeout", "seconds": round(time.perf_counter() - t0, 1)}
            ev = (await call(c, "GET", f"{BASE}/api/channels/{ch}/latest", params={"limit": 50}))["events"]
            end = next((e for e in ev if e["id"] > after and e["kind"] in ("delivered", "error")), None)
            if end:
                if end["kind"] == "error":
                    return {"status": "error", "error": end["data"].get("message"), "seconds": round(time.perf_counter() - t0, 1)}
                break
            await asyncio.sleep(5)
        runs = await call(c, "GET", f"{BASE}/api/runs", params={"channel": ch, "limit": 1})
        run_id = runs[0]["run_id"] if runs else None
    look = await call(c, "GET", f"{BASE}/api/lookup", params={"youtube_id": yid})
    if not look.get("ready"):
        return {"status": "error", "error": "no graph after ingest", "seconds": round(time.perf_counter() - t0, 1)}
    if run_id is None:  # processed before: the newest ingest run of that channel
        runs = await call(c, "GET", f"{BASE}/api/runs", params={"channel": f"ingest_{yid.replace('-', '_')}", "limit": 1})
        run_id = runs[0]["run_id"] if runs else None
    return {"status": "ok", "video_id": look["video_id"], "run_id": run_id,
            "seconds": round(time.perf_counter() - t0, 1)}


async def probe(c: httpx.AsyncClient, vid: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        r = await call(c, "POST", f"{BASE}/api/videos/{vid}/ask", json={"question": QUESTION, "learner_id": "learner_priya"},
                       timeout=300)
        return {"question": QUESTION, "answer": r.get("answer", ""), "found_in_video": r.get("found_in_video"),
                "citations": len(r.get("citations", [])), "seconds": round(time.perf_counter() - t0, 1)}
    except Exception as e:
        return {"question": QUESTION, "error": f"{type(e).__name__}: {e}"}


class Edge:
    """Headless Edge over the DevTools protocol (WebGL on, so the 3-D views render)."""

    def __init__(self, port: int = 9351, scale: float = 1.0, width: int = 1440, height: int = 900,
                 extension: str | None = None) -> None:
        self.port, self.scale, self.size = port, scale, (width, height)
        self.prof = tempfile.mkdtemp(prefix="loom-edge-")
        self.proc = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={self.prof}",
                                      f"--window-size={width},{height}", "--mute-audio", "--autoplay-policy=no-user-gesture-required",
                                      "--use-angle=d3d11", "--enable-gpu", "--ignore-gpu-blocklist",
                                      *([f"--load-extension={extension}", f"--disable-extensions-except={extension}"]
                                        if extension else []), "about:blank"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.ws: Any = None
        self.n = 0

    async def connect(self) -> None:
        import websockets

        for _ in range(60):
            try:
                pages = httpx.get(f"http://127.0.0.1:{self.port}/json", timeout=2).json()  # noqa: ASYNC210 - startup poll
                url = next(p["webSocketDebuggerUrl"] for p in pages if p["type"] == "page")
                self.ws = await websockets.connect(url, max_size=64 * 2**20)
                break
            except Exception:
                await asyncio.sleep(0.5)
        await self.send("Page.enable")
        await self.send("Runtime.enable")
        await self.send("Emulation.setDeviceMetricsOverride", {"width": self.size[0], "height": self.size[1],
                                                               "deviceScaleFactor": self.scale, "mobile": False})

    async def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.n += 1
        mid = self.n
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    async def js(self, expr: str) -> Any:
        r = await self.send("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True})
        if r.get("exceptionDetails"):
            raise RuntimeError(str(r["exceptionDetails"])[:300])
        return r["result"].get("value")

    async def shot(self, path: Path, clip: dict[str, float] | None = None) -> None:
        params: dict[str, Any] = {"format": "png"} if path.suffix == ".png" else {"format": "jpeg", "quality": 88}
        if clip:
            params["clip"] = {**clip, "scale": 1}
        data = (await self.send("Page.captureScreenshot", params))["data"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(data))

    async def click(self, x: float, y: float) -> None:
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            await self.send("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1})

    async def close(self) -> None:
        try:
            if self.ws:
                await self.ws.close()
        finally:
            self.proc.kill()


STAGE_JS = """(() => { const r = document.querySelector('.stagewrap').getBoundingClientRect();
  return {x: r.left + scrollX, y: r.top + scrollY, width: r.width, height: r.height}; })()"""  # page coordinates


SEEK_JS = """(async () => { const v = document.querySelector('#vid'); if (!v) return false; v.muted = true;
  v.currentTime = %s; await v.play().catch(() => {}); await new Promise(r => setTimeout(r, 600)); v.pause();
  document.querySelector('.stagewrap')?.scrollIntoView({block: 'center'}); return true; })()"""


async def ready(edge: Edge) -> None:
    """Wait until the player can play and the agents have woven the cut (press Skip after 90 s)."""
    for _ in range(120):
        await asyncio.sleep(1)
        if await edge.js("!!document.querySelector('#play') && !document.querySelector('#play').disabled"):
            break
    for _ in range(90):
        if not await edge.js("!!document.querySelector('#lpskip') && !!document.querySelector('#lpskip').offsetParent"):
            break
        await asyncio.sleep(1)
    else:
        await edge.js("document.querySelector('#lpskip')?.click(); true")
    await asyncio.sleep(1.5)


async def shoot(edge: Edge, g: dict[str, Any], run_id: str | None, out: Path) -> dict[str, Any]:
    vid, t = g["video_id"], busiest_time(g)
    shots: dict[str, Any] = {"t": t}
    await edge.send("Page.navigate", {"url": f"{BASE}/#/runs"})  # storage belongs to the site's origin
    await asyncio.sleep(2)
    await edge.js("localStorage.setItem('loom.showall','1'); true")
    await edge.send("Page.navigate", {"url": f"{BASE}/#/watch/{vid}"})
    await ready(edge)
    for _ in range(10):  # the stage can re-render once the cut lands: retry until the video element is there
        if await edge.js(SEEK_JS % t):
            break
        await asyncio.sleep(1.5)
    await asyncio.sleep(1.5)
    clip = await edge.js(STAGE_JS)
    shots["on_screen"] = await edge.js("parseInt(document.querySelector('#countchip')?.textContent || '0')")
    await edge.shot(out / f"{vid}_overlay.jpg", clip)
    shots["overlay"] = f"{vid}_overlay.jpg"
    # lift the on-screen element with the most parts (else the largest), via its parent if the click lands on a child
    target = await edge.js(f"""(async () => {{
      const g = await (await fetch('/api/videos/{vid}/graph')).json(), t = {t};
      const st = document.querySelector('#stage').getBoundingClientRect(), v = document.querySelector('#vid');
      const s = Math.min(st.width / v.videoWidth, st.height / v.videoHeight), fw = v.videoWidth * s, fh = v.videoHeight * s;
      const fx = st.left + (st.width - fw) / 2, fy = st.top + (st.height - fh) / 2, [rx, ry, rw, rh] = g.frame.content_rect;
      let best = null;
      for (const o of g.objects) for (const i of o.instances) {{
        if (t < i.start || t > i.end || !i.track.length) continue;
        const smp = i.track.reduce((a, b) => Math.abs(b.t - t) < Math.abs(a.t - t) ? b : a), [x, y, w, h] = smp.bbox;
        const score = (o.parts || []).length * 10 + w * h;
        if (!best || score > best.score) best = {{ score, label: o.label, parts: (o.parts || []).length,
          x: fx + (rx + (x + w / 2) * rw) * fw, y: fy + (ry + (y + h / 2) * rh) * fh }};
      }}
      return best; }})()""")
    if target:
        await edge.click(target["x"], target["y"])
        await asyncio.sleep(1.6)
        if not await edge.js("document.querySelectorAll('.li-chip').length") and await edge.js("!!document.querySelector('.li-parent')"):
            await edge.js("document.querySelector('.li-parent').click(); true")
            await asyncio.sleep(1.6)
        shots["lifted"] = await edge.js("document.querySelector('.li-title b')?.textContent || null")
        shots["lift_chips"] = await edge.js("document.querySelectorAll('.li-chip').length")
        await edge.shot(out / f"{vid}_lift.jpg", clip)
        shots["lift"] = f"{vid}_lift.jpg"
    if run_id:
        await edge.send("Page.navigate", {"url": f"{BASE}/#/run/{run_id}"})
        await asyncio.sleep(9)  # the run replays itself (about 12 s): capture it near the end
        await edge.shot(out / f"{vid}_run.jpg")
        shots["run"] = f"{vid}_run.jpg"
    return shots


async def main(list_path: Path, shots_only: bool = False) -> None:
    sys.path.insert(0, str(ROOT))
    from loom.core.config import load_config

    data = load_config().data_dir
    res_dir, img_dir = data / "eval" / "batch", ROOT / "docs" / "img" / "batch"
    res_dir.mkdir(parents=True, exist_ok=True)
    summary_path = res_dir / "summary.json"
    summary: list[dict[str, Any]] = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else []
    done = {s["url"] for s in summary if s.get("status") == "ok"}
    items = load_list(list_path)
    if shots_only:  # re-take missing screenshots for finished videos, without re-running perception
        for row in summary:
            if row.get("status") != "ok" or (row.get("screens") or {}).get("overlay"):
                continue
            g = json.loads((data / "graphs" / f"{row['video_id']}.json").read_text(encoding="utf-8"))
            edge = Edge(port=9363)
            try:
                await edge.connect()
                row["screens"] = await shoot(edge, g, row.get("run_id"), img_dir)
            except Exception as e:
                row["screens"] = {"error": f"{type(e).__name__}: {e}"}
            finally:
                await edge.close()
            print(row["video_id"], "->", row["screens"].get("overlay") or row["screens"].get("error"), flush=True)
            (res_dir / f"{row['video_id']}.json").write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
        fresh = json.loads(summary_path.read_text(encoding="utf-8"))  # the batch may have added rows meanwhile
        shot = {r["url"]: r["screens"] for r in summary if r.get("screens")}
        for r in fresh:
            if r["url"] in shot and not (r.get("screens") or {}).get("overlay"):
                r["screens"] = shot[r["url"]]
        summary_path.write_text(json.dumps(fresh, ensure_ascii=False, indent=1), encoding="utf-8")
        return
    async with httpx.AsyncClient(timeout=60) as c:
        for n, it in enumerate(items, 1):
            if it["url"] in done:
                print(f"[{n}/{len(items)}] skip (done) {it['url']}", flush=True)
                continue
            print(f"[{n}/{len(items)}] {it['category']}: {it['url']}", flush=True)
            try:
                row: dict[str, Any] = {**it, **await ingest(c, it["url"])}
            except Exception as e:
                row = {**it, "status": "error", "error": f"{type(e).__name__}: {e}"}
            if row["status"] == "ok":
                g = json.loads((data / "graphs" / f"{row['video_id']}.json").read_text(encoding="utf-8"))
                row["metrics"] = metrics(g)
                row["ask"] = await probe(c, row["video_id"])
                edge = Edge()
                try:
                    await edge.connect()
                    row["screens"] = await shoot(edge, g, row.get("run_id"), img_dir)
                except Exception as e:
                    row["screens"] = {"error": f"{type(e).__name__}: {e}"}
                finally:
                    await edge.close()
                (res_dir / f"{row['video_id']}.json").write_text(json.dumps(row, ensure_ascii=False, indent=1),
                                                                encoding="utf-8")
            summary = [s for s in summary if s["url"] != it["url"]] + [row]
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
            m = row.get("metrics", {})
            print(f"    -> {row['status']} in {row.get('seconds')} s: {m.get('objects')} elements, {m.get('parts')} parts, "
                  f"{len(m.get('concepts', []))} concepts, {m.get('quiz_questions')} questions {row.get('error') or ''}",
                  flush=True)
    print("BATCH DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), "--shots" in sys.argv))
