"""Graph fusion: transcript + on-screen text + tracked objects → concept nodes.

1. Units: transcript sentences (or, for silent videos, on-screen text spans / object appearances).
2. Topic segmentation: consecutive units join while they stay semantically close, pauses are short
   and the concept stays under max_node_seconds; tiny leftovers merge into their closer neighbour.
3. Each concept owns the timeline from its first unit until the next concept begins, so text and
   objects that appear a little after the narrator mentions them still attach to the right concept.
4. Objects attach when they are on screen during that window and either relate to what is said
   (label ↔ text similarity) or dominate the window; text attaches by time overlap.
5. Labels come from Gemini when available, otherwise from the best-matching key phrase.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from dataclasses import dataclass
from typing import Callable, Protocol

import numpy as np

from .config import FusionConfig
from .types import ConceptNode, ObjectTrack, TextSpan, TranscriptSegment
from .vocab import STOPWORDS

log = logging.getLogger(__name__)


class Embedder(Protocol):
    def __call__(self, texts: list[str]) -> np.ndarray: ...


class SentenceEmbedder:
    def __init__(self, model: str):
        from sentence_transformers import SentenceTransformer

        try:
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
        self.model = SentenceTransformer(model, device=device)

    def __call__(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 1))
        return np.asarray(self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False))


class HashingEmbedder:
    """Dependency-free fallback: normalized bag of hashed word stems. Good enough to keep topics apart."""

    def __init__(self, dim: int = 512):
        self.dim = dim

    def __call__(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim))
        for i, t in enumerate(texts):
            for w in _words(t):
                if w in STOPWORDS:
                    continue
                h = int(hashlib.md5(w[:6].encode()).hexdigest(), 16)
                out[i, h % self.dim] += 1.0
            n = np.linalg.norm(out[i])
            if n:
                out[i] /= n
        return out


def make_embedder(cfg: FusionConfig) -> Embedder:
    try:
        return SentenceEmbedder(cfg.embed_model)
    except Exception as e:
        log.warning("sentence-transformers unavailable (%s); using hashing embedder", e)
        return HashingEmbedder()


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9\-+]*", text.lower())


@dataclass
class _Unit:
    start: float
    end: float
    text: str
    kind: str  # transcript | text | object


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _units(transcript, text_spans, objects) -> list[_Unit]:
    if transcript:
        return [_Unit(s.start, s.end, s.text, "transcript") for s in sorted(transcript, key=lambda s: s.start)]
    if text_spans:
        return [_Unit(s.start, s.end, s.text, "text") for s in sorted(text_spans, key=lambda s: s.start)]
    units = [_Unit(i.start, i.end, o.label, "object") for o in objects for i in o.instances]
    return sorted(units, key=lambda u: u.start)


def segment_topics(units: list[_Unit], emb: np.ndarray, cfg: FusionConfig) -> list[list[int]]:
    if not units:
        return []
    groups: list[list[int]] = [[0]]
    for i in range(1, len(units)):
        g = groups[-1]
        centroid = emb[g].mean(axis=0)
        norm = np.linalg.norm(centroid)
        sim = float(centroid @ emb[i] / norm) if norm else 0.0
        gap = units[i].start - units[g[-1]].end
        span = units[i].end - units[g[0]].start
        if gap <= cfg.max_pause_seconds and span <= cfg.max_node_seconds and sim >= cfg.merge_similarity:
            g.append(i)
        else:
            groups.append([i])
    return _absorb_short(groups, units, emb, cfg)


def _absorb_short(groups: list[list[int]], units: list[_Unit], emb: np.ndarray, cfg: FusionConfig, min_seconds: float = 4.0) -> list[list[int]]:
    changed = True
    while changed and len(groups) > 1:
        changed = False
        for gi, g in enumerate(groups):
            if units[g[-1]].end - units[g[0]].start >= min_seconds:
                continue
            cands = []
            for nj in (gi - 1, gi + 1):
                if 0 <= nj < len(groups):
                    other = groups[nj]
                    merged = sorted(g + other)
                    if units[merged[-1]].end - units[merged[0]].start > cfg.max_node_seconds:
                        continue
                    c = emb[other].mean(axis=0)
                    sim = float(c @ emb[g].mean(axis=0)) / ((np.linalg.norm(c) * np.linalg.norm(emb[g].mean(axis=0))) or 1)
                    cands.append((sim, nj))
            if not cands:
                continue
            _, nj = max(cands)
            groups[nj] = sorted(groups[nj] + g)
            del groups[gi]
            changed = True
            break
    return groups


def fuse(
    duration: float,
    transcript: list[TranscriptSegment],
    text_spans: list[TextSpan],
    objects: list[ObjectTrack],
    embed: Embedder,
    cfg: FusionConfig,
    labeler: Callable[[list[dict]], list[str]] | None = None,
) -> list[ConceptNode]:
    units = _units(transcript, text_spans, objects)
    if not units:
        return []
    emb = embed([u.text for u in units])
    groups = segment_topics(units, emb, cfg)

    label_emb = {o.object_id: v for o, v in zip(objects, embed([o.label for o in objects]))} if objects else {}
    drafts = []
    for gi, g in enumerate(groups):
        own_start = 0.0 if gi == 0 else units[g[0]].start
        own_end = units[groups[gi + 1][0]].start if gi + 1 < len(groups) else max(duration, units[g[-1]].end)
        said = " ".join(units[i].text for i in g)
        centroid = emb[g].mean(axis=0)
        cn = np.linalg.norm(centroid)
        centroid = centroid / cn if cn else centroid

        texts = [s for s in text_spans if _attach_text(s, own_start, own_end)] if units[0].kind != "text" else [
            s for s in text_spans if any(abs(s.start - units[i].start) < 1e-6 and s.text == units[i].text for i in g)
        ]
        window = (units[g[0]].start, units[g[-1]].end)
        scored = []
        for o in objects:
            presence = sum(_overlap(i.start, i.end, own_start, own_end) for i in o.instances)
            if presence <= 0:
                continue
            frac = presence / max(1e-6, own_end - own_start)
            share = presence / max(1e-6, sum(i.end - i.start for i in o.instances))
            rel = _relevance(o, said + " " + " ".join(t.text for t in texts), centroid, label_emb.get(o.object_id))
            if rel >= cfg.object_relevance or frac >= cfg.object_presence or share >= cfg.object_share:
                scored.append((rel + 0.5 * frac + 0.25 * share, o))
        scored.sort(key=lambda x: -x[0])
        attached = [o for _, o in scored[: cfg.max_objects_per_node]]

        t_refs = [(units[i].start, units[i].end) for i in g] if units[0].kind == "transcript" else []
        x_refs = [(s.start, s.end) for s in texts]
        # A concept's span covers its speech plus its text, but never reaches into a neighbour's time.
        start = min([window[0]] + [max(s, own_start) for s, _ in x_refs])
        end = max([window[1]] + [min(e, own_end) for _, e in x_refs])
        drafts.append(
            dict(
                start=start,
                end=end,
                said=said if units[0].kind == "transcript" else "",
                shown=[t.text for t in texts],
                objects=attached,
                t_refs=t_refs,
                x_refs=x_refs,
                centroid=centroid,
            )
        )

    labels = None
    if labeler is not None:
        try:
            labels = labeler(
                [{"said": d["said"][:1500], "on_screen": d["shown"][:10], "objects": [o.label for o in d["objects"]]} for d in drafts]
            )
        except Exception as e:
            log.warning("LLM concept labelling failed (%s); using key phrases", e)
    if labels is None:
        labels = [
            keyphrase(d["said"], [o.label for o in d["objects"]] + [t for t in d["shown"] if len(t.split()) <= 4], d["centroid"], embed)
            for d in drafts
        ]

    nodes = []
    for n, (d, label) in enumerate(zip(drafts, labels), 1):
        nodes.append(
            ConceptNode(
                node_id=f"c_{n:02d}",
                label=label or "untitled concept",
                start=d["start"],
                end=d["end"],
                object_ids=[o.object_id for o in sorted(d["objects"], key=lambda o: o.object_id)],
                transcript_refs=d["t_refs"],
                on_screen_text_refs=d["x_refs"],
            )
        )
    return nodes


def _attach_text(span: TextSpan, own_start: float, own_end: float) -> bool:
    ov = _overlap(span.start, span.end, own_start, own_end)
    span_len = max(1e-6, span.end - span.start)
    return ov >= 0.3 * span_len or ov >= 0.3 * max(1e-6, own_end - own_start)


def _relevance(obj: ObjectTrack, text: str, centroid: np.ndarray, label_vec: np.ndarray | None) -> float:
    words = set(_words(text))
    names = [obj.label] + obj.aliases
    for name in names:
        head = _words(name)[-1:] if _words(name) else []
        if head and (head[0] in words or head[0].rstrip("s") in words or head[0] + "s" in words):
            return 1.0
    if label_vec is None:
        return 0.0
    return float(label_vec @ centroid)


_VERB_ENDINGS = ("izes", "ises", "ates", "ifies", "ing", "ed")
_NP = re.compile(r"\b(?:the|a|an|this|that|these|those|our|your|each|its|their)\s+((?:[a-z][a-z\-]+\s+){0,2}[a-z][a-z\-]+)")


def keyphrase(text: str, extra: list[str], centroid: np.ndarray, embed: Embedder) -> str:
    """Best-matching noun phrase for a concept: phrases after determiners, object labels, short on-screen text."""
    cands: dict[str, int] = {}
    for m in _NP.finditer(text.lower()):
        words = [w for w in m.group(1).split() if w not in STOPWORDS and not w.endswith("ly")]
        # "the base neutralizes …": a trailing verb is not part of the noun phrase.
        while len(words) > 1 and words[-1].endswith(_VERB_ENDINGS):
            words.pop()
        if words and all(len(w) >= 3 for w in words):
            p = " ".join(words)
            cands[p] = cands.get(p, 0) + 1
    for e in extra:
        cands[e.lower()] = cands.get(e.lower(), 0) + 1
    if not cands:  # no noun phrases found: fall back to content-word n-grams
        words = _words(text)
        for n in (2, 1):
            for i in range(len(words) - n + 1):
                gram = words[i : i + n]
                if gram[0] in STOPWORDS or gram[-1] in STOPWORDS or any(len(w) < 3 for w in gram if w.isalpha()):
                    continue
                cands[" ".join(gram)] = cands.get(" ".join(gram), 0) + 1
    if not cands:
        return "untitled concept"
    phrases = list(cands)
    vecs = embed(phrases)
    scores = [float(v @ centroid) + 0.04 * math.log1p(cands[p]) + 0.02 * (len(p.split()) - 1) for p, v in zip(phrases, vecs)]
    return phrases[int(np.argmax(scores))]
