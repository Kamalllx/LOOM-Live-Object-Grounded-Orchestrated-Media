"""`GET /api/events/{channel}` — SSE over persisted events with `Last-Event-ID` resume (spec/02 §7)."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from loom.core.events import format_sse
from loom.gateway.state import GatewayState, get_state

router = APIRouter()

_CHANNEL = re.compile(r"^(sess|ingest|tap|job|system)_[A-Za-z0-9_]+$|^system$")


@router.get("/api/events/{channel}")
async def events(
    channel: str,
    request: Request,
    state: GatewayState = Depends(get_state),
    last_event_id_header: str | None = Header(None, alias="Last-Event-ID"),
    last_event_id: int | None = Query(None, ge=0, description="resume point when the header cannot be set"),
    once: bool = Query(False, description="replay stored events and close (no live tail)"),
) -> StreamingResponse:
    if not _CHANNEL.match(channel):
        raise HTTPException(400, f"invalid channel {channel!r}")
    resume = last_event_id or 0
    if last_event_id_header:
        try:
            resume = max(resume, int(last_event_id_header))
        except ValueError as exc:
            raise HTTPException(400, "Last-Event-ID must be an integer") from exc

    async def stream() -> AsyncIterator[str]:
        yield "retry: 2000\n\n"
        if once:
            for event in state.events.history(channel, resume):
                yield format_sse(event)
            return
        async for live in state.events.subscribe(channel, resume):
            if await request.is_disconnected():
                break
            yield format_sse(live)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
