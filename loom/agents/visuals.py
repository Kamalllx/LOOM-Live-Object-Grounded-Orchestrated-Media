"""Pictures for explainers: crops of the lesson itself, and (opt-in) freely licensed images from Wikimedia Commons.

Lesson visuals come from the video the learner is watching: the elements the explainer is grounded on (a board
diagram, a tracked object) are cropped at their clearest sample; on filmed boards the teacher-free board snapshot is
used, so the picture shows the writing, not the person in front of it.

Web visuals are the one network exception to the local-only rule (CLAUDE.md rule 1): Wikimedia Commons only, freely
licensed, with author and licence shown on screen; off in offline mode or with `animator.web_images = false`. A
failure here never fails an explainer: it just has fewer pictures. The planner decides which pictures to use.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

COMMONS = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "LOOM-explainer/1.0 (local educational video tool; https://github.com/Kamalllx/GenAI_7thSem)"
FREE = re.compile(r"(cc[- ]by|cc0|public domain|pd|gfdl|cc[- ]by[- ]sa)", re.IGNORECASE)
MAX_LESSON, MAX_WEB = 4, 3


def web_allowed(cfg: Any) -> bool:
    return bool(cfg.animator.web_images) and not cfg.runtime.offline and os.environ.get("LOOM_OFFLINE") != "1"


def _strip(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def caption_of(title: str) -> str:
    """'File:Photosynthesis_en.svg' -> 'Photosynthesis en'."""
    t = re.sub(r"^File:", "", title)
    t = re.sub(r"\.[a-z0-9]{2,4}$", "", t, flags=re.IGNORECASE)
    return re.sub(r"[_\s]+", " ", t).strip()[:80]


def commons_pick(pages: list[dict[str, Any]], limit: int = MAX_WEB) -> list[dict[str, Any]]:
    """Commons API pages -> freely licensed bitmap images [{title, url, credit, licence}] (pure; unit-tested)."""
    out = []
    for p in sorted(pages, key=lambda p: p.get("index", 0)):
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        licence = _strip((meta.get("LicenseShortName") or {}).get("value", ""))
        mime = info.get("mime", "")
        url = info.get("thumburl") or info.get("url")
        if not url or mime not in ("image/jpeg", "image/png", "image/svg+xml") or not FREE.search(licence):
            continue
        raw = _strip((meta.get("Artist") or {}).get("value", ""))
        artist = " ".join(raw.splitlines()[0].split())[:80] if raw else "unknown author"
        out.append({"title": caption_of(p.get("title", "")), "url": url, "licence": licence,
                    "credit": f"{artist}, {licence}, via Wikimedia Commons"})
        if len(out) == limit:
            break
    return out


def web_visuals(query: str, out_dir: Path, limit: int = MAX_WEB) -> list[dict[str, Any]]:
    import httpx

    params: dict[str, str | int] = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
                                    "gsrlimit": 10,
              "gsrsearch": f"{query} filetype:bitmap|drawing", "prop": "imageinfo",
              "iiprop": "url|mime|extmetadata", "iiurlwidth": 900}
    try:
        with httpx.Client(timeout=8, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as c:
            pages = list(((c.get(COMMONS, params=params).json().get("query") or {}).get("pages") or {}).values())
            picked = commons_pick(pages, limit)
            out = []
            for n, p in enumerate(picked):
                r = c.get(p["url"])
                if r.status_code != 200 or len(r.content) > 6_000_000:
                    continue
                png = p["url"].lower().endswith(".png") or "png" in r.headers.get("content-type", "")
                ext = ".png" if png else ".jpg"
                f = out_dir / f"w{n}{ext}"
                f.write_bytes(r.content)
                out.append({"id": f"web_{n + 1}", "caption": p["title"], "source": "Wikimedia Commons",
                            "credit": p["credit"], "file": f.name})
            return out
    except Exception as e:  # pictures are optional; the explainer goes on without them
        log.info("web visuals unavailable for %r: %s", query, e)
        return []


def lesson_visuals(data: Path, graph: Any, object_ids: list[str], out_dir: Path,
                   limit: int = MAX_LESSON) -> list[dict[str, Any]]:
    """Crops of grounded elements from the lesson (teacher-free on filmed boards)."""
    import cv2

    video = data / "media" / "videos" / f"{graph.video_id}.mp4"
    snaps_ix = data / "media" / "boards" / graph.video_id / "index.json"
    snaps = json.loads(snaps_ix.read_text(encoding="utf-8"))["snapshots"] if snaps_ix.exists() else []
    rx, ry, rw, rh = graph.frame.content_rect
    cap = cv2.VideoCapture(str(video))
    out: list[dict[str, Any]] = []
    try:
        for oid in object_ids:
            o = next((x for x in graph.objects if x.object_id == oid), None)
            if o is None:
                continue
            inst = max(o.instances, key=lambda i: i.end - i.start)
            s = inst.track[len(inst.track) // 2]
            pic = None
            if o.phrase_source == "board" and snaps:
                snap = max((x for x in snaps if x["t"] <= s.t), key=lambda x: x["t"], default=snaps[0])
                img = cv2.imread(str(data / snap["url"].removeprefix("/")), cv2.IMREAD_UNCHANGED)
                if img is not None and img.shape[2] == 4:
                    alpha = img[..., 3:4].astype("float32") / 255
                    pic = (img[..., :3] * alpha + 18 * (1 - alpha)).astype("uint8")
            if pic is None:
                cap.set(cv2.CAP_PROP_POS_MSEC, s.t * 1000)
                ok, frame = cap.read()
                if not ok:
                    continue
                fh, fw = frame.shape[:2]
                pic = frame[round(ry * fh):round((ry + rh) * fh), round(rx * fw):round((rx + rw) * fw)]
            ph, pw = pic.shape[:2]
            x, y, w, h = s.bbox
            pad = 0.25 * max(w, h)
            x0, y0 = max(0, round((x - pad) * pw)), max(0, round((y - pad) * ph))
            x1, y1 = min(pw, round((x + w + pad) * pw)), min(ph, round((y + h + pad) * ph))
            if x1 - x0 < 24 or y1 - y0 < 24:
                continue
            crop = pic[y0:y1, x0:x1]
            scale = max(1.0, 640 / max(1, crop.shape[1]))
            if scale > 1:
                crop = cv2.resize(crop, (round(crop.shape[1] * scale), round(crop.shape[0] * scale)),
                                  interpolation=cv2.INTER_CUBIC)
            name = f"v_{oid}.jpg"
            cv2.imwrite(str(out_dir / name), crop, [cv2.IMWRITE_JPEG_QUALITY, 88])
            mm, ss = divmod(int(s.t), 60)
            out.append({"id": f"lesson_{len(out) + 1}", "caption": o.label, "source": f"this lesson at {mm}:{ss:02d}",
                        "credit": "", "file": name})
            if len(out) == limit:
                break
    finally:
        cap.release()
    return out


def gather(cfg: Any, data: Path, graph: Any, hits: list[dict[str, Any]], focus_ids: list[str], query: str,
           out_dir: Path) -> list[dict[str, Any]]:
    """All pictures an explainer may use: lesson crops first (most trustworthy), then web pictures."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ids = list(dict.fromkeys([*focus_ids, *(h["id"] for h in hits if h["kind"] == "object")]))
    visuals = lesson_visuals(data, graph, ids, out_dir)
    if web_allowed(cfg) and query.strip():
        visuals += web_visuals(query, out_dir)
    return visuals
