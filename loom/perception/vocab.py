"""Object vocabulary — what the detector looks for (spec/04 FR-PER-04).

Union of
  (a) `brain` VLM `vocab_propose`, one call per shot (mid frame + that shot's narration and on-screen text,
      ≤ 6 concrete, visible objects each; ≤ 24 shots per lesson);
  (b) transcript noun phrases that match the lab/classroom lexicon;
  (c) the always-on hazard classes from config, each with its curated look-alike list.
If the brain call fails, (b) ∪ (c) is used and the result is flagged `degraded: vocab_heuristic` (FR-PER-04 accept).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from loom.core.config import LoomConfig
from loom.core.contracts.common import Contract

STAGE_VERSION = "vocab@1"
PROMPT = "vocab_propose"
MAX_VLM_OBJECTS = 12
MAX_KEYFRAMES = 8
MAX_PER_SHOT = 6
MAX_SHOT_CALLS = 24

# Concrete objects a lab/classroom lesson may name (longest phrases are matched first).
LAB_LEXICON: tuple[str, ...] = (
    "bunsen burner",
    "safety goggles",
    "safety glasses",
    "lab coat",
    "test tube rack",
    "test tube",
    "conical flask",
    "erlenmeyer flask",
    "volumetric flask",
    "round bottom flask",
    "measuring cylinder",
    "graduated cylinder",
    "evaporating dish",
    "petri dish",
    "watch glass",
    "stirring rod",
    "glass rod",
    "dropping pipette",
    "pipette",
    "burette",
    "funnel",
    "filter paper",
    "beaker",
    "flask",
    "thermometer",
    "tripod",
    "gauze",
    "spatula",
    "tongs",
    "crucible",
    "clamp stand",
    "retort stand",
    "balance",
    "scale",
    "microscope",
    "slide",
    "magnifying glass",
    "indicator paper",
    "litmus paper",
    "universal indicator",
    "dropper",
    "wash bottle",
    "gloves",
    "goggles",
    "apron",
    "fume cupboard",
    "fire blanket",
    "fire extinguisher",
    "brush",
    "dustpan",
    "dust pan",
    "bottle",
    "jar",
    "glassware",
    "magnet",
    "battery",
    "wire",
    "bulb",
    "ammeter",
    "voltmeter",
    "ruler",
    "stopwatch",
    "spring",
    "pulley",
    "ramp",
    "trolley",
    "prism",
    "lens",
    "mirror",
    "candle",
    "match",
    "lighter",
    "magnesium ribbon",
    "zinc granules",
    "marble chips",
    "salt",
    "sugar",
    "vinegar",
    "baking soda",
)

# nouns a viewer (and a detector prompt) uses in the plural
_PLURAL_ONLY = {"goggles", "glasses", "gloves", "tongs", "scissors", "pliers", "tweezers", "chips", "granules"}
_SYNONYMS = {
    "dust pan": "dustpan",
    "graduated cylinder": "measuring cylinder",
    "safety glasses": "safety goggles",
    "erlenmeyer flask": "conical flask",
    "retort stand": "clamp stand",
}


class VocabObject(Contract):
    phrase: str = Field(min_length=2, max_length=60)
    why: str = Field(max_length=200)
    evidence: Literal["visual", "spoken", "text"]


class VocabProposal(Contract):
    objects: list[VocabObject] = Field(max_length=MAX_VLM_OBJECTS)


class VocabPhrase(Contract):
    phrase: str
    sources: list[Literal["vlm", "transcript", "hazard_class"]]
    is_hazard_class: bool = False
    lookalikes: list[str] = []


class VocabResult(Contract):
    phrases: list[VocabPhrase]
    keyframes: list[float]
    degraded: list[str] = []
    model: str | None = None


def normalize_phrase(phrase: str) -> str:
    p = re.sub(r"[^a-z0-9 \-]", " ", phrase.lower())
    p = re.sub(r"\s+", " ", p).strip()
    p = re.sub(r"^(a|an|the|some|two|three|several) ", "", p)
    words = p.split()
    if (
        words
        and words[-1] not in _PLURAL_ONLY
        and len(words[-1]) > 3
        and words[-1].endswith("s")
        and not words[-1].endswith(("ss", "us", "is"))
    ):
        last = words[-1]
        words[-1] = (
            last[:-3] + "y"
            if last.endswith("ies")
            else last[:-2]
            if last.endswith(("ches", "shes", "xes"))
            else last[:-1]
        )
    p = " ".join(words)
    return _SYNONYMS.get(p, p)


def transcript_phrases(sentences: list[str]) -> list[str]:
    """Lexicon phrases mentioned in the narration (longest match wins; 'test tube rack' hides 'test tube')."""
    text = " " + re.sub(r"[^a-z ]", " ", " ".join(sentences).lower()) + " "
    found: list[str] = []
    for term in sorted(LAB_LEXICON, key=len, reverse=True):
        variants = (term, term + "s", term + "es")
        for v in variants:
            pattern = f" {v} "
            if pattern in text:
                found.append(normalize_phrase(term))
                text = text.replace(pattern, " " * len(pattern))
                break
    return list(dict.fromkeys(found))


def choose_keyframes(
    candidates: list[float], limit: int = MAX_KEYFRAMES, primary: list[float] | None = None
) -> list[float]:
    """Pick ≤ limit frames: every `primary` frame first (one per shot, mid-shot), then evenly spread extras."""
    first = sorted(set(round(t, 2) for t in primary or []))
    if len(first) >= limit:
        step = (len(first) - 1) / (limit - 1)
        return sorted({first[round(i * step)] for i in range(limit)})
    rest = sorted(set(round(t, 2) for t in candidates) - set(first))
    room = limit - len(first)
    if len(rest) > room:
        step = (len(rest) - 1) / max(1, room - 1)
        rest = [rest[round(i * step)] for i in range(room)] if room > 1 else [rest[len(rest) // 2]]
    return sorted(set(first) | set(rest))


def merge_vocab(
    vlm: list[str], spoken: list[str], hazards: list[str], lookalikes: dict[str, list[str]]
) -> list[VocabPhrase]:
    merged: dict[str, VocabPhrase] = {}

    def add(phrase: str, source: Literal["vlm", "transcript", "hazard_class"]) -> None:
        key = normalize_phrase(phrase)
        if not key:
            return
        if key not in merged:
            merged[key] = VocabPhrase(phrase=key, sources=[source])
        elif source not in merged[key].sources:
            merged[key] = merged[key].model_copy(update={"sources": [*merged[key].sources, source]})

    for p in vlm:
        add(p, "vlm")
    for p in spoken:
        add(p, "transcript")
    for h in hazards:
        add(h, "hazard_class")
    hazard_keys = {normalize_phrase(h) for h in hazards}
    out = []
    for key, v in merged.items():
        is_h = key in hazard_keys
        out.append(
            v.model_copy(update={"is_hazard_class": is_h, "lookalikes": lookalikes.get(key, []) if is_h else []})
        )
    return out


def save_keyframes(video: Path, times: list[float], outdir: Path, width: int = 960) -> list[Path]:
    import cv2

    from loom.perception.ocr import FrameReader

    outdir.mkdir(parents=True, exist_ok=True)
    reader = FrameReader(video)
    paths = []
    try:
        for t in sorted(times):
            frame = reader.at(t)
            if frame is None:
                continue
            h, w = frame.shape[:2]
            if w > width:
                frame = cv2.resize(frame, (width, round(h * width / w)), interpolation=cv2.INTER_AREA)
            p = outdir / f"kf_{t:08.2f}.jpg"
            cv2.imwrite(str(p), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            paths.append(p)
    finally:
        reader.close()
    return paths


TimedText = tuple[float, float, str]


def _within(items: list[TimedText], start: float, end: float) -> list[str]:
    return [text for s, e, text in items if s < end and e > start]


async def build_vocab(
    cfg: LoomConfig,
    llm: Any,
    video: Path,
    shots: list[tuple[float, float]],
    sentences: list[TimedText],
    ocr: list[TimedText],
    workdir: Path,
    priority: Any = "ingest",
) -> VocabResult:
    """One `vocab_propose` call per shot (its mid frame + the narration/on-screen text of that shot).

    S1 finding: a single call over 8 keyframes found 7/8 demo objects (missed the volumetric flask, named glassware
    inconsistently); one frame per call found 8/8. Long lessons are capped at MAX_SHOT_CALLS evenly chosen shots."""
    from loom.core.llm import LLMError

    chosen = choose_keyframes([round((s + e) / 2, 2) for s, e in shots], limit=MAX_SHOT_CALLS)
    spoken = transcript_phrases([t for _, _, t in sentences])
    hazards = list(cfg.perception.hazard_classes)
    lookalikes = {normalize_phrase(k): v for k, v in cfg.perception.lookalikes.items()}
    degraded: list[str] = []
    vlm: list[str] = []
    model = None
    failures = 0
    images: list[Path] = []
    try:
        images = save_keyframes(video, chosen, workdir / "keyframes")
    except Exception:  # unreadable video: no visual vocabulary
        images = []
    failures += len(chosen) - len(images)  # frames that could not be read count as failed calls
    for t, image in zip(chosen, images, strict=False):
        start, end = next(((s, e) for s, e in shots if s <= t <= e), (t - 1, t + 1))
        try:
            res = await llm.call(
                "brain",
                PROMPT,
                {
                    "narration": " ".join(_within(sentences, start, end))[:1500],
                    "on_screen_text": _within(ocr, start, end)[:10],
                },
                VocabProposal,
                images=[image],
                params={"max_objects": str(MAX_PER_SHOT), "lexicon": ", ".join(LAB_LEXICON)},
                priority=priority,
            )
        except LLMError:
            failures += 1
            continue
        vlm.extend(o.phrase for o in res.value.objects)
        model = f"{res.model}@{res.digest[:12]}"
    if chosen and failures == len(chosen):
        degraded.append("vocab_heuristic")
    elif failures:
        degraded.append("vocab_partial")
    return VocabResult(
        phrases=merge_vocab(vlm, spoken, hazards, lookalikes), keyframes=chosen, degraded=degraded, model=model
    )
