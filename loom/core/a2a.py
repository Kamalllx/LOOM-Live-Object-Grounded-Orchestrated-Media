"""A2A helper: server router + client (spec/02 §5, FR-MESH-01).

Server: `build_router(card, skills)` returns a FastAPI router serving the Agent Card (A2A 0.3 path and the legacy
`agent.json` path) and JSON-RPC 2.0 `message/send` / `tasks/get`. Requests and responses are validated against the
skill's contracts; failures map to LOOM error codes (spec/05 §8).

Client: `A2AClient.send(url, skill, data, OutputModel)` with timeout, retries for idempotent skills only, task
polling for long skills, latency measurement and `agent_call`/`agent_done` events.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from loom.core.contracts.a2a import (
    AgentCard,
    DataPart,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    LoomErrorCode,
    Message,
    MessageSendParams,
    Task,
    TaskQueryParams,
    TaskStatus,
)
from loom.core.contracts.common import Contract
from loom.core.events import EventBus

CARD_PATH = "/.well-known/agent-card.json"
LEGACY_CARD_PATH = "/.well-known/agent.json"


class A2AError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.data = data


def error_code_for(exc: BaseException) -> int:
    """Typed errors elsewhere (e.g. llm.ModelUnavailable) declare their JSON-RPC code via `a2a_code`."""
    if isinstance(exc, A2AError):
        return exc.code
    code = getattr(exc, "a2a_code", None)
    return int(code) if code is not None else int(LoomErrorCode.INTERNAL_ERROR)


@dataclass
class Skill:
    id: str
    name: str
    description: str
    input_model: type[Contract]
    output_model: type[Contract]
    handler: Callable[[Any], Awaitable[Contract]]
    timeout_s: float = 30.0
    long_running: bool = False  # returns a Task; the client polls tasks/get
    tags: list[str] = field(default_factory=list)


def _rpc_error(req_id: Any, code: int, message: str, data: Any = None) -> JSONResponse:
    body = JsonRpcResponse(id=req_id, error=JsonRpcError(code=code, message=message, data=data))
    return JSONResponse(body.model_dump(mode="json", exclude_none=True))


def _rpc_result(req_id: Any, result: Contract) -> JSONResponse:
    body = JsonRpcResponse(id=req_id, result=result.model_dump(mode="json", by_alias=True, exclude_none=True))
    return JSONResponse(body.model_dump(mode="json", exclude_none=True))


def build_router(card: AgentCard, skills: list[Skill]) -> APIRouter:
    by_id = {s.id: s for s in skills}
    if set(by_id) != {s.id for s in card.skills}:
        raise ValueError(f"card skills {sorted(s.id for s in card.skills)} != handlers {sorted(by_id)}")
    tasks: dict[str, Task] = {}
    background: set[asyncio.Task[None]] = set()
    router = APIRouter()
    card_json = card.model_dump(mode="json", by_alias=True, exclude_none=True)

    @router.get(CARD_PATH)
    @router.get(LEGACY_CARD_PATH)
    async def agent_card() -> dict[str, Any]:
        return card_json

    async def run_skill(skill: Skill, data: dict[str, Any]) -> Contract:
        try:
            request = skill.input_model.model_validate(data)
        except ValidationError as exc:
            raise A2AError(LoomErrorCode.CONTRACT_INVALID, f"{skill.id}: invalid request", exc.errors()) from exc
        try:
            result = await asyncio.wait_for(skill.handler(request), timeout=skill.timeout_s)
        except TimeoutError as exc:
            raise A2AError(LoomErrorCode.TIMEOUT, f"{skill.id}: exceeded {skill.timeout_s}s") from exc
        try:
            return skill.output_model.model_validate(result.model_dump(mode="json", by_alias=True))
        except ValidationError as exc:
            raise A2AError(LoomErrorCode.CONTRACT_INVALID, f"{skill.id}: invalid response", exc.errors()) from exc

    async def run_task(task_id: str, skill: Skill, data: dict[str, Any]) -> None:
        try:
            out = await run_skill(skill, data)
            tasks[task_id] = Task(
                id=task_id,
                status=TaskStatus(state="completed"),
                artifacts=[DataPart(data=out.model_dump(mode="json", by_alias=True))],
            )
        except Exception as exc:
            tasks[task_id] = Task(
                id=task_id,
                status=TaskStatus(state="failed", message=str(exc)),
                error={"code": error_code_for(exc), "message": str(exc)},
            )

    @router.post("/")
    async def jsonrpc(request: Request) -> JSONResponse:
        try:
            raw = json.loads(await request.body())
        except ValueError:
            return _rpc_error(None, LoomErrorCode.PARSE_ERROR, "invalid JSON")
        try:
            rpc = JsonRpcRequest.model_validate(raw)
        except ValidationError as exc:
            req_id = raw.get("id") if isinstance(raw, dict) else None
            return _rpc_error(req_id, LoomErrorCode.INVALID_REQUEST, "invalid JSON-RPC request", exc.errors())

        if rpc.method == "tasks/get":
            try:
                q = TaskQueryParams.model_validate(rpc.params)
            except ValidationError as exc:
                return _rpc_error(rpc.id, LoomErrorCode.INVALID_PARAMS, "invalid tasks/get params", exc.errors())
            task = tasks.get(q.id)
            if task is None:
                return _rpc_error(rpc.id, LoomErrorCode.ARTIFACT_NOT_FOUND, f"unknown task {q.id}")
            return _rpc_result(rpc.id, task)

        if rpc.method != "message/send":
            return _rpc_error(rpc.id, LoomErrorCode.METHOD_NOT_FOUND, f"unsupported method {rpc.method}")
        try:
            params = MessageSendParams.model_validate(rpc.params)
        except ValidationError as exc:
            return _rpc_error(rpc.id, LoomErrorCode.CONTRACT_INVALID, "invalid message/send params", exc.errors())
        skill_id = params.message.metadata.get("skill")
        skill = by_id.get(skill_id) if isinstance(skill_id, str) else None
        if skill is None:
            return _rpc_error(rpc.id, LoomErrorCode.METHOD_NOT_FOUND, f"unknown skill {skill_id!r}")
        data = params.message.parts[0].data

        if skill.long_running:
            task_id = "task_" + uuid.uuid4().hex[:12]
            tasks[task_id] = Task(id=task_id, status=TaskStatus(state="working"))
            t = asyncio.create_task(run_task(task_id, skill, data))
            background.add(t)
            t.add_done_callback(background.discard)
            return _rpc_result(rpc.id, tasks[task_id])

        try:
            out = await run_skill(skill, data)
        except Exception as exc:
            return _rpc_error(rpc.id, error_code_for(exc), str(exc), getattr(exc, "data", None))
        reply = Message(
            role="agent",
            messageId=uuid.uuid4().hex,
            parts=[DataPart(data=out.model_dump(mode="json", by_alias=True))],
            metadata={"skill": skill.id},
        )
        return _rpc_result(rpc.id, reply)

    return router


@dataclass(frozen=True)
class CallResult[T]:
    value: T
    latency_ms: int
    agent: str
    skill: str


class A2AClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        events: EventBus | None = None,
        timeout_s: float = 30.0,
        retries: int = 1,
        poll_interval_s: float = 0.5,
    ) -> None:
        self.http = http
        self.events = events
        self.timeout_s = timeout_s
        self.retries = retries
        self.poll_interval_s = poll_interval_s

    async def get_card(self, url: str) -> AgentCard:
        resp = await self.http.get(url.rstrip("/") + CARD_PATH, timeout=self.timeout_s)
        resp.raise_for_status()
        try:
            return AgentCard.model_validate(resp.json())
        except ValidationError as exc:
            raise A2AError(LoomErrorCode.CONTRACT_INVALID, f"invalid agent card at {url}", exc.errors()) from exc

    async def send[T: Contract](
        self,
        url: str,
        skill: str,
        data: dict[str, Any] | Contract,
        output_model: type[T],
        *,
        agent: str = "",
        idempotent: bool = False,
        timeout_s: float | None = None,
        channel: str | None = None,
    ) -> CallResult[T]:
        timeout = timeout_s or self.timeout_s
        payload = data.model_dump(mode="json", by_alias=True) if isinstance(data, Contract) else data
        agent = agent or url
        self._event(channel, "agent_call", agent, skill, "started")
        start = time.perf_counter()
        try:
            raw = await asyncio.wait_for(self._send_with_retries(url, skill, payload, idempotent, timeout), timeout)
            if raw.get("kind") == "task":
                raw = await asyncio.wait_for(self._poll(url, raw["id"]), timeout)
            try:
                value = output_model.model_validate(raw)
            except ValidationError as exc:
                raise A2AError(
                    LoomErrorCode.CONTRACT_INVALID, f"{agent}.{skill}: invalid response", exc.errors()
                ) from exc
        except TimeoutError as exc:
            self._event(channel, "agent_done", agent, skill, "failed", start)
            raise A2AError(LoomErrorCode.TIMEOUT, f"{agent}.{skill}: exceeded {timeout}s") from exc
        except Exception:
            self._event(channel, "agent_done", agent, skill, "failed", start)
            raise
        latency = int((time.perf_counter() - start) * 1000)
        self._event(channel, "agent_done", agent, skill, "ok", start)
        return CallResult(value=value, latency_ms=latency, agent=agent, skill=skill)

    async def _send_with_retries(
        self, url: str, skill: str, payload: dict[str, Any], idempotent: bool, timeout: float
    ) -> dict[str, Any]:
        attempts = 1 + (self.retries if idempotent else 0)
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                return await self._rpc(
                    url,
                    "message/send",
                    {
                        "message": {
                            "kind": "message",
                            "role": "user",
                            "messageId": uuid.uuid4().hex,
                            "parts": [{"kind": "data", "data": payload}],
                            "metadata": {"skill": skill},
                        }
                    },
                    timeout,
                )
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last = exc
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.2 * (attempt + 1))
        raise A2AError(LoomErrorCode.INTERNAL_ERROR, f"{url}: {type(last).__name__}: {last}") from last

    async def _poll(self, url: str, task_id: str) -> dict[str, Any]:
        while True:
            task = Task.model_validate(await self._rpc(url, "tasks/get", {"id": task_id}, self.timeout_s))
            if task.status.state == "completed":
                if not task.artifacts:
                    raise A2AError(LoomErrorCode.CONTRACT_INVALID, f"task {task_id} completed without an artifact")
                return task.artifacts[0].data
            if task.status.state in ("failed", "canceled"):
                err = task.error or {}
                raise A2AError(int(err.get("code", LoomErrorCode.INTERNAL_ERROR)), str(err.get("message", "failed")))
            await asyncio.sleep(self.poll_interval_s)

    async def _rpc(self, url: str, method: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        req = JsonRpcRequest(id=uuid.uuid4().hex, method=method, params=params)
        resp = await self.http.post(url.rstrip("/") + "/", json=req.model_dump(mode="json"), timeout=timeout)
        resp.raise_for_status()
        try:
            body = JsonRpcResponse.model_validate(resp.json())
        except (ValidationError, ValueError) as exc:
            raise A2AError(LoomErrorCode.CONTRACT_INVALID, f"{url}: invalid JSON-RPC response") from exc
        if body.error is not None:
            raise A2AError(body.error.code, body.error.message, body.error.data)
        if body.result is None:
            raise A2AError(LoomErrorCode.CONTRACT_INVALID, f"{url}: empty JSON-RPC result")
        if method == "message/send" and body.result.get("kind") == "message":
            msg = Message.model_validate(body.result)
            return msg.parts[0].data
        return body.result

    def _event(
        self, channel: str | None, kind: str, agent: str, skill: str, status: str, start: float | None = None
    ) -> None:
        if self.events is None or channel is None:
            return
        data: dict[str, Any] = {"agent": agent, "skill": skill, "status": status}
        if start is not None:
            data["latency_ms"] = int((time.perf_counter() - start) * 1000)
        self.events.publish(channel, kind, data)
