from __future__ import annotations

from loom.perception.asr import MAX_SENTENCE_S, MIN_SENTENCE_S, words_to_sentences
from loom.perception.models import WordTiming


def words(spec: list[tuple[str, float, float]]) -> list[WordTiming]:
    return [WordTiming(w=w, start=s, end=e, p=0.9) for w, s, e in spec]


def test_split_on_terminal_punctuation_with_contiguous_ids() -> None:
    out = words_to_sentences(
        words(
            [
                (" Hello", 0.0, 0.5),
                (" there.", 0.5, 1.4),
                (" Acids", 1.6, 2.0),
                (" release", 2.0, 2.6),
                (" ions.", 2.6, 3.3),
                (" Done?", 3.5, 4.8),
            ]
        )
    )
    assert [s.seg_id for s in out] == ["s_001", "s_002", "s_003"]
    assert [s.text for s in out] == ["Hello there.", "Acids release ions.", "Done?"]
    assert all(s.start < s.end for s in out)
    assert out[1].words[0].w == " Acids"


def test_long_run_is_split_at_a_comma_or_pause() -> None:
    spec = [(f" w{i}", i * 0.5, i * 0.5 + 0.4) for i in range(40)]  # 20 s without punctuation
    spec[15] = (" w15,", 7.5, 7.9)
    out = words_to_sentences(words(spec))
    assert len(out) >= 2
    assert all(s.end - s.start <= MAX_SENTENCE_S for s in out)
    assert out[0].text.endswith("w15,")


def test_short_fragments_are_merged() -> None:
    out = words_to_sentences(
        words(
            [
                (" OK.", 0.0, 0.4),
                (" Now", 0.6, 1.0),
                (" we", 1.0, 1.2),
                (" pour", 1.2, 1.6),
                (" acid.", 1.6, 2.5),
                (" Yes.", 2.7, 3.0),
            ]
        )
    )
    assert all(s.end - s.start >= MIN_SENTENCE_S for s in out[:-1]) or len(out) == 1
    assert out[0].text.startswith("OK.")
    assert "".join(s.text for s in out).replace(" ", "") == "OK.Nowwepouracid.Yes."


def test_empty_and_unterminated() -> None:
    assert words_to_sentences([]) == []
    out = words_to_sentences(words([(" trailing", 0.0, 0.9), (" words", 0.9, 1.8)]))
    assert len(out) == 1 and out[0].text == "trailing words"


def test_wer_normalization() -> None:
    from loom.eval.asr_eval import normalize, wer

    assert normalize("Universal indicator turns green at pH 7, which is neutral.") == normalize(
        "universal indicator turns green at ph seven which is neutral"
    )
    assert normalize("Acid-Base") == "acid base"
    assert normalize("It's 42") == "its forty two"
    assert wer("a b c d", "a b x d")["wer"] == 0.25
