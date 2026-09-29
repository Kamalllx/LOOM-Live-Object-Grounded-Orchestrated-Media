"""LOOM gateway: hosts every first-party A2A agent, the delivery API, and the media files.

    .venv/bin/python -m uvicorn server:app --app-dir services/delivery/api --port 8000

Each agent is served under /a2a/<name>/ with its own Agent Card at /a2a/<name>/.well-known/agent.json.
Agents only talk to each other through those URLs (JSON-RPC message/send), exactly as a third-party
agent on another host would; running them in one process is a deployment choice, not a coupling.
"""
import asyncio
import datetime
import json
import os
import pathlib
import subprocess
import sys
import threading
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[3]
for p in ["packages/shared-types", "services/agent-mesh/orchestrator", "services/agent-mesh/agents/curator",
          "services/agent-mesh/agents/pedagogy", "services/agent-mesh/agents/personalizer",
          "services/agent-mesh/agents/assessment", "services/verification", "services/verification/guardian",
          "services/verification/animator", "services/verification/critic", "services/delivery/memory",
          "services/perception"]:
    sys.path.insert(0, str(ROOT / p))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import animator  # noqa: E402
import assessment  # noqa: E402
import critic  # noqa: E402
import curator  # noqa: E402
import guardian  # noqa: E402
import loop  # noqa: E402
import orchestrator  # noqa: E402
import pedagogy  # noqa: E402
import personalizer  # noqa: E402
import store  # noqa: E402
from loom_shared import a2a, contracts, events, llm  # noqa: E402
from loom_shared.config import BACKEND_URL, GRAPHS_DIR, MEDIA_DIR  # noqa: E402

AGENTS = {
    # name: (module, description, skills)
    "curator": (curator, "Breaks the concept graph into short, self-contained knowledge threads",
                [{"id": "build_threads", "input": ["concept_graph"], "output": ["threads"]}]),
    "pedagogy": (pedagogy, "Maps each thread to what this learner already knows",
                 [{"id": "plan_threads", "input": ["threads", "concept_graph", "learner_profile"],
                   "output": ["planned_threads"]}]),
    "personalizer": (personalizer, "Assembles the viewer's cut: threads, explainer and redaction requests",
                     [{"id": "assemble_cut", "input": ["planned_threads", "concept_graph", "learner_profile"],
                       "output": ["candidate_cut"]},
                      {"id": "revise_cut", "input": ["candidate_cut", "issues"], "output": ["candidate_cut"]}]),
    "assessment": (assessment, "Writes targeted checks and updates the mastery graph",
                   [{"id": "write_quiz", "input": ["candidate_cut", "concept_graph", "learner_profile"],
                     "output": ["quiz"]},
                    {"id": "update_mastery", "input": ["learner_profile", "session_log"],
                     "output": ["learner_profile"]}]),
    "guardian": (guardian, "Flags and redacts unsafe objects per viewer profile",
                 [{"id": "review_objects", "input": ["concept_graph_segment", "viewer_profile"],
                   "output": ["redaction_mask_list"]}]),
    "animator": (animator, "Drafts, safety-checks and renders Manim explainers, cached per concept",
                 [{"id": "render_explainer", "input": ["concept_node", "level"], "output": ["clip_url", "storyboard"]}]),
    "critic": (critic, "Scores factuality, coherence and safety; gates delivery",
               [{"id": "score_cut", "input": ["candidate_cut", "masks", "explainers"], "output": ["scores", "issues"]}]),
    "verifier": (loop, "Runs the bounded Perceive-Plan-Act-Verify loop with fallback",
                 [{"id": "verify_cut", "input": ["candidate_cut"], "output": ["verified_cut"]},
                  {"id": "explain_concept", "input": ["concept_node_id"], "output": ["clip_url"]}]),
    "orchestrator": (orchestrator, "A2A client that coordinates the mesh for one viewing session",
                     [{"id": "personalize", "input": ["video_id", "learner_id"], "output": ["verified_cut"]},
                      {"id": "revise_cut", "input": ["candidate_cut", "issues"], "output": ["candidate_cut"]}]),
}

app = FastAPI(title="LOOM")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")

for name, (module, desc, skills) in AGENTS.items():
    card = a2a.agent_card(f"loom-{name}", desc, f"{BACKEND_URL}/a2a/{name}", skills)
    app.include_router(a2a.a2a_router(card, module.handle), prefix=f"/a2a/{name}")

