"""Explainers teach the topic: diverse grounding evidence, and lines that narrate the video are rejected."""

from __future__ import annotations

from loom.agents.animator import not_teaching
from loom.agents.knowledge import diverse


def test_lines_that_narrate_the_video_or_repeat_are_rejected() -> None:
    lines = [
        "The video introduces the topic by showing the word Photosynthesis.",
        "Photosynthesis is how plants make their own food using sunlight.",
        "Plants take in carbon dioxide from the air and water from the soil.",
        "Plants take in carbon dioxide from the air, and water from the soil.",
        "On the board, the teacher writes the equation.",
        "Chlorophyll in the leaves captures the energy of sunlight.",
        "The word Photosynthess appears again.",
    ]
    bad = not_teaching(lines)
    assert sorted(bad) == [0, 3, 4, 6]
    assert bad[3] == "repeats an earlier line"
    assert "describes the video" in bad[0]


def test_teaching_lines_pass() -> None:
    lines = [
        "A foreign key is a column that points to a row in another table.",
        "Glucose stores the energy the plant captured from light.",
        "Oxygen is released as a by-product.",
    ]
    assert not_teaching(lines) == {}


def _hit(i: str, kind: str, text: str, t: float) -> dict[str, object]:
    return {"id": i, "kind": kind, "text": text, "t": t, "label": text[:60]}


def test_diverse_drops_ocr_repeats_and_keeps_concepts_and_speech() -> None:
    ocr = [_hit(f"x_{k}", "screen", txt, 10.0 + k) for k, txt in enumerate(
        ["Photosymthes(18", "Photosynthesis", "Photosynthess", "Photosynthesis.", "food making poocess",
         "food making process", "feod making poocens"])]
    speech = [_hit("s_001", "speech", "The food making process in plant, in presence of sunlight is known as "
                                      "photosynthesis.", 3.0),
              _hit("s_005", "speech", "Okay, so this is CO2 plus 6H2O.", 30.0)]
    concepts = [_hit("c_01", "concept", "Photosynthesis definition. The food making process in plants in the "
                                        "presence of sunlight.", 3.0),
                _hit("c_04", "concept", "Photosynthesis chemical equation. CO2 plus 6H2O with sunlight and "
                                        "chlorophyll producing C6H12O6 and oxygen.", 30.0)]
    hits = ocr + speech  # the noisy screen text ranks first, as it did for the real lesson
    ev = diverse(hits, concepts, k=10)
    ids = [h["id"] for h in ev]
    assert "c_01" in ids and "c_04" in ids and "s_001" in ids and "s_005" in ids
    assert sum(1 for h in ev if h["kind"] == "screen") <= 2
    assert [h["t"] for h in ev] == sorted(h["t"] for h in ev)


def test_upload_titles_drop_downloader_and_quality_tags() -> None:
    from loom.gateway.routes.app_api import upload_name

    assert upload_name("vidssave.com The Process of photosynthesis 720P.mp4")[1] == "The Process of photosynthesis"
    assert upload_name("Cell demo (1).mp4")[1] == "Cell demo"
    assert upload_name("lecture_1080p_HD.mkv")[1] == "lecture"


def test_a_judge_rejection_for_absence_alone_is_overruled_but_not_one_that_says_wrong() -> None:
    from loom.agents.animator import absence_only

    assert absence_only("The evidence does not describe this specific step")
    assert absence_only("The evidence describes the general method but not the congruence")
    assert not absence_only("Incorrect: the first arc is drawn from the vertex, not from D")
    assert not absence_only("The evidence does not mention this and it contradicts the board")


def test_a_concept_citing_only_objects_is_dropped_not_fatal() -> None:
    """Two batch lessons failed outright: fusion returned a concept backed by objects alone, which the graph rejects."""
    from types import SimpleNamespace as NS

    from loom.perception.pipeline import build_concepts

    c = lambda label, segs, texts, objs: NS(label=label, summary=label, segment_ids=segs, text_ids=texts,  # noqa: E731
                                            object_ids=objs, prerequisites=[], difficulty="beginner")
    fused = NS(concepts=[c("Heart", ["s_001"], [], []), c("Valve", [], [], ["o_001"]), c("Blood", [], ["x_001"], [])])
    nodes = build_concepts(fused, {"s_001"}, {"x_001"}, {"o_001"})
    assert [n.label for n in nodes] == ["Heart", "Blood"]
