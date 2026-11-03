"""Shared helpers for `loom eval` suites: every result file embeds machine, model and commit info (spec/07)."""

from __future__ import annotations

import json
import platform
import subprocess
from pathlib import Path
from typing import Any

from loom import __version__
from loom.core.config import PROJECT_ROOT, LoomConfig
from loom.core.store import iso_now

EVAL_DATA = PROJECT_ROOT / "tests" / "eval_data"
GROUND_TRUTH_DEMO = EVAL_DATA / "groundtruth_demo.json"


def machine_info() -> dict[str, Any]:
    info: dict[str, Any] = {"platform": platform.platform(), "python": platform.python_version(), "loom": __version__}
    try:
        info["gpu"] = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        info["gpu"] = None
    try:
        info["git_commit"] = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        info["git_commit"] = None
    return info


async def _unload_ollama(cfg: LoomConfig) -> list[str]:
    from loom.core.ollama import OllamaHttp

    http = OllamaHttp(cfg)
    try:
        loaded = await http.loaded_models()
        for tag in loaded:
            await http.unload(tag)
        return loaded
    except Exception:  # Ollama down: nothing of ours is on the GPU
        return []
    finally:
        await http.aclose()


def free_gpu_for_torch(cfg: LoomConfig) -> list[str]:
    """Eval suites run torch stages directly: unload every Ollama model first (CLAUDE.md rule 6)."""
    import asyncio

    return asyncio.run(_unload_ollama(cfg))


def load_ground_truth(path: Path = GROUND_TRUTH_DEMO) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{path} missing - run `uv run loom eval make-demo` first")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def demo_video(cfg: LoomConfig, gt: dict[str, Any]) -> Path:
    path = cfg.data_dir / "media" / "videos" / f"{gt['video_id']}.mp4"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing - run `uv run loom eval make-demo` first")
    return path


def write_result(cfg: LoomConfig, suite: str, body: dict[str, Any]) -> Path:
    out = cfg.data_dir / "eval" / f"{suite}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"suite": suite, "measured_at": iso_now(), "machine": machine_info(), **body}
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out
