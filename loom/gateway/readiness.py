"""Real readiness (FR-OPS-01; fixes audit B2 "health lies").

A background loop re-checks every `ollama.ready_poll_s` (default 10 s, so a stopped Ollama is reported well within
30 s): Ollama reachable, each role's model present (`/api/tags` — loads nothing into VRAM), last successful call per
role (LLM client metrics or the last `loom doctor` smoke run), worker spawnable, disk free, offline/locality.
`ready` is false when Ollama is unreachable or any of brain/judge/safety is missing; embed/ocr only degrade.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from loom.core.config import REQUIRED_ROLES, ROLES, LoomConfig
from loom.core.contracts.ops import Readiness, RoleReadiness
from loom.core.llm import LLMClient
from loom.core.offline import LocalityViolation, check_model_host
from loom.core.ollama import OllamaHttp, OllamaHTTPError, same_tag
from loom.core.store import utcnow

log = logging.getLogger(__name__)

WORKER_CHECK_EVERY_S = 300.0


def smoke_file(cfg: LoomConfig) -> Path:
    return cfg.data_dir / "run" / "smoke.json"


async def worker_selftest(timeout_s: float = 30.0) -> bool:
    """Spawn `python -m loom.worker --selftest` and require a clean exit (the worker is spawnable)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "loom.worker",
            "--selftest",
            stdin=asyncio.subprocess.DEVNULL,  # never inherit the gateway's console handles (they may be gone)
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout_s)
    except (OSError, TimeoutError):
        return False
    if proc.returncode != 0:
        return False
    try:
        return bool(json.loads(out.decode("utf-8").strip().splitlines()[-1]).get("ok"))
    except (ValueError, IndexError):
        return False


class ReadinessMonitor:
    def __init__(self, cfg: LoomConfig, http: OllamaHttp, llm: LLMClient | None = None) -> None:
        self.cfg = cfg
        self.http = http
        self.llm = llm
        self._snapshot: Readiness | None = None
        self._checked_mono = 0.0
        self._worker_ok: bool | None = None
        self._worker_checked_mono = -WORKER_CHECK_EVERY_S
        self._lock = asyncio.Lock()

    async def current(self) -> Readiness:
        """Latest snapshot; refreshed on demand if older than the poll interval."""
        if self._snapshot is None or time.monotonic() - self._checked_mono > self.cfg.ollama.ready_poll_s:
            return await self.refresh()
        return self._snapshot

    async def run(self) -> None:
        while True:
            try:
                await self.refresh()
            except Exception:  # the monitor must never die; the next tick retries
                log.exception("readiness check failed")
            await asyncio.sleep(self.cfg.ollama.ready_poll_s)

    async def refresh(self) -> Readiness:
        async with self._lock:
            snap = await self._check()
            self._snapshot = snap
            self._checked_mono = time.monotonic()
            return snap

    async def _check(self) -> Readiness:
        cfg = self.cfg
        missing: list[str] = []
        degraded: list[str] = []
        timeout = cfg.ollama.probe_timeout_s

        try:
            check_model_host(cfg)
        except LocalityViolation as exc:
            missing.append(str(exc))

        version: str | None = None
        present: dict[str, str] = {}
        reachable = False
        try:
            version = await self.http.version(timeout=timeout)
            present = {m.name: m.digest for m in await self.http.tags(timeout=timeout)}
            reachable = True
        except (httpx.HTTPError, OllamaHTTPError) as exc:
            missing.append(f"ollama unreachable at {cfg.ollama.host} ({type(exc).__name__})")

        smoke = self._read_smoke()
        metrics = self.llm.metrics_snapshot() if self.llm else {}
        roles: list[RoleReadiness] = []
        for role in ROLES:
            tag = cfg.models.role(role).tag
            digest = next((d for name, d in present.items() if same_tag(name, tag)), None)
            is_present = digest is not None
            required = role in REQUIRED_ROLES
            last_ok, last_err = _latest(smoke.get(role), metrics.get(role))
            roles.append(
                RoleReadiness(
                    role=role,
                    tag=tag,
                    required=required,
                    present=is_present,
                    digest=digest,
                    last_ok_at=last_ok,
                    last_error=last_err,
                )
            )
            if not is_present:
                why = "not present" if reachable else "unavailable (ollama unreachable)"
                (missing if required else degraded).append(f"role {role}: {tag} {why}")

        if self._worker_ok is None or time.monotonic() - self._worker_checked_mono > WORKER_CHECK_EVERY_S:
            self._worker_ok = await worker_selftest()
            self._worker_checked_mono = time.monotonic()
        if not self._worker_ok:
            missing.append("worker not spawnable (python -m loom.worker --selftest failed)")

        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        free_gb = shutil.disk_usage(cfg.data_dir).free / 1e9
        if free_gb < cfg.runtime.min_free_disk_gb:
            missing.append(f"disk free {free_gb:.1f} GB < {cfg.runtime.min_free_disk_gb} GB")
        elif free_gb < cfg.runtime.warn_free_disk_gb:
            degraded.append(f"disk free {free_gb:.1f} GB (warn below {cfg.runtime.warn_free_disk_gb} GB)")

        return Readiness(
            ready=not missing,
            missing=missing,
            degraded=degraded,
            ollama_reachable=reachable,
            ollama_version=version,
            roles=roles,
            worker_ok=bool(self._worker_ok),
            disk_free_gb=round(free_gb, 1),
            offline=cfg.runtime.offline,
            checked_at=utcnow(),
        )

    def _read_smoke(self) -> dict[str, dict[str, Any]]:
        p = smoke_file(self.cfg)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        roles = data.get("roles", {}) if isinstance(data, dict) else {}
        return roles if isinstance(roles, dict) else {}


def _latest(smoke: dict[str, Any] | None, metric: object) -> tuple[datetime | None, str | None]:
    """Combine the doctor smoke record and live call metrics: newest success wins; error only if no newer success."""
    ok_times: list[datetime] = []
    err: str | None = None
    if smoke:
        if smoke.get("ok") is True and smoke.get("at"):
            ok_times.append(datetime.fromisoformat(smoke["at"]))
        elif smoke.get("error"):
            err = str(smoke["error"])
    last_ok = getattr(metric, "last_ok_at", None)
    if last_ok is not None:
        ok_times.append(last_ok)
    if (e := getattr(metric, "last_error", None)) is not None:
        err = e
    return (max(ok_times) if ok_times else None), err
