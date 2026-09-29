"""Minimal Agent2Agent (A2A) protocol support.

Implements the parts of A2A that LOOM relies on:
  * Agent Card discovery at  GET  {agent_url}/.well-known/agent.json
  * JSON-RPC 2.0 tasking at  POST {agent_url}/   method "message/send"
Payloads travel as a single `data` part, so agents exchange contract JSON directly.
"""
import time
import uuid

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

PROTOCOL_VERSION = "0.3.0"


def agent_card(name, description, url, skills, version="1.0"):
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "name": name,
        "description": description,
        "url": url,
        "version": version,
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {"id": s["id"], "name": s.get("name", s["id"]), "description": s.get("description", ""),
             "tags": s.get("tags", []), "inputModes": ["application/json"], "outputModes": ["application/json"],
             "input": s.get("input", []), "output": s.get("output", [])}
            for s in skills
        ],
    }


def a2a_router(card, handler):
    """Router exposing an agent. `handler(skill_id, data) -> dict` does the work."""
    router = APIRouter()

    @router.get("/.well-known/agent.json")
    def get_card():
        return card

    @router.post("/")
    async def rpc(request: Request):
        body = await request.json()
        rpc_id = body.get("id")
        if body.get("method") != "message/send":
            return JSONResponse({"jsonrpc": "2.0", "id": rpc_id,
                                 "error": {"code": -32601, "message": "Method not found"}})
        msg = body.get("params", {}).get("message", {})
        data = next((p.get("data") for p in msg.get("parts", []) if p.get("kind") == "data"), {}) or {}
        skill = (msg.get("metadata") or {}).get("skill") or card["skills"][0]["id"]
        try:
            from starlette.concurrency import run_in_threadpool
            out = await run_in_threadpool(handler, skill, data)
        except Exception as e:
            return JSONResponse({"jsonrpc": "2.0", "id": rpc_id,
                                 "error": {"code": -32000, "message": f"{type(e).__name__}: {e}"}})
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {
            "kind": "message", "role": "agent", "messageId": uuid.uuid4().hex,
            "parts": [{"kind": "data", "data": out}],
            "metadata": {"agent": card["name"], "version": card["version"]},
        }}

    return router


class A2AError(RuntimeError):
    pass


def fetch_card(agent_url, timeout=10):
    r = httpx.get(agent_url.rstrip("/") + "/.well-known/agent.json", timeout=timeout)
    r.raise_for_status()
    return r.json()


def send(agent_url, data, skill=None, timeout=300):
    """Send one message/send call; returns (data, meta) with meta = {agent, version, latency_ms}."""
    payload = {
        "jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": "message/send",
        "params": {"message": {
            "role": "user", "messageId": uuid.uuid4().hex,
            "parts": [{"kind": "data", "data": data}],
            "metadata": {"skill": skill} if skill else {},
        }},
    }
    t0 = time.time()
    r = httpx.post(agent_url.rstrip("/") + "/", json=payload, timeout=timeout)
    r.raise_for_status()
    body = r.json()
    if "error" in body:
        raise A2AError(f"{agent_url}: {body['error']['message']}")
    result = body["result"]
    out = next(p["data"] for p in result["parts"] if p.get("kind") == "data")
    meta = dict(result.get("metadata") or {}, latency_ms=round((time.time() - t0) * 1000))
    return out, meta


class Registry:
    """Agent Card registry: agents are discovered by URL and looked up by skill id."""

    def __init__(self):
        self.cards = {}

    def register(self, agent_url):
        card = fetch_card(agent_url)
        self.cards[card["name"]] = card
        return card

    def unregister(self, name):
        self.cards.pop(name, None)

    def with_skill(self, skill_id):
        return [c for c in self.cards.values() if any(s["id"] == skill_id for s in c["skills"])]

    def by_name(self, name):
        return self.cards.get(name)
