"""One optional LLM client for the three agents: JSON-mode completions with a disk cache and provider fallback.

Providers, in "auto" order: Vertex Gemini (GOOGLE_CLOUD_PROJECT, the team's setup), Gemini API key, Groq. Every
configured provider is kept; a call that fails on one (auth, unknown model, rate limit) moves on to the next.
Every caller has a deterministic fallback, so get_llm() returning None is a supported configuration.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time

from .config import Config

log = logging.getLogger(__name__)
NEEDS = {"vertex": "GOOGLE_CLOUD_PROJECT", "gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY"}
FATAL = ("401", "403", "404", "PERMISSION_DENIED", "NOT_FOUND", "invalid_api_key")   # this provider/model won't work
SKIP = ("429", "rate_limit", "RESOURCE_EXHAUSTED")                                   # try the next model now


class LLMError(RuntimeError):
    pass


def _parse_json(text: str):
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            return json.loads(text[start:end + 1])
        raise


class _Backend:
    def __init__(self, provider: str, cfg: Config):
        self.provider, self.cfg = provider, cfg
        if provider == "groq":
            from groq import Groq
            # No silent SDK retries: a rate-limited model fails fast and we move to the next one.
            self.client = Groq(api_key=os.environ["GROQ_API_KEY"], max_retries=0, timeout=90)
        else:
            from google import genai
            self.client = (genai.Client(vertexai=True, project=os.environ["GOOGLE_CLOUD_PROJECT"],
                                        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
                           if provider == "vertex" else genai.Client(api_key=os.environ["GEMINI_API_KEY"]))

    def models(self, role: str) -> list[str]:
        if self.provider == "groq":
            first = self.cfg.groq_safety_model if role == "safety" else self.cfg.groq_model
            return list(dict.fromkeys([first, self.cfg.groq_model, "qwen/qwen3.8-27b"]))
        return [self.cfg.gemini_model]

    def call(self, model: str, system: str, user: str, temperature: float) -> str:
        if self.provider == "groq":
            r = self.client.chat.completions.create(
                model=model, temperature=temperature, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
            return r.choices[0].message.content
        from google.genai import types
        r = self.client.models.generate_content(model=model, contents=user, config=types.GenerateContentConfig(
            system_instruction=system, temperature=temperature, response_mime_type="application/json"))
        return r.text


class LLM:
    def __init__(self, backends: list[_Backend], cfg: Config):
        self.backends, self.cfg = backends, cfg
        self.cache_dir = cfg.cache_dir / "llm"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.stats = {"calls": 0, "cache_hits": 0, "failures": 0}
        self.used = None            # "provider:model" that last answered
        self._dead: set[tuple[str, str]] = set()
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self.used or "+".join(b.provider for b in self.backends)

    def json(self, system: str, user: str, *, role: str = "default", temperature: float = 0.0, use_cache: bool = True):
        key = hashlib.sha256(json.dumps([role, system, user, temperature]).encode()).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if use_cache and path.exists():
            with self._lock:
                self.stats["cache_hits"] += 1
            return json.loads(path.read_text(encoding="utf-8"))
        last = None
        for b in self.backends:
            for model in b.models(role):
                if (b.provider, model) in self._dead:
                    continue
                for attempt in range(2):
                    try:
                        result = _parse_json(b.call(model, system, user, temperature))
                        with self._lock:
                            self.stats["calls"] += 1
                            self.used = f"{b.provider}:{model}"
                        if use_cache:
                            path.write_text(json.dumps(result), encoding="utf-8")
                        return result
                    except Exception as e:
                        last, msg = e, str(e)
                        if any(s in msg for s in FATAL):
                            with self._lock:
                                self._dead.add((b.provider, model))   # don't pay for it again this process
                            log.warning("LLM %s:%s unusable (%s); trying the next one", b.provider, model, msg[:120])
                            break
                        if any(s in msg for s in SKIP):
                            break
                        time.sleep(1.0 + attempt)                  # bad JSON / 5xx: one quick retry
        with self._lock:
            self.stats["failures"] += 1
        raise LLMError(f"no LLM provider answered: {last}")


def get_llm(cfg: Config) -> LLM | None:
    want = cfg.llm_provider.lower()
    if want == "none":
        return None
    order = ["vertex", "gemini", "groq"] if want == "auto" else [want]
    backends = []
    for p in order:
        if p in NEEDS and os.environ.get(NEEDS[p]):
            try:
                backends.append(_Backend(p, cfg))
            except Exception as e:  # missing SDK: skip this provider
                log.warning("LLM provider %s unavailable: %s", p, e)
    if not backends:
        log.info("no LLM configured; using deterministic fallbacks")
        return None
    return LLM(backends, cfg)
