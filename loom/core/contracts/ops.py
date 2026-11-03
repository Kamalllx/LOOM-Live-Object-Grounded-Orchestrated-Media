"""Operations payloads: health, readiness, model status, jobs (spec/02 §8, FR-OPS-01, FR-ING-02)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from loom.core.contracts.common import Contract


class Health(Contract):
    """Liveness only: the process is up. It says nothing about models — that is `/api/ready`."""

    alive: Literal[True] = True
    version: str
    uptime_s: float = Field(ge=0)


class RoleReadiness(Contract):
    role: str
    tag: str
    required: bool
    present: bool
    digest: str | None = None
    last_ok_at: datetime | None = None
    last_error: str | None = None


class Readiness(Contract):
    ready: bool
    missing: list[str] = []  # human-readable reasons, e.g. "role brain: qwen3.5:9b not present"
    degraded: list[str] = []  # non-blocking problems (embed/ocr missing, low disk warning)
    ollama_reachable: bool
    ollama_version: str | None = None
    roles: list[RoleReadiness] = []
    worker_ok: bool
    disk_free_gb: float
    offline: bool
    checked_at: datetime


class RoleMetrics(Contract):
    calls: int = 0
    cache_hits: int = 0
    failures: int = 0
    repairs: int = 0
    p50_ms: float | None = None
    p95_ms: float | None = None
    last_latency_ms: float | None = None
    last_ok_at: datetime | None = None
    last_error: str | None = None


class ModelStatus(Contract):
    role: str
    tag: str
    present: bool
    digest: str | None = None
    resident: bool = False
    size_vram_bytes: int | None = None
    metrics: RoleMetrics = RoleMetrics()


class ModelsReport(Contract):
    models: list[ModelStatus]
    resident: list[str] = []
    gpu_holder: str | None = None


JobStatus = Literal["queued", "running", "completed", "failed", "canceled"]
JobKind = Literal["ingest", "render", "prerender"]


class Job(Contract):
    id: str = Field(pattern=r"^job_[a-z0-9]+$")
    kind: JobKind
    status: JobStatus
    stage: str | None = None
    progress: float = Field(0.0, ge=0, le=1)
    error: str | None = None
    payload: dict[str, Any] = {}
    attempts: int = Field(0, ge=0)
    dedupe_key: str | None = None
    created_at: datetime
    updated_at: datetime
