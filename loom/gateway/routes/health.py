"""`/api/health` (liveness) and `/api/ready` (real per-role readiness) — FR-OPS-01."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from loom import __version__
from loom.core.contracts.ops import Health, Readiness
from loom.gateway.state import GatewayState, get_state

router = APIRouter()


@router.get("/api/health", response_model=Health)
async def health(state: GatewayState = Depends(get_state)) -> Health:
    """The process is up. Deliberately says nothing about models: that is /api/ready."""
    return Health(version=__version__, uptime_s=round(time.monotonic() - state.started_mono, 1))


@router.get("/api/ready", response_model=Readiness, responses={503: {"model": Readiness}})
async def ready(state: GatewayState = Depends(get_state)) -> JSONResponse:
    snap = await state.readiness.current()
    return JSONResponse(snap.model_dump(mode="json"), status_code=200 if snap.ready else 503)
