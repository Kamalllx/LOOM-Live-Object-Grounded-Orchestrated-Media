from __future__ import annotations

import numpy as np

from loom_perception.config import FusionConfig
from loom_perception.fusion import HashingEmbedder, fuse, keyphrase
from loom_perception.types import ObjectInstance, ObjectTrack, TextSpan, TranscriptSegment

CHEM = {"acid", "base", "solutions", "pink", "neutralizes", "beaker", "naoh", "hcl", "colour"}
SAFETY = {"glass", "shards", "sharps", "hands", "bin", "broken"}


class TopicEmbedder:
    """2-D embedding: chemistry vs lab safety, by keyword. Makes grouping deterministic."""

    def __call__(self, texts):
        out = []
        for t in texts:
            w = set(t.lower().replace(".", " ").replace(",", " ").split())
            v = np.array([len(w & CHEM), len(w & SAFETY)], dtype=float) + 1e-3
            out.append(v / np.linalg.norm(v))
        return np.array(out)


TRANSCRIPT = [
    TranscriptSegment(2.0, 6.0, "Today we look at what happens when an acid meets a base."),
    TranscriptSegment(12.0, 15.4, "Combine the two solutions slowly."),
    TranscriptSegment(16.0, 19.5, "The pink colour fades as the base neutralizes the acid."),
    TranscriptSegment(40.0, 44.0, "Always sweep broken glass into the sharps bin."),
    TranscriptSegment(44.5, 48.0, "Never pick up shards with your hands."),
]
TEXT = [TextSpan(20.1, 25.0, "NaOH + HCl -> NaCl + H2O")]
BEAKER = ObjectTrack("obj_001", "beaker", 0.98, [ObjectInstance(14.2, 22.5, [0.31, 0.42, 0.12, 0.18])])
GLASS = ObjectTrack("obj_002", "broken glass", 0.9, [ObjectInstance(40.0, 46.0, [0.47, 0.7, 0.4, 0.22])])


def _labels(items):
    return [f"topic {i}" for i, _ in enumerate(items)]


def test_concepts_follow_topics_and_pauses():
    nodes = fuse(60.0, TRANSCRIPT, TEXT, [BEAKER, GLASS], TopicEmbedder(), FusionConfig(), labeler=_labels)
    assert [n.node_id for n in nodes] == ["c_01", "c_02", "c_03"]
    intro, demo, safety = nodes
    assert intro.transcript_refs == [(2.0, 6.0)]
    assert demo.transcript_refs == [(12.0, 15.4), (16.0, 19.5)]
    assert safety.transcript_refs == [(40.0, 44.0), (44.5, 48.0)]


def test_text_and_objects_attach_to_the_concept_that_owns_their_time():
    _, demo, safety = fuse(60.0, TRANSCRIPT, TEXT, [BEAKER, GLASS], TopicEmbedder(), FusionConfig(), labeler=_labels)
    # The equation appears ~5 s after the narration moves on, yet belongs to the demo.
    assert demo.on_screen_text_refs == [(20.1, 25.0)]
    assert demo.object_ids == ["obj_001"]
    assert safety.object_ids == ["obj_002"]
    assert (demo.start, demo.end) == (12.0, 25.0)


def test_object_not_on_screen_never_attaches():
    far = ObjectTrack("obj_003", "beaker", 0.9, [ObjectInstance(55.0, 58.0, [0, 0, 0.1, 0.1])])
    nodes = fuse(60.0, TRANSCRIPT[:3], [], [far], TopicEmbedder(), FusionConfig(), labeler=_labels)
    # The last concept owns the rest of the video, so the late beaker attaches there only.
    assert [n.object_ids for n in nodes] == [[], ["obj_003"]]


def test_silent_video_uses_on_screen_text_as_units():
    spans = [TextSpan(0, 10, "Acids and bases"), TextSpan(30, 40, "Handling broken glass")]
    nodes = fuse(60.0, [], spans, [], HashingEmbedder(), FusionConfig(), labeler=None)
    assert len(nodes) == 2
    assert all(n.transcript_refs == [] for n in nodes)
    assert [n.on_screen_text_refs for n in nodes] == [[(0, 10)], [(30, 40)]]


def test_labeler_failure_falls_back_to_key_phrases():
    def broken(_):
        raise RuntimeError("quota")

    nodes = fuse(60.0, TRANSCRIPT, TEXT, [BEAKER, GLASS], TopicEmbedder(), FusionConfig(), labeler=broken)
    assert all(n.label and n.label != "untitled concept" for n in nodes)


def test_keyphrase_picks_topical_noun_phrase_not_verbs():
    emb = TopicEmbedder()
    centroid = emb(["acid base"])[0]
    assert keyphrase("Now the base neutralizes the acid slowly.", [], centroid, emb) in {"base", "acid"}
    centroid = emb(["broken glass shards"])[0]
    assert keyphrase("Always sweep the broken glass into the bin. Never pick it up.", [], centroid, emb) == "broken glass"


def test_unmentioned_object_joins_the_concept_holding_most_of_its_screen_time():
    stand = ObjectTrack("obj_004", "retort stand", 0.8, [ObjectInstance(14.0, 22.0, [0, 0, 0.1, 0.6])])
    cfg = FusionConfig(object_relevance=2.0)  # relevance alone can never qualify here
    _, demo, safety = fuse(60.0, TRANSCRIPT, TEXT, [stand], TopicEmbedder(), cfg, labeler=_labels)
    assert demo.object_ids == ["obj_004"] and safety.object_ids == []


def test_background_object_spread_across_concepts_does_not_attach_everywhere():
    bench = ObjectTrack("obj_005", "bench", 0.8, [ObjectInstance(0.0, 60.0, [0, 0.6, 1, 0.4])])
    cfg = FusionConfig(object_relevance=2.0, object_presence=1.1)
    nodes = fuse(60.0, TRANSCRIPT, TEXT, [bench], TopicEmbedder(), cfg, labeler=_labels)
    assert all(n.object_ids == [] for n in nodes)


def test_empty_inputs_give_no_nodes():
    assert fuse(10.0, [], [], [], HashingEmbedder(), FusionConfig()) == []
