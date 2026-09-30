"""Which concepts should SAM 3.1 look for? SAM is promptable, so perception starts by choosing noun phrases.

With Gemini available, each chunk gets its own prompts proposed from that chunk's keyframes and
narration, so SAM only searches a chunk for things that plausibly appear in it. Without Gemini,
every chunk uses the same list mined from the transcript.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path

from .types import TextSpan, TranscriptSegment

log = logging.getLogger(__name__)

STOPWORDS = set(
    """a an the this that these those it its is are was were be been being to of in on at for with by from as and or but
    if then so than too very can will just not no yes we you i he she they them our your their my me us his her what which
    who whom when where why how all any both each few more most other some such only own same here there now also into
    about over under again further once do does did doing have has had having would should could might must shall may
    one two three first second next last way thing things lot bit kind type part time step steps let lets go going get
    today video lesson look see make sure okay ok right well""".split()
)

# Phrases following a determiner or number are, in narration, very often the objects being shown.
_DET = re.compile(r"\b(?:the|a|an|this|that|these|those|our|your|each|two|three|four|another)\s+([a-z][a-z\-]+(?:\s+[a-z][a-z\-]+)?)")


def heuristic_prompts(transcript: list[TranscriptSegment], limit: int) -> list[str]:
    counts: Counter[str] = Counter()
    corpus = " ".join(s.text for s in transcript).lower()
    for m in _DET.finditer(corpus):
        words = [w for w in m.group(1).split() if w not in STOPWORDS and not w.endswith("ly")]
        if not words:
            continue
        counts[" ".join(words)] += 1
        if len(words) == 2:
            counts[words[-1]] += 0.5  # the head noun on its own
    return [p for p, _ in counts.most_common(limit)]


def _merge(fixed: list[str], proposed: list[str], limit: int) -> list[str]:
    out: list[str] = []
    for p in [*fixed, *proposed]:
        p = p.strip().lower()
        if p and p not in out:
            out.append(p)
    return out[:limit]


def choose_prompts(
    fixed: list[str],
    transcript: list[TranscriptSegment],
    text: list[TextSpan],
    chunk_windows: list[tuple[float, float]],
    keyframes_by_chunk: dict[int, list[Path]],
    gemini,
    limit: int,
    discover: bool,
) -> tuple[dict[int, list[str]], str]:
    """Returns ({chunk index: prompts}, source), source ∈ config | gemini | transcript."""
    if not discover:
        base = _merge(fixed, [], limit)
        return {i: base for i in range(len(chunk_windows))}, "config"

    if gemini is not None:
        try:
            out = {}
            for i, (s, e) in enumerate(chunk_windows):
                said = " ".join(t.text for t in transcript if t.end > s and t.start < e)
                shown = " | ".join(t.text for t in text if t.end > s and t.start < e)
                proposed = gemini.propose_objects(keyframes_by_chunk.get(i, []), f"{said}\nOn screen: {shown}", limit)
                out[i] = _merge(fixed, proposed, limit)
            return out, "gemini"
        except Exception as e:
            log.warning("Gemini prompt discovery failed (%s); falling back to transcript heuristics", e)

    base = _merge(fixed, heuristic_prompts(transcript, limit), limit)
    return {i: base for i in range(len(chunk_windows))}, ("transcript" if base != _merge(fixed, [], limit) else "config")
