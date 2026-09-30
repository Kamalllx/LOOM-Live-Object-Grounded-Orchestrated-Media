"""Minimal Agent2Agent (A2A) support, so the agent mesh (Person 2) can discover and task these agents:
  GET  <agent>/.well-known/agent.json   Agent Card
  POST <agent>/                         JSON-RPC 2.0 "message/send"; contract JSON travels as one `data` part
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

PROTOCOL_VERSION = "0.3.0"


def agent_card(name: str, description: str, url: str, skills: list[dict], version: str) -> dict:
    return {
        "protocolVersion": PROTOCOL_VERSION, "name": name, "description": description, "url": url, "version": version,
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["application/json"], "defaultOutputModes": ["application/json"],
        "skills": [{"id": s["id"], "name": s.get("name", s["id"]), "description": s.get("description", ""),
                    "tags": s.get("tags", []), "inputModes": ["application/json"], "outputModes": ["application/json"]}
                   for s in skills],
    }


def a2a_router(card: dict, handler) -> APIRouter:
    """handler(skill_id, data) -> dict. Unknown methods and handler errors become JSON-RPC errors."""
    router = APIRouter()

    @router.get("/.well-known/agent.json")
    def get_card():
        return card

    @router.post("/")
    async def rpc(request: Request):
        body = await request.json()
        rid = body.get("id")
        if body.get("method") != "message/send":
            return JSONResponse({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Method not found"}})
        msg = (body.get("params") or {}).get("message") or {}
        data = next((p.get("data") for p in msg.get("parts", []) if p.get("kind") == "data"), None) or {}
        skill = (msg.get("metadata") or {}).get("skill") or card["skills"][0]["id"]
        try:
            out = await run_in_threadpool(handler, skill, data)
        except Exception as e:
            return JSONResponse({"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": f"{type(e).__name__}: {e}"}})
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "kind": "message", "role": "agent", "messageId": uuid.uuid4().hex,
            "parts": [{"kind": "data", "data": out}], "metadata": {"agent": card["name"], "version": card["version"]}}}

    return router