_registered = threading.Event()
_register_lock = threading.Lock()


def ensure_registered():
    """Discover every first-party agent through its card (lazily: the server must be up to answer)."""
    with _register_lock:
        if _registered.is_set():
            return
        for name in AGENTS:
            url = f"{BACKEND_URL}/a2a/{name}"
            orchestrator.REGISTRY.register(url)
            loop.REGISTRY.register(url)
        _registered.set()


@app.on_event("startup")
def _startup():
    store.seed_personas()


# ---------- videos ----------

@app.get("/api/videos")
def list_videos():
    out = []
    for p in sorted(GRAPHS_DIR.glob("*.json")):
        g = json.loads(p.read_text())
        out.append({"video_id": g["video_id"], "title": g.get("title", g["video_id"]), "video_url": g.get("video_url"),
                    "duration_seconds": g.get("duration_seconds"), "objects": len(g["objects"]),
                    "concepts": len(g["concept_nodes"])})
    return out


@app.get("/api/videos/{video_id}/graph")
def video_graph(video_id: str):
    p = GRAPHS_DIR / f"{video_id}.json"
    if not p.exists():
        raise HTTPException(404, "unknown video")
    return json.loads(p.read_text())


@app.get("/api/videos/{video_id}/cuts")
def video_cuts(video_id: str):
    """Latest verified cut per learner for this video: the 'same threads, different weave' view."""
    out = []
    for p in sorted(loop.LAST_VERIFIED.glob(f"{video_id}__*.json")):
        cut = json.loads(p.read_text())
        try:
            learner = store.get_learner(cut["learner_id"])
        except FileNotFoundError:
            continue
        out.append({"learner": {k: learner.get(k) for k in ("learner_id", "display_name", "persona")}, "cut": cut})
    return out


PIPELINE = ROOT / "services" / "perception" / "pipeline.py"
PROGRESS_PREFIXES = ("ingest:", "asr:", "ocr:", "grounding:", "fusion:", "done:")
_ingest_lock = threading.Lock()      # one video at a time: GPU (Metal/MPS) work is not safe to run concurrently
_active_ingests = {}                 # source -> (job_id, video_id), so a double submit reuses the running job


def _ingest_job(job_id, source, video_id, title):
    """Perception runs in its own process: a GPU/driver crash or out-of-memory kill there cannot take the
    gateway (agents, player API) down with it. Its progress lines are relayed as events."""
    if _ingest_lock.locked():
        events.publish(job_id, "progress", message="queued: another video is being processed")
    try:
        with _ingest_lock:
            cmd = [sys.executable, str(PIPELINE), "--source", source, "--video-id", video_id]
            if title:
                cmd += ["--title", title]
            proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    env=dict(os.environ, PYTHONUNBUFFERED="1", PYTORCH_ENABLE_MPS_FALLBACK="1"))
            tail = []
            for line in proc.stdout:
                line = line.rstrip()
                tail = (tail + [line])[-5:]
                if line.startswith(PROGRESS_PREFIXES) or line.startswith("[download]"):
                    events.publish(job_id, "progress", message=line)
            code = proc.wait()
        if code == 0 and (GRAPHS_DIR / f"{video_id}.json").exists():
            events.publish(job_id, "done", video_id=video_id)
        else:
            reason = next((ln for ln in reversed(tail) if ln.strip()), f"exit code {code}")
            events.publish(job_id, "error", message=f"perception failed ({reason[:200]})")
    finally:
        _active_ingests.pop(source, None)


def _start_ingest(source, title, default_title):
    if source in _active_ingests:
        job_id, vid = _active_ingests[source]
        return {"job_id": job_id, "video_id": vid, "reused": True}
    job_id, vid = f"ingest_{uuid.uuid4().hex[:8]}", _new_video_id(title or default_title)
    _active_ingests[source] = (job_id, vid)
    threading.Thread(target=_ingest_job, args=(job_id, source, vid, title), daemon=True).start()
    return {"job_id": job_id, "video_id": vid}


class IngestRequest(BaseModel):
    url: str
    title: str | None = None


def _new_video_id(title):
    slug = "".join(c if c.isalnum() else "_" for c in (title or "video").lower())[:24].strip("_")
    return f"vid_{slug}_{uuid.uuid4().hex[:4]}"


