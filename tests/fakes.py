"""A scriptable in-process fake of the Ollama HTTP API (httpx.MockTransport) for unit and contract tests."""

from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class FakeOllama:
    models: dict[str, str] = field(default_factory=dict)  # tag -> digest (the fixture builds it from loom.toml)
    up: bool = True
    loaded: list[str] = field(default_factory=list)
    replies: dict[str, deque[str | Exception]] = field(default_factory=lambda: defaultdict(deque))
    default_reply: str = '{"ok": true}'
    requests: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    embed_dim: int = 8

    def queue(self, tag: str, *replies: str | Exception) -> None:
        self.replies[tag].extend(replies)

    def calls(self, path: str) -> list[dict[str, Any]]:
        return [body for p, body in self.requests if p == path]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if not self.up:
            raise httpx.ConnectError("connection refused", request=request)
        path = request.url.path
        body: dict[str, Any] = json.loads(request.content) if request.content else {}
        self.requests.append((path, body))
        if path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.12"})
        if path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": n, "digest": d, "size": 1000} for n, d in self.models.items()]}
            )
        if path == "/api/ps":
            return httpx.Response(
                200, json={"models": [{"name": n, "size": 1000, "size_vram": 900} for n in self.loaded]}
            )
        model = body.get("model", "")
        if model and model not in self.models:
            return httpx.Response(404, json={"error": f"model '{model}' not found"})
        if path == "/api/generate":
            if body.get("keep_alive") == 0 and "prompt" not in body:
                if model in self.loaded:
                    self.loaded.remove(model)
                return httpx.Response(200, json={"model": model, "response": "", "done": True})
            self._load(model)
            return httpx.Response(200, json={"model": model, "response": "ready", "done": True})
        if path == "/api/chat":
            self._load(model)
            reply = self.replies[model].popleft() if self.replies[model] else self.default_reply
            if isinstance(reply, Exception):
                raise reply
            return httpx.Response(200, json={"model": model, "message": {"role": "assistant", "content": reply}})
        if path == "/api/embed":
            self._load(model)
            vecs = [[float((len(t) + i) % 7 + 1) for i in range(self.embed_dim)] for t in body["input"]]
            return httpx.Response(200, json={"model": model, "embeddings": vecs})
        if path == "/api/show":
            return httpx.Response(200, json={"details": {}})
        return httpx.Response(404, json={"error": "unknown path"})

    def _load(self, model: str) -> None:
        if model not in self.loaded:
            self.loaded.append(model)
