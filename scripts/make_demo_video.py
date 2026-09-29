"""Build the LOOM demo lesson "Acid-Base Neutralization" from royalty-free Pexels footage.

Narration is synthesized with macOS `say`; text cards are rendered with Pillow and burned in
so the OCR pass has real on-screen text. A ground-truth file records exactly when each
segment, caption card and the broken-glass hazard appear, for evaluation.

Usage: .venv/bin/python scripts/make_demo_video.py
Output: media/videos/vid_demo_neutralization.mp4, data/eval/groundtruth_vid_demo_neutralization.json
"""
import json
import pathlib
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "media" / "source"
OUT_VIDEO = ROOT / "media" / "videos" / "vid_demo_neutralization.mp4"
OUT_GT = ROOT / "data" / "eval" / "groundtruth_vid_demo_neutralization.json"
W, H, FPS = 1280, 720, 30
VOICE = "Samantha"
FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

# Each segment: footage (or None for a title card), narration, optional banner text burned in.
SEGMENTS = [
    {"id": "s0_title", "clip": None, "card": "Acid-Base Neutralization",
     "narration": "Welcome. In this short lesson, we will learn what happens when an acid meets a base. "
                  "This reaction is called neutralization."},
    {"id": "s1_safety_gear", "clip": "pexels_8534101.mp4", "clip_start": 0.0,
     "narration": "Before any experiment, a chemist puts on protective gear: a lab coat, gloves, and safety goggles. "
                  "Acids and bases can burn the skin and the eyes."},
    {"id": "s2_pour", "clip": "pexels_8544763.mp4", "clip_start": 0.0, "objects": ["beaker"],
     "narration": "Here we pour a solution into a beaker. An acid, like hydrochloric acid, releases hydrogen ions in water. "
                  "A base, like sodium hydroxide, releases hydroxide ions. Combine the two solutions slowly."},
    {"id": "s3_stir_formula", "clip": "pexels_8392756.mp4", "clip_start": 0.0, "banner": "NaOH + HCl -> NaCl + H2O",
     "objects": ["beaker"],
     "narration": "As we stir, each hydrogen ion joins a hydroxide ion to form a molecule of water. "
                  "The sodium and chloride ions that remain form table salt. "
                  "So sodium hydroxide plus hydrochloric acid gives sodium chloride and water."},
    {"id": "s4_indicator", "clip": "pexels_8486033.mp4", "clip_start": 0.0, "banner": "pH 7 = neutral",
     "objects": ["test tube", "flask"],
     "narration": "An indicator tells us when the reaction is complete. When exactly enough base has been added, "
                  "the solution reaches p H seven, which is neutral."},
    {"id": "s5_broken_glass", "clip": "pexels_31637076.mp4", "clip_start": 0.0, "hazard": "broken glass",
     "objects": ["glass jar", "broken glass"],
     "narration": "Accidents can happen. If a glass container breaks, never pick up the shards with your hands. "
                  "Tell your teacher, and use a brush and a dustpan."},
    {"id": "s6_summary", "clip": None, "card": "Acid + Base -> Salt + Water",
     "narration": "To summarize: an acid plus a base gives a salt plus water. This is neutralization, "
                  "and it is used in everything from antacid tablets to treating acidic soil."},
]


def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return float(out.strip())


def title_card(text, path):
    img = Image.new("RGB", (W, H), (14, 17, 30))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 64)
    box = d.textbbox((0, 0), text, font=font)
    d.text(((W - (box[2] - box[0])) / 2, (H - (box[3] - box[1])) / 2 - 20), text, font=font, fill=(245, 243, 237))
    small = ImageFont.truetype(FONT, 26)
    sub = "LOOM demo lesson - Chemistry"
    sb = d.textbbox((0, 0), sub, font=small)
    d.text(((W - (sb[2] - sb[0])) / 2, H / 2 + 60), sub, font=small, fill=(255, 176, 32))
    img.save(path)


