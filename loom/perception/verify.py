"""Detection verification with look-alikes (spec/04 FR-PER-07).

Step 1 (torch, worker phase): SigLIP2 zero-shot on a track's best 3 crops — the phrase competes against its curated
look-alikes, the other vocabulary phrases and "background"; it passes if it wins by a margin ≥ `siglip_margin`
(mean over crops). Step 2 (Ollama, `brain` phase, hazard tracks only): `hazard_crop_check` on the same crops.
Decision: a non-hazard track is kept iff SigLIP passes. A hazard is kept if *either* step confirms it (recall over
precision), dropped only if both reject it (logged), and kept as `unverified` (counts as a hazard) if a step could
not run — fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from loom.core.contracts.common import Contract
from loom.core.weights import cached_snapshot
from loom.perception.track import Track

STAGE_VERSION = "verify@2"
# words that, in the VLM's own "better label", still describe the hazard (S1 finding: the VLM answers "not broken
# glass" and then labels the crop "glass bottle with shattered glass shards") - counted as a confirmation
HAZARD_WORDS = {
    "broken glass": ("shard", "shatter", "broken", "fragment", "smash", "crack"),
    "knife": ("knife", "blade", "cutter"),
    "blade": ("blade", "razor", "knife"),
    "open flame": ("flame", "fire", "burning", "burner"),
    "fire": ("flame", "fire", "burning"),
    "needle": ("needle", "syringe"),
    "syringe": ("syringe", "needle"),
    "blood": ("blood",),
}


def vlm_confirms(phrase: str, is_phrase: bool, better_label: str | None) -> bool:
    if is_phrase:
        return True
    label = (better_label or "").lower()
    return any(w in label for w in HAZARD_WORDS.get(phrase, ()))
REPO = "google/siglip2-base-patch16-224"
CROP_PAD = 0.08


class CropCheck(Contract):
    is_phrase: bool
    confidence: float = Field(ge=0, le=1)
    better_label: str | None = None


@dataclass
class TrackVerdict:
    siglip_margin: float | None = None
    siglip_pass: bool | None = None  # None = could not run
    vlm: Literal["confirmed", "rejected", "not_run", "failed"] = "not_run"
    better_label: str | None = None
    crops: list[Path] = field(default_factory=list)

    def decide(self, is_hazard: bool) -> tuple[bool, Literal["verified", "unverified"]]:
        """(keep, status)."""
        if not is_hazard:
            if self.siglip_pass is None:
                return True, "unverified"
            return self.siglip_pass, "verified"
        if self.siglip_pass is True or self.vlm == "confirmed":
            return True, "verified"
        if self.siglip_pass is False and self.vlm == "rejected":
            return False, "verified"
        return True, "unverified"  # a step failed or did not run: treat as hazard


def crop_boxes(video: Path, track: Track, rect: tuple[float, float, float, float], outdir: Path) -> list[Path]:
    import cv2

    from loom.perception.ocr import FrameReader

    outdir.mkdir(parents=True, exist_ok=True)
    reader = FrameReader(video)
    paths = []
    try:
        for i, b in enumerate(sorted(track.best, key=lambda b: b.t)):
            frame = reader.at(b.t)
            if frame is None:
                continue
            fh, fw = frame.shape[:2]
            rx, ry, rw, rh = rect
            x, y, w, h = b.box
            x0 = int(max(0, (rx + (x - CROP_PAD * w) * rw) * fw))
            y0 = int(max(0, (ry + (y - CROP_PAD * h) * rh) * fh))
            x1 = int(min(fw, (rx + (x + w * (1 + CROP_PAD)) * rw) * fw))
            y1 = int(min(fh, (ry + (y + h * (1 + CROP_PAD)) * rh) * fh))
            if x1 - x0 < 8 or y1 - y0 < 8:
                continue
            p = outdir / f"{track.shot_id}_{track.phrase.replace(' ', '-')}_{b.t:07.2f}_{i}.jpg"
            cv2.imwrite(str(p), frame[y0:y1, x0:x1])
            paths.append(p)
    finally:
        reader.close()
    return paths


class SiglipVerifier:
    def __init__(self, device: str = "cuda") -> None:
        import torch
        from transformers import AutoModel, AutoProcessor

        snap = cached_snapshot(REPO)
        src = str(snap) if snap else REPO
        self.device = device if torch.cuda.is_available() else "cpu"
        self.processor = AutoProcessor.from_pretrained(src)
        self.model = AutoModel.from_pretrained(src).to(self.device).eval()

    def margin(self, crops: list[Path], phrase: str, negatives: list[str]) -> float:
        """Mean over crops of P(phrase) − max P(negative), softmax over the candidate labels."""
        import torch
        from PIL import Image

        labels = [phrase, *dict.fromkeys(n for n in negatives if n != phrase), "background"]
        texts = [f"a photo of {label}." for label in labels]
        images = [Image.open(p).convert("RGB") for p in crops]
        inputs = self.processor(text=texts, images=images, padding="max_length", max_length=64, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.inference_mode():
            out = self.model(**inputs)
        probs = out.logits_per_image.softmax(dim=-1)  # (crops, labels)
        margins = probs[:, 0] - probs[:, 1:].max(dim=-1).values
        return round(float(margins.mean()), 4)

    def close(self) -> None:
        import torch

        del self.model
        torch.cuda.empty_cache()


def negatives_for(phrase: str, vocab: list[str], lookalikes: dict[str, list[str]], limit: int = 12) -> list[str]:
    """Curated look-alikes first, then other vocabulary phrases (the competition the detector actually faces)."""
    own = lookalikes.get(phrase, [])
    others = [v for v in vocab if v != phrase and v not in own and phrase not in v and v not in phrase]
    return (own + others)[:limit]


def siglip_phase(
    verifier: SiglipVerifier | None,
    tracks: list[Track],
    crops: dict[int, list[Path]],
    vocab: list[str],
    lookalikes: dict[str, list[str]],
    min_margin: float,
) -> dict[int, TrackVerdict]:
    verdicts: dict[int, TrackVerdict] = {}
    for i, tr in enumerate(tracks):
        v = TrackVerdict(crops=crops.get(i, []))
        if verifier is not None and v.crops:
            try:
                v.siglip_margin = verifier.margin(v.crops, tr.phrase, negatives_for(tr.phrase, vocab, lookalikes))
                v.siglip_pass = v.siglip_margin >= min_margin
            except (RuntimeError, ValueError):
                v.siglip_pass = None
        verdicts[i] = v
    return verdicts


async def vlm_phase(
    llm: Any,
    tracks: list[Track],
    verdicts: dict[int, TrackVerdict],
    hazards: set[str],
    lookalikes: dict[str, list[str]],
    priority: Any = "ingest",
) -> None:
    from loom.core.llm import LLMError

    for i, tr in enumerate(tracks):
        v = verdicts[i]
        if tr.phrase not in hazards or not v.crops:
            continue
        try:
            res = await llm.call(
                "brain",
                "hazard_crop_check",
                {},
                CropCheck,
                images=v.crops[:4],
                params={"phrase": tr.phrase, "lookalikes": ", ".join(lookalikes.get(tr.phrase, [])) or "none listed"},
                priority=priority,
            )
        except LLMError:
            v.vlm = "failed"
            continue
        v.vlm = "confirmed" if vlm_confirms(tr.phrase, res.value.is_phrase, res.value.better_label) else "rejected"
        v.better_label = res.value.better_label
