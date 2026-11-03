"""Offline / locality enforcement (spec/01 NFR-LOC-01/02, FR-OPS-03).

`LOOM_OFFLINE=1` makes the whole system work with the network cable out: Hugging Face libraries are forced offline,
link ingest is refused, and every model host must be loopback. A non-loopback Ollama host is refused even when
online unless `LOOM_ALLOW_REMOTE_OLLAMA=1` is set deliberately.
"""

from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlsplit

from loom.core.config import LoomConfig

OFFLINE_ENV = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"}


class LocalityViolation(RuntimeError):
    """A component tried to reach a non-local host where only local hosts are allowed."""


class OfflineRefused(RuntimeError):
    """An action that needs the network was attempted in offline mode (REST 409 offline)."""


def is_loopback_url(url: str) -> bool:
    host = urlsplit(url if "://" in url else f"http://{url}").hostname
    if host is None:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def apply_offline_env(cfg: LoomConfig) -> None:
    """Set the HF offline variables in this process (inherited by spawned workers)."""
    if cfg.runtime.offline:
        os.environ.update(OFFLINE_ENV)


def check_model_host(cfg: LoomConfig, url: str | None = None) -> str:
    """Return the Ollama host if it is allowed, else raise `LocalityViolation`."""
    url = url or cfg.ollama.host
    if is_loopback_url(url):
        return url
    if cfg.runtime.offline:
        raise LocalityViolation(f"offline mode: model host {url!r} is not loopback")
    if not cfg.runtime.allow_remote_ollama:
        raise LocalityViolation(f"model host {url!r} is not loopback; set LOOM_ALLOW_REMOTE_OLLAMA=1 to allow it")
    return url


def require_network(cfg: LoomConfig, action: str) -> None:
    """Guard for the only network-using feature (explicit link ingest)."""
    if cfg.runtime.offline:
        raise OfflineRefused(f"{action} is disabled in offline mode (LOOM_OFFLINE=1)")
