"""Knowledge layer: semantic index of a video, grounded answers, question-driven explainers, topic quizzes.

Items = spoken sentences, on-screen text, concepts, tracked objects (each with a time); embedded with the `embed` role
(qwen3-embedding) and projected to 2-D (PCA) for the similarity map. Index cached per graph_sha under
`<data>/index/<video_id>.json`. Every learner question is stored in `asks` (history + preferences).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import Field

from loom.core.contracts.common import Contract
from loom.core.contracts.graph import ConceptGraph
from loom.core.store import Store, iso_now

log = logging.getLogger(__name__)


class Answered(Contract):
    answer: str
    cite: list[str] = []
    found_in_video: bool = True
    suggest: list[str] = []


class CustomDraft(Contract):
    title: str = "Explainer"
    storyboard: list[str] = Field(min_length=3, max_length=10)
    code: str = Field(min_length=20)


# ---------------------------------------------------------------- index


def items_of(graph: ConceptGraph) -> list[dict[str, Any]]:
    sent = {s.seg_id: s for s in graph.transcript}
    out: list[dict[str, Any]] = []
    for s in graph.transcript:
        out.append({"id": s.seg_id, "kind": "speech", "t": s.start, "end": s.end, "text": s.text, "label": s.text[:60]})
    for x in graph.on_screen_text:
        out.append({"id": x.text_id, "kind": "screen", "t": x.start, "end": x.end, "text": x.text, "label": x.text[:60]})
    for c in graph.concept_nodes:
        ts = [sent[s].start for s in c.evidence.segment_ids if s in sent] or [0.0]
        out.append({"id": c.node_id, "kind": "concept", "t": min(ts), "end": max(ts) + 4,
                    "text": f"{c.label}. {c.summary}", "label": c.label, "objects": c.evidence.object_ids,
                    "prerequisites": c.prerequisites})
    for o in graph.objects:
        first = min(i.start for i in o.instances)
        near = " ".join(s.text for s in graph.transcript
                        if any(i.start - 2 <= s.start <= i.end + 2 for i in o.instances))[:400]
        what = f" ({o.element_kind}) {o.content or ''} {o.description or ''}" if o.phrase_source == "board" else ""
        out.append({"id": o.object_id, "kind": "object", "t": first, "end": max(i.end for i in o.instances),
                    "text": f"{o.label}.{what} {near}"[:900], "label": o.label,
                    "unsafe": o.safety.child_unsafe, "tags": list(o.safety.tags)})
    return out


def pca2(vecs: np.ndarray) -> np.ndarray:
    x = vecs - vecs.mean(axis=0, keepdims=True)
    _, _, vt = np.linalg.svd(x, full_matrices=False)
    p = x @ vt[:2].T
    lo, hi = p.min(axis=0), p.max(axis=0)
    return (p - lo) / np.where(hi - lo > 1e-9, hi - lo, 1.0)


async def build_index(llm: Any, data: Path, graph: ConceptGraph) -> dict[str, Any]:
    path = data / "index" / f"{graph.video_id}.json"
    sha = graph.graph_sha or graph.compute_sha()
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("graph_sha") == sha:
            return cached
    items = items_of(graph)
    vecs = await llm.embed([i["text"] for i in items], priority="session")
    xy = pca2(np.asarray(vecs))
    for i, it in enumerate(items):
        it["vec"] = [round(float(v), 5) for v in vecs[i]]
        it["x"], it["y"] = round(float(xy[i, 0]), 4), round(float(xy[i, 1]), 4)
    # similarity edges for the map: each object/concept to its 3 nearest items
    m = np.asarray(vecs) @ np.asarray(vecs).T
    edges = []
    for i, it in enumerate(items):
        if it["kind"] in ("object", "concept"):
            for j in np.argsort(-m[i])[1:4]:
                edges.append([it["id"], items[int(j)]["id"], round(float(m[i, j]), 3)])
    index = {"graph_sha": sha, "video_id": graph.video_id, "items": items, "edges": edges}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index), encoding="utf-8")
    return index


def public_map(index: dict[str, Any]) -> dict[str, Any]:
    return {"items": [{k: v for k, v in it.items() if k != "vec"} for it in index["items"]], "edges": index["edges"]}


async def search(llm: Any, index: dict[str, Any], query: str, k: int = 8, boost_object: str | None = None) -> list[dict[str, Any]]:
    q = (await llm.embed([query], priority="session"))[0]
    vecs = np.asarray([it["vec"] for it in index["items"]])
    scores = vecs @ np.asarray(q)
    if boost_object:
        for i, it in enumerate(index["items"]):
            if it["id"] == boost_object or boost_object in it.get("objects", []):
                scores[i] += 0.08
    order = np.argsort(-scores)[:k]
    return [{**{kk: vv for kk, vv in index["items"][int(i)].items() if kk != "vec"}, "score": round(float(scores[i]), 3)}
            for i in order]


GROUND_CAPS = {"concept": 3, "speech": 5, "object": 3, "screen": 2}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def diverse(hits: list[dict[str, Any]], concepts: list[dict[str, Any]], k: int = 10) -> list[dict[str, Any]]:
    """Ranked hits -> grounding evidence: near-duplicates dropped (OCR reads one title many times, each a bit wrong),
    at most GROUND_CAPS per kind (noisy screen text must not crowd out what the teacher said), and the best-matching
    concept summaries always in (they are the cleanest statement of what the lesson teaches)."""
    from difflib import SequenceMatcher

    out: list[dict[str, Any]] = []
    seen: list[str] = []
    per: dict[str, int] = {}
    for h in [*concepts[:2], *hits]:
        n = _norm(h["text"])
        if not n or any(h["id"] == o["id"] for o in out):
            continue
        if h["kind"] == "screen" and len(n) < 8:  # an OCR fragment ("en", "Gience") says nothing
            continue
        if any(SequenceMatcher(None, n, s).ratio() >= 0.75 or (len(n) > 12 and n in s) for s in seen):
            continue
        if per.get(h["kind"], 0) >= GROUND_CAPS.get(h["kind"], 3):
            continue
        per[h["kind"]] = per.get(h["kind"], 0) + 1
        seen.append(n)
        out.append(h)
        if len(out) >= k:
            break
    return sorted(out, key=lambda h: h["t"])


async def grounding(llm: Any, index: dict[str, Any], query: str, boost_object: str | None = None,
                    k: int = 10) -> list[dict[str, Any]]:
    """Evidence for an answer or an explainer: every item of the lesson ranked (a few hundred dot products), then
    `diverse`. A vague question ("explain the concept") ranks noisy screen text first; the concept summaries and the
    teacher's sentences must still reach the evidence."""
    hits = await search(llm, index, query, k=len(index["items"]), boost_object=boost_object)
    concepts = [h for h in hits if h["kind"] == "concept"]
    return diverse(hits, concepts, k)


