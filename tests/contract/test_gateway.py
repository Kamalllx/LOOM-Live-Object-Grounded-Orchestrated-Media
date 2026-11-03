"""Contract tests for the gateway skeleton: health, ready, models, SSE resume, media range requests."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import uvicorn
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from loom.core.config import LoomConfig
from loom.core.contracts.ops import Health, ModelsReport, Readiness
from loom.gateway.app import create_app
from loom.gateway.state import GatewayState
from tests.conftest import BRAIN, OCR, SAFETY
from tests.fakes import FakeOllama


@pytest.fixture
async def gw(cfg: LoomConfig, fake_ollama: FakeOllama) -> AsyncIterator[tuple[httpx.AsyncClient, GatewayState]]:
    app = create_app(cfg, ollama_transport=fake_ollama.transport(), run_monitor=False)
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gw.test") as client:
            yield client, app.state.loom


async def test_health_is_liveness_only(gw: tuple[httpx.AsyncClient, GatewayState], fake_ollama: FakeOllama) -> None:
    client, _ = gw
    fake_ollama.up = False
    r = await client.get("/api/health")
    assert r.status_code == 200
    Health.model_validate(r.json())
    assert "ok" not in r.json()  # never claims the system is fine


async def test_ready_when_every_role_present(gw: tuple[httpx.AsyncClient, GatewayState]) -> None:
    client, _ = gw
    r = await client.get("/api/ready")
    snap = Readiness.model_validate(r.json())
    assert r.status_code == 200 and snap.ready, snap.missing
    assert snap.ollama_reachable and snap.worker_ok and snap.offline
    assert {x.role for x in snap.roles} == {"brain", "judge", "safety", "embed", "ocr"}
    assert all(x.present and x.digest for x in snap.roles)


async def test_ready_reports_missing_roles(gw: tuple[httpx.AsyncClient, GatewayState], fake_ollama: FakeOllama) -> None:
    client, state = gw
    del fake_ollama.models[SAFETY]
    del fake_ollama.models[OCR]
    snap = Readiness.model_validate((await client.get("/api/ready")).json())
    if snap.ready:  # cached snapshot younger than the poll interval
        snap = await state.readiness.refresh()
    assert not snap.ready
    assert snap.missing == [f"role safety: {SAFETY} not present"]
    assert snap.degraded[0] == f"role ocr: {OCR} not present"  # optional role only degrades


async def test_stopping_ollama_flips_ready_within_poll(
    gw: tuple[httpx.AsyncClient, GatewayState], fake_ollama: FakeOllama, cfg: LoomConfig
) -> None:
    client, _ = gw
    assert (await client.get("/api/ready")).status_code == 200
    fake_ollama.up = False
    await asyncio.sleep(cfg.ollama.ready_poll_s + 0.05)
    r = await client.get("/api/ready")
    snap = Readiness.model_validate(r.json())
    assert r.status_code == 503 and not snap.ready and not snap.ollama_reachable
    assert any("ollama unreachable" in m for m in snap.missing)
    # every required role is named, optional roles only degrade
    assert {m.split(":")[0] for m in snap.missing if m.startswith("role ")} == {
        "role brain",
        "role judge",
        "role safety",
    }
    assert {m.split(":")[0] for m in snap.degraded if m.startswith("role ")} == {"role embed", "role ocr"}
    fake_ollama.up = True
    await asyncio.sleep(cfg.ollama.ready_poll_s + 0.05)
    assert (await client.get("/api/ready")).status_code == 200


async def test_models_report(gw: tuple[httpx.AsyncClient, GatewayState], fake_ollama: FakeOllama) -> None:
    client, _ = gw
    fake_ollama.loaded = [BRAIN]
    report = ModelsReport.model_validate((await client.get("/api/models")).json())
    brain = next(m for m in report.models if m.role == "brain")
    assert brain.resident and brain.size_vram_bytes == 900 and brain.digest == "sha256-brain"
    assert report.resident == [BRAIN] and report.gpu_holder is None


def _ids(sse: str) -> list[int]:
    return [int(line[4:]) for line in sse.splitlines() if line.startswith("id: ")]


async def test_sse_replays_and_resumes(gw: tuple[httpx.AsyncClient, GatewayState]) -> None:
    client, state = gw
    ids = [state.events.publish("sess_abc", "degraded", {"component": "c", "reason": str(i)}).id for i in range(4)]
    full = (await client.get("/api/events/sess_abc", params={"once": True})).text
    assert full.startswith("retry: 2000") and _ids(full) == ids
    resumed = await client.get("/api/events/sess_abc", params={"once": True}, headers={"Last-Event-ID": str(ids[1])})
    assert resumed.headers["content-type"].startswith("text/event-stream")
    assert _ids(resumed.text) == ids[2:]
    assert (await client.get("/api/events/bad channel!")).status_code in (400, 404)


@pytest.fixture
def live_gateway(cfg: LoomConfig, fake_ollama: FakeOllama) -> Iterator[tuple[str, FastAPI]]:
    """A real uvicorn server (httpx's ASGI transport buffers whole bodies, so it cannot test a live SSE tail)."""
    app = create_app(cfg, ollama_transport=fake_ollama.transport(), run_monitor=False)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("gateway did not start")
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}", app
    server.should_exit = True
    thread.join(10)