def banner(text, path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 46)
    box = d.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    x, y = W - tw - 70, 50
    d.rounded_rectangle((x - 24, y - 18, x + tw + 24, y + th + 26), radius=12, fill=(10, 12, 20, 225))
    d.text((x, y), text, font=font, fill=(255, 255, 255, 255))
    img.save(path)
    return [(x - 24) / W, (y - 18) / H, (tw + 48) / W, (th + 44) / H]


def main():
    OUT_VIDEO.parent.mkdir(parents=True, exist_ok=True)
    OUT_GT.parent.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="loom_demo_"))
    parts, gt, t = [], {"video_id": "vid_demo_neutralization", "segments": [], "on_screen_text": [],
                        "hazards": [], "narration": []}, 0.0

    for i, seg in enumerate(SEGMENTS):
        wav = tmp / f"{i}.aiff"
        run(["say", "-v", VOICE, "-r", "165", "-o", str(wav), seg["narration"]])
        dur = duration(wav) + 0.6  # small breath between segments
        part = tmp / f"{i}.mp4"
        scale = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},format=yuv420p"

        if seg["clip"] is None:
            png = tmp / f"{i}.png"
            title_card(seg["card"], png)
            vin = ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(png)]
            vf = f"[0:v]{scale}[v]"
            gt["on_screen_text"].append({"start": round(t, 2), "end": round(t + dur, 2), "text": seg["card"],
                                         "bbox": [0.1, 0.4, 0.8, 0.15]})
        else:
            clip = SRC / seg["clip"]
            clip_len = duration(clip) - seg.get("clip_start", 0)
            # Slow the footage (down to 0.6x) to cover the narration, then loop if still short.
            speed = max(0.6, min(1.0, clip_len / dur))
            vin = ["-stream_loop", "-1", "-ss", str(seg.get("clip_start", 0)), "-i", str(clip)]
            vf = f"[0:v]setpts={1 / speed:.4f}*PTS,{scale}[v]"
            if seg.get("banner"):
                png = tmp / f"{i}_banner.png"
                bbox = banner(seg["banner"], png)
                vin += ["-loop", "1", "-i", str(png)]
                vf = f"[0:v]setpts={1 / speed:.4f}*PTS,{scale}[b];[b][1:v]overlay=0:0:shortest=1,format=yuv420p[v]"
                gt["on_screen_text"].append({"start": round(t, 2), "end": round(t + dur, 2),
                                             "text": seg["banner"], "bbox": [round(v, 3) for v in bbox]})
        audio_idx = len([a for a in vin if a == "-i"])
        run(["ffmpeg", "-y", *vin, "-i", str(wav), "-filter_complex", vf, "-map", "[v]", "-map", f"{audio_idx}:a",
             "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-c:a", "aac", "-ar", "44100",
             "-ac", "2", "-af", "apad", str(part)])
        parts.append(part)

        gt["segments"].append({"id": seg["id"], "start": round(t, 2), "end": round(t + dur, 2),
                               "source": seg["clip"] or "title_card", "objects": seg.get("objects", [])})
        gt["narration"].append({"start": round(t, 2), "end": round(t + dur - 0.6, 2), "text": seg["narration"]})
        if seg.get("hazard"):
            gt["hazards"].append({"label": seg["hazard"], "segment": seg["id"], "start": round(t, 2),
                                  "end": round(t + dur, 2), "note": "shards visible after the jar lands (~0.8s in)"})
        t += dur

    listing = tmp / "list.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in parts))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", "-movflags", "+faststart",
         str(OUT_VIDEO)])
    gt["duration_seconds"] = round(duration(OUT_VIDEO), 2)
    gt["sources"] = {s["clip"]: f"https://www.pexels.com/video/{s['clip'].split('_')[1].split('.')[0]}/"
                     for s in SEGMENTS if s["clip"]}
    OUT_GT.write_text(json.dumps(gt, indent=2))
    print(f"wrote {OUT_VIDEO} ({gt['duration_seconds']}s) and {OUT_GT}")


if __name__ == "__main__":
    main()
