"""The whole pipeline on a real (synthetic) video with fake models: stages, caching, sidecars, contract."""

from __future__ import annotations

import json
import time

import pytest

from conftest import fake_components
from loom_perception.pipeline import Pipeline, PipelineError
from loom_perception.schema import validate


def test_end_to_end_produces_valid_graph_matching_the_sample_shape(tmp_path, lesson_video, cfg):
    graph = Pipeline(cfg, fake_components()).run(lesson_video, tmp_path, video_id="vid_00123")
    assert validate(graph) == []
    assert graph["video_id"] == "vid_00123"
    assert graph["duration_seconds"] == pytest.approx(60.0, abs=0.2)

    labels = {o["label"]: o for o in graph["objects"]}
    assert set(labels) == {"beaker", "glass"}
    beaker = labels["beaker"]
    assert beaker["object_id"] == "obj_001" and beaker["confidence"] == 0.98
    inst = beaker["instances"][0]
    assert inst["start"] == pytest.approx(14.5, abs=0.5) and inst["end"] == pytest.approx(23.0, abs=0.5)
    assert inst["bbox"] == [0.2, 0.34, 0.27, 0.58]

    assert [s["text"] for s in graph["transcript"]][1] == "Combine the two solutions slowly."
    eq = graph["on_screen_text"][0]
    assert eq["text"] == "NaOH + HCl -> NaCl + H2O"
    assert eq["start"] == pytest.approx(20.0, abs=1.0) and eq["end"] == pytest.approx(25.0, abs=1.0)

    owner = next(n for n in graph["concept_nodes"] if "obj_001" in n["object_ids"])
    assert {"start": 12.0, "end": 15.4} in owner["transcript_refs"]
    assert any(abs(r["start"] - eq["start"]) < 1e-6 for r in owner["on_screen_text_refs"])


def test_masks_sidecars_and_run_report_written(tmp_path, lesson_video, cfg):
    graph = Pipeline(cfg, fake_components()).run(lesson_video, tmp_path)
    for o in graph["objects"]:
        side = json.loads((tmp_path / o["mask_ref"]).read_text())
        assert side["object_id"] == o["object_id"] and side["frames"][0]["rle"]["counts"]
    run = json.loads((tmp_path / "run.json").read_text())
    assert run["counts"]["objects"] == 2 and set(run["timings"]) >= {"asr", "ocr", "sam", "fusion"}
    assert not (tmp_path / "work").exists()


def test_video_is_processed_in_overlapping_chunks(tmp_path, lesson_video, cfg):
    holder = []
    Pipeline(cfg, fake_components(holder)).run(lesson_video, tmp_path)
    calls = holder[0].calls
    assert [c[0] for c in calls] == [0, 1, 2]  # 60 s in 30 s chunks with 1 s overlap
    assert calls[1][1][0] == pytest.approx(29.0)


def test_second_run_reuses_cached_stages(tmp_path, lesson_video, cfg):
    Pipeline(cfg, fake_components()).run(lesson_video, tmp_path)
    holder = []
    Pipeline(cfg, fake_components(holder)).run(lesson_video, tmp_path)
    assert holder == []  # the segmenter was never built
    run = json.loads((tmp_path / "run.json").read_text())
    assert set(run["cached"]) >= {"asr", "ocr", "sam"}

    holder = []
    Pipeline(cfg, fake_components(holder)).run(lesson_video, tmp_path, force=True)
    assert holder and holder[0].calls


def test_changing_config_invalidates_only_affected_stages(tmp_path, lesson_video, cfg):
    Pipeline(cfg, fake_components()).run(lesson_video, tmp_path)
    cfg.sam.score_threshold = 0.6
    Pipeline(cfg, fake_components()).run(lesson_video, tmp_path)
    run = json.loads((tmp_path / "run.json").read_text())
    assert "asr" in run["cached"] and "sam" not in run["cached"]


def test_skipping_stages(tmp_path, lesson_video, cfg):
    graph = Pipeline(cfg, fake_components()).run(lesson_video, tmp_path, skip={"sam", "ocr"})
    assert graph["objects"] == [] and graph["on_screen_text"] == []
    assert len(graph["transcript"]) == 5 and graph["concept_nodes"]


def test_per_run_prompts_extend_config(tmp_path, lesson_video, cfg):
    cfg.sam.prompts = []
    holder = []
    graph = Pipeline(cfg, fake_components(holder)).run(lesson_video, tmp_path, prompts=["beaker"])
    assert [o["label"] for o in graph["objects"]] == ["beaker"]
    assert cfg.sam.prompts == []


def test_unknown_skip_rejected(tmp_path, lesson_video, cfg):
    with pytest.raises(PipelineError):
        Pipeline(cfg, fake_components()).run(lesson_video, tmp_path, skip={"nope"})


def test_progress_reports_every_stage(tmp_path, lesson_video, cfg):
    seen = []
    Pipeline(cfg, fake_components()).run(lesson_video, tmp_path, progress=lambda s, f, m: seen.append(s))
    assert {"asr", "ocr", "prompts", "sam", "fusion", "done"} <= set(seen)
