"""Open-weight models used outside Ollama (spec/03 §2.2): Hugging Face repo -> files LOOM loads.

Single list shared by `setup/fetch_weights.py` (download) and `loom doctor` (cache check).
"""

from __future__ import annotations

import os
from pathlib import Path

# repo -> allow patterns (None = whole repo)
WEIGHTS: dict[str, list[str] | None] = {
    "mobiuslabsgmbh/faster-whisper-large-v3-turbo": None,
    "IDEA-Research/grounding-dino-base": ["*.json", "*.txt", "model.safetensors"],
    "facebook/sam2.1-hiera-base-plus": None,
    "google/siglip2-base-patch16-224": ["*.json", "*.model", "*.txt", "model.safetensors"],
    "onnx-community/Kokoro-82M-v1.0-ONNX": ["config.json", "tokenizer.json", "onnx/model.onnx", "voices/*.bin"],
}


def hf_hub_cache() -> Path:
    if v := os.environ.get("HF_HUB_CACHE"):
        return Path(v)
    if v := os.environ.get("HF_HOME"):
        return Path(v) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def cached_snapshot(repo: str) -> Path | None:
    """Newest local snapshot directory of a repo, or None if it is not cached."""
    snaps = hf_hub_cache() / ("models--" + repo.replace("/", "--")) / "snapshots"
    if not snaps.is_dir():
        return None
    candidates = [p for p in snaps.iterdir() if p.is_dir() and any(p.rglob("*"))]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None
