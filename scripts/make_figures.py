"""Paper figures, drawn from the real system's outputs (data/eval, data/sessions, media/clips).

    .venv/bin/python scripts/make_figures.py      -> docs/figures/*.png
"""
import json
import pathlib
import subprocess

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "figures"
OUT.mkdir(parents=True, exist_ok=True)
BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
REG = "/System/Library/Fonts/Supplemental/Arial.ttf"
INK, MUTED, LINE = (20, 24, 40), (95, 100, 120), (60, 66, 90)
AMBER, TEAL, PURPLE, PINK = (224, 150, 20), (20, 160, 150), (120, 90, 210), (220, 70, 100)


def font(size, bold=False):
    return ImageFont.truetype(BOLD if bold else REG, size)


def box(d, xy, title, lines, color, fill=(250, 250, 252)):
    x0, y0, x1, y1 = xy
    d.rounded_rectangle(xy, radius=14, fill=fill, outline=color, width=4)
    d.rectangle((x0 + 2, y0 + 2, x1 - 2, y0 + 46), fill=color)
    d.rounded_rectangle((x0, y0, x1, y0 + 48), radius=14, fill=color)
    d.text((x0 + 16, y0 + 11), title, font=font(24, True), fill=(255, 255, 255))
    y = y0 + 62
    for ln in lines:
        d.text((x0 + 16, y), ln, font=font(19), fill=INK)
        y += 27


def arrow(d, a, b, label=None, color=LINE):
    d.line([a, b], fill=color, width=4)
    (ax, ay), (bx, by) = a, b
    import math
    ang = math.atan2(by - ay, bx - ax)
    for s in (-0.45, 0.45):
        d.line([b, (bx - 18 * math.cos(ang + s), by - 18 * math.sin(ang + s))], fill=color, width=4)
    if label:
        mx, my = (ax + bx) / 2, (ay + by) / 2
        f = font(17, True)
        w = d.textlength(label, font=f)
        d.rounded_rectangle((mx - w / 2 - 8, my - 15, mx + w / 2 + 8, my + 13), radius=6, fill=(255, 255, 255), outline=color, width=2)
        d.text((mx - w / 2, my - 11), label, font=f, fill=color)


def architecture():
    W, H = 2200, 970
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    box(d, (40, 60, 480, 420), "1  Perception", ["ingest + normalize (ffmpeg)", "ASR: Whisper large-v3-turbo",
                                                  "OCR: Tesseract, merged by place", "LLM object vocabulary",
                                                  "  + always-on hazard phrases", "Grounding DINO + IoU tracking",
                                                  "CLIP verification (hazard", "  look-alike negatives)", "LLM graph fusion"], AMBER)
    box(d, (650, 60, 1090, 420), "2  Agent mesh (A2A)", ["Orchestrator = A2A client", "Agent Card registry",
                                                         "Curator: threads + roles", "Pedagogy: mastery policy",
                                                         "Personalizer: assemble/revise", "Assessment: quiz + mastery",
                                                         "Plug-in: school-policy agent", "  (separate process, own card)"], TEAL)
    box(d, (1260, 60, 1700, 420), "3  Verification loop", ["Guardian: safety model tags,", "  per-viewer masks",
                                                           "Animator: LLM -> Manim code,", "  AST gate, render, repair",
                                                           "Critic: safety / coherence /", "  factuality + issues",
                                                           "Perceive-Plan-Act-Verify", "budget 3, fallback"], PURPLE)
    box(d, (1870, 60, 2160, 420), "4  Delivery", ["Next.js player", "thread playback", "client-side blur masks",
                                                  "tap-to-learn", "live loop (SSE)", "quiz"], PINK)
    for (x0, x1, lab) in [(480, 650, ["A: concept", "graph"]), (1090, 1260, ["B: candidate", "cut"]),
                          (1700, 1870, ["C: verified", "cut"])]:
        arrow(d, (x0 + 4, 250), (x1 - 4, 250))
        for k, ln in enumerate(lab):
            w = d.textlength(ln, font=font(18, True))
            d.text(((x0 + x1) / 2 - w / 2, 190 + k * 24), ln, font=font(18, True), fill=LINE)
    d.line([(1480, 420), (1480, 520), (870, 520), (870, 430)], fill=PURPLE, width=4)
    arrow(d, (870, 470), (870, 424), color=PURPLE)
    d.text((1000, 532), "revise_cut (A2A): structured Critic issues", font=font(19, True), fill=PURPLE)
    box(d, (1260, 640, 2160, 830), "Learner memory", ["mastery graph per learner (Contract A2)",
                                                     "update: correct +0.35(1-m), wrong x0.75, explainer +0.05(1-m)",
                                                     "next session's Curator + Pedagogy start from here"], (90, 96, 120))
    arrow(d, (2015, 420), (2015, 640), "D: session log", PINK)
    d.line([(1260, 740), (760, 740), (760, 430)], fill=(90, 96, 120), width=4)
    arrow(d, (760, 470), (760, 424), color=(90, 96, 120))
    d.text((780, 750), "A2: learner profile", font=font(19, True), fill=(90, 96, 120))
    d.text((40, 880), "Every arrow is a JSON contract validated against a schema; every agent is reached only through its A2A",
           font=font(22), fill=MUTED)
    d.text((40, 915), "Agent Card (GET /.well-known/agent.json) and JSON-RPC message/send - first-party and third-party alike.",
           font=font(22), fill=MUTED)
    img.save(OUT / "architecture.png")


