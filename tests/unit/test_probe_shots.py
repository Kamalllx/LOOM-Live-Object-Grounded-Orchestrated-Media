"""FR-ING-01 / FR-PER-03 on synthetic videos generated with FFmpeg (no fixtures needed)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from loom.core.blobs import BlobStore
from loom.perception.probe import media_info, probe
from loom.perception.shots import detect_shots, shots_from_cuts

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

FPS = 25
SEGMENT_S = 2.0
PATTERNS = ["testsrc2", "smptebars", "color=c=darkorange", "rgbtestsrc"]


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, capture_output=True)


@pytest.fixture(scope="module")
def cuts_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """4 visually different 2 s segments → 3 hard cuts at 2, 4, 6 s, with a tone track."""
    out = tmp_path_factory.mktemp("vid") / "cuts.mp4"
    inputs: list[str] = []
    for p in PATTERNS:
        sep = ":" if "=" in p else "="
        inputs += ["-f", "lavfi", "-i", f"{p}{sep}size=320x240:rate={FPS}:duration={SEGMENT_S}"]
    inputs += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={SEGMENT_S * len(PATTERNS)}"]
    concat = "".join(f"[{i}:v]" for i in range(len(PATTERNS))) + f"concat=n={len(PATTERNS)}:v=1:a=0[v]"
    _ffmpeg(
        *inputs,
        "-filter_complex",
        concat,
        "-map",
        "[v]",
        "-map",
        f"{len(PATTERNS)}:a",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(out),
    )
    return out


@pytest.fixture(scope="module")
def letterboxed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A 640x360 picture padded with black bars to 640x480 (letterbox), silent."""
    out = tmp_path_factory.mktemp("vid") / "letterbox.mp4"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=640x360:rate={FPS}:duration=3",
        "-vf",
        "pad=640:480:0:60:black",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(out),
    )
    return out


def test_three_hard_cuts_give_exactly_three_boundaries(cuts_video: Path) -> None:
    result = detect_shots(cuts_video, media_info(cuts_video).duration_s)
    starts = [s.start for s in result.shots[1:]]
    assert len(starts) == 3
    for got, want in zip(starts, (2.0, 4.0, 6.0), strict=True):
        assert abs(got - want) <= 1 / FPS + 1e-6  # ± 1 frame
    assert [s.shot_id for s in result.shots] == ["sh_01", "sh_02", "sh_03", "sh_04"]
    assert result.shots[0].start == 0.0 and result.shots[-1].end == pytest.approx(8.0, abs=0.05)
    for s in result.shots:
        assert all(s.start <= k <= s.end for k in s.keyframes)


def test_shots_partition_and_merge_tiny_shots() -> None:
    shots = shots_from_cuts([0.2, 3.0, 3.3, 9.9], duration=10.0)
    assert [(s.start, s.end) for s in shots] == [(0.0, 3.0), (3.0, 10.0)]  # 0.2/9.9 at the edges, 3.3 too close
    assert shots_from_cuts([], 5.0)[0].end == 5.0


def test_probe_normalizes_and_hashes(cuts_video: Path, tmp_path: Path) -> None:
    blobs = BlobStore(tmp_path / "blobs")
    r = probe(cuts_video, blobs, tmp_path / "work", max_seconds=600)
    assert r.video_sha256.startswith("sha256:") and Path(r.path).exists() and Path(r.path).suffix == ".mp4"
    assert r.has_audio and r.fps == pytest.approx(FPS, abs=0.01) and (r.width, r.height) == (320, 240)
    assert r.duration_s == pytest.approx(8.0, abs=0.1) and not r.trimmed
    assert r.content_rect == (0.0, 0.0, 1.0, 1.0)
    again = probe(cuts_video, blobs, tmp_path / "work", max_seconds=600)
    assert again.video_sha256 == r.video_sha256  # same file -> same identity


def test_probe_trims_long_videos(cuts_video: Path, tmp_path: Path) -> None:
    r = probe(cuts_video, BlobStore(tmp_path / "blobs"), tmp_path / "work", max_seconds=5)
    assert r.trimmed and r.source_duration_s == pytest.approx(8.0, abs=0.1)
    assert r.duration_s == pytest.approx(5.0, abs=0.15)


def test_letterbox_content_rect(letterboxed: Path, tmp_path: Path) -> None:
    r = probe(letterboxed, BlobStore(tmp_path / "blobs"), tmp_path / "work", max_seconds=600)
    x, y, w, h = r.content_rect
    assert not r.has_audio
    assert x == pytest.approx(0.0, abs=0.01) and w == pytest.approx(1.0, abs=0.01)
    assert y == pytest.approx(60 / 480, abs=0.02) and h == pytest.approx(360 / 480, abs=0.02)