def _evidence(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"id": h["id"], "kind": h["kind"], "t": round(h["t"], 1), "text": h["text"][:300]} for h in hits]


def level_for(store: Store, learner_id: str | None) -> str:
    from loom.agents import mesh
    from loom.agents.session import load_learner

    if not learner_id:
        return "intermediate"
    try:
        p = load_learner(store, learner_id)
    except KeyError:
        return "intermediate"
    return mesh.level_of(p.preferences.prior_knowledge)


def apply_overrides(store: Store, graph: ConceptGraph) -> ConceptGraph:
    """Labels learners corrected (object or part) replace the model's labels wherever the lesson is shown or asked
    about. The sealed hash is kept: it identifies what perception produced, the overrides are a layer on top."""
    rows = store.query("SELECT object_id, part_id, label FROM label_overrides WHERE video_id = ?", (graph.video_id,))
    if not rows:
        return graph
    fix = {(r["object_id"], r["part_id"]): r["label"] for r in rows}
    objects = []
    for o in graph.objects:
        parts = [p.model_copy(update={"label": fix.get((o.object_id, p.part_id), p.label)}) for p in o.parts]
        objects.append(o.model_copy(update={"label": fix.get((o.object_id, ""), o.label), "parts": parts}))
    return graph.model_copy(update={"objects": objects})


