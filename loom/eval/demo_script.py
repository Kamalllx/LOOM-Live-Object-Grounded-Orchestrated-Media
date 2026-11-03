"""The demo lesson "Acid-Base Neutralization" (spec/07 §1 `demo`): the single source of its script.

`loom eval make-demo` renders this into a video + ground truth; the golden fixtures in `tests/fixtures/` are authored
against the same script. Written fresh for the remake (nothing is taken from the old build).
"""

from __future__ import annotations

from dataclasses import dataclass, field

TITLE = "Acid-Base Neutralization"
VOICE = "af_heart"
WIDTH, HEIGHT, FPS = 1280, 720, 30


@dataclass(frozen=True)
class Source:
    clip_id: str
    page: str
    note: str


@dataclass(frozen=True)
class Segment:
    id: str
    sentences: list[str]
    clip: str | None = None  # Source.clip_id, or None for a title card
    card: str | None = None  # full-screen card text (title / summary)
    banner: str | None = None  # on-screen caption burned at the top right
    speed: float = 1.0  # playback speed of the clip (0.5 = half speed)
    objects: list[str] = field(default_factory=list)  # ground-truth visible objects
    hazard: str | None = None  # hazard object visible for the whole segment


SOURCES: dict[str, Source] = {
    "4132752": Source("4132752", "https://www.pexels.com/video/rekawiczki-4132752/", "hand putting on a latex glove"),
    "8326501": Source(
        "8326501",
        "https://www.pexels.com/video/a-scientist-doing-an-experiment-8326501/",
        "scientist in a lab coat pouring",
    ),
    "8392557": Source(
        "8392557", "https://www.pexels.com/video/mixing-colored-liquid-in-a-beaker-8392557/", "stirring a blue solution"
    ),
    "8544763": Source(
        "8544763",
        "https://www.pexels.com/video/a-hand-pouring-blue-liquid-into-a-beaker-8544763/",
        "blue poured into yellow, the beaker turns green",
    ),
    "854406": Source(
        "854406", "https://www.pexels.com/video/bottle-shattering-slow-motion-854406/", "glass bottle shattering"
    ),
}
LICENSE = "Pexels License (https://www.pexels.com/license/): free to use and modify, no attribution required"

SEGMENTS: list[Segment] = [
    Segment(
        "title",
        ["Welcome. In this short lesson we will find out what happens when an acid meets a base."],
        card=TITLE,
    ),
    Segment(
        "ppe",
        [
            "Before any experiment, put on a lab coat, gloves and safety goggles.",
            "Acids and bases can damage your skin and eyes.",
        ],
        clip="4132752",
        objects=["gloves"],
    ),
    Segment(
        "acid_base",
        [
            "Here a scientist pours a solution in the lab.",
            "An acid such as hydrochloric acid releases hydrogen ions in water.",
            "A base such as sodium hydroxide releases hydroxide ions.",
        ],
        clip="8326501",
        objects=["lab coat", "glass beaker", "microscope"],
    ),
    Segment(
        "reaction",
        [
            "When the two solutions are mixed, each hydrogen ion joins a hydroxide ion to form water.",
            "The sodium and chloride ions that remain make table salt, which stays dissolved.",
        ],
        clip="8392557",
        banner="NaOH + HCl → NaCl + H₂O",
        objects=["beaker", "measuring cylinder", "gloves"],
    ),
    Segment(
        "indicator",
        [
            "An indicator shows when the reaction is complete.",
            "Universal indicator turns green at pH seven, which is neutral.",
        ],
        clip="8544763",
        banner="pH 7 = neutral",
        objects=["beaker", "volumetric flask"],
    ),
    Segment(
        "hazard",
        [
            "Accidents can happen in any lab.",
            "If glassware breaks, never pick up the sharp pieces with your hands.",
            "Tell your teacher and sweep them up with a brush and dustpan.",
        ],
        clip="854406",
        speed=0.5,
        objects=["broken glass"],
        hazard="broken glass",
    ),
    Segment(
        "summary",
        [
            "So, an acid plus a base gives a salt plus water.",
            "This reaction is called neutralization, and antacid tablets use it to settle an upset stomach.",
        ],
        card="Acid + Base → Salt + Water",
    ),
]

# Per-object safety ground truth (spec/07 §1: "safety labels per object").
SAFETY_LABELS: dict[str, dict[str, object]] = {
    "broken glass": {"child_unsafe": True, "tags": ["sharp_object", "injury_risk"]},
    "gloves": {"child_unsafe": False, "tags": []},
    "lab coat": {"child_unsafe": False, "tags": []},
    "glass beaker": {"child_unsafe": False, "tags": []},
    "beaker": {"child_unsafe": False, "tags": []},
    "microscope": {"child_unsafe": False, "tags": []},
    "measuring cylinder": {"child_unsafe": False, "tags": []},
    "volumetric flask": {"child_unsafe": False, "tags": []},
}
