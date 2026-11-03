from __future__ import annotations

from pathlib import Path

import pytest

from loom.core.config import LoomConfig
from loom.core.llm import LLMClient
from loom.core.ollama import OllamaHttp
from loom.perception.vocab import build_vocab, choose_keyframes, merge_vocab, normalize_phrase, transcript_phrases
from tests.fakes import FakeOllama


def test_normalize_phrase() -> None:
    assert normalize_phrase("The Safety Goggles") == "safety goggles"
    assert normalize_phrase("nitrile gloves") == "nitrile gloves"
    assert normalize_phrase("two test tubes") == "test tube"
    assert normalize_phrase("Dust pan") == "dustpan"
    assert normalize_phrase("glass") == "glass" and normalize_phrase("Petri dishes") == "petri dish"


def test_transcript_phrases_longest_match() -> None:
    found = transcript_phrases(
        [
            "Put on a lab coat, gloves and safety goggles.",
            "Place the test tubes in the test tube rack.",
            "Sweep them up with a brush and dustpan.",
        ]
    )
    assert {"lab coat", "gloves", "test tube rack", "test tube", "brush", "dustpan"} <= set(found)


def test_merge_marks_hazards_with_lookalikes() -> None:
    out = merge_vocab(
        ["glass beaker", "broken glass"],
        ["beaker"],
        ["broken glass", "knife"],
        {"broken glass": ["glass beaker", "ice"]},
    )
    by = {v.phrase: v for v in out}
    assert by["broken glass"].sources == ["vlm", "hazard_class"] and by["broken glass"].is_hazard_class
    assert by["broken glass"].lookalikes == ["glass beaker", "ice"]
    assert by["knife"].sources == ["hazard_class"] and not by["glass beaker"].is_hazard_class


def test_choose_keyframes_spreads_evenly() -> None:
    assert choose_keyframes([5.0, 1.0, 1.0, 3.0]) == [1.0, 3.0, 5.0]
    picked = choose_keyframes([float(i) for i in range(20)], limit=8)
    assert len(picked) == 8 and picked[0] == 0.0 and picked[-1] == 19.0
    mids = [2.5, 7.5, 12.5]
    with_mids = choose_keyframes([float(i) for i in range(20)], limit=8, primary=mids)
    assert set(mids) <= set(with_mids) and len(with_mids) == 8  # every shot represented


async def test_brain_down_falls_back_to_heuristic(cfg: LoomConfig, fake_ollama: FakeOllama, tmp_path: Path) -> None:
    fake_ollama.up = False
    llm = LLMClient(cfg, OllamaHttp(cfg, transport=fake_ollama.transport()))
    res = await build_vocab(
        cfg, llm, tmp_path / "missing.mp4", [(0.0, 2.0)], [(0.0, 1.5, "Pour acid into the beaker.")], [], tmp_path
    )
    phrases = {v.phrase for v in res.phrases}
    assert res.degraded == ["vocab_heuristic"]
    assert "beaker" in phrases
    assert {"broken glass", "knife", "open flame"} <= phrases  # always-on hazard classes survive an outage


@pytest.mark.parametrize("bad", ["", "   "])
def test_empty_phrases_are_ignored(bad: str) -> None:
    assert merge_vocab([bad], [], [], {}) == []
