"""`/api/models` — per-role model status, residency, latency and failure counts (spec/03 §4.8)."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends

from loom.core.config import ROLES
from loom.core.contracts.ops import ModelsReport, ModelStatus
from loom.core.ollama import LoadedModel, OllamaHTTPError, same_tag
from loom.gateway.state import GatewayState, get_state

router = APIRouter()


@router.get("/api/models", response_model=ModelsReport)
async def models(state: GatewayState = Depends(get_state)) -> ModelsReport:
    snap = await state.readiness.current()
    by_role = {r.role: r for r in snap.roles}
    loaded: list[LoadedModel] = []
    if snap.ollama_reachable:
        try:
            loaded = await state.ollama.ps(timeout=state.cfg.ollama.probe_timeout_s)
        except (httpx.HTTPError, OllamaHTTPError):
            loaded = []
    metrics = state.llm.metrics_snapshot()
    out: list[ModelStatus] = []
    for role in ROLES:
        tag = state.cfg.models.role(role).tag
        res = next((m for m in loaded if same_tag(m.name, tag)), None)
        r = by_role.get(role)
        out.append(
            ModelStatus(
                role=role,
                tag=tag,
                present=bool(r and r.present),
                digest=r.digest if r else None,
                resident=res is not None,
                size_vram_bytes=res.size_vram if res else None,
                metrics=metrics[role],
            )
        )
    holder = state.arbiter.holder
    return ModelsReport(models=out, resident=[m.name for m in loaded], gpu_holder=holder.resource if holder else None)
