"""Stage logic without models: OCR span merging, sentence splitting, track building, chunk planning, prompts."""

from __future__ import annotations

import pytest

from conftest import _mask
from loom_perception.asr import split_sentences
from loom_perception.config import OcrConfig, SamConfig
from loom_perception.media import plan_chunks
from loom_perception.ocr import Line, merge_spans, similar
from loom_perception.sam import RawDetection
from loom_perception.tracks import box_iou, build_tracks, split_instances
from loom_perception.types import TranscriptSegment
from loom_perception.vocab import choose_prompts, heuristic_prompts

EQ = [0.3, 0.02, 0.4, 0.05]


# ---------- OCR ----------

def test_ocr_merges_jittery_readings_into_one_span():
    frames = [(float(t), [Line(txt, EQ, 0.9)]) for t, txt in [(20, "NaOH + HCl -> NaCl + H2O"), (21, "NaOH + HCI -> NaCl + H2O"), (22, "NaOH + HCl -> NaCl + H20"), (23, "NaOH + HCl -> NaCl + H2O")]]
    frames.append((24.0, []))
    spans = merge_spans(frames, OcrConfig(), step=1.0)
    assert len(spans) == 1
    assert (spans[0].start, spans[0].end) == (20.0, 24.0)
    assert spans[0].text == "NaOH + HCl -> NaCl + H2O"


def test_ocr_keeps_best_confidence_reading_and_splits_after_long_gap():
    cfg = OcrConfig(max_gap_seconds=1.5)
    frames = [(0.0, [Line("Titration", EQ, 0.7)]), (1.0, [Line("Titratlon", EQ, 0.95)]), (2.0, []), (3.0, []), (4.0, []), (5.0, [Line("Titration", EQ, 0.9)]), (6.0, [Line("Titration", EQ, 0.9)])]
    spans = merge_spans(frames, cfg, step=1.0)
    assert [(s.start, s.end) for s in spans] == [(0.0, 2.0), (5.0, 7.0)]
    assert spans[0].text == "Titratlon"  # the higher-confidence reading wins


def test_ocr_drops_low_confidence_short_and_empty_lines():
    frames = [(0.0, [Line("x", EQ, 0.99), Line("noise", EQ, 0.2)]), (1.0, [])]
    assert merge_spans(frames, OcrConfig(), step=1.0) == []


def test_ocr_separates_different_text_in_same_frame():
    frames = [(t, [Line("Acids", [0.1, 0.1, 0.2, 0.05], 0.9), Line("Bases", [0.6, 0.1, 0.2, 0.05], 0.9)]) for t in (0.0, 1.0)]
    assert sorted(s.text for s in merge_spans(frames, OcrConfig(), step=1.0)) == ["Acids", "Bases"]


def test_similarity_ignores_case_and_spacing():
    assert similar("NaOH + HCl", "naoh+hcl") == 1.0


# ---------- ASR ----------

def test_sentence_split_uses_word_timestamps():
    words = [(0.0, 0.4, " Combine"), (0.4, 0.6, " the"), (0.6, 1.0, " solutions."), (1.4, 1.8, " Watch"), (1.8, 2.0, " the"), (2.0, 2.6, " colour.")]
    parts = split_sentences(words, 0.0, 2.6, " Combine the solutions. Watch the colour.", max_seconds=12)
    assert parts == [(0.0, 1.0, "Combine the solutions."), (1.4, 2.6, "Watch the colour.")]


def test_short_single_sentence_passes_through():
    assert split_sentences([(0, 1, " Hi.")], 0.0, 1.0, " Hi.", 12) == [(0.0, 1.0, "Hi.")]


def test_overlong_sentence_splits_at_longest_pause():
    words = [(i * 1.0, i * 1.0 + 0.8, f" w{i}") for i in range(10)] + [(14.0, 14.8, " end"), (15.0, 15.8, " now.")]
    parts = split_sentences(words, 0.0, 15.8, " ".join(w for *_, w in words), max_seconds=8)
    assert all(e - s <= 10 for s, e, _ in parts)
    assert parts[-1][2].endswith("now.")


# ---------- chunks ----------

