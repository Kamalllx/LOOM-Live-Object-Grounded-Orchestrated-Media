"""Gemini (Vertex AI) helpers: proposing SAM prompts from keyframes, and naming concept nodes.

Both are optional; callers fall back to heuristics when the client can't be created.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from .config import LlmConfig

log = logging.getLogger(__name__)


def _default_project() -> str | None:
    try:
        import google.auth

        _, project = google.auth.default()
        if project:
            return project
    except Exception:
        pass
    try:
        out = subprocess.run(["gcloud", "config", "get-value", "project"], capture_output=True, text=True, shell=False, timeout=20)
        return out.stdout.strip() or None
    except Exception:
        return None


class Gemini:
    def __init__(self, cfg: LlmConfig):
        from google import genai

        project = cfg.project or _default_project()
        if not project:
            raise RuntimeError("no Google Cloud project configured (set GOOGLE_CLOUD_PROJECT)")
        self.cfg = cfg
        self.client = genai.Client(vertexai=True, project=project, location=cfg.location)

    def _json(self, parts: list, schema: dict) -> object:
        from google.genai import types

        resp = self.client.models.generate_content(
            model=self.cfg.model,
            contents=parts,
            # temperature 0: the same video should get the same prompts and labels on every run
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema, temperature=0.0),
        )
        return json.loads(resp.text)

    def propose_objects(self, keyframes: list[Path], context: str, limit: int) -> list[str]:
        from google.genai import types

        parts: list = [types.Part.from_bytes(data=p.read_bytes(), mime_type="image/jpeg") for p in keyframes]
        parts.append(
            "These are frames from an instructional video. "
            f"Narration and on-screen text excerpt:\n{context[:4000]}\n\n"
            f"List up to {limit} distinct physical objects, apparatus, diagrams or on-screen visual elements "
            "that are clearly visible in the frames and matter for what is being taught. "
            "These names are fed to an open-vocabulary object detector, so describe what each thing looks like, "
            "not what happened to it (e.g. 'glass shards' rather than 'broken glass'). "
            "Use short, concrete noun phrases (1–3 words, lowercase, plural only when the thing is a scattered group, "
            "e.g. 'beaker', 'conical flask', 'bar chart', 'glass shards'). Do not list people, hands, gloves, clothing, furniture, benches, tables, walls, floors, "
            "liquids, abstract ideas, or text."
        )
        items = self._json(parts, {"type": "array", "items": {"type": "string"}})
        return [str(i).strip().lower() for i in items if str(i).strip()][:limit]

    def name_objects(self, crops: list, candidates: list[str]) -> list[str | None]:
        """For each crop (PIL image of one tracked object), the best-fitting candidate name, or None."""
        import io

        from google.genai import types

        parts: list = []
        for i, crop in enumerate(crops):
            buf = io.BytesIO()
            crop.convert("RGB").save(buf, format="JPEG", quality=90)
            parts += [f"Object {i + 1}:", types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")]
        parts.append(
            f"Each image above is a crop around one object found by a detector in a lesson video. "
            f"For each object, in order, answer with exactly one name from this list: {json.dumps(candidates)}, "
            "or 'none' if the object is none of them. Judge only what is visible in the crop."
        )
        names = self._json(parts, {"type": "array", "items": {"type": "string"}})
        if not isinstance(names, list) or len(names) != len(crops):
            raise ValueError(f"expected {len(crops)} names, got {names!r}")
        lowered = {c.lower(): c for c in candidates}
        return [lowered.get(str(n).strip().lower()) for n in names]

    def label_concepts(self, nodes: list[dict]) -> list[str]:
        prompt = (
            "Each item below is one segment of an instructional video: what the narrator said, the text on screen, "
            "and the objects visible. Name the single concept each segment teaches, as a short lowercase noun phrase "
            "of 2–5 words (for example 'acid-base neutralization'). Return one label per item, in order.\n\n"
            + json.dumps(nodes, ensure_ascii=False)
        )
        labels = self._json([prompt], {"type": "array", "items": {"type": "string"}})
        if not isinstance(labels, list) or len(labels) != len(nodes):
            raise ValueError(f"expected {len(nodes)} labels, got {labels!r}")
        return [str(l).strip().lower() for l in labels]


def try_gemini(cfg: LlmConfig) -> Gemini | None:
    if not cfg.enabled:
        return None
    try:
        return Gemini(cfg)
    except Exception as e:
        log.warning("Gemini unavailable (%s); using heuristic fallbacks", e)
        return None