async def test_sse_live_stream_over_real_http(live_gateway: tuple[str, FastAPI]) -> None:
    base, app = live_gateway
    state: GatewayState = app.state.loom
    first = state.events.publish("sess_live", "degraded", {"component": "c", "reason": "1"})

    async def later() -> None:
        await asyncio.sleep(0.2)
        await asyncio.to_thread(state.events.publish, "sess_live", "delivered", {"status": "approved", "pass_count": 1})

    seen: list[str] = []
    ids: list[int] = []
    async with httpx.AsyncClient(base_url=base, timeout=10) as client:
        task = asyncio.create_task(later())
        async with client.stream("GET", "/api/events/sess_live") as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            async for line in r.aiter_lines():
                if line.startswith("event: "):
                    seen.append(line[7:])
                if line.startswith("id: "):
                    ids.append(int(line[4:]))
                if len(seen) == 2:
                    break
        await task
        # reconnect with Last-Event-ID: only what came after is replayed
        resumed = await client.get(
            "/api/events/sess_live", params={"once": True}, headers={"Last-Event-ID": str(first.id)}
        )
    assert seen == ["degraded", "delivered"] and ids[0] == first.id
    assert _ids(resumed.text) == ids[1:]


async def test_media_full_and_range(gw: tuple[httpx.AsyncClient, GatewayState]) -> None:
    client, state = gw
    data = bytes(range(256)) * 40  # 10240 bytes
    (state.media_dir / "videos").mkdir(parents=True, exist_ok=True)
    (state.media_dir / "videos" / "demo.mp4").write_bytes(data)

    full = await client.get("/media/videos/demo.mp4")
    assert full.status_code == 200 and full.content == data
    assert full.headers["accept-ranges"] == "bytes" and full.headers["content-type"] == "video/mp4"

    part = await client.get("/media/videos/demo.mp4", headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and part.content == data[100:200]
    assert part.headers["content-range"] == "bytes 100-199/10240"

    tail = await client.get("/media/videos/demo.mp4", headers={"Range": "bytes=-16"})
    assert tail.status_code == 206 and tail.content == data[-16:]

    open_end = await client.get("/media/videos/demo.mp4", headers={"Range": "bytes=10000-"})
    assert open_end.content == data[10000:]

    bad = await client.get("/media/videos/demo.mp4", headers={"Range": "bytes=99999-"})
    assert bad.status_code == 416 and bad.headers["content-range"] == "bytes */10240"


async def test_media_cannot_escape_its_root(gw: tuple[httpx.AsyncClient, GatewayState]) -> None:
    client, state = gw
    (state.cfg.data_dir / "loom_secret.txt").write_text("x", encoding="utf-8")
    for path in ("/media/../loom_secret.txt", "/media/%2e%2e/loom_secret.txt", "/media/videos/missing.mp4"):
        assert (await client.get(path)).status_code == 404


async def test_cors_allows_only_web_origin(gw: tuple[httpx.AsyncClient, GatewayState]) -> None:
    client, _ = gw
    ok = await client.get("/api/health", headers={"Origin": "http://localhost:3001"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3001"
    evil = await client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in evil.headers
