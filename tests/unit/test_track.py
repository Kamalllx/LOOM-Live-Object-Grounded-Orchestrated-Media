from __future__ import annotations

from loom.perception.detect import Box, prompt_and_spans, to_picture
from loom.perception.track import group_into_objects, track_shot

B = (0.3, 0.3, 0.2, 0.2)


def box(t: float, phrase: str = "beaker", b: tuple[float, float, float, float] = B, s: float = 0.6) -> Box:
    return Box(t=t, phrase=phrase, box=b, score=s)


def test_links_over_time_and_pads_by_half_interval() -> None:
    tracks = track_shot([box(1.25), box(1.75), box(2.25)], "sh_01", 1.0, 5.0, 0.5, set())
    assert len(tracks) == 1
    t = tracks[0]
    assert (t.start, t.end) == (1.0, 2.5) and len(t.samples) == 3 and t.score == 0.6


def test_gap_or_jump_starts_a_new_track() -> None:
    gap = track_shot([box(1.25), box(3.25)], "sh_01", 1.0, 5.0, 0.5, set())
    jump = track_shot([box(1.25), box(1.75, b=(0.8, 0.8, 0.1, 0.1))], "sh_01", 1.0, 5.0, 0.5, set())
    assert len(gap) == 2 and len(jump) == 2


def test_single_low_score_noise_dropped_but_hazards_kept() -> None:
    boxes = [box(1.25, s=0.32), box(1.25, "broken glass", s=0.31)]
    phrases = [t.phrase for t in track_shot(boxes, "sh_01", 1.0, 5.0, 0.5, {"broken glass"})]
    assert phrases == ["broken glass"]


def test_simultaneous_same_label_tracks_become_separate_objects() -> None:
    left = [box(1.25), box(1.75)]
    right = [box(1.25, b=(0.7, 0.3, 0.2, 0.2)), box(1.75, b=(0.7, 0.3, 0.2, 0.2))]
    later = [box(4.25), box(4.75)]
    tracks = track_shot(left + right + later, "sh_01", 1.0, 5.0, 0.5, set())
    objects = group_into_objects(tracks)
    assert len(objects) == 2
    for obj in objects:  # no two instances of one object overlap in time within a shot
        for a in obj:
            for b in obj:
                assert a is b or a.end <= b.start or b.end <= a.start


def test_prompt_spans_and_picture_coords() -> None:
    class Tok:
        def __call__(self, text: str, return_offsets_mapping: bool) -> dict[str, list[tuple[int, int]]]:
            offs, i = [(0, 0)], 0
            for word in text.split(" "):
                offs.append((i, i + len(word)))
                i += len(word) + 1
            offs.append((0, 0))
            return {"offset_mapping": offs}

    text, spans = prompt_and_spans(["glass beaker", "knife"], Tok())
    assert text == "glass beaker . knife ."
    assert spans == [(1, 3), (4, 5)]
    assert to_picture((0.5, 0.5, 0.2, 0.2), (0.0, 0.0, 1.0, 1.0)) == (0.4, 0.4, 0.2, 0.2)
    assert to_picture((0.5, 0.05, 0.2, 0.05), (0.0, 0.125, 1.0, 0.75)) is None  # inside the letterbox bar


def test_hazard_window_times_resample_inside_the_shot() -> None:
    from loom.perception.detect import hazard_window_times

    extra = hazard_window_times([10.0], [(9.5, 20.0)], base={9.75, 10.25}, fps=4.0, radius=0.5)
    assert extra == [9.5, 10.0, 10.5]
    assert hazard_window_times([1.0], [(0.0, 1.2)], base=set(), fps=4.0, radius=0.5) == [0.5, 0.75, 1.0]
