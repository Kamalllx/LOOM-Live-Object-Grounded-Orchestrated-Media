from __future__ import annotations

import asyncio

import pytest

from loom.core.events import EventBus
from loom.core.gpu import GpuArbiter, ollama_resource
from loom.core.store import Store

PRIORITIES = {"tap_explainer": 0, "session": 1, "ingest": 2, "prerender": 3}


class Control:
    def __init__(self, loaded: list[str], up: bool = True) -> None:
        self.loaded = loaded
        self.up = up
        self.unloaded: list[str] = []

    async def loaded_models(self) -> list[str]:
        if not self.up:
            raise ConnectionError("ollama down")
        return list(self.loaded)

    async def unload(self, tag: str) -> None:
        self.unloaded.append(tag)
        self.loaded.remove(tag)


async def test_torch_lease_unloads_every_ollama_model() -> None:
    ctl = Control(["qwen3.5:9b", "qwen3-embedding:0.6b"])
    arb = GpuArbiter(PRIORITIES, ctl)  # type: ignore[arg-type]
    async with arb.lease("torch", "ingest") as lease:
        assert lease.resource == "torch"
        assert ctl.loaded == []  # perception never runs while an Ollama model is loaded
    assert arb.holder is None


async def test_ollama_lease_keeps_its_own_model_and_unloads_others() -> None:
    ctl = Control(["gemma4:e4b", "qwen3.5:9b"])
    arb = GpuArbiter(PRIORITIES, ctl)  # type: ignore[arg-type]
    async with arb.lease(ollama_resource("qwen3.5:9b"), "session"):
        assert ctl.loaded == ["qwen3.5:9b"]
        assert ctl.unloaded == ["gemma4:e4b"]


async def test_priority_order_then_fifo() -> None:
    arb = GpuArbiter(PRIORITIES)
    order: list[str] = []
    release = asyncio.Event()

    async def holder() -> None:
        async with arb.lease("torch", "ingest"):
            await release.wait()

    async def job(name: str, priority: str) -> None:
        async with arb.lease("torch", priority):  # type: ignore[arg-type]
            order.append(name)

    h = asyncio.create_task(holder())
    await asyncio.sleep(0.01)
    tasks = [
        asyncio.create_task(job("prerender", "prerender")),
        asyncio.create_task(job("ingest-1", "ingest")),
        asyncio.create_task(job("session", "session")),
        asyncio.create_task(job("ingest-2", "ingest")),
        asyncio.create_task(job("tap", "tap_explainer")),
    ]
    await asyncio.sleep(0.01)
    assert arb.waiting == 5
    release.set()
    await asyncio.gather(h, *tasks)
    assert order == ["tap", "session", "ingest-1", "ingest-2", "prerender"]


async def test_one_holder_at_a_time() -> None:
    arb = GpuArbiter(PRIORITIES)
    active = 0
    peak = 0

    async def job() -> None:
        nonlocal active, peak
        async with arb.lease("torch", "session"):
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.005)
            active -= 1

    await asyncio.gather(*(job() for _ in range(10)))
    assert peak == 1


async def test_cancelled_waiter_does_not_block_the_queue() -> None:
    arb = GpuArbiter(PRIORITIES)
    release = asyncio.Event()
    done: list[str] = []

    async def holder() -> None:
        async with arb.lease("torch", "ingest"):
            await release.wait()

    async def job(name: str) -> None:
        async with arb.lease("torch", "session"):
            done.append(name)

    h = asyncio.create_task(holder())
    await asyncio.sleep(0.01)
    doomed = asyncio.create_task(job("doomed"))
    survivor = asyncio.create_task(job("survivor"))
    await asyncio.sleep(0.01)
    doomed.cancel()
    release.set()
    await asyncio.gather(h, survivor)
    with pytest.raises(asyncio.CancelledError):
        await doomed
    assert done == ["survivor"] and arb.holder is None


async def test_ollama_down_does_not_block_a_lease() -> None:
    arb = GpuArbiter(PRIORITIES, Control([], up=False))  # type: ignore[arg-type]
    async with arb.lease("torch", "ingest"):
        pass


async def test_lease_events_and_validation(store: Store) -> None:
    bus = EventBus(store)
    arb = GpuArbiter(PRIORITIES, events=bus)
    async with arb.lease("torch", "tap_explainer"):
        pass
    states = [e.data["state"] for e in bus.history("system")]
    assert states == ["granted", "released"]
    with pytest.raises(ValueError, match="resource"):
        async with arb.lease("cuda:0", "session"):
            pass
    with pytest.raises(ValueError, match="priority"):
        async with arb.lease("torch", "urgent"):  # type: ignore[arg-type]
            pass