def weaves():
    runs = json.loads((ROOT / "data" / "eval" / "sessions.json").read_text())["runs"]
    graph = json.loads((ROOT / "data" / "graphs" / "vid_demo_neutralization.json").read_text())
    D = graph["duration_seconds"]
    names = {"learner_alex": "Alex - expert", "learner_priya": "Priya - beginner", "learner_family": "Parent + child"}
    cuts = {}
    for sess in sorted((ROOT / "data" / "sessions").glob("sess_*"), key=lambda p: p.stat().st_mtime):
        v = sess / "verified_cut.json"
        if v.exists():
            c = json.loads(v.read_text())
            cuts[c["learner_id"]] = c
    W, H, L, R = 2000, 560, 330, 1900
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    x = lambda t: L + (R - L) * t / D
    d.text((L, 20), "source video (74.6 s)", font=font(22, True), fill=MUTED)
    for t in range(0, int(D) + 1, 10):
        d.line([(x(t), 58), (x(t), 66)], fill=MUTED, width=2)
        d.text((x(t) - 10, 68), f"{t}s", font=font(17), fill=MUTED)
    for i, lid in enumerate(["learner_alex", "learner_priya", "learner_family"]):
        c = cuts[lid]
        y = 120 + i * 140
        d.text((30, y + 18), names[lid], font=font(24, True), fill=INK)
        d.rectangle((L, y, R, y + 70), fill=(236, 238, 244))
        for th in c["final_threads"]:
            col = AMBER if th.get("action") in ("keep", "expand") else (240, 200, 120)
            d.rectangle((x(th["start"]), y, x(th["end"]) - 3, y + 70), fill=col)
        for m in c["redaction_masks"]:
            d.rectangle((x(m["start"]), y, x(m["end"]), y + 70), fill=PINK)
        for e in c["explainer_clips"]:
            if e.get("anchor_time") is not None:
                d.rectangle((x(e["anchor_time"]) - 5, y - 8, x(e["anchor_time"]) + 5, y + 78), fill=PURPLE)
        kept = sum(t["end"] - t["start"] for t in c["final_threads"])
        d.text((L, y + 80), f"{kept:.0f}s of source · {len(c['explainer_clips'])} Manim explainers · "
                            f"{len(c['redaction_masks'])} object masks · {c['status']}, pass {c['pass_count']}",
               font=font(19), fill=MUTED)
    lx = L
    for col, lab in [(AMBER, "kept thread"), ((240, 200, 120), "condensed"), ((236, 238, 244), "skipped"),
                     (PURPLE, "generated explainer"), (PINK, "per-object redaction")]:
        d.rectangle((lx, 525, lx + 26, 545), fill=col)
        d.text((lx + 34, 523), lab, font=font(19), fill=INK)
        lx += 300
    img.save(OUT / "weaves.png")


def explainer_strip():
    meta = sorted((ROOT / "media" / "clips").glob("*.json"), key=lambda p: p.stat().st_mtime)
    approved = set(json.loads((ROOT / "data" / "cache" / "critic_verified_clips.json").read_text()))
    pick = next(m for m in reversed(meta) if "eutraliz" in json.loads(m.read_text())["concept"]
                and f"/media/clips/{m.stem}.mp4" in approved)   # only clips the Critic approved
    clip = pick.with_suffix(".mp4")
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(clip)],
                               capture_output=True, text=True).stdout)
    frames = []
    for k, frac in enumerate((0.22, 0.38, 0.62, 0.9)):   # moments when each beat is fully drawn
        f = OUT / f"_ex{k}.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{dur * frac:.2f}", "-i", str(clip),
                        "-frames:v", "1", "-vf", "scale=640:-1", str(f)], check=True)
        frames.append(Image.open(f).convert("RGB"))
        f.unlink()
    strip = Image.new("RGB", (4 * 640 + 3 * 10, frames[0].height), (255, 255, 255))
    for k, fr in enumerate(frames):
        strip.paste(fr, (k * 650, 0))
    strip.save(OUT / "explainer_strip.png")
    (OUT / "explainer_strip.json").write_text(pick.read_text())


if __name__ == "__main__":
    architecture()
    weaves()
    explainer_strip()
    print(sorted(p.name for p in OUT.iterdir()))
