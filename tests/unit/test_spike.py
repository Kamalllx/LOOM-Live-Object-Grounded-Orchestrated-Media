from __future__ import annotations

import pytest

from loom.core.config import LoomConfig
from loom.eval.spike import compact_sim, merge_results, parse_guardian, parse_ocr, targets


def test_extra_candidates_survive_only_filter(cfg: LoomConfig) -> None:
    ts = targets(cfg, ["none"], ["safety:granite4.1-guardian:8b-q4_K_M"])
    assert [t.label for t in ts] == ["safety candidate granite4.1-guardian:8b-q4_K_M"]
    assert {t.label for t in targets(cfg, ["judge"])} == {"judge", "judge fallback"}
    with pytest.raises(ValueError, match="role:tag"):
        targets(cfg, None, ["guardian"])


def test_merge_never_drops_other_results() -> None:
    existing = [{"label": "brain", "v": 1}, {"label": "judge", "v": 1}]
    merged = merge_results(existing, {"label": "judge", "v": 2})
    assert merged == [{"label": "brain", "v": 1}, {"label": "judge", "v": 2}]
    assert merge_results([], {"label": "ocr"}) == [{"label": "ocr"}]


def test_parsers() -> None:
    assert parse_guardian("<think>\n</think>\n<score> yes </score>").answer == "yes"
    assert parse_guardian("<score>NO</score>").answer == "no"
    with pytest.raises(ValueError):
        parse_guardian("maybe")
    assert parse_ocr(r"$\mathrm{H}_{2}\mathrm{O}$").text == "H₂O"
    assert compact_sim("NaOH + HCl", "NaOH+HCl") == 1.0
