from __future__ import annotations

from loom.perception.ocr import Detection, group_spans, iou, is_math_like, sample_times, to_picture_box

BOX = (0.6, 0.05, 0.35, 0.08)


def det(t: float, text: str, box: tuple[float, float, float, float] = BOX, conf: float = 0.95) -> Detection:
    return Detection(t=t, text=text, box=box, confidence=conf)


def test_spans_track_similar_text_at_the_same_place() -> None:
    dets = [
        det(1.0, "NaOH + HCl → NaCl + H2O"),
        det(1.5, "NaOH + HCI → NaCl + H2O", conf=0.7),
        det(2.0, "NaOH + HCl → NaCl + H2O", conf=0.99),
        det(1.0, "pH 7", box=(0.1, 0.8, 0.1, 0.05)),
    ]
    spans = group_spans(dets, interval=0.5)
    assert len(spans) == 2
    formula = next(s for s in spans if "NaOH" in s.best.text)
    assert (formula.start, formula.end) == (1.0, 2.0)
    assert formula.best.confidence == 0.99 and formula.box == BOX


def test_gap_or_moved_text_starts_a_new_span() -> None:
    gap = group_spans([det(1.0, "Title"), det(1.5, "Title"), det(4.0, "Title")], interval=0.5)
    assert [(s.start, s.end) for s in gap] == [(1.0, 1.5), (4.0, 4.0)]
    moved = group_spans([det(1.0, "Title"), det(1.5, "Title", box=(0.1, 0.7, 0.2, 0.05))], interval=0.5)
    assert len(moved) == 2


def test_different_text_same_place_is_a_new_span() -> None:
    spans = group_spans([det(1.0, "Acid + Base"), det(1.5, "pH 7 = neutral")], interval=0.5)
    assert len(spans) == 2


def test_picture_coordinates_remove_letterbox() -> None:
    quad = [[64.0, 60.0], [320.0, 60.0], [320.0, 96.0], [64.0, 96.0]]
    assert to_picture_box(quad, 640, 480, (0.0, 0.0, 1.0, 1.0)) == (0.1, 0.125, 0.4, 0.075)
    # 640x480 frame with a 640x360 picture starting at y=60
    assert to_picture_box(quad, 640, 480, (0.0, 0.125, 1.0, 0.75)) == (0.1, 0.0, 0.4, 0.1)
    assert to_picture_box([[0, 0], [10, 0], [10, 20], [0, 20]], 640, 480, (0.0, 0.125, 1.0, 0.75)) is None


def test_math_like_and_iou_and_sampling() -> None:
    assert is_math_like("NaOH + HCl") and is_math_like("H2O") and not is_math_like("Safety first")
    assert iou(BOX, BOX) == 1.0 and iou(BOX, (0.0, 0.5, 0.1, 0.1)) == 0.0
    times = sample_times([(0.0, 2.0, [0.1, 1.0]), (2.0, 3.0, [2.1])], fps=2.0, duration=3.0)
    assert times == [0.1, 0.25, 0.75, 1.0, 1.25, 1.75, 2.1, 2.25, 2.75]


def test_clean_text_drops_non_latin_noise() -> None:
    from loom.perception.ocr import clean_text

    assert clean_text("区") is None
    assert clean_text("NaOH + HCl → NaCl + H₂O") == "NaOH + HCl → NaCl + H₂O"
    assert clean_text("pH 7 = neutral") == "pH 7 = neutral"
    assert clean_text("50") == "50"
    assert clean_text("→ ·") is None


def test_hyphenated_words_are_not_math() -> None:
    assert not is_math_like("Acid-Base Neutralization")
    assert is_math_like("pH 7 = neutral") and is_math_like("4 - 2") and is_math_like("x − y")