def focus(graph: ConceptGraph, object_id: str | None, part_id: str | None) -> tuple[Any, Any, str | None]:
    """(object, part, how to name it): a selected part is asked about as "the petal of the flower diagram"."""
    obj = next((o for o in graph.objects if o.object_id == object_id), None)
    part = next((p for p in obj.parts if p.part_id == part_id), None) if obj and part_id else None
    what = f"the {part.label} of the {obj.label}" if obj and part else (obj.label if obj else None)
    return obj, part, what


async def answer(llm: Any, store: Store, index: dict[str, Any], graph: ConceptGraph, question: str,
                 object_id: str | None, learner_id: str | None, part_id: str | None = None,
                 feedback: str | None = None) -> dict[str, Any]:
    obj, part, what = focus(graph, object_id, part_id)
    query = f"{what}: {question}" if what else question
    hits = await grounding(llm, index, query, boost_object=object_id)
    level = level_for(store, learner_id)
    data: dict[str, Any] = {"evidence": _evidence(hits)}
    if part:
        data["selected_part"] = {"part": part.label, "of": obj.label, "what": part.description or ""}
    if feedback:
        data["learner_feedback"] = feedback[:400]
    res = (await llm.call("brain", "answer_grounded", data, Answered,
                          params={"question": question, "object": what or "none", "level": level},
                          priority="tap_explainer", timeout_s=120)).value
    by_id = {h["id"]: h for h in hits}
    cites = [by_id[c] for c in res.cite if c in by_id] or hits[:2]
    # jump to the most relevant cited moment (the model lists citations most-relevant first)
    jumps = [round(c["t"], 1) for c in cites if c["kind"] in ("speech", "screen", "object", "concept")]
    store.execute("INSERT INTO asks (video_id, learner_id, object_id, kind, query, answer, citations, created_at) "
                  "VALUES (?,?,?,?,?,?,?,?)", (graph.video_id, learner_id or "anon", object_id, "ask", question,
                                               res.answer, json.dumps([c["id"] for c in cites]), iso_now()))
    return {"answer": res.answer, "found_in_video": res.found_in_video, "suggest": res.suggest[:3],
            "citations": [{k: c[k] for k in ("id", "kind", "t", "end", "label", "score")} for c in cites],
            "jump_to": jumps[0] if jumps else None, "retrieved": [h["id"] for h in hits]}


# ---------------------------------------------------------------- question-driven explainer


EXPLAINER_VERSION = 5  # bump when planning changes: v1 narrated the video; v2 drew constructions as orbs;
#                        v3-4 dropped constructions whose arcs were too narrow or whose angle was straight


LENGTHS = {"short": "4 to 5 beats, one clear idea", "medium": "6 to 8 beats",
           "deep": "10 to 14 beats in 2 or 3 chapters: the idea, how it works step by step, an example or "
                   "application, and a recap"}


def explainer_key(video_id: str, question: str, level: str, part_id: str | None = None,
                  feedback: str | None = None, length: str | None = None) -> str:
    question = " ".join(x for x in (question, part_id or "", feedback or "",
                                    "" if (length or "medium") == "medium" else length or "") if x)
    norm = re.sub(r"\W+", " ", question.lower()).strip()
    return hashlib.sha256(f"v{EXPLAINER_VERSION}|{video_id}|{norm}|{level}".encode()).hexdigest()[:24]


