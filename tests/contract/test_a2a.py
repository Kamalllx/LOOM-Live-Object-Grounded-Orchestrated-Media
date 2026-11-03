"""Contract tests for the A2A helper: card paths, JSON-RPC message/send, tasks/get, error codes (spec/05 §8)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from loom.core.a2a import A2AClient, A2AError, Skill, build_router
from loom.core.contracts.a2a import AgentCard, AgentSkill, LoomCardExtension, LoomErrorCode
from loom.core.contracts.common import Contract
from loom.core.events import EventBus
from loom.core.llm import ModelUnavailable
from loom.core.store import Store

BASE = "http://agents.test/a2a/echo"


class EchoIn(Contract):
    text: str
    delay_s: float = 0.0
    fail: str | None = None


class EchoOut(Contract):
    text: str
    length: int


async def echo(req: EchoIn) -> EchoOut:
    await asyncio.sleep(req.delay_s)
    if req.fail == "model":
        raise ModelUnavailable("connection refused", role="brain", tag="qwen3.5:9b", prompt="x@1")
    if req.fail == "shape":
        return EchoIn(text="wrong contract")  # type: ignore[return-value]
    return EchoOut(text=req.text.upper(), length=len(req.text))


def card() -> AgentCard:
    return AgentCard(
        name="loom-echo",
        description="test agent",
        url=BASE,
        version="2.0",
        skills=[
            AgentSkill(id="echo", name="Echo", description="uppercase"),
            AgentSkill(id="echo_long", name="Echo (task)", description="uppercase as a task"),
        ],
        x_loom=LoomCardExtension(input_contract="EchoIn", output_contract="EchoOut", trust="first_party"),
    )


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    app.include_router(
        build_router(
            card(),
            [
                Skill("echo", "Echo", "uppercase", EchoIn, EchoOut, echo, timeout_s=0.5),
                Skill("echo_long", "Echo (task)", "task", EchoIn, EchoOut, echo, timeout_s=5, long_running=True),
            ],
        ),
        prefix="/a2a/echo",
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agents.test") as c:
        yield c


async def test_card_served_on_both_paths(client: httpx.AsyncClient) -> None:
    new = (await client.get("/a2a/echo/.well-known/agent-card.json")).json()
    legacy = (await client.get("/a2a/echo/.well-known/agent.json")).json()
    assert new == legacy
    parsed = AgentCard.model_validate(new)
    assert new["x-loom"]["trust"] == "first_party" and parsed.protocolVersion.startswith("0.3")
    assert (await A2AClient(client).get_card(BASE)).name == "loom-echo"


async def test_message_send_round_trip_with_events(client: httpx.AsyncClient, store: Store) -> None:
    bus = EventBus(store)
    res = await A2AClient(client, events=bus).send(
        BASE, "echo", EchoIn(text="acid"), EchoOut, agent="loom-echo", channel="sess_t1"
    )
    assert res.value == EchoOut(text="ACID", length=4) and res.latency_ms >= 0
    kinds = [(e.kind, e.data["status"]) for e in bus.history("sess_t1")]
    assert kinds == [("agent_call", "started"), ("agent_done", "ok")]


async def test_raw_jsonrpc_shape(client: httpx.AsyncClient) -> None:
    body = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "role": "user",
                "messageId": "m1",
                "parts": [{"kind": "data", "data": {"text": "hi"}}],
                "metadata": {"skill": "echo"},
            }
        },
    }
    r = (await client.post("/a2a/echo/", json=body)).json()
    assert r["id"] == 7 and r["result"]["kind"] == "message" and r["result"]["role"] == "agent"
    assert r["result"]["parts"][0]["data"] == {"text": "HI", "length": 2}


@pytest.mark.parametrize(
    ("skill", "data", "code"),
    [
        ("echo", {"txt": "typo"}, LoomErrorCode.CONTRACT_INVALID),
        ("nope", {"text": "x"}, LoomErrorCode.METHOD_NOT_FOUND),
        ("echo", {"text": "x", "delay_s": 2}, LoomErrorCode.TIMEOUT),
        ("echo", {"text": "x", "fail": "model"}, LoomErrorCode.MODEL_UNAVAILABLE),
        ("echo", {"text": "x", "fail": "shape"}, LoomErrorCode.CONTRACT_INVALID),
    ],
)
async def test_error_codes(client: httpx.AsyncClient, skill: str, data: dict[str, object], code: int) -> None:
    with pytest.raises(A2AError) as err:
        await A2AClient(client).send(BASE, skill, data, EchoOut)
    assert err.value.code == code


async def test_bad_json_and_bad_envelope(client: httpx.AsyncClient) -> None:
    r = (await client.post("/a2a/echo/", content=b"{nope")).json()
    assert r["error"]["code"] == LoomErrorCode.PARSE_ERROR
    r = (await client.post("/a2a/echo/", json={"jsonrpc": "1.0", "id": 1, "method": "x"})).json()
    assert r["error"]["code"] == LoomErrorCode.INVALID_REQUEST


async def test_long_task_is_polled(client: httpx.AsyncClient) -> None:
    res = await A2AClient(client, poll_interval_s=0.01).send(
        BASE, "echo_long", {"text": "base", "delay_s": 0.05}, EchoOut
    )
    assert res.value.text == "BASE"


async def test_long_task_failure_carries_code(client: httpx.AsyncClient) -> None:
    with pytest.raises(A2AError) as err:
        await A2AClient(client, poll_interval_s=0.01).send(BASE, "echo_long", {"text": "x", "fail": "model"}, EchoOut)
    assert err.value.code == LoomErrorCode.MODEL_UNAVAILABLE


async def test_client_side_output_validation(client: httpx.AsyncClient) -> None:
    class Strict(Contract):
        text: str
        length: int
        extra_required: bool

    with pytest.raises(A2AError) as err:
        await A2AClient(client).send(BASE, "echo", {"text": "x"}, Strict)
    assert err.value.code == LoomErrorCode.CONTRACT_INVALID


async def test_retries_only_for_idempotent_skills() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("refused", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        c = A2AClient(http, retries=2)
        with pytest.raises(A2AError):
            await c.send(BASE, "echo", {"text": "x"}, EchoOut)
        assert attempts == 1
        with pytest.raises(A2AError):
            await c.send(BASE, "echo", {"text": "x"}, EchoOut, idempotent=True)
        assert attempts == 1 + 3


def test_card_skills_must_match_handlers() -> None:
    with pytest.raises(ValueError, match="card skills"):
        build_router(card(), [Skill("echo", "Echo", "", EchoIn, EchoOut, echo)])
