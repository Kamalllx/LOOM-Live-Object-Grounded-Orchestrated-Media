"""`loom eval make-demo` — build the demo lesson and its ground truth on Windows (spec/07 §1, spec/06 S0).

1. Royalty-free source clips are downloaded once (Pexels 720p) into `tests/eval_data/sources/` — the only network
   use; refused in offline mode if a clip is missing.
2. Narration is synthesized locally with Kokoro-82M (ONNX, CPU), one sentence at a time, so every sentence's exact
   start/end is known.
3. Each segment's picture (clip at the requested speed, or a title card) is cut to its narration length; captions are
   rendered with Pillow (Windows fonts) and burned in with FFmpeg.
4. Output: `data/media/videos/<video_id>.mp4` (H.264 + AAC, faststart) and `tests/eval_data/groundtruth_demo.json`.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from loom.core.config import PROJECT_ROOT, LoomConfig
from loom.core.contracts.common import sha256_of
from loom.core.offline import require_network
from loom.core.weights import cached_snapshot
from loom.eval.demo_script import (
    FPS,
    HEIGHT,
    LICENSE,
    SAFETY_LABELS,
    SEGMENTS,
    SOURCES,
    TITLE,
    VOICE,
    WIDTH,
    Segment,
)

EVAL_DATA = PROJECT_ROOT / "tests" / "eval_data"
SOURCES_DIR = EVAL_DATA / "sources"
BUILD = EVAL_DATA / "build"
GROUND_TRUTH = EVAL_DATA / "groundtruth_demo.json"
SOURCES_JSON = EVAL_DATA / "demo_sources.json"
KOKORO_REPO = "onnx-community/Kokoro-82M-v1.0-ONNX"
SAMPLE_RATE = 24000
LEAD_S, GAP_S, TAIL_S, MIN_CARD_S = 0.4, 0.35, 0.7, 4.0
BANNER_MARGIN = 28


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _run(cmd: list[str]) -> None:
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if res.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed ({res.returncode}): {res.stderr[-1500:]}")


def _probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return float(out.strip())


# ------------------------------------------------------------------------------------------------ sources


def fetch_sources(cfg: LoomConfig) -> dict[str, Path]:
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for clip_id in SOURCES:
        path = SOURCES_DIR / f"pexels_{clip_id}.mp4"
        if not path.exists():
            require_network(cfg, f"downloading demo source clip {clip_id}")
            url = f"https://www.pexels.com/download/video/{clip_id}/?h=720&w=1280"
            with httpx.stream(
                "GET", url, follow_redirects=True, timeout=120, headers={"User-Agent": "Mozilla/5.0"}
            ) as r:
                r.raise_for_status()
                tmp = path.with_suffix(".part")
                with tmp.open("wb") as fh:
                    for chunk in r.iter_bytes():
                        fh.write(chunk)
            tmp.replace(path)
        paths[clip_id] = path
    SOURCES_JSON.write_text(
        json.dumps(
            {
                "license": LICENSE,
                "clips": [
                    {
                        "clip_id": s.clip_id,
                        "page": s.page,
                        "note": s.note,
                        "file": f"sources/pexels_{s.clip_id}.mp4",
                        "sha256": sha256_file(paths[s.clip_id]),
                    }
                    for s in SOURCES.values()
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return paths


def sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


# ------------------------------------------------------------------------------------------------ narration


class Narrator:
    """Kokoro-82M via kokoro-onnx, using the HF-cached ONNX model and per-voice style vectors."""

    def __init__(self) -> None:
        from kokoro_onnx import Kokoro

        snap = cached_snapshot(KOKORO_REPO)
        if snap is None:
            raise RuntimeError(f"{KOKORO_REPO} is not in the HF cache; run setup/pull-models.ps1 -OpenWeights")
        voices = BUILD / "kokoro_voices.npz"
        if not voices.exists():
            BUILD.mkdir(parents=True, exist_ok=True)
            arrays = {
                p.stem: np.fromfile(p, dtype=np.float32).reshape(-1, 1, 256) for p in (snap / "voices").glob("*.bin")
            }
            np.savez(voices, **arrays)  # type: ignore[arg-type]
        self.tts = Kokoro(str(snap / "onnx" / "model.onnx"), str(voices))

    def say(self, text: str) -> np.ndarray:
        audio, sr = self.tts.create(text, voice=VOICE, speed=1.0, lang="en-us")
        if sr != SAMPLE_RATE:
            raise RuntimeError(f"unexpected Kokoro sample rate {sr}")
        return np.asarray(audio, dtype=np.float32)


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(round(seconds * SAMPLE_RATE), dtype=np.float32)


# ------------------------------------------------------------------------------------------------ pictures


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = ["segoeuib.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"]
    for name in names:
        p = Path("C:/Windows/Fonts") / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    raise RuntimeError("no Windows UI font found (segoeui/arial)")


def render_card(text: str, path: Path) -> tuple[float, float, float, float]:
    """Full-screen title card. Returns the normalized text bbox."""
    im = Image.new("RGB", (WIDTH, HEIGHT), (18, 22, 40))
    d = ImageDraw.Draw(im)
    font = _font(64, bold=True)
    x0, y0, x1, y1 = d.textbbox((0, 0), text, font=font)
    w, h = x1 - x0, y1 - y0
    x, y = (WIDTH - w) / 2 - x0, (HEIGHT - h) / 2 - y0
    d.text((x, y), text, fill=(245, 243, 237), font=font)
    im.save(path)
    return _norm_box(x + x0, y + y0, w, h)


def render_banner(text: str, path: Path) -> tuple[float, float, float, float]:
    """Transparent overlay with a caption box at the top right. Returns the normalized box."""
    im = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    font = _font(40, bold=True)
    x0, y0, x1, y1 = d.textbbox((0, 0), text, font=font)
    pad = 18
    bw, bh = (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad
    bx, by = WIDTH - bw - BANNER_MARGIN, BANNER_MARGIN
    d.rounded_rectangle((bx, by, bx + bw, by + bh), radius=12, fill=(10, 12, 24, 215))
    d.text((bx + pad - x0, by + pad - y0), text, fill=(255, 255, 255, 255), font=font)
    im.save(path)
    return _norm_box(bx, by, bw, bh)


def _norm_box(x: float, y: float, w: float, h: float) -> tuple[float, float, float, float]:
    return (round(x / WIDTH, 4), round(y / HEIGHT, 4), round(w / WIDTH, 4), round(h / HEIGHT, 4))


def render_segment(seg: Segment, duration: float, clips: dict[str, Path], out: Path) -> dict[str, Any]:
    vf_base = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},fps={FPS},format=yuv420p"
    )
    enc = ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-r", str(FPS), "-t", f"{duration:.3f}"]
    info: dict[str, Any] = {}
    if seg.card is not None:
        card = BUILD / f"card_{seg.id}.png"
        info["card_bbox"] = render_card(seg.card, card)
        _run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(card), "-vf", vf_base, *enc, str(out)])
        return info
    assert seg.clip is not None
    src = clips[seg.clip]
    speed_vf = f"setpts={1 / seg.speed:.4f}*PTS," if seg.speed != 1.0 else ""
    inputs = ["-stream_loop", "-1", "-i", str(src)]
    if seg.banner is not None:
        banner = BUILD / f"banner_{seg.id}.png"
        info["banner_bbox"] = render_banner(seg.banner, banner)
        filt = f"[0:v]{speed_vf}{vf_base}[v];[v][1:v]overlay=0:0:format=auto,format=yuv420p[o]"
        cmd = [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            *inputs,
            "-loop",
            "1",
            "-i",
            str(banner),
            "-filter_complex",
            filt,
            "-map",
            "[o]",
            *enc,
            str(out),
        ]
    else:
        cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-vf", speed_vf + vf_base, *enc, str(out)]
    _run(cmd)
    info["clip_loops"] = duration > _probe_duration(src) / seg.speed
    return info


# ------------------------------------------------------------------------------------------------ build


def make_demo(cfg: LoomConfig, log: Any = print) -> dict[str, Any]:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise RuntimeError(f"{tool} not on PATH")
    BUILD.mkdir(parents=True, exist_ok=True)
    clips = fetch_sources(cfg)
    log(f"sources ready: {len(clips)} clips")
    narrator = Narrator()

    t = 0.0
    audio_parts: list[np.ndarray] = []
    seg_files: list[Path] = []
    gt_segments: list[dict[str, Any]] = []
    narration: list[dict[str, Any]] = []
    captions: list[dict[str, Any]] = []
    hazards: list[dict[str, Any]] = []
    for seg in SEGMENTS:
        pieces = [_silence(LEAD_S)]
        cursor = LEAD_S
        for k, sentence in enumerate(seg.sentences):
            if k:
                pieces.append(_silence(GAP_S))
                cursor += GAP_S
            wav = narrator.say(sentence)
            dur = len(wav) / SAMPLE_RATE
            narration.append(
                {"segment": seg.id, "start": round(t + cursor, 3), "end": round(t + cursor + dur, 3), "text": sentence}
            )
            pieces.append(wav)
            cursor += dur
        pieces.append(_silence(TAIL_S))
        cursor += TAIL_S
        if seg.card is not None and cursor < MIN_CARD_S:
            pieces.append(_silence(MIN_CARD_S - cursor))
            cursor = MIN_CARD_S
        # snap the segment to whole frames so audio and video never drift
        frames = int(np.ceil(cursor * FPS))
        duration = frames / FPS
        audio = np.concatenate(pieces)
        audio = np.pad(audio, (0, max(0, round(duration * SAMPLE_RATE) - len(audio))))
        audio_parts.append(audio)

        out = BUILD / f"seg_{len(seg_files):02d}_{seg.id}.mp4"
        info = render_segment(seg, duration, clips, out)
        seg_files.append(out)
        start, end = round(t, 3), round(t + duration, 3)
        gt_segments.append(
            {
                "id": seg.id,
                "start": start,
                "end": end,
                "source": f"pexels_{seg.clip}" if seg.clip else "title_card",
                "speed": seg.speed,
                "objects": seg.objects,
                **info,
            }
        )
        if seg.card is not None:
            captions.append({"start": start, "end": end, "text": seg.card, "bbox": info["card_bbox"]})
        if seg.banner is not None:
            captions.append({"start": start, "end": end, "text": seg.banner, "bbox": info["banner_bbox"]})
        if seg.hazard is not None:
            hazards.append(
                {
                    "label": seg.hazard,
                    "segment": seg.id,
                    "start": start,
                    "end": end,
                    "note": "the shattering bottle and its shards are visible for the whole segment",
                }
            )
        log(f"  {seg.id}: {start:6.2f}-{end:6.2f}s")
        t += duration

    wav_path = BUILD / "narration.wav"
    import soundfile as sf

    sf.write(str(wav_path), np.concatenate(audio_parts), SAMPLE_RATE, subtype="PCM_16")
    concat_list = BUILD / "segments.txt"
    concat_list.write_text("".join(f"file '{p.as_posix()}'\n" for p in seg_files), encoding="utf-8")
    raw = BUILD / "demo_raw.mp4"
    _run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-i",
            str(wav_path),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            "-shortest",
            str(raw),
        ]
    )

    file_sha = sha256_file(raw)
    video_id = f"{slug(TITLE)}_{file_sha.removeprefix('sha256:')[:6]}"
    media = cfg.data_dir / "media" / "videos"
    media.mkdir(parents=True, exist_ok=True)
    final = media / f"{video_id}.mp4"
    shutil.copyfile(raw, final)
    duration = _probe_duration(final)

    gt = {
        "video_id": video_id,
        "title": TITLE,
        "video_file_sha256": file_sha,
        "duration_seconds": round(duration, 3),
        "frame": {"width": WIDTH, "height": HEIGHT, "fps": FPS},
        "voice": f"kokoro-82m/{VOICE}",
        "segments": gt_segments,
        "narration": narration,
        "on_screen_text": captions,
        "hazards": hazards,
        "safety_labels": SAFETY_LABELS,
        "keyframe_annotations": "pending (S1): object boxes and masks on 20 keyframes are annotated by hand",
        "script_sha256": sha256_of([s.__dict__ for s in SEGMENTS]),
    }
    GROUND_TRUTH.write_text(json.dumps(gt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"built {final} ({duration:.2f}s), ground truth {GROUND_TRUTH.relative_to(PROJECT_ROOT)}")
    return gt
