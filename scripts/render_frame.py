"""Render what a viewer sees at time t in a verified cut: the source frame with the cut's masks applied
(blurred, outlined, labelled) and tap targets drawn - the same compositing the web player does.

    .venv/bin/python scripts/render_frame.py <session_id> <seconds> out.png [--taps]
"""
import json
import pathlib
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def box_at(track, t, fallback):
    if not track:
        return fallback
    if t <= track[0]["t"]:
        return track[0]["bbox"]
    for a, b in zip(track, track[1:]):
        if a["t"] <= t <= b["t"]:
            k = (t - a["t"]) / max(1e-6, b["t"] - a["t"])
            return [va + (vb - va) * k for va, vb in zip(a["bbox"], b["bbox"])]
    return track[-1]["bbox"]


def render(session_id, t, out, taps=False):
    cut = json.loads((ROOT / "data" / "sessions" / session_id / "verified_cut.json").read_text())
    graph = json.loads((ROOT / "data" / "graphs" / f"{cut['video_id']}.json").read_text())
    video = ROOT / "media" / "videos" / f"{cut['video_id']}.mp4"
    frame = pathlib.Path(out).with_suffix(".raw.png")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1", str(frame)],
                   check=True)
    img = Image.open(frame).convert("RGB")
    W, H = img.size
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 18)
    for m in cut["redaction_masks"]:
        if m["start"] <= t < m["end"]:
            track = json.loads((ROOT / m["mask_url"].lstrip("/")).read_text())["track"]
            x, y, w, h = box_at(track, t, m["bbox"])
            box = (int(x * W), int(y * H), int((x + w) * W), int((y + h) * H))
            img.paste(img.crop(box).filter(ImageFilter.GaussianBlur(28)), box[:2])
            d = ImageDraw.Draw(img)
            d.rounded_rectangle(box, radius=12, outline=(255, 101, 132), width=3)
            label = f"{m['object_id']} · redacted for this viewer"
            tw = d.textlength(label, font=font)
            d.rounded_rectangle((box[0], box[1] - 30, box[0] + tw + 14, box[1] - 4), radius=6, fill=(255, 101, 132))
            d.text((box[0] + 7, box[1] - 27), label, font=font, fill=(42, 6, 16))
    if taps:
        concept_of = {o: n for n in graph["concept_nodes"] for o in n["object_ids"]}
        masked = {m["object_id"] for m in cut["redaction_masks"]}
        for o in graph["objects"]:
            if o["object_id"] in masked or o["object_id"] not in concept_of:
                continue
            for inst in o["instances"]:
                if inst["start"] <= t < inst["end"]:
                    x, y, w, h = box_at(inst.get("track"), t, inst["bbox"])
                    box = (int(x * W), int(y * H), int((x + w) * W), int((y + h) * H))
                    d.rounded_rectangle(box, radius=10, outline=(255, 176, 32), width=3)
                    label = f"{concept_of[o['object_id']]['node_id']} · {o['label']}"
                    tw = d.textlength(label, font=font)
                    d.rounded_rectangle((box[0], box[1] - 30, box[0] + tw + 14, box[1] - 4), radius=6, fill=(255, 176, 32))
                    d.text((box[0] + 7, box[1] - 27), label, font=font, fill=(26, 20, 5))
    img.save(out)
    frame.unlink()
    return out


if __name__ == "__main__":
    print(render(sys.argv[1], float(sys.argv[2]), sys.argv[3], "--taps" in sys.argv))
