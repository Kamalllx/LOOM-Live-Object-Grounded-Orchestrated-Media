"""`loom doctor` (FR-OPS-02): check the machine and print fixes.

Python/uv · CUDA + VRAM · FFmpeg + NVENC · LaTeX · Ollama server settings (as *applied by the running server*, read
from its startup log, not just the user environment) · each role's model present + smoke call · fallbacks · open
weights in the HF cache · worker spawnable · ports · disk · offline mode · config + prompt files.
A smoke run writes `<data>/run/smoke.json`, which `/api/ready` reports as the last smoke result per role.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx

from loom.core.config import ROLES, LoomConfig, Role
from loom.core.offline import LocalityViolation, check_model_host
from loom.core.ollama import OllamaHttp, OllamaHTTPError, same_tag
from loom.core.prompts import PromptError, PromptLibrary
from loom.core.store import iso_now
from loom.core.weights import WEIGHTS, cached_snapshot
from loom.gateway.readiness import smoke_file, worker_selftest

Status = Literal["ok", "warn", "fail"]

# spec/03 §3 — what the running Ollama server must have applied
OLLAMA_EXPECTED = {
    "OLLAMA_HOST": "http://127.0.0.1:11434",
    "OLLAMA_MAX_LOADED_MODELS": "1",
    "OLLAMA_NUM_PARALLEL": "1",
    "OLLAMA_FLASH_ATTENTION": "true",
    "OLLAMA_KV_CACHE_TYPE": "q8_0",
    "OLLAMA_CONTEXT_LENGTH": "8192",
    "OLLAMA_KEEP_ALIVE": "10m0s",
}
IDLE_VRAM_WARN_MIB = 1024


@dataclass
class Check:
    name: str
    status: Status
    detail: str
    fix: str = ""


def _run(cmd: list[str], timeout: float = 20) -> tuple[int, str]:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return res.returncode, (res.stdout or "") + (res.stderr or "")


def check_python() -> list[Check]:
    out = []
    ver = platform.python_version()
    ok = sys.version_info[:2] == (3, 12)
    in_venv = sys.prefix != sys.base_prefix
    out.append(
        Check(
            "python",
            "ok" if ok and in_venv else "fail",
            f"{ver} ({'project venv' if in_venv else 'NOT in the project venv'}: {sys.executable})",
            "" if ok and in_venv else "run through uv: `uv run loom doctor`",
        )
    )
    uv = shutil.which("uv") or os.environ.get("UV")  # `uv run` exports UV=<path to uv>

    out.append(
        Check(
            "uv",
            "ok" if uv else "warn",
            uv or "uv not on this shell's PATH",
            "" if uv else "winget install --id astral-sh.uv -e, then open a new terminal",
        )
    )
    return out


def check_gpu() -> list[Check]:
    if not shutil.which("nvidia-smi"):
        return [Check("cuda", "fail", "nvidia-smi not found", "install the NVIDIA driver (CUDA 12.8+ capable)")]
    code, text = _run(
        ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,driver_version", "--format=csv,noheader,nounits"]
    )
    if code != 0 or not text.strip():
        return [Check("cuda", "fail", f"nvidia-smi failed: {text.strip()[:200]}", "check the NVIDIA driver")]
    name, total, used, driver = (p.strip() for p in text.strip().splitlines()[0].split(","))
    checks = [Check("cuda", "ok", f"{name}, {int(total)} MiB VRAM, driver {driver}")]
    used_i = int(used)
    status: Status = "warn" if used_i > IDLE_VRAM_WARN_MIB else "ok"
    checks.append(
        Check(
            "vram baseline",
            status,
            f"{used_i} MiB in use by other processes ({int(total) - used_i} MiB free)",
            "close GPU-using apps or set them to the integrated GPU (Windows Settings > Display > Graphics); "
            "on ASUS laptops use Standard/Optimus GPU mode instead of Ultimate"
            if status == "warn"
            else "",
        )
    )
    return checks


def check_ffmpeg() -> list[Check]:
    if not shutil.which("ffmpeg"):
        return [Check("ffmpeg", "fail", "ffmpeg not on PATH", "winget install Gyan.FFmpeg")]
    _, ver = _run(["ffmpeg", "-hide_banner", "-version"])
    _, enc = _run(["ffmpeg", "-hide_banner", "-encoders"])
    nvenc = "h264_nvenc" in enc
    first = ver.splitlines()[0] if ver else "ffmpeg"
    return [
        Check("ffmpeg", "ok", first[:80]),
        Check(
            "nvenc",
            "ok" if nvenc else "warn",
            "h264_nvenc available" if nvenc else "no h264_nvenc (libx264 will be used)",
            "" if nvenc else "use an FFmpeg build with NVENC",
        ),
    ]


def check_latex() -> list[Check]:
    tools = {t: shutil.which(t) for t in ("latex", "dvisvgm")}
    missing = [t for t, p in tools.items() if not p]
    return [
        Check(
            "latex",
            "ok" if not missing else "warn",
            "latex + dvisvgm on PATH" if not missing else f"missing {missing} (Manim MathTex disabled)",
            "" if not missing else "install MiKTeX and let it add its bin dir to PATH",
        )
    ]


def ollama_server_config() -> dict[str, str] | None:
    """The OLLAMA_* settings the running server logged at startup (Windows: %LOCALAPPDATA%/Ollama/server.log)."""
    candidates = []
    if la := os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(la) / "Ollama" / "server.log")
    candidates.append(Path.home() / ".ollama" / "logs" / "server.log")
    for log in candidates:
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = [ln for ln in text.splitlines() if "server config" in ln]
        if lines:
            return dict(re.findall(r"(OLLAMA_[A-Z_]+):(\S*)", lines[-1]))
    return None


def check_ollama_config() -> list[Check]:
    applied = ollama_server_config()
    if applied is None:
        return [
            Check(
                "ollama settings",
                "warn",
                "could not read the Ollama server log to confirm applied settings",
                "run setup/pull-models.ps1 -ConfigureServer and restart Ollama",
            )
        ]
    wrong = {k: applied.get(k, "<unset>") for k, v in OLLAMA_EXPECTED.items() if applied.get(k) != v}
    if not wrong:
        return [
            Check(
                "ollama settings",
                "ok",
                "server applied " + ", ".join(f"{k}={v}" for k, v in applied.items() if k in OLLAMA_EXPECTED),
            )
        ]
    return [
        Check(
            "ollama settings",
            "fail",
            "server runs with " + ", ".join(f"{k}={v} (want {OLLAMA_EXPECTED[k]})" for k, v in wrong.items()),
            "powershell -File setup/pull-models.ps1 -ConfigureServer -VerifyOnly, then quit and restart Ollama",
        )
    ]


async def _smoke(http: OllamaHttp, role: str, tag: str) -> tuple[bool, str]:
    try:
        if role == "embed":
            vecs = await http.embed(tag, ["loom smoke test"], timeout=300)
            return (len(vecs) == 1 and len(vecs[0]) > 0), f"dim={len(vecs[0]) if vecs else 0}"
        r = await http.generate(
            {
                "model": tag,
                "prompt": "Reply with the single word: ready",
                "stream": False,
                "think": False,
                "keep_alive": 0,
                "options": {"num_ctx": 2048, "num_predict": 16},
            },
            timeout=600,
        )
        text = re.sub(r"\s+", " ", str(r.get("response", ""))).strip()
        return bool(text), repr(text[:40])
    except (httpx.HTTPError, OllamaHTTPError) as exc:
        return False, f"{type(exc).__name__}: {exc}"[:200]


async def check_models(cfg: LoomConfig, smoke: bool) -> list[Check]:
    checks: list[Check] = []
    try:
        check_model_host(cfg)
    except LocalityViolation as exc:
        return [Check("ollama host", "fail", str(exc), "point [ollama].host at 127.0.0.1")]
    http = OllamaHttp(cfg)
    try:
        try:
            version = await http.version()
            tags = await http.tags()
        except (httpx.HTTPError, OllamaHTTPError) as exc:
            return [
                Check(
                    "ollama",
                    "fail",
                    f"unreachable at {cfg.ollama.host}: {type(exc).__name__}",
                    "start Ollama (tray app) or `ollama serve`",
                )
            ]
        checks.append(Check("ollama", "ok", f"version {version} at {cfg.ollama.host}"))
        names = [m.name for m in tags]
        record: dict[str, dict[str, object]] = {}
        wanted: list[tuple[str, Role, str]] = [(r, r, cfg.models.role(r).tag) for r in ROLES]
        for r in ROLES:
            if fb := cfg.models.role(r).fallback:
                wanted.append((f"{r} fallback", r, fb))
        for label, role, tag in wanted:
            is_fallback = label != role
            present = any(same_tag(n, tag) for n in names)
            if not present:
                checks.append(
                    Check(
                        f"model {label}", "warn" if is_fallback else "fail", f"{tag} not pulled", f"ollama pull {tag}"
                    )
                )
                if not is_fallback:
                    record[role] = {"ok": False, "at": iso_now(), "error": "not present"}
                continue
            if not smoke:
                checks.append(Check(f"model {label}", "ok", f"{tag} present (smoke skipped)"))
                continue
            ok, info = await _smoke(http, role, tag)
            checks.append(
                Check(
                    f"model {label}",
                    "ok" if ok else ("warn" if is_fallback else "fail"),
                    f"{tag} smoke {info}",
                    "" if ok else f"ollama run {tag} to see the error",
                )
            )
            if not is_fallback:
                record[role] = {"ok": ok, "at": iso_now(), **({} if ok else {"error": info})}
        if smoke:
            p = smoke_file(cfg)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"at": iso_now(), "roles": record}, indent=2), encoding="utf-8")
    finally:
        await http.aclose()
    return checks


def check_weights() -> list[Check]:
    out = []
    for repo in WEIGHTS:
        snap = cached_snapshot(repo)
        out.append(
            Check(
                f"weights {repo.split('/')[-1]}",
                "ok" if snap else "fail",
                str(snap) if snap else "not in the Hugging Face cache",
                "" if snap else "powershell -File setup/pull-models.ps1 -OpenWeights",
            )
        )
    return out


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def check_ports(cfg: LoomConfig) -> list[Check]:
    out = []
    for name, port in (("gateway", cfg.runtime.gateway_port), ("web", cfg.runtime.web_port)):
        free = _port_free(port)
        out.append(
            Check(
                f"port {port} ({name})",
                "ok" if free else "warn",
                "free" if free else "in use (fine if LOOM is already running)",
                "" if free else f"stop whatever listens on {port} before `loom gateway`",
            )
        )
    return out


def check_disk(cfg: LoomConfig) -> list[Check]:
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(cfg.data_dir).free / 1e9
    status: Status = (
        "fail" if free < cfg.runtime.min_free_disk_gb else "warn" if free < cfg.runtime.warn_free_disk_gb else "ok"
    )
    return [
        Check(
            "disk",
            status,
            f"{free:.1f} GB free at {cfg.data_dir.resolve()}",
            "" if status == "ok" else "free disk space",
        )
    ]


def check_project(cfg: LoomConfig) -> list[Check]:
    out = [Check("config", "ok", f"{cfg.source_path} (offline={'on' if cfg.runtime.offline else 'off'})")]
    try:
        prompts = PromptLibrary().all()
        out.append(Check("prompts", "ok", f"{len(prompts)} prompt files valid"))
    except PromptError as exc:
        out.append(Check("prompts", "fail", str(exc), "fix the prompt front matter"))
    return out


async def run_doctor(cfg: LoomConfig, smoke: bool = True) -> list[Check]:
    checks: list[Check] = []
    checks += check_project(cfg)
    checks += check_python()
    checks += check_gpu()
    checks += check_ffmpeg()
    checks += check_latex()
    checks += check_ollama_config()
    checks += await check_models(cfg, smoke)
    checks += check_weights()
    worker = await worker_selftest()
    checks.append(
        Check(
            "worker",
            "ok" if worker else "fail",
            "spawnable" if worker else "selftest failed",
            "" if worker else "run `uv run python -m loom.worker --selftest` to see the error",
        )
    )
    checks += check_ports(cfg)
    checks += check_disk(cfg)
    return checks


def render(checks: list[Check]) -> str:
    mark = {"ok": "[ OK ]", "warn": "[WARN]", "fail": "[FAIL]"}
    width = max(len(c.name) for c in checks)
    lines = []
    for c in checks:
        lines.append(f"{mark[c.status]} {c.name.ljust(width)}  {c.detail}")
        if c.fix:
            lines.append(f"{' ' * 7}{' ' * width}  fix: {c.fix}")
    fails = sum(c.status == "fail" for c in checks)
    warns = sum(c.status == "warn" for c in checks)
    lines.append("")
    lines.append(f"{len(checks)} checks: {len(checks) - fails - warns} ok, {warns} warn, {fails} fail")
    return "\n".join(lines)


def doctor_main(cfg: LoomConfig, smoke: bool, as_json: bool) -> int:
    checks = asyncio.run(run_doctor(cfg, smoke))
    if as_json:
        print(json.dumps([c.__dict__ for c in checks], indent=2))
    else:
        print(render(checks))
    return 1 if any(c.status == "fail" for c in checks) else 0
