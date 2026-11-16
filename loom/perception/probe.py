"""Probe + normalize + letterbox detection (spec/04 FR-ING-01).

Normalized form: H.264 + AAC MP4 with `+faststart`, trimmed to `runtime.max_seconds`, native resolution capped at
1080p. `content_rect` is the picture inside any letterbox/pillarbox (FFmpeg `cropdetect`), normalized to the frame,
so overlays align to the picture rather than to the black bars.
"""

from __future__ import annotations

import json
import re
import os
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from loom.core.blobs import BlobStore
from loom.perception.models import ProbeResult

STAGE_VERSION = "probe@1"
MAX_HEIGHT = 1080
CROP_MIN_GAIN = 0.02  # ignore crops that remove < 2 % of either dimension (noise, not letterbox)


class ProbeError(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaInfo:
    duration_s: float
    width: int
    height: int
    fps: float
    has_audio: bool


def _run(cmd: list[str], timeout: float = 3600) -> subprocess.CompletedProcess[str]:
    res = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False
    )
    if res.returncode != 0:
        raise ProbeError(f"{Path(cmd[0]).name} failed ({res.returncode}): {res.stderr[-800:]}")
    return res


def media_info(path: Path) -> MediaInfo:
    res = _run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], timeout=120
    )
    data = json.loads(res.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if video is None:
        raise ProbeError(f"{path.name}: no video stream")
    rate = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
    fps = float(Fraction(rate)) if rate != "0/0" else 0.0
    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    if duration <= 0 or fps <= 0:
        raise ProbeError(f"{path.name}: cannot read duration/fps")
    return MediaInfo(
        duration_s=duration,
        width=int(video["width"]),
        height=int(video["height"]),
        fps=round(fps, 3),
        has_audio=any(s.get("codec_type") == "audio" for s in data.get("streams", [])),
    )


def nvenc_available() -> bool:
    try:
        res = _run(["ffmpeg", "-hide_banner", "-encoders"], timeout=30)
    except (ProbeError, OSError, subprocess.SubprocessError):
        return False
    return "h264_nvenc" in res.stdout


_CROP = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")


def detect_content_rect(path: Path, info: MediaInfo, samples: int = 8) -> tuple[float, float, float, float]:
    """Union of `cropdetect` results over frames sampled across the video → normalized [x, y, w, h]."""
    boxes: list[tuple[int, int, int, int]] = []
    for k in range(samples):
        t = info.duration_s * (k + 0.5) / samples
        res = _run(
            [
                "ffmpeg",
                "-hide_banner",
                "-ss",
                f"{t:.2f}",
                "-i",
                str(path),
                "-frames:v",
                "3",
                "-vf",
                "cropdetect=limit=24:round=2:reset=0",
                "-f",
                "null",
                "-",
            ],
            timeout=120,
        )
        found = _CROP.findall(res.stderr)
        if found:
            w, h, x, y = (int(v) for v in found[-1])
            boxes.append((x, y, w, h))
    if not boxes:
        return (0.0, 0.0, 1.0, 1.0)
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return (0.0, 0.0, 1.0, 1.0)
    if w >= info.width * (1 - CROP_MIN_GAIN) and h >= info.height * (1 - CROP_MIN_GAIN):
        return (0.0, 0.0, 1.0, 1.0)
    return (
        round(x0 / info.width, 4),
        round(y0 / info.height, 4),
        round(w / info.width, 4),
        round(h / info.height, 4),
    )


def normalize(src: Path, out: Path, max_seconds: int, use_nvenc: bool | None = None,
              max_height: int | None = None) -> tuple[MediaInfo, bool, str]:
    """Transcode to the normalized MP4. Returns (source info, trimmed, encoder). `max_height` (e.g. 480) downscales
    below the default 1080 cap, for lighter playback and faster perception of long lessons."""
    if shutil.which("ffmpeg") is None:
        raise ProbeError("ffmpeg not on PATH")
    info = media_info(src)
    trimmed = info.duration_s > max_seconds + 0.5
    # "480p" caps the *short* side: a portrait phone video (720x1280) keeps 480 px of width, not 270
    cap = min(MAX_HEIGHT, max_height or MAX_HEIGHT)
    if min(info.width, info.height) <= cap:
        vf = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    elif info.height <= info.width:
        vf = f"scale=-2:{cap}"
    else:
        vf = f"scale={cap}:-2"
    nvenc = nvenc_available() if use_nvenc is None else use_nvenc
    venc = ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "21"] if nvenc else ["-c:v", "libx264", "-crf", "20"]
    audio = ["-c:a", "aac", "-b:a", "160k", "-ar", "48000"] if info.has_audio else ["-an"]
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-t", str(max_seconds), "-map", "0:v:0"]
    if info.has_audio:
        cmd += ["-map", "0:a:0"]
    # write to a private temp file and swap it in whole: a second ingest of the same video (CLI + web at once) must
    # never read a half-written MP4 ("moov atom not found")
    tmp = out.with_name(f"{out.stem}.{os.getpid()}.part.mp4")
    cmd += ["-vf", vf, "-pix_fmt", "yuv420p", *venc, *audio, "-movflags", "+faststart", str(tmp)]
    try:
        _run(cmd)
    except ProbeError:
        tmp.unlink(missing_ok=True)
        if not nvenc:
            raise
        # NVENC busy/unavailable: CPU encode
        return normalize(src, out, max_seconds, use_nvenc=False, max_height=max_height)
    os.replace(tmp, out)
    return info, trimmed, "h264_nvenc" if nvenc else "libx264"


def probe(src: Path, blobs: BlobStore, workdir: Path, max_seconds: int) -> ProbeResult:
    tmp = workdir / "normalized.mp4"
    source, trimmed, encoder = normalize(src, tmp, max_seconds)
    ref = blobs.put_file(tmp, ".mp4")
    tmp.unlink(missing_ok=True)
    info = media_info(ref.path)
    return ProbeResult(
        video_sha256=ref.sha256,
        path=str(ref.path),
        duration_s=round(info.duration_s, 3),
        width=info.width,
        height=info.height,
        fps=info.fps,
        has_audio=info.has_audio,
        content_rect=detect_content_rect(ref.path, info),
        source_duration_s=round(source.duration_s, 3),
        trimmed=trimmed,
        encoder=encoder,
    )
