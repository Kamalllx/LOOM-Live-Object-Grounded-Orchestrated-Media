"""Typed view of `loom.toml` (spec/02 §11, NFR-MNT-03).

Every model tag, threshold, port and budget lives in the TOML file; code reads it only through `LoomConfig`.
Unknown keys are rejected so a typo cannot silently fall back to a default.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Role = Literal["brain", "judge", "safety", "embed", "ocr"]
ROLES: tuple[Role, ...] = ("brain", "judge", "safety", "embed", "ocr")
# Roles whose absence makes the system not ready (spec/03 §6); embed/ocr degrade instead.
REQUIRED_ROLES: tuple[Role, ...] = ("brain", "judge", "safety")

Priority = Literal["tap_explainer", "session", "ingest", "prerender"]

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuntimeConfig(_Section):
    offline: bool = True
    data_dir: Path = Path("data")
    max_seconds: int = Field(600, gt=0)
    gateway_port: int = 8000
    web_port: int = 3001
    plugin_allowlist: list[str] = ["127.0.0.1", "localhost"]
    min_free_disk_gb: float = 5.0
    warn_free_disk_gb: float = 20.0
    allow_remote_ollama: bool = False


class OllamaConfig(_Section):
    host: str = "http://127.0.0.1:11434"
    default_num_ctx: int = 8192
    keep_alive: str = "10m"
    ready_poll_s: float = Field(10.0, gt=0, le=25)
    probe_timeout_s: float = Field(3.0, gt=0)


class ModelRoleConfig(_Section):
    tag: str
    fallback: str | None = None
    fallback_role: Role | None = None
    temperature: float = 0.0
    seed: int | None = None
    top_p: float | None = None
    num_ctx: int | None = None
    think: bool = False
    timeout_s: float = 120.0
    max_tokens: int | None = None  # Ollama num_predict cap (guards runaway generation)
    batch: int | None = None
    reread_below_confidence: float | None = None


class ModelsConfig(_Section):
    brain: ModelRoleConfig
    judge: ModelRoleConfig
    safety: ModelRoleConfig
    embed: ModelRoleConfig
    ocr: ModelRoleConfig

    def role(self, role: Role) -> ModelRoleConfig:
        cfg: ModelRoleConfig = getattr(self, role)
        return cfg


class PerceptionConfig(_Section):
    segmentation_tier: Literal["boxes", "sam2", "sam3"] = "sam2"
    sample_fps: float = 2.0
    hazard_window_fps: float = 4.0
    frame_width: int = 960
    chunk_seconds: float = 60.0
    chunk_overlap_seconds: float = 1.0
    asr_model: str = "large-v3-turbo"
    detector: str
    segmenter: str
    verifier: str
    box_threshold: float = 0.30
    text_threshold: float = 0.25
    siglip_margin: float = 0.10
    hazard_classes: list[str]
    lookalikes: dict[str, list[str]] = {}


class SafetyConfig(_Section):
    taxonomy: list[str]
    standard_threshold: float = 0.5
    strict_threshold: float = 0.2
    mask_pad: float = 0.04
    mask_dilate_diag: float = 0.03
    time_pad_s: float = 0.5


class PedagogyConfig(_Section):
    skip: float = 0.80
    condense: float = 0.60
    keep: float = 0.35
    pace_shift: dict[str, float]
    prereq_mastery: float = 0.35


class PersonalizerConfig(_Section):
    condense_ratio: float = 0.5
    condense_min_s: float = 6.0
    formula_hold_s: float = 3.0
    too_short_ratio: float = 0.30


class AssessmentConfig(_Section):
    max_questions: int = 3
    correct_gain: float = 0.35
    wrong_decay: float = 0.75
    explainer_gain: float = 0.05
    exposure_gain: float = 0.03


class CriticConfig(_Section):
    factuality: float = 0.80
    coherence: float = 0.80
    safety: float = 1.0
    evidence_top_k: int = 5


class LoopConfig(_Section):
    budget: int = 3
    tap_budget: int = 2


class AnimatorConfig(_Section):
    version: str = "2.0"
    max_repairs: int = 2
    render_timeout_s: float = 120.0
    render_quality: str = "-qm"
    sandbox_memory_mb: int = 2048
    max_source_lines: int = 250
    tts: list[str] = ["kokoro", "piper", "sapi"]
    voice: str = "af_heart"


class A2AConfig(_Section):
    default_timeout_s: float = 30.0
    retries: int = Field(1, ge=0, le=3)


class GpuConfig(_Section):
    max_vram_gb: float = 7.5
    priorities: dict[Priority, int]

    @field_validator("priorities")
    @classmethod
    def _all_priorities(cls, v: dict[Priority, int]) -> dict[Priority, int]:
        missing = {"tap_explainer", "session", "ingest", "prerender"} - set(v)
        if missing:
            raise ValueError(f"gpu.priorities missing {sorted(missing)}")
        return v


class LoomConfig(_Section):
    runtime: RuntimeConfig
    ollama: OllamaConfig
    models: ModelsConfig
    perception: PerceptionConfig
    safety: SafetyConfig
    pedagogy: PedagogyConfig
    personalizer: PersonalizerConfig
    assessment: AssessmentConfig
    critic: CriticConfig
    loop: LoopConfig
    animator: AnimatorConfig
    a2a: A2AConfig = A2AConfig()
    gpu: GpuConfig

    source_path: Path | None = None

    @property
    def data_dir(self) -> Path:
        d = self.runtime.data_dir
        if d.is_absolute():
            return d
        base = self.source_path.parent if self.source_path else PROJECT_ROOT
        return base / d


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_overrides(raw: dict[str, object]) -> None:
    """Apply LOOM_* environment overrides (spec/01 NFR-LOC-01/02, FR-ING-01)."""
    runtime = raw.setdefault("runtime", {})
    assert isinstance(runtime, dict)
    if (v := os.environ.get("LOOM_OFFLINE")) is not None:
        runtime["offline"] = _truthy(v)
    if (v := os.environ.get("LOOM_MAX_SECONDS")) is not None:
        runtime["max_seconds"] = int(v)
    if (v := os.environ.get("LOOM_DATA_DIR")) is not None:
        runtime["data_dir"] = v
    if (v := os.environ.get("LOOM_ALLOW_REMOTE_OLLAMA")) is not None:
        runtime["allow_remote_ollama"] = _truthy(v)
    if (v := os.environ.get("LOOM_OLLAMA_HOST")) is not None:
        ollama = raw.setdefault("ollama", {})
        assert isinstance(ollama, dict)
        ollama["host"] = v


def config_path() -> Path:
    if env := os.environ.get("LOOM_CONFIG"):
        return Path(env)
    return PROJECT_ROOT / "loom.toml"


def load_config(path: Path | None = None) -> LoomConfig:
    path = path or config_path()
    with path.open("rb") as fh:
        raw: dict[str, object] = tomllib.load(fh)
    _env_overrides(raw)
    raw["source_path"] = path.resolve()
    return LoomConfig.model_validate(raw)