async def custom_explainer(cfg: Any, llm: Any, store: Store, data: Path, index: dict[str, Any], graph: ConceptGraph,
                           question: str, object_id: str | None, learner_id: str | None, progress: Any,
                           note: Any = None, part_id: str | None = None, feedback: str | None = None,
                           length: str | None = None) -> dict[str, Any]:
    """Learner-driven explainer: plan (brain) -> fact-check (judge; drops a few unsupported beats instead of failing)
    -> per-beat narration (Kokoro) -> cinematic scene JSON played in the browser. The Manim MP4 export renders in the
    background afterwards. Every step is narrated on the live channel via `note`."""
    import asyncio

    from loom.agents.animator import Verdict, Verdicts, absence_only, not_teaching
    from loom.agents.geometry import ConstructionPlan, is_construction, resolve
    from loom.agents.scene_dsl import ScenePlan
    from loom.core.llm import LLMError

    note = note or (lambda *a, **k: None)
    level = level_for(store, learner_id)
    length = length if length in LENGTHS else "medium"
    key = explainer_key(graph.video_id, question, level, part_id, feedback, length)
    row = store.query_one("SELECT * FROM custom_explainers WHERE key = ?", (key,))
    if row:
        return _clip_row(row, cached=True)
    obj, part, what = focus(graph, object_id, part_id)
    note("loom-retriever", f"Searching the video for everything about: {question}")
    hits = await grounding(llm, index, f"{what}: {question}" if what else question, boost_object=object_id)
    ev = _evidence(hits)
    if part:
        ev.insert(0, {"id": object_id, "kind": "object", "t": round(part.t, 1),
                      "text": f"{part.label} (part of {obj.label}): {part.description or ''}"[:300]})
    if feedback:
        note("loom-animator", f"The learner said the last version was not right: {feedback}. Re-planning for that.")
    from loom.agents.visuals import gather

    scene_dir = data / "media" / "scenes" / key
    query = re.sub(r"\s*\(\d+\)$", "", part.label if part else obj.label if obj else
                   next((h["label"] for h in hits if h["kind"] == "concept"), graph.title))
    focus_ids = [object_id] if object_id else []
    visuals = await asyncio.to_thread(gather, cfg, data, graph, hits, focus_ids, query, scene_dir)
    if visuals:
        note("loom-animator", f"Collected {len(visuals)} pictures the scene may use.", "output",
             [f"{v['caption']} ({v['source']})" for v in visuals])
    topic = "; ".join([graph.title, *(c.label for c in graph.concept_nodes[:6])])[:300]
    note("loom-retriever", f"Found {len(hits)} relevant moments to ground the explanation.", "output",
         [f"{int(h['t'] // 60)}:{int(h['t'] % 60):02d} {h['kind']}: {h['label']}" for h in hits[:6]])
    # a compass-and-straightedge question is drawn as an exact construction, not as glowing shapes
    construction = is_construction(question, what or "", graph.title)
    if construction:
        note("loom-animator", "This is a geometric construction: planning it as compass and straightedge steps that "
                              "LOOM computes exactly and draws on a slate.")
    rejected: list[str] = []
    geo_errors: list[str] = []
    for attempt in range(1, 4):
        progress("draft", attempt)
        note("loom-animator", ("Planning the construction step by step: points, rays, compass arcs and where they "
                               "cross, one narrated sentence per step." if construction else
                               "Planning the scene: which shapes appear, how they move and merge, and one narrated "
                               "sentence per beat.")
             + (" Rewriting the lines the fact-checker rejected." if rejected else "")
             + (" Fixing the steps that could not be drawn." if geo_errors else ""))
        payload: dict[str, Any] = {"lesson_evidence": ev}
        if visuals and not construction:
            payload["visuals"] = [{"id": v["id"], "shows": v["caption"], "from": v["source"]} for v in visuals]
        if rejected:
            payload["fact_checker_rejected"] = rejected
        if geo_errors:
            payload["geometry_errors"] = geo_errors
        if feedback:
            payload["learner_feedback_on_previous_version"] = feedback[:400]
        try:
            plan = (await llm.call("brain", "construction_plan" if construction else "manim_plan", payload,
                                   ConstructionPlan if construction else ScenePlan,
                                   params={"question": question, "about": what or graph.title,
                                           "level": level, "length": f"{length}: {LENGTHS[length]}"},
                                   priority="tap_explainer", use_cache=attempt == 1, timeout_s=300)).value
        except LLMError as e:
            raise RuntimeError(f"planner unavailable: {e}") from e
        note("loom-animator", f"Planned '{plan.title}' in {len(plan.beats)} beats.", "output",
             [b.narration for b in plan.beats])
        if construction:
            _, geo_errors = resolve(plan)
            drawn = sum(len(b.steps) for b in plan.beats)
            note("loom-animator", f"Computed the construction: {drawn - len(geo_errors)} of {drawn} steps resolve "
                                  "exactly.", "output", geo_errors[:8])
            if geo_errors and attempt < 3:
                rejected = []
                continue
        progress("verify", attempt)
        note("loom-critic", f"Fact-checking {len(plan.beats)} narrated lines against the lesson.")
        claims = [{"id": i, "claim": b.narration} for i, b in enumerate(plan.beats)]
        meta = not_teaching([b.narration for b in plan.beats])
        try:
            verdicts = (await llm.call("judge", "claims_verify",
                                       {"lesson_topic": topic + ("; a standard compass-and-straightedge construction"
                                                                 if construction else ""),
                                        "evidence": ev, "claims": claims}, Verdicts,
                                       priority="tap_explainer", timeout_s=180)).value.verdicts
        except LLMError as e:
            raise RuntimeError(f"fact-checker unavailable - explainer not shown: {e}") from e
        overruled = [v for v in verdicts if not v.supported and absence_only(v.reason)]
        if overruled:
            note("loom-critic", f"Kept {len(overruled)} line(s) the judge rejected only for not being said in the "
                                "video (absence is not an error).", "output",
                 [f"{plan.beats[v.id].narration[:90]} ({v.reason[:80]})"
                  for v in overruled if 0 <= v.id < len(plan.beats)])
            verdicts = [v.model_copy(update={"supported": True}) if v in overruled else v for v in verdicts]
        by_id = {v.id: v for v in verdicts}
        for i, why in meta.items():  # a line that narrates the video or repeats itself never teaches anything
            by_id[i] = Verdict(id=i, supported=False, reason=why)
        bad = [i for i in range(len(plan.beats)) if not (i in by_id and by_id[i].supported)]
        over_ids = {v.id for v in overruled}
        checks = [{"line": b.narration, "ok": i not in bad, "draft": attempt,
                   "reason": "" if i not in bad else (by_id[i].reason if i in by_id else "no verdict"),
                   "overruled": i in over_ids} for i, b in enumerate(plan.beats)]
        lines = []
        for i, beat in enumerate(plan.beats):
            if i in bad:
                why = by_id[i].reason if i in by_id else "no verdict"
                lines.append(f"cut  {beat.narration[:120]} ({why})")
            else:
                lines.append(f"ok   {beat.narration[:120]}")
        note("loom-critic", f"{len(plan.beats) - len(bad)} of {len(plan.beats)} lines are supported.", "output", lines)
        keep = [beat for i, beat in enumerate(plan.beats) if i not in bad]
        if construction and bad:
            # a dropped sentence must not drop its drawing: later steps refer to it. Its steps join the next beat.
            keep, carry = [], []
            for i, beat in enumerate(plan.beats):
                if i in bad:
                    carry += beat.steps
                    continue
                keep.append(beat.model_copy(update={"steps": [*carry, *beat.steps]}) if carry else beat)
                carry = []
            if carry and keep:
                keep[-1] = keep[-1].model_copy(update={"steps": [*keep[-1].steps, *carry]})
        if bad and (len(keep) < 3 or len(bad) > max(2, len(plan.beats) // 3)):
            rejected = [f"{plan.beats[i].narration} -> {by_id[i].reason if i in by_id else 'no verdict'}" for i in bad]
            log.warning("custom explainer attempt %d: too many unsupported lines: %s", attempt, rejected)
            continue
        if bad:
            note("loom-critic", f"Dropped {len(bad)} unsupported line(s); the rest of the scene stands.")
        plan = plan.model_copy(update={"beats": keep})
        draw = resolve(plan)[0] if construction else None
        progress("narrate", attempt)
        note("loom-animator", f"Recording narration for {len(keep)} beats with Kokoro, on this laptop.")
        scene = await asyncio.to_thread(_narrate_scene, data, key, plan, visuals, length, draw)
        store.execute(
            "INSERT OR REPLACE INTO custom_explainers (key, video_id, question, object_id, title, clip_ref, storyboard, "
            "evidence, judge_model, created_at, scene_ref) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (key, graph.video_id, question, object_id, plan.title[:80], "",
             json.dumps({"lines": plan.storyboard, "duration": scene["duration"], "checks": checks}),
             json.dumps([{"id": e["id"], "t": e["t"]} for e in ev[:4]]), cfg.models.judge.tag, iso_now(),
             scene["url"]))
        store.execute("INSERT INTO asks (video_id, learner_id, object_id, kind, query, answer, citations, created_at) "
                      "VALUES (?,?,?,?,?,?,?,?)", (graph.video_id, learner_id or "anon", object_id, "explain",
                                                   question, plan.title, "[]", iso_now()))
        note("loom-animator", f"Scene ready: {scene['duration']:.0f} seconds. Exporting an MP4 copy in the background.",
             "output")
        asyncio.get_running_loop().create_task(asyncio.to_thread(_export_mp4, cfg, store, data, key, plan))
        row = store.query_one("SELECT * FROM custom_explainers WHERE key = ?", (key,))
        return _clip_row(row, cached=False)
    raise RuntimeError("the fact-checker rejected too many lines in 3 plans; try asking more specifically about "
                       "what the video shows")


def _narrate_scene(data: Path, key: str, plan: Any, visuals: list[dict[str, Any]] | None = None,
                   length: str = "medium", draw: list[list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    """Per-beat Kokoro narration + scene JSON for the in-browser 3-D player (pictures resolved to URLs). `draw`:
    a construction's resolved drawing per beat (`geometry.resolve`), played on the slate instead of shapes."""
    import soundfile as sf

    from loom.eval.make_demo import SAMPLE_RATE, Narrator

    out = data / "media" / "scenes" / key
    out.mkdir(parents=True, exist_ok=True)
    by_id = {v["id"]: v for v in (visuals or [])}
    tts = Narrator()
    beats, total = [], 0.0
    for i, b in enumerate(plan.beats):
        audio = tts.say(b.narration)
        sf.write(str(out / f"b{i}.wav"), audio, SAMPLE_RATE)
        dur = round(len(audio) / SAMPLE_RATE + 0.6, 2)
        total += dur
        beat = b.model_dump(mode="json")
        beat.setdefault("elements", [])
        if draw is not None:
            beat["draw"] = draw[i] if i < len(draw) else []
        for el in beat["elements"]:  # a picture the planner chose: its URL and credit; an unknown id becomes a label
            v = by_id.get(el.get("image") or "") if el["kind"] == "image" else None
            if el["kind"] == "image" and v is None:
                el["kind"] = "text"
            elif v is not None:
                el.update(src=f"/media/scenes/{key}/{v['file']}", credit=v["credit"], caption=v["caption"],
                          source=v["source"])
        beats.append({**beat, "audio": f"/media/scenes/{key}/b{i}.wav", "duration": dur})
    scene = {"title": plan.title, "takeaway": plan.takeaway, "beats": beats, "duration": round(total + 3, 1),
             "length": length, "version": 3, "mode": "construction" if draw is not None else "scene",
             "visuals": [{"src": f"/media/scenes/{key}/{v['file']}", "caption": v["caption"], "source": v["source"],
                          "credit": v["credit"]} for v in (visuals or [])]}
    (out / "scene.json").write_text(json.dumps(scene, ensure_ascii=False), encoding="utf-8")
    return {"url": f"/media/scenes/{key}/scene.json", "duration": scene["duration"]}


def _export_mp4(cfg: Any, store: Store, data: Path, key: str, plan: Any) -> None:
    """Background MP4 export of the same plan (Manim + narration) for downloads and the YouTube extension."""
    import shutil

    from loom.agents.animator import check_code, narrate, render
    from loom.agents.scene_dsl import ScenePlan, compile_plan

    if not isinstance(plan, ScenePlan):  # constructions play in the browser only (no Manim compiler for them yet)
        return
    try:
        code = compile_plan(plan)
        check_code(code, 400)
        mp4, wd = render(code, 300, cfg.animator.render_quality)
        dest = data / "media" / "clips" / f"q_{key}.mp4"
        dest.parent.mkdir(parents=True, exist_ok=True)
        narrate(mp4, plan.storyboard, dest)
        store.execute("UPDATE custom_explainers SET clip_ref = ? WHERE key = ?", (f"/media/clips/{dest.name}", key))
        shutil.rmtree(wd, ignore_errors=True)
    except Exception:  # the scene is already delivered; the export is best-effort and logged
        log.exception("mp4 export failed for %s", key)


def _clip_row(row: Any, cached: bool) -> dict[str, Any]:
    sb = json.loads(row["storyboard"])
    scene = row["scene_ref"] if "scene_ref" in row.keys() else None
    return {"key": row["key"], "title": row["title"], "question": row["question"], "clip_url": row["clip_ref"],
            "scene_url": scene,
            "storyboard": sb["lines"], "duration_seconds": sb["duration"], "verified_by": row["judge_model"],
            "checks": sb.get("checks", []),
            "evidence": json.loads(row["evidence"]), "object_id": row["object_id"], "cached": cached}


def list_custom(store: Store, video_id: str, data: Path | None = None) -> list[dict[str, Any]]:
    """The lesson's explainers, newest first. When the planner improves (EXPLAINER_VERSION), asking again makes a new
    explainer for the same question; the library shows only the newest per question, object and length, so an older
    version (say, a construction drawn as orbs) is not offered next to the one that replaced it. Rows are kept."""
    rows = store.query("SELECT * FROM custom_explainers WHERE video_id = ? ORDER BY created_at DESC", (video_id,))
    out, seen = [], set()
    for r in rows:
        length, mode = "", ""
        if data is not None and r["scene_ref"]:
            p = data / r["scene_ref"].removeprefix("/")
            with contextlib.suppress(OSError, ValueError):
                sc = json.loads(p.read_text(encoding="utf-8"))
                length, mode = sc.get("length", ""), sc.get("mode", "scene")
        key = (re.sub(r"\W+", " ", (r["question"] or "").lower()).strip(), r["object_id"], length)
        if key in seen:
            continue
        seen.add(key)
        out.append({**_clip_row(r, cached=True), "length": length, "mode": mode})
    return out


# ---------------------------------------------------------------- quiz on any topic


async def topic_quiz(cfg: Any, llm: Any, store: Store, index: dict[str, Any], graph: ConceptGraph, topic: str,
                     learner_id: str | None) -> dict[str, Any]:
    """Questions about any topic in the video: verified bank first, else written + judge-verified now."""
    from loom.core.llm import LLMError
    from loom.perception.pipeline import QChecks, Written

    hits = await search(llm, index, topic, k=8)
    concepts = [h["id"] for h in hits if h["kind"] == "concept"]
    bank = [q for q in graph.quiz_bank if concepts and q.concept_node_id == concepts[0]]
    level = level_for(store, learner_id)
    out: list[dict[str, Any]] = []
    if bank and hits[0]["kind"] == "concept" and hits[0]["score"] > 0.6:
        for q in sorted(bank, key=lambda q: q.level != level)[:3]:
            qid = f"bank_{q.question_id}"
            _store_q(store, graph.video_id, topic, qid, q.stem, q.options, q.answer_index, q.rationale,
                     [{"id": s, "t": next((x.start for x in graph.transcript if x.seg_id == s), 0)} for s in q.evidence_segment_ids],
                     q.verified_by)
            out.append(qid)
        source = "verified bank"
    else:
        ev = [h for h in _evidence(hits) if h["kind"] in ("speech", "screen")]
        try:
            qs = (await llm.call("brain", "quiz_write", {"lesson_sentences": ev}, Written, params={"label": topic},
                                 priority="tap_explainer", timeout_s=180, use_cache=False)).value.questions
            items = [{"id": i, "question": q.stem, "options": q.options, "answer_index": q.answer_index} for i, q in enumerate(qs)]
            checks = (await llm.call("judge", "quiz_verify", {"evidence": ev, "questions": items}, QChecks,
                                     priority="tap_explainer", timeout_s=180)).value.checks
        except LLMError as e:
            raise RuntimeError(f"quiz models unavailable: {e}") from e
        good = {c.id for c in checks if c.answerable and c.unique_answer and c.marked_correct}
        for i, q in enumerate(qs):
            if i not in good or len(set(q.options)) != 4:
                continue
            qid = "adhoc_" + hashlib.sha256(f"{graph.video_id}|{q.stem}".encode()).hexdigest()[:16]
            evid = [{"id": e["id"], "t": e["t"]} for e in ev if e["id"] in q.evidence_segment_ids] or [{"id": ev[0]["id"], "t": ev[0]["t"]}]
            _store_q(store, graph.video_id, topic, qid, q.stem, q.options, q.answer_index, q.rationale or "From the lesson.",
                     evid, cfg.models.judge.tag)
            out.append(qid)
        source = "written now and fact-checked"
    store.execute("INSERT INTO asks (video_id, learner_id, object_id, kind, query, answer, citations, created_at) "
                  "VALUES (?,?,?,?,?,?,?,?)", (graph.video_id, learner_id or "anon", None, "quiz", topic,
                                               f"{len(out)} questions", json.dumps(out), iso_now()))
    rows = [store.query_one("SELECT * FROM adhoc_questions WHERE question_id = ?", (q,)) for q in out]
    return {"topic": topic, "source": source, "rejected": max(0, 3 - len(out)) if source != "verified bank" else 0,
            "questions": [{"question_id": r["question_id"], "stem": r["stem"], "options": _shuffled(r)} for r in rows if r]}


def _order(qid: str) -> list[int]:
    import random

    rng = random.Random(qid)  # deterministic per question; grading uses the same order
    o = [0, 1, 2, 3]
    rng.shuffle(o)
    return o


def _shuffled(row: Any) -> list[str]:
    opts = json.loads(row["options"])
    return [opts[i] for i in _order(row["question_id"])]


def _store_q(store: Store, video_id: str, topic: str, qid: str, stem: str, options: list[str], answer_index: int,
             rationale: str, evidence: list[dict[str, Any]], verified_by: str) -> None:
    store.execute("INSERT OR REPLACE INTO adhoc_questions (question_id, video_id, topic, stem, options, answer_index, "
                  "rationale, evidence, verified_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (qid, video_id, topic, stem, json.dumps(options), answer_index, rationale, json.dumps(evidence),
                   verified_by, iso_now()))


def grade_adhoc(store: Store, question_id: str, option_index: int, learner_id: str | None) -> dict[str, Any]:
    r = store.query_one("SELECT * FROM adhoc_questions WHERE question_id = ?", (question_id,))
    if r is None:
        raise KeyError(question_id)
    shown = _order(question_id).index(r["answer_index"])
    correct = option_index == shown
    store.execute("INSERT INTO adhoc_attempts (question_id, learner_id, option_index, correct, ts) VALUES (?,?,?,?,?)",
                  (question_id, learner_id or "anon", option_index, int(correct), iso_now()))
    return {"correct": correct, "correct_index": shown, "rationale": r["rationale"], "evidence": json.loads(r["evidence"])}


def history(store: Store, video_id: str, learner_id: str) -> list[dict[str, Any]]:
    rows = store.query("SELECT kind, query, answer, created_at FROM asks WHERE video_id = ? AND learner_id = ? "
                       "ORDER BY id DESC LIMIT 20", (video_id, learner_id))
    return [dict(r) for r in rows]
