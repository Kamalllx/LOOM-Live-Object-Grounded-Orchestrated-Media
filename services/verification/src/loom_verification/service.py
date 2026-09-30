"""HTTP service (default port 8003, the address the delivery client's VERIFIED_CUT_URL already points at).

  POST /v1/verify                         candidate-cut.json (Contract B) -> verified-cut.json (Contract C)
  GET  /verified-cut/{session_id}         the stored verified cut (what the delivery client fetches)
  GET  /v1/sessions/{session_id}/verified-cut   same, versioned path
  GET  /v1/sessions/{session_id}/report   loop trace, Critic claims and verdicts, warnings
  POST /v1/explain                        tap-to-learn: {video_id, concept_node_id, level?, learner_id?}
  GET  /media/{bucket}/{key}              rendered masks and clips (set LOOM_PUBLIC_MEDIA_BASE to use them)
  GET  /healthz
  A2A agents under /a2a/{verifier,guardian,animator,critic} (Agent Cards at .../.well-known/agent.json)
"""

from __future__ import annotations

import json
import os
import re
import shutil

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import __version__
from .a2a import a2a_router, agent_card
from .animator import AnimatorError, Explainer
from .config import Config
from .llm import get_llm
from .loop import CandidateError, Verifier
from .sources import load_concept_graph, load_learner_profile

SESSION_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


class ExplainRequest(BaseModel):
    video_id: str
    concept_node_id: str
    level: str | None = None
    learner_id: str | None = None


def create_app(cfg: Config | None = None, verifier: Verifier | None = None) -> FastAPI:
    cfg = cfg or Config()
    verifier = verifier or Verifier(cfg, get_llm(cfg))
    app = FastAPI(title="LOOM verification", version=__version__)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    public = os.environ.get("LOOM_VERIFY_PUBLIC_URL", "http://localhost:8003").rstrip("/")

    def check_session(session_id: str) -> str:
        if not SESSION_RE.match(session_id):
            raise HTTPException(400, "invalid session id")
        return session_id

    def run_verify(candidate: dict) -> dict:
        try:
            return verifier.verify(candidate)
        except CandidateError as e:
            raise HTTPException(422, str(e))
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "version": __version__, "llm": verifier.llm.name if verifier.llm else None,
                "animator": verifier.animator.available(), "ffmpeg": shutil.which("ffmpeg") is not None,
                "loop_budget": cfg.loop_budget}

    @app.post("/v1/verify")
    async def verify(request: Request):
        from fastapi.concurrency import run_in_threadpool
        body = await request.json()
        return await run_in_threadpool(run_verify, body.get("candidate_cut", body))

    def stored(session_id: str, name: str) -> dict:
        path = cfg.sessions_dir / check_session(session_id) / name
        if not path.is_file():
            raise HTTPException(404, f"no {name} for session {session_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/verified-cut/{session_id}")
    def verified_cut(session_id: str):
        return stored(session_id, "verified-cut.json")

    @app.get("/v1/sessions/{session_id}/verified-cut")
    def verified_cut_v1(session_id: str):
        return stored(session_id, "verified-cut.json")

    @app.get("/v1/sessions/{session_id}/report")
    def report(session_id: str):
        return stored(session_id, "report.json")

    @app.post("/v1/explain")
    def explain(req: ExplainRequest):
        try:
            return verifier.explain(req.video_id, req.concept_node_id, req.level, req.learner_id)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        except AnimatorError as e:
            raise HTTPException(503, str(e))

    @app.get("/media/{bucket}/{key:path}")
    def media(bucket: str, key: str):
        if bucket not in (cfg.mask_bucket, cfg.clip_bucket):
            raise HTTPException(404, "unknown bucket")
        root = (cfg.media_root / bucket).resolve()
        path = (root / key).resolve()
        if root not in path.parents or not path.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(path)

    # ---------------- A2A agents
    def verifier_skill(skill, data):
        if skill == "explain_concept":
            return verifier.explain(data["video_id"], data["concept_node_id"], data.get("level"), data.get("learner_id"))
        return verifier.verify(data.get("candidate_cut", data))

    def guardian_skill(skill, data):
        src = load_concept_graph(data["video_id"], cfg)
        profile = data.get("learner_profile") or load_learner_profile(data["learner_id"], cfg)[0]
        tags = verifier.guardian.tag_objects(src)
        decisions = verifier.guardian.decide(src.graph, profile, data.get("redaction_requests", []), tags)
        threads = data.get("threads") or [{"start": 0, "end": src.graph.get("duration_seconds", 1e9)}]
        return {"decisions": decisions, "tags": tags, "redaction_masks": verifier.guardian.build_masks(src, threads, decisions)}

    def animator_skill(skill, data):
        src = load_concept_graph(data["video_id"], cfg)
        ex = verifier.animator.render(src, data["concept_node_id"], data.get("level", "beginner"), data.get("feedback"))
        return {"clip_url": ex.url, "cached": ex.cached, "storyboard": ex.storyboard, "duration_seconds": ex.duration_s,
                "attempts": ex.attempts, "source": ex.source}

    def critic_skill(skill, data):
        cand = data["candidate_cut"]
        src = load_concept_graph(cand["video_id"], cfg)
        profile = data.get("learner_profile") or load_learner_profile(cand["learner_id"], cfg)[0]
        exps = {e["concept_node_id"]: Explainer(e["concept_node_id"], "", e.get("clip_url", ""), e.get("storyboard", []),
                                                False, 0, 0, None, "external") for e in data.get("explainers", [])}
        return verifier.critic.score(cand["threads"], cand.get("quiz", []), src.graph, profile, set(data.get("flagged", [])),
                                     data.get("redaction_masks", []), exps, {})

    agents = {
        "verifier": ("loom-verifier", "Runs the bounded Perceive-Plan-Act-Verify loop: candidate-cut -> verified-cut",
                     [{"id": "verify_cut", "description": "Contract B in, Contract C out"},
                      {"id": "explain_concept", "description": "Tap-to-learn explainer, fact-checked before it is shown"}],
                     verifier_skill),
        "guardian": ("loom-guardian", "Flags and redacts unsafe objects per viewer profile",
                     [{"id": "review_objects", "description": "Safety tags, redaction decisions and masks"}], guardian_skill),
        "animator": ("loom-animator", "Drafts, safety-checks, renders and caches Manim explainers",
                     [{"id": "render_explainer", "description": "Concept + level -> clip and storyboard"}], animator_skill),
        "critic": ("loom-critic", "Scores factuality, coherence and safety; gates delivery",
                   [{"id": "score_cut", "description": "Scores and structured issues for a candidate cut"}], critic_skill),
    }
    cards = {}
    for path, (name, desc, skills, handler) in agents.items():
        cards[path] = agent_card(name, desc, f"{public}/a2a/{path}", skills, __version__)
        app.include_router(a2a_router(cards[path], handler), prefix=f"/a2a/{path}")

    @app.get("/.well-known/agent.json")
    def root_card():
        return cards["verifier"]

    return app
