"""The LLM client (spec/03 §4): roles, structured output, one repair, typed errors, a cache that never stores failures.

    result = await llm.call("judge", "claims_verify", {"claims": [...]}, Verdicts)

1. role -> tag + options from `loom.toml` (never a model name in calling code);
2. prompt rendered from `prompts/<id>.md`, untrusted data only inside `<data>` blocks;
3. GPU lease `ollama:<tag>` from the arbiter;
4. `POST /api/chat` with `format` = the schema's JSON Schema (or a caller-supplied text parser for models with a
   native output format, e.g. Granite Guardian);
5. validate; on failure exactly one repair call quoting the validation error; then `ModelOutputInvalid`;
6. typed errors `ModelUnavailable` / `ModelOutputInvalid` / `ModelRefused` (all carry role, tag, prompt);
7. successful, validated results cached by (digest, prompt@version, data, images, options, schema);
8. per-role metrics for `/api/models`.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from PIL import Image
from pydantic import BaseModel, ValidationError

from loom.core.config import ROLES, LoomConfig, Priority, Role
from loom.core.contracts.a2a import LoomErrorCode
from loom.core.contracts.common import canonical_json
from loom.core.contracts.ops import RoleMetrics
from loom.core.gpu import GpuArbiter, ollama_resource
from loom.core.ollama import OllamaHttp, OllamaHTTPError, same_tag
from loom.core.prompts import PromptLibrary
from loom.core.store import Store, iso_now, utcnow

MAX_IMAGE_SIDE = 1024
EMBED_PROMPT = "embed@1"


class LLMError(RuntimeError):
    a2a_code = LoomErrorCode.MODEL_UNAVAILABLE

    def __init__(self, message: str, *, role: str, tag: str, prompt: str) -> None:
        super().__init__(f"{role} ({tag}) {prompt}: {message}")
        self.role = role
        self.tag = tag
        self.prompt = prompt
        self.reason = message


class ModelUnavailable(LLMError):
    """Connection refused, model not found, 5xx, or timeout."""


class ModelOutputInvalid(LLMError):
    """Output still invalid after the single repair attempt."""


class ModelRefused(LLMError):
    """Empty reply or refusal."""


@dataclass(frozen=True)
class LLMResult[T]:
    value: T
    model: str
    digest: str
    prompt: str
    latency_ms: int
    cache_hit: bool
    repaired: bool = False
    thinking: str | None = None


@dataclass
class _Metrics:
    calls: int = 0
    cache_hits: int = 0
    failures: int = 0
    repairs: int = 0
    latencies: deque[float] = field(default_factory=lambda: deque(maxlen=500))
    last_ok_at: datetime | None = None
    last_error: str | None = None

    def snapshot(self) -> RoleMetrics:
        lat = sorted(self.latencies)

        def pct(p: float) -> float | None:
            return round(lat[min(len(lat) - 1, int(p * len(lat)))], 1) if lat else None

        return RoleMetrics(
            calls=self.calls,
            cache_hits=self.cache_hits,
            failures=self.failures,
            repairs=self.repairs,
            p50_ms=pct(0.5),
            p95_ms=pct(0.95),
            last_latency_ms=round(self.latencies[-1], 1) if self.latencies else None,
            last_ok_at=self.last_ok_at,
            last_error=self.last_error,
        )


def encode_image(path: Path) -> tuple[str, str]:
    """Downscale to <= 1024 px on the long side; return (base64 PNG, sha256 of the encoded bytes)."""
    with Image.open(path) as src:
        im = src.convert("RGB")
    im.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=False)
    raw = buf.getvalue()
    return base64.b64encode(raw).decode("ascii"), hashlib.sha256(raw).hexdigest()


def _schema_fingerprint(schema: type[BaseModel]) -> str:
    return hashlib.sha256(canonical_json(schema.model_json_schema())).hexdigest()[:16]


class LLMClient:
    def __init__(
        self,
        cfg: LoomConfig,
        http: OllamaHttp,
        *,
        store: Store | None = None,
        arbiter: GpuArbiter | None = None,
        prompts: PromptLibrary | None = None,
    ) -> None:
        self.cfg = cfg
        self.http = http
        self.store = store
        self.arbiter = arbiter
        self.prompts = prompts or PromptLibrary()
        self.metrics: dict[str, _Metrics] = {r: _Metrics() for r in ROLES}
        self._digests: dict[str, str] = {}

    # ------------------------------------------------------------------ public API
    async def call[T: BaseModel](
        self,
        role: Role,
        prompt_id: str,
        data: dict[str, Any],
        schema: type[T],
        *,
        images: list[Path] | None = None,
        think: bool | None = None,
        timeout_s: float | None = None,
        use_cache: bool = True,
        params: dict[str, str] | None = None,
        parser: Callable[[str], T] | None = None,
        priority: Priority = "session",
        model: str | None = None,
    ) -> LLMResult[T]:
        """Structured call for a role. `model` is for evaluation only (spike/fallback comparison of a role)."""
        prompt = self.prompts.get(prompt_id)
        if prompt.model_role != role:
            raise ValueError(f"prompt {prompt.ref} is written for role {prompt.model_role!r}, not {role!r}")
        rcfg = self.cfg.models.role(role)
        tag = model or rcfg.tag
        metrics = self.metrics[role]
        metrics.calls += 1
        try:
            digest = await self.digest(tag, role=role, prompt=prompt.ref)
            think_on = think if think is not None else (prompt.think if prompt.think is not None else rcfg.think)
            options: dict[str, Any] = {
                "temperature": rcfg.temperature,
                "num_ctx": rcfg.num_ctx or self.cfg.ollama.default_num_ctx,
            }
            if rcfg.seed is not None:
                options["seed"] = rcfg.seed
            if rcfg.top_p is not None:
                options["top_p"] = rcfg.top_p
            if rcfg.max_tokens is not None:
                options["num_predict"] = rcfg.max_tokens
            system, user = prompt.render(data, params)
            encoded = [encode_image(p) for p in images or []]
            use_format = prompt.output == "json" and parser is None
            key = hashlib.sha256(
                canonical_json(
                    {
                        "digest": digest,
                        "prompt": prompt.ref,
                        "system": system,
                        "user": user,
                        "images": [h for _, h in encoded],
                        "options": options,
                        "think": think_on,
                        "schema": _schema_fingerprint(schema),
                        "parser": getattr(parser, "__qualname__", None),
                    }
                )
            ).hexdigest()
            cacheable = use_cache and self.store is not None and (rcfg.temperature == 0 or rcfg.seed is not None)
            if cacheable and (hit := self._cache_get(key, schema)) is not None:
                metrics.cache_hits += 1
                metrics.last_ok_at = utcnow()
                return LLMResult(hit, tag, digest, prompt.ref, 0, cache_hit=True)

            messages: list[dict[str, Any]] = []
            if system:
                messages.append({"role": "system", "content": system})
            user_msg: dict[str, Any] = {"role": "user", "content": user}
            if encoded:
                user_msg["images"] = [b for b, _ in encoded]
            messages.append(user_msg)
            payload: dict[str, Any] = {
                "model": tag,
                "messages": messages,
                "stream": False,
                "think": think_on,
                "options": options,
                "keep_alive": self.cfg.ollama.keep_alive,
            }
            if use_format:
                payload["format"] = schema.model_json_schema()
            timeout = timeout_s or rcfg.timeout_s
            ctx = dict(role=role, tag=tag, prompt=prompt.ref)

            start = time.perf_counter()
            async with self._lease(tag, priority):
                content, thinking = await self._chat(payload, timeout, ctx)
                repaired = False
                try:
                    value = self._parse(content, schema, parser)
                except (ValidationError, ValueError) as first_error:
                    repaired = True
                    metrics.repairs += 1
                    payload["messages"] = [
                        *messages,
                        {"role": "assistant", "content": content},
                        {"role": "user", "content": _repair_instruction(first_error, use_format)},
                    ]
                    content, thinking = await self._chat(payload, timeout, ctx)
                    try:
                        value = self._parse(content, schema, parser)
                    except (ValidationError, ValueError) as second_error:
                        raise ModelOutputInvalid(_short(second_error), **ctx) from second_error
            latency = (time.perf_counter() - start) * 1000
        except LLMError as exc:
            metrics.failures += 1
            metrics.last_error = f"{type(exc).__name__}: {exc.reason}"
            raise

        metrics.latencies.append(latency)
        metrics.last_ok_at = utcnow()
        metrics.last_error = None
        if cacheable:
            self._cache_put(key, role, tag, digest, prompt.ref, value)
        return LLMResult(value, tag, digest, prompt.ref, int(latency), False, repaired, thinking)

    async def embed(
        self, texts: list[str], *, priority: Priority = "session", use_cache: bool = True, model: str | None = None
    ) -> np.ndarray:
        """L2-normalized embeddings, batched, cached by text hash (spec/03 §4)."""
        rcfg = self.cfg.models.embed
        tag = model or rcfg.tag
        metrics = self.metrics["embed"]
        metrics.calls += 1
        ctx = dict(role="embed", tag=tag, prompt=EMBED_PROMPT)
        try:
            digest = await self.digest(tag, role="embed", prompt=EMBED_PROMPT)
            keys = [hashlib.sha256(canonical_json([digest, t])).hexdigest() for t in texts]
            vectors: dict[int, list[float]] = {}
            if use_cache and self.store is not None:
                for i, k in enumerate(keys):
                    row = self.store.query_one("SELECT value FROM llm_cache WHERE key = ?", (k,))
                    if row is not None:
                        vectors[i] = json.loads(row["value"])
                metrics.cache_hits += len(vectors)
            todo = [i for i in range(len(texts)) if i not in vectors]
            batch = rcfg.batch or 64
            start = time.perf_counter()
            if todo:
                async with self._lease(tag, priority):
                    for s in range(0, len(todo), batch):
                        idx = todo[s : s + batch]
                        try:
                            out = await self.http.embed(tag, [texts[i] for i in idx], timeout=rcfg.timeout_s)
                        except (httpx.HTTPError, OllamaHTTPError) as exc:
                            raise ModelUnavailable(_transport_reason(exc), **ctx) from exc
                        if len(out) != len(idx):
                            raise ModelOutputInvalid(f"{len(out)} vectors for {len(idx)} texts", **ctx)
                        for i, v in zip(idx, out, strict=True):
                            vectors[i] = v
                            if use_cache and self.store is not None:
                                self.store.execute(
                                    "INSERT OR REPLACE INTO llm_cache (key, role, model, digest, prompt, value, "
                                    "created_at) VALUES (?, 'embed', ?, ?, ?, ?, ?)",
                                    (keys[i], tag, digest, EMBED_PROMPT, json.dumps(v), iso_now()),
                                )
        except LLMError as exc:
            metrics.failures += 1
            metrics.last_error = f"{type(exc).__name__}: {exc.reason}"
            raise
        if todo:
            metrics.latencies.append((time.perf_counter() - start) * 1000)
        metrics.last_ok_at = utcnow()
        metrics.last_error = None
        arr = np.asarray([vectors[i] for i in range(len(texts))], dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        if arr.size and np.any(norms == 0):
            raise ModelOutputInvalid("zero-norm embedding", **ctx)
        return arr / norms if arr.size else arr

    async def digest(self, tag: str, *, role: str, prompt: str) -> str:
        """Model digest from `/api/tags`, cached per process; a missing model is `ModelUnavailable`."""
        if tag in self._digests:
            return self._digests[tag]
        try:
            models = await self.http.tags(timeout=self.cfg.ollama.probe_timeout_s)
        except (httpx.HTTPError, OllamaHTTPError) as exc:
            raise ModelUnavailable(_transport_reason(exc), role=role, tag=tag, prompt=prompt) from exc
        for m in models:
            if same_tag(m.name, tag):
                self._digests[tag] = m.digest
                return m.digest
        raise ModelUnavailable("model not present in Ollama", role=role, tag=tag, prompt=prompt)

    def forget_digests(self) -> None:
        """Drop cached digests (a re-pulled model gets a new digest, which invalidates its cache entries)."""
        self._digests.clear()

    def metrics_snapshot(self) -> dict[str, RoleMetrics]:
        return {role: m.snapshot() for role, m in self.metrics.items()}

    # ------------------------------------------------------------------ internals
    def _lease(self, tag: str, priority: Priority) -> Any:
        if self.arbiter is None:
            return _NullLease()
        return self.arbiter.lease(ollama_resource(tag), priority)

    async def _chat(self, payload: dict[str, Any], timeout: float, ctx: dict[str, str]) -> tuple[str, str | None]:
        try:
            resp = await self.http.chat(payload, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise ModelUnavailable(f"timeout after {timeout}s", **ctx) from exc
        except (httpx.HTTPError, OllamaHTTPError) as exc:
            raise ModelUnavailable(_transport_reason(exc), **ctx) from exc
        msg = resp.get("message") or {}
        content = str(msg.get("content") or "").strip()
        thinking = msg.get("thinking") or None
        if not content:
            hint = " (thinking consumed the reply)" if thinking else ""
            raise ModelRefused(f"empty reply{hint}", **ctx)
        return content, thinking

    @staticmethod
    def _parse[T: BaseModel](content: str, schema: type[T], parser: Callable[[str], T] | None) -> T:
        if parser is not None:
            value = parser(content)
            return schema.model_validate(value.model_dump())
        return schema.model_validate_json(_strip_fences(content))

    def _cache_get[T: BaseModel](self, key: str, schema: type[T]) -> T | None:
        assert self.store is not None
        row = self.store.query_one("SELECT value FROM llm_cache WHERE key = ?", (key,))
        if row is None:
            return None
        try:
            return schema.model_validate_json(row["value"])
        except ValidationError:
            return None  # schema changed shape: treat as a miss, the fresh result overwrites it

    def _cache_put(self, key: str, role: str, tag: str, digest: str, prompt: str, value: BaseModel) -> None:
        assert self.store is not None
        self.store.execute(
            "INSERT OR REPLACE INTO llm_cache (key, role, model, digest, prompt, value, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (key, role, tag, digest, prompt, value.model_dump_json(), iso_now()),
        )


class _NullLease:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> None:
        return None


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def _short(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        errs = exc.errors()[:5]
        return "; ".join(f"{'.'.join(map(str, e['loc'])) or '<root>'}: {e['msg']}" for e in errs)
    return str(exc)[:500]


def _repair_instruction(error: Exception, use_format: bool) -> str:
    what = "valid JSON that matches the required schema exactly" if use_format else "the required output format"
    return f"Your previous reply was invalid: {_short(error)}. Reply again with only {what}. Do not add commentary."


def _transport_reason(exc: Exception) -> str:
    if isinstance(exc, OllamaHTTPError):
        return f"HTTP {exc.status}: {exc.message}"
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
