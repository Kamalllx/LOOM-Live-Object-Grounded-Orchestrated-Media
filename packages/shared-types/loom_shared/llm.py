"""One LLM client for every agent: Groq or Gemini, JSON mode, disk cache, retry + fallback.

Every call is recorded in STATS so the evaluation script can report LLM latency.
"""
import hashlib
import json
import os
import re
import threading
import time

from .config import CACHE_DIR

LLM_CACHE = CACHE_DIR / "llm"
LLM_CACHE.mkdir(parents=True, exist_ok=True)

MODELS = {
    "groq": {
        "default": "openai/gpt-oss-120b",
        "fast": "qwen/qwen3.8-27b",
        "safety": "openai/gpt-oss-safeguard-20b",
    },
    "gemini": {
        "default": "gemini-3.5-flash",
        "fast": "gemini-3.5-flash-lite",
        "safety": "gemini-3.5-flash",
    },
}

STATS = {"calls": 0, "cache_hits": 0, "failures": 0, "latency_ms": []}
_lock = threading.Lock()


class LLMError(RuntimeError):
    pass


def _providers():
    primary = (os.getenv("LLM_PROVIDER") or "groq").strip().lower()
    order = [primary] + [p for p in ("groq", "gemini") if p != primary]
    keys = {"groq": os.getenv("GROQ_API_KEY"), "gemini": os.getenv("GEMINI_API_KEY")}
    return [p for p in order if keys.get(p)]


def _call_groq(model, system, user, json_mode, temperature):
    from groq import Groq
    # No silent SDK retries: a rate-limited model should fail fast so we can move to the next one.
    client = Groq(api_key=os.getenv("GROQ_API_KEY"), max_retries=0, timeout=60)
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    r = client.chat.completions.create(
        model=model, temperature=temperature,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        **kwargs,
    )
    return r.choices[0].message.content


def _call_gemini(model, system, user, json_mode, temperature):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    cfg = types.GenerateContentConfig(
        system_instruction=system, temperature=temperature,
        response_mime_type="application/json" if json_mode else "text/plain",
    )
    return client.models.generate_content(model=model, contents=user, config=cfg).text


def _parse_json(text):
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def complete(system, user, *, role="default", json_mode=True, temperature=0.2, use_cache=True, retries=2):
    """Return parsed JSON (json_mode) or text. Tries each configured provider in order."""
    providers = _providers()
    if not providers:
        raise LLMError("No LLM key configured: set GROQ_API_KEY or GEMINI_API_KEY in .env")

    key_src = json.dumps([providers[0], role, system, user, json_mode, temperature])
    cache_file = LLM_CACHE / (hashlib.sha256(key_src.encode()).hexdigest() + ".json")
    if use_cache and cache_file.exists():
        with _lock:
            STATS["cache_hits"] += 1
        return json.loads(cache_file.read_text())["result"]

    last_err = None
    # Each provider/model has its own rate limit, so on a 429 move straight to the next model.
    chain = [(p, m) for p in providers for m in dict.fromkeys([MODELS[p][role], MODELS[p]["default"], MODELS[p]["fast"]])]
    for provider, model in chain:
        call = _call_groq if provider == "groq" else _call_gemini
        for attempt in range(retries + 1):
            t0 = time.time()
            try:
                raw = call(model, system, user, json_mode, temperature)
                result = _parse_json(raw) if json_mode else raw.strip()
                with _lock:
                    STATS["calls"] += 1
                    STATS["latency_ms"].append((time.time() - t0) * 1000)
                if use_cache:
                    cache_file.write_text(json.dumps({"model": model, "result": result}))
                return result
            except Exception as e:  # bad JSON / 5xx: retry briefly; rate limit or auth: next model
                last_err = e
                msg = str(e)
                if any(s in msg for s in ("429", "rate_limit", "PERMISSION_DENIED", "401", "invalid_api_key", "404")):
                    break
                time.sleep(1.0 * (attempt + 1))
    with _lock:
        STATS["failures"] += 1
    raise LLMError(f"All LLM providers failed: {last_err}")