@app.post("/api/videos/ingest")
def ingest_url(req: IngestRequest):
    return _start_ingest(req.url.strip(), req.title, "youtube")


@app.post("/api/videos/upload")
async def ingest_upload(file: UploadFile = File(...), title: str = Form(None)):
    uploads = MEDIA_DIR / "uploads"
    uploads.mkdir(exist_ok=True)
    dest = uploads / f"{uuid.uuid4().hex[:8]}_{pathlib.Path(file.filename).name}"
    dest.write_bytes(await file.read())
    return _start_ingest(str(dest), title or file.filename, pathlib.Path(file.filename).stem)


# ---------- learners (memory) ----------

@app.get("/api/learners")
def learners():
    return store.list_learners()


@app.get("/api/learners/{learner_id}")
def learner(learner_id: str):
    return store.get_learner(learner_id)


@app.post("/api/learners/reset")
def reset_learners():
    store.seed_personas(reset=True)
    return store.list_learners()


# ---------- sessions ----------

class SessionRequest(BaseModel):
    video_id: str
    learner_id: str


def _run_session(session_id, video_id, learner_id):
    try:
        ensure_registered()
        orchestrator.personalize(video_id, learner_id, session_id)
    except Exception as e:
        events.publish(session_id, "error", message=f"{type(e).__name__}: {e}")


@app.post("/api/sessions")
def start_session(req: SessionRequest):
    session_id = f"sess_{uuid.uuid4().hex[:8]}"
    threading.Thread(target=_run_session, args=(session_id, req.video_id, req.learner_id), daemon=True).start()
    return {"session_id": session_id}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    cut = store.get_verified(session_id)
    if not cut:
        raise HTTPException(404, "not ready")
    return cut


@app.get("/api/events/{channel}")
async def stream(channel: str):
    """Server-sent events: live agent calls and loop phases for a session or ingest job."""
    async def gen():
        idx = 0
        while True:
            new = await asyncio.to_thread(events.since, channel, idx, 15.0)
            for ev in new:
                yield f"data: {json.dumps(ev)}\n\n"
                if ev["kind"] in ("delivered", "done", "error"):
                    return
            idx += len(new)
            if not new:
                yield ": keep-alive\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class ExplainRequest(BaseModel):
    concept_node_id: str
    level: str | None = None


@app.post("/api/sessions/{session_id}/explain")
def explain(session_id: str, req: ExplainRequest):
    ensure_registered()
    cut = store.get_verified(session_id)
    if not cut:
        raise HTTPException(404, "unknown session")
    graph = video_graph(cut["video_id"])
    profile = store.get_learner(cut["learner_id"])
    level = req.level or pedagogy.learner_level(
        pedagogy.level_of([req.concept_node_id], pedagogy.mastery_lookup(profile, cut["video_id"]),
                          profile.get("preferences", {}).get("prior_knowledge", 0.3)))
    out, _ = a2a.send(f"{BACKEND_URL}/a2a/verifier", {"concept_graph": graph, "concept_node_id": req.concept_node_id,
                                                      "level": level, "session_id": session_id},
                      skill="explain_concept")
    return out


@app.post("/api/sessions/{session_id}/log")
def log_session(session_id: str, log: dict):
    ensure_registered()
    log = store.save_session_log(dict(log, session_id=session_id))
    cut = store.get_verified(session_id)
    profile = store.get_learner(log["learner_id"])
    out, _ = a2a.send(f"{BACKEND_URL}/a2a/assessment", {
        "learner_profile": profile, "session_log": log, "video_id": cut["video_id"],
        "now": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}, skill="update_mastery")
    store.save_learner(out["learner_profile"])
    log["mastery_updates"] = out["mastery_updates"]
    store.save_session_log(log)
    return {"mastery_updates": out["mastery_updates"], "learner_profile": out["learner_profile"]}


# ---------- agents (open protocol) ----------

@app.get("/api/agents")
def agents():
    ensure_registered()
    return list(orchestrator.REGISTRY.cards.values())


class RegisterRequest(BaseModel):
    url: str


@app.post("/api/agents/register")
def register_agent(req: RegisterRequest):
    ensure_registered()
    return orchestrator.REGISTRY.register(req.url)


@app.delete("/api/agents/{name}")
def unregister_agent(name: str):
    orchestrator.REGISTRY.unregister(name)
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True, "llm": llm.STATS | {"latency_ms": len(llm.STATS["latency_ms"])}}
