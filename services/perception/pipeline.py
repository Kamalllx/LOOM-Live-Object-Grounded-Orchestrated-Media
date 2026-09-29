"""Perception service: video (file or URL) -> concept-graph.json (Contract A).

    .venv/bin/python services/perception/pipeline.py --source media/videos/x.mp4 --video-id vid_x
    .venv/bin/python services/perception/pipeline.py --source "https://youtube.com/..." --video-id vid_y

Steps: ingest/normalize (ffmpeg) -> ASR -> OCR -> object vocabulary (LLM) -> grounding + tracking
-> graph fusion -> validate against contracts/concept-graph.schema.json -> data/graphs/<video_id>.json
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "packages" / "shared-types"))
for sub in ("asr", "ocr", "sam", "graph-fusion"):
    sys.path.insert(0, str(HERE / sub))

from loom_shared import contracts  # noqa: E402
from loom_shared.config import GRAPHS_DIR, VIDEOS_DIR  # noqa: E402

MAX_SECONDS = 600


def _probe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return float(out.strip())


# Tried in order. A single progressive file needs no merge step; byte-range downloads (--download-sections)
# are avoided because YouTube often refuses them - the 10-minute cap is applied by ffmpeg afterwards.
DOWNLOAD_FORMATS = [
    ["-f", "b[height<=720][ext=mp4]/b[height<=720]/b"],
    ["-f", "bv*[height<=720]+ba/b[height<=720]/b", "--merge-output-format", "mp4"],
]


def _download(url, video_id):
    tmpl = str(VIDEOS_DIR / f"{video_id}.download.%(ext)s")
    errors = []
    for fmt in DOWNLOAD_FORMATS:
        for leftover in VIDEOS_DIR.glob(f"{video_id}.download.*"):
            leftover.unlink()
        proc = subprocess.run([sys.executable, "-m", "yt_dlp", *fmt, "--no-playlist", "--retries", "3",
                               "--newline", "-o", tmpl, url], capture_output=True, text=True)
        files = [f for f in VIDEOS_DIR.glob(f"{video_id}.download.*") if not f.name.endswith((".part", ".ytdl"))]
        if proc.returncode == 0 and files:
            return files[0]
        err = [ln for ln in (proc.stderr + proc.stdout).splitlines() if "ERROR" in ln]
        errors.append(err[-1] if err else f"yt-dlp exit code {proc.returncode}")
        print(f"ingest: download attempt failed ({errors[-1][:160]}), trying another format", flush=True)
    raise RuntimeError(f"could not download the video: {errors[-1][:300]}")


def ingest(source, video_id):
    """Download (URL) or copy (file), then normalize to 1280x720 H.264 with faststart for web playback."""
    target = VIDEOS_DIR / f"{video_id}.mp4"
    if target.exists() and pathlib.Path(source).resolve() == target.resolve():
        return target
    src = pathlib.Path(source)
    if source.startswith(("http://", "https://")):
        src = _download(source, video_id)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-t", str(MAX_SECONDS),
                    "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=30",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-c:a", "aac", "-ac", "2",
                    "-movflags", "+faststart", str(target)], check=True)
    if src.name.startswith(f"{video_id}.download."):
        src.unlink()
    return target


def run(source, video_id, title=None, progress=print):
    from detect import detect_objects
    from fuse import HAZARD_PHRASES, fuse, object_vocabulary
    from read_text import read_text
    from transcribe import transcribe

    timings = {}
    t = time.time()
    progress("ingest: normalizing video")
    video = ingest(source, video_id)
    timings["ingest"] = time.time() - t

    t = time.time()
    progress("asr: transcribing speech")
    transcript, asr_engine = transcribe(video)
    timings["asr"] = time.time() - t

    t = time.time()
    progress("ocr: reading on-screen text")
    on_screen = read_text(video)
    timings["ocr"] = time.time() - t

    t = time.time()
    phrases = object_vocabulary(transcript, on_screen)
    progress(f"grounding: looking for {phrases}")
    grounding_stats = {}
    shown = set()

    def grounding_progress(frac):  # the slowest step: report every 10% so the page never looks frozen
        step = int(frac * 10)
        if step not in shown:
            shown.add(step)
            progress(f"grounding: {step * 10}% of frames checked")

    objects = detect_objects(video, phrases, progress=grounding_progress, stats=grounding_stats,
                             hazards=HAZARD_PHRASES)
    timings["grounding"] = time.time() - t

    t = time.time()
    progress("fusion: building concept graph")
    nodes = fuse(transcript, on_screen, objects)
    timings["fusion"] = time.time() - t

    graph = {
        "schema_version": "1.0",
        "video_id": video_id,
        "title": title or video_id,
        "video_url": f"/media/videos/{video_id}.mp4",
        "duration_seconds": round(_probe_duration(video), 2),
        "objects": objects,
        "transcript": transcript,
        "on_screen_text": on_screen,
        "concept_nodes": nodes,
        "perception_meta": {"asr": asr_engine, "grounding": "grounding-dino-tiny + IoU tracking + CLIP verification",
                            "grounding_stats": grounding_stats,
                            "ocr": "tesseract", "object_phrases": phrases,
                            "timings_s": {k: round(v, 1) for k, v in timings.items()}},
    }
    contracts.validate("concept-graph", graph)
    out = GRAPHS_DIR / f"{video_id}.json"
    out.write_text(json.dumps(graph, indent=2))
    progress(f"done: {len(objects)} objects, {len(transcript)} sentences, {len(on_screen)} text items, "
             f"{len(nodes)} concepts -> {out.name}")
    return graph


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="video file path or http(s) URL")
    ap.add_argument("--video-id", required=True)
    ap.add_argument("--title")
    a = ap.parse_args()
    run(a.source, a.video_id, a.title)
