"""Process-wide gateway state, built in the app lifespan and reached from routes via `request.app.state.loom`."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Request

from loom.core.blobs import BlobStore
from loom.core.config import LoomConfig
from loom.core.events import EventBus
from loom.core.gpu import GpuArbiter
from loom.core.jobs import JobQueue
from loom.core.llm import LLMClient
from loom.core.ollama import OllamaHttp
from loom.core.store import Store
from loom.gateway.readiness import ReadinessMonitor


@dataclass
class GatewayState:
    cfg: LoomConfig
    store: Store
    blobs: BlobStore
    events: EventBus
    jobs: JobQueue
    ollama: OllamaHttp
    arbiter: GpuArbiter
    llm: LLMClient
    readiness: ReadinessMonitor
    started_mono: float = field(default_factory=time.monotonic)

    @property
    def media_dir(self) -> Path:
        return self.cfg.data_dir / "media"


def get_state(request: Request) -> GatewayState:
    state: GatewayState = request.app.state.loom
    return state