def test_chunks_cover_video_with_overlap():
    chunks = plan_chunks(130.0, 60.0, 1.0)
    assert [(c.start, c.end) for c in chunks] == [(0.0, 60.0), (59.0, 119.0), (118.0, 130.0)]
    assert plan_chunks(20.0, 60.0, 1.0)[0].end == 20.0


# ---------- tracks ----------

def _det(chunk, prompt, lid, t, box, score=0.9, rle=True):
    return RawDetection(chunk, prompt, lid, t, box, score, _mask(box) if rle else None)


B = [0.2, 0.3, 0.3, 0.5]


def test_box_iou():
    assert box_iou(B, B) == pytest.approx(1.0)
    assert box_iou(B, [0.8, 0.8, 0.1, 0.1]) == 0.0


def test_track_stitched_across_chunks_and_ids_assigned_by_time():
    dets = [_det(0, "beaker", 3, t / 2, B) for t in range(100, 120)]  # 50–59.5 s
    dets += [_det(1, "beaker", 1, t / 2, B) for t in range(118, 140)]  # 59–69.5 s, SAM gave a new id
    dets += [_det(0, "flask", 2, t / 2, [0.6, 0.2, 0.2, 0.3]) for t in range(10, 20)]
    tracks = build_tracks(dets, SamConfig(), step=0.5)
    assert [t.label for t in tracks] == ["flask", "beaker"]
    assert [t.object_id for t in tracks] == ["obj_001", "obj_002"]
    beaker = tracks[1]
    assert len(beaker.instances) == 1
    assert (beaker.instances[0].start, beaker.instances[0].end) == (50.0, 70.0)


def test_two_prompts_on_same_object_merge_to_higher_scoring_label():
    dets = [_det(0, "beaker", 1, t / 2, B, 0.95) for t in range(10)] + [_det(0, "glass", 1, t / 2, B, 0.6) for t in range(10)]
    tracks = build_tracks(dets, SamConfig(), step=0.5)
    assert len(tracks) == 1
    assert tracks[0].label == "beaker" and tracks[0].aliases == ["glass"]


def test_same_prompt_duplicate_of_one_object_merges():
    dets = [_det(0, "beaker", 1, t / 2, B, 0.6) for t in range(20)]
    dets += [_det(0, "beaker", 4, 5.0 + t / 2, B, 0.4) for t in range(6)]  # a later, weaker second track
    tracks = build_tracks(dets, SamConfig(), step=0.5)
    assert len(tracks) == 1 and tracks[0].instances[0].end == 10.0


def test_instances_split_on_gaps_and_drop_blips():
    cfg = SamConfig(max_gap_seconds=1.0, min_track_seconds=1.0)
    ts = [0, 0.5, 1.0, 1.5, 10.0, 10.5, 11.0, 30.0]
    inst = split_instances([_det(0, "x", 1, t, B) for t in ts], cfg, step=0.5)
    assert [(i.start, i.end) for i in inst] == [(0, 2.0), (10.0, 11.5)]  # the lone 30 s frame is dropped


# ---------- prompts ----------

def test_heuristic_prompts_pick_objects_after_determiners():
    tr = [TranscriptSegment(0, 1, "Pour the acid into the beaker."), TranscriptSegment(1, 2, "Now swirl the conical flask and watch the beaker.")]
    p = heuristic_prompts(tr, 5)
    assert p[0] == "beaker"
    assert "conical flask" in p


def test_choose_prompts_fixed_first_and_per_chunk():
    tr = [TranscriptSegment(0, 1, "Hold the beaker.")]
    by_chunk, source = choose_prompts(["Scale"], tr, [], [(0, 60), (59, 120)], {}, None, 5, True)
    assert source == "transcript"
    assert by_chunk[0] == by_chunk[1] == ["scale", "beaker"]


class _Gemini:
    def propose_objects(self, frames, context, limit):
        return ["burette"] if "titrate" in context else ["beaker"]


def test_choose_prompts_uses_gemini_per_chunk():
    tr = [TranscriptSegment(0, 5, "Pour it."), TranscriptSegment(70, 75, "Now titrate slowly.")]
    by_chunk, source = choose_prompts([], tr, [], [(0, 60), (59, 120)], {0: [], 1: []}, _Gemini(), 5, True)
    assert source == "gemini"
    assert by_chunk == {0: ["beaker"], 1: ["burette"]}
