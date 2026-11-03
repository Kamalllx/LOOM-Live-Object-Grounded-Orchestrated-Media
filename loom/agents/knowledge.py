"""Knowledge layer: semantic index of a video, grounded answers, question-driven explainers, topic quizzes.

Items = spoken sentences, on-screen text, concepts, tracked objects (each with a time); embedded with the `embed` role
(qwen3-embedding) and projected to 2-D (PCA) for the similarity map. Index cached per graph_sha under
`<data>/index/<video_id>.json`. Every learner question is stored in `asks` (history + preferences).
"""

from __future__ import annotations

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
        out.append({"id": o.object_id, "kind": "object", "t": first, "end": max(i.end for i in o.instances),
                    "text": f"{o.label}. {near}", "label": o.label,
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


async def answer(llm: Any, store: Store, index: dict[str, Any], graph: ConceptGraph, question: str,
                 object_id: str | None, learner_id: str | None) -> dict[str, Any]:
    obj = next((o for o in graph.objects if o.object_id == object_id), None)
    query = f"{obj.label}: {question}" if obj else question
    hits = await search(llm, index, query, k=8, boost_object=object_id)
    level = level_for(store, learner_id)
    res = (await llm.call("brain", "answer_grounded", {"evidence": _evidence(hits)}, Answered,
                          params={"question": question, "object": obj.label if obj else "none", "level": level},
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


def explainer_key(video_id: str, question: str, level: str) -> str:
    norm = re.sub(r"\W+", " ", question.lower()).strip()
    return hashlib.sha256(f"{video_id}|{norm}|{level}".encode()).hexdigest()[:24]


async def custom_explainer(cfg: Any, llm: Any, store: Store, data: Path, index: dict[str, Any], graph: ConceptGraph,
                           question: str, object_id: str | None, learner_id: str | None, progress: Any,
                           note: Any = None) -> dict[str, Any]:
    """Learner-driven explainer: plan (brain) -> fact-check (judge; drops a few unsupported beats instead of failing)
    -> per-beat narration (Kokoro) -> cinematic scene JSON played in the browser. The Manim MP4 export renders in the
    background afterwards. Every step is narrated on the live channel via `note`."""
    import asyncio

    from loom.agents.animator import Verdicts
    from loom.agents.scene_dsl import ScenePlan
    from loom.core.llm import LLMError

    note = note or (lambda *a, **k: None)
    level = level_for(store, learner_id)
    key = explainer_key(graph.video_id, question, level)
    row = store.query_one("SELECT * FROM custom_explainers WHERE key = ?", (key,))
    if row:
        return _clip_row(row, cached=True)
    obj = next((o for o in graph.objects if o.object_id == object_id), None)
    note("loom-retriever", f"Searching the video for everything about: {question}")
    hits = await search(llm, index, f"{obj.label}: {question}" if obj else question, k=8, boost_object=object_id)
    ev = _evidence(hits)
    note("loom-retriever", f"Found {len(hits)} relevant moments to ground the explanation.", "output",
         [f"{int(h['t'] // 60)}:{int(h['t'] % 60):02d} {h['kind']}: {h['label']}" for h in hits[:6]])
    feedback: list[str] = []
    for attempt in range(1, 4):
        progress("draft", attempt)
        note("loom-animator", "Planning the scene: which shapes appear, how they move and merge, and one narrated "
                              "sentence per beat." + (" Rewriting the lines the fact-checker rejected." if feedback else ""))
        payload: dict[str, Any] = {"lesson_evidence": ev}
        if feedback:
            payload["fact_checker_rejected"] = feedback
        try:
            plan = (await llm.call("brain", "manim_plan", payload, ScenePlan,
                                   params={"question": question, "about": obj.label if obj else graph.title,
                                           "level": level},
                                   priority="tap_explainer", use_cache=attempt == 1, timeout_s=300)).value
        except LLMError as e:
            raise RuntimeError(f"planner unavailable: {e}") from e
        note("loom-animator", f"Planned '{plan.title}' in {len(plan.beats)} beats.", "output",
             [b.narration for b in plan.beats])
        progress("verify", attempt)
        note("loom-critic", f"Fact-checking {len(plan.beats)} narrated lines against the lesson.")
        claims = [{"id": i, "claim": b.narration} for i, b in enumerate(plan.beats)]
        try:
            verdicts = (await llm.call("judge", "claims_verify", {"evidence": ev, "claims": claims}, Verdicts,
                                       priority="tap_explainer", timeout_s=180)).value.verdicts
        except LLMError as e:
            raise RuntimeError(f"fact-checker unavailable - explainer not shown: {e}") from e
        by_id = {v.id: v for v in verdicts}
        bad = [i for i in range(len(plan.beats)) if not (i in by_id and by_id[i].supported)]
        lines = []
        for i, beat in enumerate(plan.beats):
            if i in bad:
                why = by_id[i].reason if i in by_id else "no verdict"
                lines.append(f"cut  {beat.narration[:120]} ({why})")
            else:
                lines.append(f"ok   {beat.narration[:120]}")
        note("loom-critic", f"{len(plan.beats) - len(bad)} of {len(plan.beats)} lines are supported.", "output", lines)
        keep = [beat for i, beat in enumerate(plan.beats) if i not in bad]
        if bad and (len(keep) < 3 or len(bad) > max(2, len(plan.beats) // 3)):
            feedback = [f"{plan.beats[i].narration} -> {by_id[i].reason if i in by_id else 'no verdict'}" for i in bad]
            log.warning("custom explainer attempt %d: too many unsupported lines: %s", attempt, feedback)
            continue
        if bad:
            note("loom-critic", f"Dropped {len(bad)} unsupported line(s); the rest of the scene stands.")
        plan = plan.model_copy(update={"beats": keep})
        progress("narrate", attempt)
        note("loom-animator", f"Recording narration for {len(keep)} beats with Kokoro, on this laptop.")
        scene = await asyncio.to_thread(_narrate_scene, data, key, plan)
        store.execute(
            "INSERT OR REPLACE INTO custom_explainers (key, video_id, question, object_id, title, clip_ref, storyboard, "
            "evidence, judge_model, created_at, scene_ref) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (key, graph.video_id, question, object_id, plan.title[:80], "",
             json.dumps({"lines": plan.storyboard, "duration": scene["duration"]}),
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


def _narrate_scene(data: Path, key: str, plan: Any) -> dict[str, Any]:
    """Per-beat Kokoro narration + scene JSON for the in-browser player."""
    import soundfile as sf

    from loom.eval.make_demo import SAMPLE_RATE, Narrator

    out = data / "media" / "scenes" / key
    out.mkdir(parents=True, exist_ok=True)
    tts = Narrator()
    beats, total = [], 0.0
    for i, b in enumerate(plan.beats):
        audio = tts.say(b.narration)
        sf.write(str(out / f"b{i}.wav"), audio, SAMPLE_RATE)
        dur = round(len(audio) / SAMPLE_RATE + 0.6, 2)
        total += dur
        beats.append({**b.model_dump(mode="json"), "audio": f"/media/scenes/{key}/b{i}.wav", "duration": dur})
    scene = {"title": plan.title, "takeaway": plan.takeaway, "beats": beats, "duration": round(total + 3, 1)}
    (out / "scene.json").write_text(json.dumps(scene, ensure_ascii=False), encoding="utf-8")
    return {"url": f"/media/scenes/{key}/scene.json", "duration": scene["duration"]}


def _export_mp4(cfg: Any, store: Store, data: Path, key: str, plan: Any) -> None:
    """Background MP4 export of the same plan (Manim + narration) for downloads and the YouTube extension."""
    import shutil

    from loom.agents.animator import check_code, narrate, render
    from loom.agents.scene_dsl import compile_plan

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
            "evidence": json.loads(row["evidence"]), "object_id": row["object_id"], "cached": cached}


def list_custom(store: Store, video_id: str) -> list[dict[str, Any]]:
    rows = store.query("SELECT * FROM custom_explainers WHERE video_id = ? ORDER BY created_at DESC", (video_id,))
    return [_clip_row(r, cached=True) for r in rows]


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
