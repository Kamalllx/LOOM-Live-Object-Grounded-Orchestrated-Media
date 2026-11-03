"""Persisted event bus + SSE (spec/02 §7, spec/05 §6).

Events are written to SQLite *before* subscribers are woken, so a reload or a restarted gateway replays history via
`Last-Event-ID`. Payloads are validated against their kind on publish (a malformed event is a bug, not a warning).
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from loom.core.contracts.common import Contract
from loom.core.contracts.events import EVENT_DATA_MODELS, Event
from loom.core.store import Store, iso_now

KEEPALIVE_S = 15.0


class EventBus:
    def __init__(self, store: Store) -> None:
        self.store = store
        self._waiters: set[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = set()
        self._lock = threading.Lock()

    def publish(self, channel: str, kind: str, data: dict[str, Any] | Contract) -> Event:
        """Persist and broadcast one event. Thread-safe; callable from sync or async code."""
        if kind not in EVENT_DATA_MODELS:
            raise ValueError(f"unknown event kind {kind!r}")
        payload = data.model_dump(mode="json") if isinstance(data, Contract) else data
        payload = EVENT_DATA_MODELS[kind].model_validate(payload).model_dump(mode="json")
        ts = iso_now()
        event_id = self.store.execute(
            "INSERT INTO events (channel, kind, payload, ts) VALUES (?, ?, ?, ?)",
            (channel, kind, json.dumps(payload, ensure_ascii=False), ts),
        )
        event = Event(id=event_id, channel=channel, ts=datetime.fromisoformat(ts), kind=kind, data=payload)
        self._wake()
        return event

    def history(self, channel: str, after_id: int = 0, limit: int = 1000) -> list[Event]:
        rows = self.store.query(
            "SELECT id, channel, kind, payload, ts FROM events WHERE channel = ? AND id > ? ORDER BY id LIMIT ?",
            (channel, after_id, limit),
        )
        return [
            Event(
                id=r["id"],
                channel=r["channel"],
                kind=r["kind"],
                data=json.loads(r["payload"]),
                ts=datetime.fromisoformat(r["ts"]),
            )
            for r in rows
        ]

    def _wake(self) -> None:
        with self._lock:
            waiters = list(self._waiters)
        for loop, ev in waiters:
            if not loop.is_closed():
                loop.call_soon_threadsafe(ev.set)

    async def subscribe(
        self, channel: str, last_event_id: int = 0, keepalive_s: float = KEEPALIVE_S
    ) -> AsyncIterator[Event | None]:
        """Yield stored events after `last_event_id`, then live ones. Yields None as a keep-alive tick."""
        loop = asyncio.get_running_loop()
        wake = asyncio.Event()
        token = (loop, wake)
        with self._lock:
            self._waiters.add(token)
        try:
            cursor = last_event_id
            while True:
                wake.clear()
                batch = await asyncio.to_thread(self.history, channel, cursor)
                for event in batch:
                    cursor = event.id
                    yield event
                if batch:
                    continue
                try:
                    await asyncio.wait_for(wake.wait(), timeout=keepalive_s)
                except TimeoutError:
                    yield None
        finally:
            with self._lock:
                self._waiters.discard(token)


def format_sse(event: Event | None) -> str:
    """One SSE frame; `None` becomes a comment line that keeps proxies from closing the stream."""
    if event is None:
        return ": keep-alive\n\n"
    data = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
    return f"id: {event.id}\nevent: {event.kind}\ndata: {data}\n\n"
