"""Product API (spec/02 §8): videos, learners, sessions, server-graded quiz, mastery, explainers, YouTube lookup."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
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
    try:
        return _player_graph(S.load_graph(state.cfg.data_dir, video_id))
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


_ingesting: dict[str, asyncio.Task[Any]] = {}


@router.post("/api/videos/link")
async def ingest_link(req: LinkRequest, state: GatewayState = Depends(get_state)) -> dict[str, Any]:
    """User-initiated link ingest (YouTube): perception runs in the background; progress on `channel`."""
    from loom.perception.pipeline import ingest_source, youtube_id

    yt = youtube_id(req.url)
    if not yt:
        raise HTTPException(400, "only YouTube links are supported")
    for g in S.list_graphs(state.cfg.data_dir):
        # graphs perceived before the board/animation stage are re-perceived (their board marks were never read)
        if g.source.youtube_id == yt and "board" in g.perception_meta.models:
            return {"status": "ready", "video_id": g.video_id}
    channel = f"ingest_{yt.replace('-', '_')}"
    if channel not in _ingesting or _ingesting[channel].done():

        def progress(stage: str, status: str, p: float, detail: str) -> None:
            state.events.publish(channel, "ingest_stage", {"stage": stage, "status": status, "progress": p,
                                                           "detail": detail[:200]})

        async def run() -> None:
            try:
                g = await ingest_source(state.cfg, req.url, req.title, progress)
                state.events.publish(channel, "delivered", {"status": "approved", "pass_count": 1})
                log.info("ingested %s as %s", req.url, g.video_id)
            except Exception as e:
                log.exception("ingest %s failed", req.url)
                state.events.publish(channel, "error", {"message": str(e)[:300], "where": "ingest"})

        _ingesting[channel] = asyncio.create_task(run())
    return {"status": "processing", "channel": channel}


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


@router.post("/api/videos/{video_id}/ask")
async def ask(video_id: str, body: AskBody, state: GatewayState = Depends(get_state)) -> dict[str, Any]:
    """Question -> loom-retriever.answer over A2A (semantic search + grounded answer + where to jump)."""
    from loom.agents.a2a_agents import AskReq, AskRes

    client, base = _a2a(state)
    channel = f"tap_{video_id}_ask"
    try:
        r = await client.send(f"{base}/a2a/loom-retriever/", "answer", AskReq(video_id=video_id, **body.model_dump()),
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
    key = K.explainer_key(video_id, body.question, level)
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
    out = K.list_custom(state.store, video_id)
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
