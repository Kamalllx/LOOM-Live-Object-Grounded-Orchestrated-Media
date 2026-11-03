"""Thin async HTTP layer over the local Ollama server (spec/03 §3–4).

Used by the LLM client, the GPU arbiter (`OllamaControl`), readiness checks, `loom doctor` and the model spike.
The host is checked against the locality rules before any request (NFR-LOC-02).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from loom.core.config import LoomConfig
from loom.core.offline import check_model_host


class OllamaHTTPError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"ollama HTTP {status}: {message}")
        self.status = status
        self.message = message


@dataclass(frozen=True)
class ModelInfo:
    name: str
    digest: str
    size: int


@dataclass(frozen=True)
class LoadedModel:
    name: str
    size: int
    size_vram: int
    context_length: int | None


def same_tag(a: str, b: str) -> bool:
    """`qwen3.5:9b` == `qwen3.5:9b`; a bare name means `:latest`."""

    def norm(t: str) -> str:
        return t if ":" in t else f"{t}:latest"

    return norm(a) == norm(b)


class OllamaHttp:
    def __init__(self, cfg: LoomConfig, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.host = check_model_host(cfg).rstrip("/")
        self.cfg = cfg
        # every request passes its own timeout; this default only guards accidental omissions
        self._client = httpx.AsyncClient(base_url=self.host, transport=transport, timeout=600.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, *, json: Any = None, timeout: float | None = None) -> Any:
        resp = await self._client.request(method, path, json=json, timeout=timeout)
        if resp.status_code >= 400:
            try:
                msg = resp.json().get("error", resp.text)
            except ValueError:
                msg = resp.text
            raise OllamaHTTPError(resp.status_code, str(msg))
        return resp.json()

    async def version(self, timeout: float = 3.0) -> str:
        data = await self._request("GET", "/api/version", timeout=timeout)
        return str(data.get("version", ""))

    async def tags(self, timeout: float = 3.0) -> list[ModelInfo]:
        data = await self._request("GET", "/api/tags", timeout=timeout)
        return [
            ModelInfo(name=m["name"], digest=str(m.get("digest", "")), size=int(m.get("size", 0)))
            for m in data.get("models", [])
        ]

    async def ps(self, timeout: float = 3.0) -> list[LoadedModel]:
        data = await self._request("GET", "/api/ps", timeout=timeout)
        return [
            LoadedModel(
                name=m["name"],
                size=int(m.get("size", 0)),
                size_vram=int(m.get("size_vram", 0)),
                context_length=m.get("context_length"),
            )
            for m in data.get("models", [])
        ]

    async def show(self, tag: str, timeout: float = 10.0) -> dict[str, Any]:
        data: dict[str, Any] = await self._request("POST", "/api/show", json={"model": tag}, timeout=timeout)
        return data

    async def chat(self, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        data: dict[str, Any] = await self._request("POST", "/api/chat", json=payload, timeout=timeout)
        return data

    async def generate(self, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        data: dict[str, Any] = await self._request("POST", "/api/generate", json=payload, timeout=timeout)
        return data

    async def embed(self, tag: str, texts: list[str], timeout: float) -> list[list[float]]:
        data = await self._request(
            "POST",
            "/api/embed",
            json={"model": tag, "input": texts, "keep_alive": self.cfg.ollama.keep_alive},
            timeout=timeout,
        )
        return [list(map(float, v)) for v in data["embeddings"]]

    # ---- OllamaControl (GPU arbiter)
    async def loaded_models(self) -> list[str]:
        return [m.name for m in await self.ps()]

    async def unload(self, tag: str) -> None:
        await self._request("POST", "/api/generate", json={"model": tag, "keep_alive": 0}, timeout=30.0)
