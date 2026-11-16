"""First-party interactive agents served over A2A (spec/02 §5): each has an Agent Card at
`/a2a/<name>/.well-known/agent-card.json` and JSON-RPC `message/send` at `/a2a/<name>/`. The gateway's product API
calls them through `A2AClient` over HTTP - the same path a third-party agent would take.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from loom.core.a2a import Skill, build_router
from loom.core.contracts.a2a import AgentCard, AgentSkill, LoomCardExtension
from loom.core.contracts.common import Contract


class AskReq(Contract):
    video_id: str
    question: str
    object_id: str | None = None
    learner_id: str | None = None
    part_id: str | None = None
    feedback: str | None = None


class AskRes(Contract):
    answer: str
    found_in_video: bool
    suggest: list[str] = []
    citations: list[dict[str, Any]] = []
    jump_to: float | None = None
    retrieved: list[str] = []


class SearchReq(Contract):
    video_id: str
    query: str
    k: int = 8


class SearchRes(Contract):
    hits: list[dict[str, Any]]


class ExplainReq(Contract):
    video_id: str
    question: str
    object_id: str | None = None
    learner_id: str | None = None
    channel: str | None = None
    part_id: str | None = None
    feedback: str | None = None
    length: str | None = None


class ExplainRes(Contract):
    key: str
    title: str
    question: str
    clip_url: str
    scene_url: str | None = None
    storyboard: list[str]
    duration_seconds: float
    verified_by: str
    evidence: list[dict[str, Any]] = []
    object_id: str | None = None
    cached: bool = False
    checks: list[dict[str, Any]] = []  # the fact-checker's verdict per narrated line (kept, cut + why, overruled)


class QuizReq(Contract):
    video_id: str
    topic: str
    learner_id: str | None = None


class QuizRes(Contract):
    topic: str
    source: str
    rejected: int = 0
    questions: list[dict[str, Any]]


AGENTS = {
    "loom-retriever": ("Semantic search over a video's speech, on-screen text, concepts and objects; grounded answers",
                       [("search", "Rank video moments for a query"), ("answer", "Answer a question with citations")]),
    "loom-animator": ("Writes, renders and fact-checks Manim explainers for a learner's own question",
                      [("explain_question", "Narrated, fact-checked animation for one question")]),
    "loom-assessment": ("Quizzes on any topic in the video: verified bank or freshly written and judge-verified",
                        [("quiz_topic", "Three checked questions about a topic")]),
}


def card(name: str, base_url: str) -> AgentCard:
    desc, skills = AGENTS[name]
    return AgentCard.model_validate({
        "name": name, "description": desc, "url": f"{base_url}/a2a/{name}/", "version": "2.0",
        "skills": [AgentSkill(id=s, name=s.replace("_", " "), description=d, tags=["loom"]).model_dump() for s, d in skills],
        "x-loom": LoomCardExtension(input_contract="json", output_contract="json", trust="first_party",
                                    graph_view="full").model_dump(),
    })


def routers(get_state: Any, base_url: str) -> list[tuple[str, APIRouter, AgentCard]]:
    from loom.agents import knowledge as K
    from loom.agents.session import load_graph

    async def index_for(video_id: str) -> tuple[Any, Any]:
        state = get_state()
        g = K.apply_overrides(state.store, load_graph(state.cfg.data_dir, video_id))
        return g, await K.build_index(state.llm, state.cfg.data_dir, g)

    async def search(req: SearchReq) -> SearchRes:
        state = get_state()
        _, idx = await index_for(req.video_id)
        return SearchRes(hits=await K.search(state.llm, idx, req.query, req.k))

    async def answer(req: AskReq) -> AskRes:
        state = get_state()
        g, idx = await index_for(req.video_id)
        return AskRes(**await K.answer(state.llm, state.store, idx, g, req.question, req.object_id, req.learner_id,
                                       req.part_id, req.feedback))

    async def explain(req: ExplainReq) -> ExplainRes:
        state = get_state()
        g, idx = await index_for(req.video_id)

        def progress(step: str, attempt: int) -> None:
            if req.channel:
                state.events.publish(req.channel, "render_progress",
                                     {"concept_node_id": "c_00", "step": step, "attempt": attempt})

        def note(agent: str, text: str, kind: str = "thinking", items: list[str] | None = None) -> None:
            if req.channel:
                state.events.publish(req.channel, "agent_note", {
                    "agent": agent, "text": text[:400], "kind": kind, "items": [i[:240] for i in (items or [])][:12]})

        return ExplainRes(**await K.custom_explainer(state.cfg, state.llm, state.store, state.cfg.data_dir, idx, g,
                                                     req.question, req.object_id, req.learner_id, progress, note,
                                                     req.part_id, req.feedback, req.length))

    async def quiz(req: QuizReq) -> QuizRes:
        state = get_state()
        g, idx = await index_for(req.video_id)
        return QuizRes(**await K.topic_quiz(state.cfg, state.llm, state.store, idx, g, req.topic, req.learner_id))

    out = []
    specs = {
        "loom-retriever": [Skill("search", "search", "Rank video moments", SearchReq, SearchRes, search, 120),
                           Skill("answer", "answer", "Grounded answer", AskReq, AskRes, answer, 240)],
        "loom-animator": [Skill("explain_question", "explain question", "Manim explainer", ExplainReq, ExplainRes,
                                explain, 1500, long_running=True)],
        "loom-assessment": [Skill("quiz_topic", "quiz topic", "Topic quiz", QuizReq, QuizRes, quiz, 600)],
    }
    for name, skills in specs.items():
        c = card(name, base_url)
        out.append((name, build_router(c, skills), c))
    return out
