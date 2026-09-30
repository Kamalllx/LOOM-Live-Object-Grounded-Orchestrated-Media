"""ffmpeg/ffprobe wrappers: probing, audio extraction, and frame sampling."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class MediaError(RuntimeError):
    pass


def _require(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        raise MediaError(f"{tool} not found on PATH; install ffmpeg")
    return path


def _run(args: list[str]) -> str:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaError(f"{Path(args[0]).name} failed: {proc.stderr.strip()[-800:]}")
    return proc.stdout


@dataclass
class VideoInfo:
    path: Path
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool


def probe(video: str | Path) -> VideoInfo:
    video = Path(video)
    if not video.is_file():
        raise MediaError(f"video not found: {video}")
    out = _run([_require("ffprobe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(video)])
    info = json.loads(out)
    vstreams = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    if not vstreams:
        raise MediaError(f"no video stream in {video}")
    v = vstreams[0]
    num, _, den = v.get("avg_frame_rate", "0/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    duration = float(info.get("format", {}).get("duration") or v.get("duration") or 0.0)
    return VideoInfo(
        path=video,
        duration=duration,
        width=int(v["width"]),
        height=int(v["height"]),
        fps=fps,
        has_audio=any(s.get("codec_type") == "audio" for s in info.get("streams", [])),
    )


def extract_audio(video: str | Path, out_wav: str | Path, sample_rate: int = 16000) -> Path:
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    _run([_require("ffmpeg"), "-y", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(out_wav)])
    return out_wav


@dataclass
class Frame:
    index: int  # index within its folder (SAM expects 0..N-1)
    t: float  # seconds from the start of the video
    path: Path


def extract_frames(
    video: str | Path,
    out_dir: str | Path,
    fps: float,
    width: int | None = None,
    start: float = 0.0,
    end: float | None = None,
) -> list[Frame]:
    """Sample frames at `fps` between start and end into out_dir/00000.jpg… (the layout SAM 3 reads)."""
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    vf = [f"fps={fps}"]
    if width:
        vf.append(f"scale={width}:-2")
    args = [_require("ffmpeg"), "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-i", str(video)]
    if end is not None:
        args += ["-t", f"{max(0.0, end - start):.3f}"]
    args += ["-vf", ",".join(vf), "-q:v", "2", "-start_number", "0", str(out_dir / "%05d.jpg")]
    _run(args)
    paths = sorted(out_dir.glob("*.jpg"))
    # The fps filter emits frame k at time k/fps (it picks the frame nearest each tick).
    return [Frame(index=i, t=round(start + i / fps, 3), path=p) for i, p in enumerate(paths)]


@dataclass
class Chunk:
    index: int
    start: float
    end: float


def plan_chunks(duration: float, chunk_seconds: float, overlap: float) -> list[Chunk]:
    if duration <= chunk_seconds:
        return [Chunk(0, 0.0, duration)]
    chunks, start, i = [], 0.0, 0
    while start < duration:
        end = min(duration, start + chunk_seconds)
        chunks.append(Chunk(i, start, end))
        if end >= duration:
            break
        start = end - overlap
        i += 1
    return chunks
