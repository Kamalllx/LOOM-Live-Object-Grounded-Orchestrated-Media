"""GPU arbiter (spec/02 §3): one heavy GPU user at a time on 8 GB VRAM.

Every piece of GPU work takes a lease on a resource:
  * `"torch"` — perception / render worker. All Ollama models are unloaded first (perception never runs while an
    Ollama model is loaded — CLAUDE.md rule 6).
  * `"ollama:<tag>"` — an Ollama call. Any *other* resident model is unloaded first; the leased model stays warm after
    release until another lease needs the VRAM.
Leases are granted strictly by priority (`tap_explainer` > `session` > `ingest` > `prerender`), FIFO within a
priority. The arbiter publishes `gpu_lease` events so the UI can show "waiting for GPU".
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Protocol

from loom.core.config import Priority
from loom.core.events import EventBus

log = logging.getLogger(__name__)

GPU_CHANNEL = "system"


class OllamaControl(Protocol):
    async def loaded_models(self) -> list[str]: ...

    async def unload(self, tag: str) -> None: ...


@dataclass(order=True)
class _Waiter:
    rank: int
    seq: int
    resource: str = field(compare=False)
    priority: Priority = field(compare=False)
    future: asyncio.Future[None] = field(compare=False)


@dataclass(frozen=True)
class Lease:
    resource: str
    priority: Priority


def ollama_resource(tag: str) -> str:
    return f"ollama:{tag}"


class GpuArbiter:
    def __init__(
        self,
        priorities: dict[Priority, int],
        control: OllamaControl | None = None,
        events: EventBus | None = None,
    ) -> None:
        self.priorities = priorities
        self.control = control
        self.events = events
        self._holder: Lease | None = None
        self._queue: list[_Waiter] = []
        self._seq = itertools.count()
        self._lock = asyncio.Lock()
        self.grant_log: list[str] = []  # resource grant order (diagnostics, tests)

    @property
    def holder(self) -> Lease | None:
        return self._holder

    @property
    def waiting(self) -> int:
        return sum(1 for w in self._queue if not w.future.done())

    @asynccontextmanager
    async def lease(self, resource: str, priority: Priority) -> AsyncIterator[Lease]:
        if resource != "torch" and not resource.startswith("ollama:"):
            raise ValueError(f"unknown GPU resource {resource!r}")
        if priority not in self.priorities:
            raise ValueError(f"unknown priority {priority!r}")
        await self._acquire(resource, priority)
        lease = Lease(resource, priority)
        try:
            await self._prepare(resource)
            yield lease
        finally:
            await self._release()

    async def _acquire(self, resource: str, priority: Priority) -> None:
        loop = asyncio.get_running_loop()
        async with self._lock:
            if self._holder is None and not self._queue:
                self._grant(Lease(resource, priority))
                return
            waiter = _Waiter(self.priorities[priority], next(self._seq), resource, priority, loop.create_future())
            heapq.heappush(self._queue, waiter)
            self._publish("waiting", resource, priority)
        try:
            await waiter.future
        except asyncio.CancelledError:
            async with self._lock:
                if waiter.future.done() and not waiter.future.cancelled():
                    # granted just as we were cancelled: hand the GPU on
                    self._holder = None
                    self._grant_next()
                else:
                    waiter.future.cancel()
            raise

    def _grant(self, lease: Lease) -> None:
        self._holder = lease
        self.grant_log.append(lease.resource)
        self._publish("granted", lease.resource, lease.priority)

    def _grant_next(self) -> None:
        while self._queue:
            w = heapq.heappop(self._queue)
            if w.future.done():  # cancelled waiter
                continue
            self._grant(Lease(w.resource, w.priority))
            w.future.set_result(None)
            return

    async def _release(self) -> None:
        async with self._lock:
            released = self._holder
            self._holder = None
            if released is not None:
                self._publish("released", released.resource, released.priority)
            self._grant_next()

    async def _prepare(self, resource: str) -> None:
        if self.control is None:
            return
        keep = resource.removeprefix("ollama:") if resource.startswith("ollama:") else None
        try:
            loaded = await self.control.loaded_models()
        except Exception as exc:  # Ollama down: nothing of ours is resident on the GPU
            log.warning("gpu arbiter: cannot list loaded models (%s)", exc)
            return
        for tag in loaded:
            if tag != keep:
                try:
                    await self.control.unload(tag)
                except Exception as exc:
                    log.warning("gpu arbiter: failed to unload %s (%s)", tag, exc)

    def _publish(self, state: str, resource: str, priority: Priority) -> None:
        if self.events is None:
            return
        holder = self._holder.resource if self._holder else None
        try:
            self.events.publish(
                GPU_CHANNEL,
                "gpu_lease",
                {"holder": holder, "waiting": self.waiting, "priority": priority, "state": state},
            )
        except Exception as exc:  # events are observability; never block GPU scheduling on them
            log.warning("gpu arbiter: event publish failed (%s) for %s", exc, resource)
