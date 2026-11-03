from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from loom.core.events import EventBus, format_sse
from loom.core.jobs import JobQueue, JobStateError
from loom.core.store import Store


def test_publish_persists_and_validates(store: Store) -> None:
    bus = EventBus(store)
    e = bus.publish("ingest_vid1", "ingest_stage", {"stage": "asr", "status": "started"})
    assert e.id >= 1 and e.data["progress"] == 0.0
    with pytest.raises(ValidationError):
        bus.publish("ingest_vid1", "ingest_stage", {"stage": "asr", "status": "exploded"})
    with pytest.raises(ValueError, match="unknown event kind"):
        bus.publish("ingest_vid1", "made_up", {})
    assert [x.id for x in bus.history("ingest_vid1")] == [e.id]


def test_history_resumes_after_id_per_channel(store: Store) -> None:
    bus = EventBus(store)
    ids = [bus.publish("sess_a", "degraded", {"component": "c", "reason": str(i)}).id for i in range(5)]
    bus.publish("sess_b", "degraded", {"component": "c", "reason": "other"})
    assert [e.id for e in bus.history("sess_a", ids[1])] == ids[2:]
    assert len(bus.history("sess_b")) == 1


def test_events_survive_restart(tmp_path: Path) -> None:
    s = Store(tmp_path / "e.db")
    s.migrate()
    EventBus(s).publish("system", "error", {"message": "m", "where": "w"})
    s.close()
    s2 = Store(tmp_path / "e.db")
    assert len(EventBus(s2).history("system")) == 1
    s2.close()


async def test_subscribe_replays_then_streams_live(store: Store) -> None:
    bus = EventBus(store)
    first = bus.publish("sess_x", "degraded", {"component": "a", "reason": "1"})
    second = bus.publish("sess_x", "degraded", {"component": "a", "reason": "2"})
    got: list[int] = []

    async def consume() -> None:
        async for ev in bus.subscribe("sess_x", last_event_id=first.id, keepalive_s=5):
            if ev is not None:
                got.append(ev.id)
            if len(got) == 2:
                return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    third = await asyncio.to_thread(bus.publish, "sess_x", "degraded", {"component": "a", "reason": "3"})
    await asyncio.wait_for(task, 5)
    assert got == [second.id, third.id]  # resumed after Last-Event-ID, then live


async def test_subscribe_keepalive(store: Store) -> None:
    bus = EventBus(store)
    gen = bus.subscribe("sess_idle", keepalive_s=0.05)
    assert await asyncio.wait_for(anext(gen), 2) is None
    await gen.aclose()


def test_format_sse(store: Store) -> None:
    e = EventBus(store).publish("system", "error", {"message": "m", "where": "w"})
    frame = format_sse(e)
    assert frame.startswith(f"id: {e.id}\nevent: error\ndata: {{") and frame.endswith("\n\n")
    assert format_sse(None) == ": keep-alive\n\n"


def test_job_lifecycle_and_dedupe(store: Store) -> None:
    q = JobQueue(store)
    job, created = q.submit("ingest", {"path": "a.mp4"}, dedupe_key="video:abc")
    assert created and job.status == "queued"
    again, created2 = q.submit("ingest", {"path": "a.mp4"}, dedupe_key="video:abc")
    assert not created2 and again.id == job.id  # uploading the same lesson twice yields one job
    claimed = q.claim(("ingest",))
    assert claimed is not None and claimed.id == job.id and claimed.status == "running" and claimed.attempts == 1
    assert q.claim(("ingest",)) is None
    q.progress(job.id, "asr", 0.4)
    assert q.get(job.id).stage == "asr"
    done = q.complete(job.id)
    assert done.status == "completed" and done.progress == 1.0
    with pytest.raises(JobStateError):
        q.fail(job.id, "too late")


def test_failed_job_allows_resubmit(store: Store) -> None:
    q = JobQueue(store)
    job, _ = q.submit("render", {}, dedupe_key="clip:1")
    q.claim(("render",))
    q.fail(job.id, "render crashed")
    retry, created = q.submit("render", {}, dedupe_key="clip:1")
    assert created and retry.id != job.id


def test_claim_order_and_kinds(store: Store) -> None:
    q = JobQueue(store)
    a, _ = q.submit("prerender", {})
    b, _ = q.submit("ingest", {})
    c, _ = q.submit("ingest", {})
    assert q.claim(("ingest",)).id == b.id  # type: ignore[union-attr]
    assert q.claim(("ingest", "prerender")).id == a.id  # type: ignore[union-attr]
    assert q.claim(("ingest",)).id == c.id  # type: ignore[union-attr]


def test_cancel(store: Store) -> None:
    q = JobQueue(store)
    queued, _ = q.submit("ingest", {})
    assert q.request_cancel(queued.id).status == "canceled"
    running, _ = q.submit("ingest", {})
    q.claim(("ingest",))
    assert q.request_cancel(running.id).status == "running"
    assert q.cancel_requested(running.id)


def test_jobs_survive_gateway_restart(tmp_path: Path) -> None:
    s = Store(tmp_path / "j.db")
    s.migrate()
    q = JobQueue(s)
    job, _ = q.submit("ingest", {"path": "a.mp4"})
    q.claim(("ingest",))
    q.progress(job.id, "segment", 0.5)
    s.close()  # the gateway dies mid-`segment`

    s2 = Store(tmp_path / "j.db")
    q2 = JobQueue(s2)
    assert q2.recover() == [job.id]
    resumed = q2.get(job.id)
    assert resumed.status == "queued" and resumed.stage == "segment"  # resumes at the stage it reached
    again = q2.claim(("ingest",))
    assert again is not None and again.attempts == 2
    s2.close()
