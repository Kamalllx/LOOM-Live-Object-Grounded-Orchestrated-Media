from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from loom.core.config import ROLES, LoomConfig, load_config
from loom.core.store import Store
from tests.fakes import FakeOllama

FIXTURES = Path(__file__).parent / "fixtures"

# Tests refer to models by role, like the code does; tags come from loom.toml.
_REPO_CFG = load_config()
BRAIN = _REPO_CFG.models.brain.tag
JUDGE = _REPO_CFG.models.judge.tag
SAFETY = _REPO_CFG.models.safety.tag
OCR = _REPO_CFG.models.ocr.tag


@pytest.fixture
def cfg(tmp_path: Path) -> LoomConfig:
    """The repo's loom.toml with data redirected to a temp dir and a fast readiness poll."""
    base = load_config()
    return base.model_copy(
        update={
            "runtime": base.runtime.model_copy(update={"data_dir": tmp_path / "data"}),
            "ollama": base.ollama.model_copy(update={"ready_poll_s": 0.2}),
        }
    )


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    s = Store(tmp_path / "loom.db")
    s.migrate()
    yield s
    s.close()


@pytest.fixture
def fake_ollama() -> FakeOllama:
    return FakeOllama(models={_REPO_CFG.models.role(r).tag: f"sha256-{r}" for r in ROLES})


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))
