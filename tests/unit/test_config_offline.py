from __future__ import annotations

import os
import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from loom.core.config import PROJECT_ROOT, LoomConfig, load_config
from loom.core.offline import (
    OFFLINE_ENV,
    LocalityViolation,
    OfflineRefused,
    apply_offline_env,
    check_model_host,
    is_loopback_url,
    require_network,
)


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "loom.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_repo_config_loads_with_every_role() -> None:
    cfg = load_config()
    assert cfg.models.brain.tag == "qwen3.5:9b"
    assert cfg.models.role("safety").fallback_role == "judge"
    assert cfg.gpu.priorities["tap_explainer"] < cfg.gpu.priorities["prerender"]
    assert "broken glass" in cfg.perception.lookalikes


def test_example_config_matches_shape() -> None:
    load_config(PROJECT_ROOT / "loom.example.toml")


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    text = (
        (PROJECT_ROOT / "loom.toml")
        .read_text(encoding="utf-8")
        .replace("[models.brain]", "[models.brain]\ntemprature = 0.3")
    )
    with pytest.raises(ValidationError, match="temprature"):
        load_config(_write(tmp_path, text))


def test_missing_gpu_priority_is_rejected(tmp_path: Path) -> None:
    raw = tomllib.loads((PROJECT_ROOT / "loom.toml").read_text(encoding="utf-8"))
    text = (
        (PROJECT_ROOT / "loom.toml")
        .read_text(encoding="utf-8")
        .replace(
            "priorities = { tap_explainer = 0, session = 1, ingest = 2, prerender = 3 }",
            "priorities = { tap_explainer = 0, session = 1, ingest = 2 }",
        )
    )
    assert raw["gpu"]["priorities"]["prerender"] == 3
    with pytest.raises(ValidationError, match="prerender"):
        load_config(_write(tmp_path, text))


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOOM_OFFLINE", "0")
    monkeypatch.setenv("LOOM_MAX_SECONDS", "120")
    cfg = load_config()
    assert cfg.runtime.offline is False
    assert cfg.runtime.max_seconds == 120


def test_data_dir_is_relative_to_config_file(tmp_path: Path) -> None:
    p = _write(tmp_path, (PROJECT_ROOT / "loom.toml").read_text(encoding="utf-8"))
    assert load_config(p).data_dir == tmp_path / "data"


@pytest.mark.parametrize(
    ("url", "loopback"),
    [
        ("http://127.0.0.1:11434", True),
        ("http://localhost:11434", True),
        ("127.0.0.1:11434", True),
        ("http://[::1]:11434", True),
        ("http://192.168.1.5:11434", False),
        ("https://api.example.com", False),
    ],
)
def test_is_loopback(url: str, loopback: bool) -> None:
    assert is_loopback_url(url) is loopback


def test_remote_ollama_refused_offline_and_online(cfg: LoomConfig) -> None:
    remote = "http://10.0.0.2:11434"
    with pytest.raises(LocalityViolation, match="offline"):
        check_model_host(cfg, remote)
    online = cfg.model_copy(update={"runtime": cfg.runtime.model_copy(update={"offline": False})})
    with pytest.raises(LocalityViolation, match="LOOM_ALLOW_REMOTE_OLLAMA"):
        check_model_host(online, remote)
    allowed = cfg.model_copy(
        update={"runtime": cfg.runtime.model_copy(update={"offline": False, "allow_remote_ollama": True})}
    )
    assert check_model_host(allowed, remote) == remote


def test_offline_env_and_link_ingest(cfg: LoomConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    for k in OFFLINE_ENV:
        monkeypatch.delenv(k, raising=False)
    apply_offline_env(cfg)
    assert all(os.environ[k] == "1" for k in OFFLINE_ENV)
    with pytest.raises(OfflineRefused):
        require_network(cfg, "YouTube link ingest")
