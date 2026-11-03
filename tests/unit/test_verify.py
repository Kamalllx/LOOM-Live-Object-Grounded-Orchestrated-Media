from __future__ import annotations

import pytest

from loom.perception.verify import TrackVerdict, negatives_for


@pytest.mark.parametrize(
    ("siglip", "vlm", "expected"),
    [
        (True, "not_run", (True, "verified")),
        (False, "confirmed", (True, "verified")),  # either step confirms -> keep
        (False, "rejected", (False, "verified")),  # both reject -> drop (logged)
        (None, "rejected", (True, "unverified")),  # SigLIP could not run -> fail closed
        (False, "failed", (True, "unverified")),  # VLM failed -> fail closed
        (False, "not_run", (True, "unverified")),  # no crops for the VLM -> still a hazard
    ],
)
def test_hazard_decision_fails_closed(siglip: bool | None, vlm: str, expected: tuple[bool, str]) -> None:
    assert TrackVerdict(siglip_pass=siglip, vlm=vlm).decide(is_hazard=True) == expected  # type: ignore[arg-type]


def test_non_hazard_follows_siglip() -> None:
    assert TrackVerdict(siglip_pass=True).decide(False) == (True, "verified")
    assert TrackVerdict(siglip_pass=False).decide(False) == (False, "verified")
    assert TrackVerdict(siglip_pass=None).decide(False) == (True, "unverified")


def test_negatives_lookalikes_first_without_self_or_substrings() -> None:
    neg = negatives_for(
        "broken glass", ["beaker", "glass beaker", "broken glass", "gloves"], {"broken glass": ["glass beaker", "ice"]}
    )
    assert neg[:2] == ["glass beaker", "ice"] and "broken glass" not in neg and "beaker" in neg


def test_vlm_better_label_describing_hazard_confirms() -> None:
    from loom.perception.verify import vlm_confirms

    assert vlm_confirms("broken glass", False, "glass bottle with liquid and shattered glass shards")
    assert not vlm_confirms("broken glass", False, "glass beaker with blue liquid")
    assert vlm_confirms("knife", True, None)
