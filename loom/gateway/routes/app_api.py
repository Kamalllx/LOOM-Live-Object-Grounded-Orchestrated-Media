"""Product API (spec/02 §8): videos, learners, sessions, server-graded quiz, mastery, explainers, YouTube lookup."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from loom.agents import session as S
from loom.gateway.state import GatewayState, get_state

log = logging.getLogger(__name__)
router = APIRouter()
_running: set[asyncio.Task[Any]] = set()


def _player_graph(g: Any) -> dict[str, Any]:
    d = g.model_dump(mode="json", exclude={"quiz_bank"})
    d["quiz_concepts"] = sorted({q.concept_node_id for q in g.quiz_bank})
    return d


@router.get("/api/videos")
def videos(state: GatewayState = Depends(get_state)) -> list[dict[str, Any]]:
    return [
        {
            "video_id": g.video_id,
            "title": g.title,
            "duration_seconds": g.duration_seconds,
            "video_url": g.video_url,
            "objects": len(g.objects),
            "concepts": len(g.concept_nodes),
            "tier": g.perception_meta.segmentation_tier,
            "youtube_id": g.source.youtube_id,
            "degraded": g.perception_meta.degraded,
        }
        for g in S.list_graphs(state.cfg.data_dir)
    ]


@router.get("/api/videos/{video_id}/graph")
def graph(video_id: str, state: GatewayState = Depends(get_state)) -> dict[str, Any]:
    from loom.agents.knowledge import apply_overrides

    try:
        return _player_graph(apply_overrides(state.store, S.load_graph(state.cfg.data_dir, video_id)))
    except FileNotFoundError as e:
        raise HTTPException(404, f"no video {video_id}") from e


@router.get("/api/lookup")
def lookup(youtube_id: str, state: GatewayState = Depends(get_state)) -> dict[str, Any]:
    for g in S.list_graphs(state.cfg.data_dir):
        if g.source.youtube_id == youtube_id:
            return {"ready": True, "video_id": g.video_id}
    job = state.store.query_one(
        "SELECT id, status, stage FROM jobs WHERE kind='ingest' AND payload LIKE ? ORDER BY created_at DESC LIMIT 1",
        (f"%{youtube_id}%",),
    )
    return {"ready": False, "job": dict(job) if job else None}


@router.get("/api/learners")
def learners(state: GatewayState = Depends(get_state)) -> list[dict[str, Any]]:
    return [p.model_dump(mode="json") for p in S.list_learners(state.store)]


@router.get("/api/learners/{learner_id}")
def learner(learner_id: str, state: GatewayState = Depends(get_state)) -> dict[str, Any]:
    try:
        return S.load_learner(state.store, learner_id).model_dump(mode="json")
    except KeyError as e:
        raise HTTPException(404, learner_id) from e


@router.post("/api/learners/{learner_id}/reset")
def reset(learner_id: str, state: GatewayState = Depends(get_state)) -> dict[str, Any]:
    state.store.execute("DELETE FROM mastery WHERE learner_id = ?", (learner_id,))
    return {"ok": True}


class SessionRequest(BaseModel):
    video_id: str
    learner_id: str


@router.post("/api/sessions")
async def start_session(req: SessionRequest, state: GatewayState = Depends(get_state)) -> dict[str, str]:
    sid = S.new_session_id()

    def publish(kind: str, data: dict[str, Any]) -> None:
        state.events.publish(sid, kind, data)

    async def run() -> None:
        try:
            await asyncio.to_thread(
                S.run_session, state.cfg, state.store, state.cfg.data_dir, req.video_id, req.learner_id, sid, publish
            )
        except Exception as e:  # surfaced to the player, never silent
            log.exception("session %s failed", sid)
            state.events.publish(sid, "error", {"message": f"{type(e).__name__}: {e}", "where": "session"})

    t = asyncio.create_task(run())
    _running.add(t)
    t.add_done_callback(_running.discard)
    return {"session_id": sid}


@router.get("/api/sessions/{session_id}")
def get_session(session_id: str, state: GatewayState = Depends(get_state)) -> dict[str, Any]:
    p = S.sessions_dir(state.cfg.data_dir) / f"{session_id}.json"
    if not p.exists():
        raise HTTPException(404, "not ready")
    data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    return data


class Answer(BaseModel):
    option_index: int


@router.post("/api/sessions/{session_id}/quiz/{question_id}/answer")
def answer(session_id: str, question_id: str, body: Answer, state: GatewayState = Depends(get_state)) -> dict[str, Any]:
    try:
        return S.grade(state.store, state.cfg.data_dir, session_id, question_id, body.option_index)
    except (KeyError, StopIteration) as e:
        raise HTTPException(404, str(e)) from e


class Finish(BaseModel):
    explainers_watched: list[str] = []


@router.post("/api/sessions/{session_id}/finish")
def finish(session_id: str, body: Finish, state: GatewayState = Depends(get_state)) -> dict[str, Any]:
    try:
        return S.finish(state.cfg, state.store, state.cfg.data_dir, session_id, body.explainers_watched)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/api/videos/{video_id}/weaves")
def weaves(video_id: str, state: GatewayState = Depends(get_state)) -> list[dict[str, Any]]:
    out = []
    for p in S.list_learners(state.store):
        r = state.store.query_one(
            "SELECT id FROM sessions WHERE video_id = ? AND learner_id = ? AND status != 'running' "
            "ORDER BY created_at DESC LIMIT 1",
            (video_id, p.learner_id),
        )
        f = S.sessions_dir(state.cfg.data_dir) / f"{r['id']}.json" if r else None
        if f and f.exists():
            cut = json.loads(f.read_text(encoding="utf-8"))
            out.append({"learner": p.display_name, "learner_id": p.learner_id, "cut": cut})
    return out


class ExplainRequest(BaseModel):
    concept_id: str
    level: str | None = None


_rendering: dict[str, asyncio.Task[Any]] = {}


@router.post("/api/sessions/{session_id}/explain")
async def explain(session_id: str, req: ExplainRequest, state: GatewayState = Depends(get_state)) -> dict[str, Any]:
    """Tap-to-learn (FR-GEN-08): a verified clip now, or a render job whose progress streams on `channel`."""
    from loom.agents import mesh
    from loom.agents.animator import make_explainer

    row = state.store.query_one("SELECT video_id, learner_id FROM sessions WHERE id = ?", (session_id,))
    if row is None:
        raise HTTPException(404, "unknown session")
    data = state.cfg.data_dir
    graph = S.load_graph(data, row["video_id"])
    if req.concept_id not in {c.node_id for c in graph.concept_nodes}:
        raise HTTPException(404, "unknown concept")
    profile = S.load_learner(state.store, row["learner_id"])
    level = req.level or mesh.level_of(
        mesh.concept_mastery(req.concept_id, mesh.mastery_table(profile, graph.video_id), profile)[0]
    )
    clips = S.verified_clips(state.store, graph).get(req.concept_id, {})
    if clips:
        clip = clips.get(level) or next(iter(clips.values()))
        return {"status": "ready", "clip": clip.model_copy(update={"trigger": "tap"}).model_dump(mode="json")}
    channel = f"tap_{graph.video_id}_{req.concept_id}"
    if channel not in _rendering or _rendering[channel].done():

        async def run() -> None:
            def progress(step: str, attempt: int) -> None:
                state.events.publish(
                    channel, "render_progress", {"concept_node_id": req.concept_id, "step": step, "attempt": attempt}
                )

            try:
                await make_explainer(state.cfg, state.llm, state.store, data, graph, req.concept_id, level, progress)
                state.events.publish(channel, "delivered", {"status": "approved", "pass_count": 1})
            except Exception as e:  # fail closed: nothing unverified is shown
                log.exception("explainer %s failed", channel)
                state.events.publish(channel, "error", {"message": str(e)[:300], "where": "animator"})

        _rendering[channel] = asyncio.create_task(run())
    return {"status": "rendering", "channel": channel}


class LinkRequest(BaseModel):
    url: str
    title: str | None = None
    max_height: int | None = None  # downscale on ingest (e.g. 480) so a long lesson stays light to play and perceive


_ingesting: dict[str, asyncio.Task[Any]] = {}
_ingest_from: dict[str, int] = {}  # channel -> last event id before the current run (its replay starts after)
UPLOAD_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
UPLOAD_MAX_BYTES = 4 * 1024**3
HEIGHTS = {360, 480, 720, 1080}


def _start_ingest(
    state: GatewayState, channel: str, ref: str, title: str | None, max_height: int | None
) -> dict[str, Any]:
    """Run perception in the background (one run per channel at a time); progress and the result go to `channel`."""
    from loom.perception.pipeline import ingest_source

    if max_height is not None and max_height not in HEIGHTS:
        raise HTTPException(400, f"max_height must be one of {sorted(HEIGHTS)}")
    if channel not in _ingesting or _ingesting[channel].done():
        # replay only this run: earlier attempts on the same channel (e.g. a failed one) must not reach the view
        _ingest_from[channel] = max((ev.id for ev in state.events.history(channel, 0, 100000)), default=0)

        def progress(stage: str, status: str, p: float, detail: str, image: str | None = None,
                     items: list[str] | None = None) -> None:
            state.events.publish(channel, "ingest_stage", {"stage": stage, "status": status, "progress": min(1.0, max(0.0, p)),
                                                           "detail": detail[:200], "image": image,
                                                           "items": [i[:240] for i in (items or [])][:12]})

        # the run's first event names it: a reloaded page, the header's running-tasks list and the run history show it
        progress("queued", "started", 0.0, title or ref)

        async def run() -> None:
            try:
                g = await ingest_source(state.cfg, ref, title, progress, max_height=max_height)
                state.events.publish(channel, "delivered", {"status": "approved", "pass_count": 1})
                log.info("ingested %s as %s", ref, g.video_id)
            except Exception as e:
                log.exception("ingest %s failed", ref)
                state.events.publish(channel, "error", {"message": str(e)[:300], "where": "ingest"})

        _ingesting[channel] = asyncio.create_task(run())
    return {"status": "processing", "channel": channel, "after": _ingest_from.get(channel, 0)}


@router.post("/api/videos/link")
async def ingest_link(req: LinkRequest, state: GatewayState = Depends(get_state)) -> dict[str, Any]:
    """User-initiated link ingest (YouTube): perception runs in the background; progress on `channel`."""
    from loom.perception.pipeline import youtube_id

    yt = youtube_id(req.url)
    if not yt:
        raise HTTPException(400, "only YouTube links are supported")
    for g in S.list_graphs(state.cfg.data_dir):
        # graphs perceived before the board and segment-everything stages are re-perceived (their marks and drawn
        # elements were never found)
        if g.source.youtube_id == yt and {"board", "elements"} <= set(g.perception_meta.models):
            return {"status": "ready", "video_id": g.video_id}
    return _start_ingest(state, f"ingest_{yt.replace('-', '_')}", req.url, req.title, req.max_height)


def upload_name(filename: str) -> tuple[str, str]:
    """Client file name -> (safe stored name, display title). Raises 400 for non-video suffixes."""
    from pathlib import PurePath

    base = PurePath(filename.replace("\\", "/")).name
    suffix = PurePath(base).suffix.lower()
    if suffix not in UPLOAD_SUFFIXES:
        allowed = ", ".join(sorted(UPLOAD_SUFFIXES))
        raise HTTPException(400, f"unsupported file type {suffix or '(none)'}; use one of {allowed}")
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", PurePath(base).stem).strip("_")[:60] or "upload"
    # downloader prefixes and quality tags are not part of the lesson's name (the title is the topic for explainers)
    title = re.sub(r"[_]+", " ", PurePath(base).stem)
    title = re.sub(r"^\s*[\w-]+\.(com|net|org|io|app|cc)\b[\s_-]*", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\b(\d{3,4}[pP]|[48][kK]|HD|FHD|UHD)\b|\(\d+\)", "", title)
    title = re.sub(r"\s+", " ", title).strip(" -_.")[:120] or "Uploaded lesson"
    return stem + suffix, title


@router.post("/api/videos/upload")
async def ingest_upload(request: Request, filename: str, title: str | None = None, max_height: int | None = None,
                        state: GatewayState = Depends(get_state)) -> dict[str, Any]:
    """Upload a local video file (raw request body, streamed to disk) and perceive it like a link. Works offline."""
    import hashlib
    import uuid

    stored, auto_title = upload_name(filename)
    if max_height is not None and max_height not in HEIGHTS:
        raise HTTPException(400, f"max_height must be one of {sorted(HEIGHTS)}")
    dest_dir = state.cfg.data_dir / "media" / "sources" / "uploads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest_dir / f".{uuid.uuid4().hex}.part"
    h, size = hashlib.sha256(), 0
    try:
        with tmp.open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > UPLOAD_MAX_BYTES:
                    raise HTTPException(413, "file is larger than 4 GB")
                h.update(chunk)
                f.write(chunk)
        if size == 0:
            raise HTTPException(400, "empty upload")
        sha = h.hexdigest()
        dest = dest_dir / f"{sha[:10]}_{stored}"
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    return {**_start_ingest(state, f"ingest_up_{sha[:12]}", str(dest), title or auto_title, max_height), "bytes": size}


@router.get("/api/channels/{channel}/latest")
def channel_latest(channel: str, limit: int = 20, state: GatewayState = Depends(get_state)) -> dict[str, Any]:
    """Recent events of a channel as JSON (for the extension, which polls instead of holding an SSE stream)."""
    hist = state.events.history(channel, 0, 5000)[-max(1, min(limit, 200)):]
    return {"events": [e.model_dump(mode="json") for e in hist]}


# ---------------------------------------------------------------- interactive layer (A2A agents)


def _a2a(state: GatewayState) -> Any:
    import httpx

    from loom.core.a2a import A2AClient

    base = f"http://127.0.0.1:{state.cfg.runtime.gateway_port}"
    return A2AClient(httpx.AsyncClient(base_url=base, timeout=1600), events=state.events, timeout_s=1500), base


@router.get("/api/agents")
def agents_list(state: GatewayState = Depends(get_state)) -> list[dict[str, Any]]:
    from loom.agents.a2a_agents import AGENTS, card

    base = f"http://127.0.0.1:{state.cfg.runtime.gateway_port}"
    return [card(n, base).model_dump(mode="json", by_alias=True) for n in AGENTS]


@router.get("/api/videos/{video_id}/map")
async def video_map(video_id: str, state: GatewayState = Depends(get_state)) -> dict[str, Any]:
    from loom.agents import knowledge as K

    g = S.load_graph(state.cfg.data_dir, video_id)
    return K.public_map(await K.build_index(state.llm, state.cfg.data_dir, g))


class AskBody(BaseModel):
    question: str
    object_id: str | None = None
    learner_id: str | None = None
    part_id: str | None = None
    feedback: str | None = None  # why the learner rejected the previous answer / explainer: re-plan for that
    length: str | None = None  # explainers: short | medium | deep


@router.post("/api/videos/{video_id}/ask")
async def ask(video_id: str, body: AskBody, state: GatewayState = Depends(get_state)) -> dict[str, Any]:
    """Question -> loom-retriever.answer over A2A (semantic search + grounded answer + where to jump)."""
    from loom.agents.a2a_agents import AskReq, AskRes

    client, base = _a2a(state)
    channel = f"tap_{video_id}_ask"
    try:
        req = AskReq(video_id=video_id, **body.model_dump(exclude={"length"}))
        r = await client.send(f"{base}/a2a/loom-retriever/", "answer", req,
                              AskRes, agent="loom-retriever", channel=channel, timeout_s=300)
    finally:
        await client.http.aclose()
    return {**r.value.model_dump(mode="json"), "agent_trace": [{"agent": r.agent, "skill": r.skill, "latency_ms": r.latency_ms}]}


@router.post("/api/videos/{video_id}/explain")
async def explain_question(video_id: str, body: AskBody, state: GatewayState = Depends(get_state)) -> dict[str, Any]:
    """Learner-driven Manim explainer via loom-animator.explain_question (A2A long-running task)."""
    from loom.agents import knowledge as K
    from loom.agents.a2a_agents import ExplainReq, ExplainRes

    level = K.level_for(state.store, body.learner_id)
    key = K.explainer_key(video_id, body.question, level, body.part_id, body.feedback,
                          body.length if body.length in K.LENGTHS else "medium")
    row = state.store.query_one("SELECT * FROM custom_explainers WHERE key = ?", (key,))
    if row:
        return {"status": "ready", "clip": K._clip_row(row, cached=True)}
    channel = f"tap_{video_id}_{key}"
    if channel not in _rendering or _rendering[channel].done():

        async def run() -> None:
            client, base = _a2a(state)
            try:
                await client.send(f"{base}/a2a/loom-animator/", "explain_question",
                                  ExplainReq(video_id=video_id, channel=channel, **body.model_dump()), ExplainRes,
                                  agent="loom-animator", channel=channel, timeout_s=1500)
                state.events.publish(channel, "delivered", {"status": "approved", "pass_count": 1})
            except Exception as e:
                log.exception("custom explainer failed")
                state.events.publish(channel, "error", {"message": str(e)[:300], "where": "animator"})
            finally:
                await client.http.aclose()

        _rendering[channel] = asyncio.create_task(run())
    return {"status": "rendering", "channel": channel, "key": key}


@router.get("/api/videos/{video_id}/explainers")
def explainers(video_id: str, state: GatewayState = Depends(get_state)) -> list[dict[str, Any]]:
    from loom.agents import knowledge as K

    g = S.load_graph(state.cfg.data_dir, video_id)
    out = K.list_custom(state.store, video_id, state.cfg.data_dir)
    for cid, levels in S.verified_clips(state.store, g).items():
        c = next(iter(levels.values()))
        out.append({"key": f"concept_{cid}", "title": c.title, "question": f"Explain {c.title}", "clip_url": c.clip_url,
                    "storyboard": c.storyboard, "duration_seconds": c.duration_seconds, "verified_by": c.verified_by,
                    "evidence": [], "object_id": None, "cached": True})
    return out


class QuizBody(BaseModel):
    topic: str
    learner_id: str | None = None


@router.post("/api/videos/{video_id}/quiz")
async def quiz_topic(video_id: str, body: QuizBody, state: GatewayState = Depends(get_state)) -> dict[str, Any]:
    from loom.agents.a2a_agents import QuizReq, QuizRes

    client, base = _a2a(state)
    try:
        r = await client.send(f"{base}/a2a/loom-assessment/", "quiz_topic", QuizReq(video_id=video_id, **body.model_dump()),
                              QuizRes, agent="loom-assessment", channel=f"tap_{video_id}_quiz", timeout_s=600)
    finally:
        await client.http.aclose()
    return {**r.value.model_dump(mode="json"), "agent_trace": [{"agent": r.agent, "skill": r.skill, "latency_ms": r.latency_ms}]}


class AdhocAnswer(BaseModel):
    option_index: int
    learner_id: str | None = None


@router.post("/api/quiz/{question_id}/answer")
def adhoc_answer(question_id: str, body: AdhocAnswer, state: GatewayState = Depends(get_state)) -> dict[str, Any]:
    from loom.agents import knowledge as K

    try:
        return K.grade_adhoc(state.store, question_id, body.option_index, body.learner_id)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/api/videos/{video_id}/history")
def ask_history(video_id: str, learner_id: str, state: GatewayState = Depends(get_state)) -> list[dict[str, Any]]:
    from loom.agents import knowledge as K

    return K.history(state.store, video_id, learner_id)


# ---------------------------------------------------------------- the learner feedback loop

class FeedbackBody(BaseModel):
    video_id: str
    target_kind: str  # answer | explainer | label | part
    target_id: str
    rating: int  # 1 helpful, -1 not helpful
    reason: str | None = None
    note: str | None = None
    learner_id: str | None = None


@router.post("/api/feedback")
def feedback(body: FeedbackBody, state: GatewayState = Depends(get_state)) -> dict[str, Any]:
    """Store a rating. A thumbs-down on an answer or explainer is followed by the client re-asking with the reason
    (`feedback` on ask/explain), so the agents re-plan for exactly what was wrong."""
    from loom.core.store import iso_now

    if body.target_kind not in ("answer", "explainer", "label", "part") or body.rating not in (-1, 1):
        raise HTTPException(400, "target_kind must be answer|explainer|label|part and rating 1 or -1")
    state.store.execute(
        "INSERT INTO feedback (video_id, learner_id, target_kind, target_id, rating, reason, note, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)", (body.video_id, body.learner_id, body.target_kind, body.target_id[:200],
                                     body.rating, (body.reason or "")[:40] or None, (body.note or "")[:400] or None,
                                     iso_now()))
    return feedback_summary(body.video_id, state)


@router.get("/api/videos/{video_id}/feedback")
def feedback_summary(video_id: str, state: GatewayState = Depends(get_state)) -> dict[str, Any]:
    rows = state.store.query("SELECT target_kind, rating, reason FROM feedback WHERE video_id = ?", (video_id,))
    fixed = state.store.query("SELECT object_id, part_id, label FROM label_overrides WHERE video_id = ?", (video_id,))
    up = sum(1 for r in rows if r["rating"] > 0)
    return {"ratings": len(rows), "helpful": up, "not_helpful": len(rows) - up,
            "reasons": {k: sum(1 for r in rows if r["reason"] == k)
                        for k in {r["reason"] for r in rows if r["reason"]}},
            "labels_fixed": [{"object_id": r["object_id"], "part_id": r["part_id"] or None, "label": r["label"]}
                             for r in fixed]}


class LabelBody(BaseModel):
    object_id: str
    label: str
    part_id: str | None = None
    learner_id: str | None = None


@router.post("/api/videos/{video_id}/labels")
def fix_label(video_id: str, body: LabelBody, state: GatewayState = Depends(get_state)) -> dict[str, Any]:
    """A learner renames an element or a part that LOOM misnamed. Applied for everyone from now on (graph, answers,
    explainers), and recorded as feedback on the reader model."""
    from loom.core.store import iso_now

    label = " ".join(body.label.split())[:80]
    if not label:
        raise HTTPException(400, "empty label")
    try:
        g = S.load_graph(state.cfg.data_dir, video_id)
    except FileNotFoundError as e:
        raise HTTPException(404, f"no video {video_id}") from e
    obj = next((o for o in g.objects if o.object_id == body.object_id), None)
    if obj is None or (body.part_id and not any(p.part_id == body.part_id for p in obj.parts)):
        raise HTTPException(404, "no such object or part")
    old = next((p.label for p in obj.parts if p.part_id == body.part_id), None) if body.part_id else obj.label
    state.store.execute(
        "INSERT OR REPLACE INTO label_overrides (video_id, object_id, part_id, label, learner_id, created_at) "
        "VALUES (?,?,?,?,?,?)", (video_id, body.object_id, body.part_id or "", label, body.learner_id, iso_now()))
    state.store.execute(
        "INSERT INTO feedback (video_id, learner_id, target_kind, target_id, rating, reason, note, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)", (video_id, body.learner_id, "part" if body.part_id else "label",
                                     f"{body.object_id}/{body.part_id or ''}", -1, "wrong_label",
                                     f"{old} -> {label}"[:400], iso_now()))
    return {"object_id": body.object_id, "part_id": body.part_id, "label": label, "was": old}
