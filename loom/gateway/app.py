"""Gateway app factory (spec/02 §2, §8). `loom gateway` serves `create_app(load_config())` with uvicorn."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from loom import __version__
from loom.core.blobs import BlobStore
from loom.core.config import LoomConfig
from loom.core.events import EventBus
from loom.core.gpu import GpuArbiter
from loom.core.jobs import JobQueue
from loom.core.llm import LLMClient
from loom.core.offline import apply_offline_env
from loom.core.ollama import OllamaHttp
from loom.core.store import Store
from loom.gateway.readiness import ReadinessMonitor
from loom.gateway.routes import app_api, events, health, media, models, runs
from loom.gateway.state import GatewayState

log = logging.getLogger(__name__)


def create_app(
    cfg: LoomConfig,
    *,
    ollama_transport: httpx.AsyncBaseTransport | None = None,
    run_monitor: bool = True,
) -> FastAPI:
    """Build the gateway. `ollama_transport` lets tests substitute a fake Ollama; `run_monitor` starts the
    background readiness loop (tests drive `refresh()` directly)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        apply_offline_env(cfg)
        data = cfg.data_dir
        data.mkdir(parents=True, exist_ok=True)
        (data / "media").mkdir(exist_ok=True)
        (data / "run").mkdir(exist_ok=True)
        store = Store(data / "loom.db")
        store.migrate()
        from loom.agents.session import seed

        seed(store, data)
        bus = EventBus(store)
        jobs = JobQueue(store)
        resumed = jobs.recover()
        if resumed:
            log.info("re-queued %d interrupted jobs: %s", len(resumed), resumed)
        ollama = OllamaHttp(cfg, transport=ollama_transport)
        arbiter = GpuArbiter(cfg.gpu.priorities, control=ollama, events=bus)
        llm = LLMClient(cfg, ollama, store=store, arbiter=arbiter)
        monitor = ReadinessMonitor(cfg, ollama, llm)
        app.state.loom = GatewayState(
            cfg=cfg,
            store=store,
            blobs=BlobStore(data / "blobs"),
            events=bus,
            jobs=jobs,
            ollama=ollama,
            arbiter=arbiter,
            llm=llm,
            readiness=monitor,
        )
        task = asyncio.create_task(monitor.run()) if run_monitor else None
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await ollama.aclose()
            store.close()

    app = FastAPI(title="LOOM gateway", version=__version__, lifespan=lifespan)
    web = cfg.runtime.web_port
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[f"http://localhost:{web}", f"http://127.0.0.1:{web}"],
        allow_origin_regex=r"^chrome-extension://[a-p]{32}$",
        allow_methods=["GET", "POST", "PATCH", "DELETE", "HEAD"],
        allow_headers=["Content-Type", "Last-Event-ID", "Range", "X-Loom-Token"],
        expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
    )
    for r in (health.router, models.router, events.router, media.router, app_api.router, runs.router):
        app.include_router(r)
    from fastapi.staticfiles import StaticFiles

    from loom.agents.a2a_agents import routers as agent_routers

    base = f"http://127.0.0.1:{cfg.runtime.gateway_port}"
    for name, r, _card in agent_routers(lambda: app.state.loom, base):
        app.include_router(r, prefix=f"/a2a/{name}")

    from loom.gateway.static import STATIC_DIR

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="player")
    return app
