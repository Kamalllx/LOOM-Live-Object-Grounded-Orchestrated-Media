"""HTTP API for the perception service.

POST /v1/jobs                              submit a video by path: JSON {"video_path": ...}
POST /v1/jobs/upload                       submit a video as a multipart upload ("file")
GET  /v1/jobs/{job_id}                     status, current stage, progress, error
GET  /v1/videos/{video_id}/concept-graph   the contract output
GET  /v1/videos/{video_id}/masks/{obj_id}  per-frame RLE masks for one object
GET  /v1/videos/{video_id}/run             run report (timings, prompts, warnings)
GET  /healthz

Jobs run one at a time on a single worker thread: the models share one GPU and stay loaded
between jobs. Results live under <data_dir>/videos/<video_id>/.
"""

from __future__ import annotations

import json
import logging
import queue
import re
import shutil
import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from . import __version__
from .config import PipelineConfig
from .pipeline import STAGES, Pipeline, default_video_id

log = logging.getLogger(__name__)
_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


@dataclass
class Job:
    job_id: str
    video_id: str
    video_path: str
    status: str = "queued"  # queued | running | succeeded | failed
    stage: str | None = None
    progress: float = 0.0
    message: str = ""
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    skip: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)
    force: bool = False

    def public(self) -> dict:
        d = asdict(self)
        d.pop("video_path")
        if self.status == "succeeded":
            d["concept_graph_url"] = f"/v1/videos/{self.video_id}/concept-graph"
        return d


class JobRunner:
    def __init__(self, pipeline: Pipeline, data_dir: Path):
        self.pipeline = pipeline
        self.data_dir = data_dir
        self.jobs: dict[str, Job] = {}
        self.q: queue.Queue[str] = queue.Queue()
        self._thread = threading.Thread(target=self._loop, name="perception-worker", daemon=True)
        self._thread.start()

    def video_dir(self, video_id: str) -> Path:
        return self.data_dir / "videos" / video_id

    def submit(self, job: Job) -> Job:
        self.jobs[job.job_id] = job
        self.q.put(job.job_id)
        return job

    def _loop(self) -> None:
        while True:
            job = self.jobs[self.q.get()]
            job.status = "running"

            def progress(stage: str, frac: float, msg: str) -> None:
                job.stage = stage
                if stage in STAGES:
                    job.progress = round((STAGES.index(stage) + frac) / len(STAGES), 3)
                job.message = msg

            try:
                self.pipeline.run(
                    job.video_path,
                    self.video_dir(job.video_id),
                    video_id=job.video_id,
                    skip=set(job.skip),
                    force=job.force,
                    progress=progress,
                    prompts=job.prompts or None,
                )
                job.status, job.progress = "succeeded", 1.0
            except Exception as e:
                log.error("job %s failed: %s", job.job_id, traceback.format_exc())
                job.status, job.error = "failed", f"{type(e).__name__}: {e}"
            finally:
                job.finished_at = time.time()


def create_app(cfg: PipelineConfig | None = None, data_dir: Path | str = "data", pipeline: Pipeline | None = None) -> FastAPI:
    data_dir = Path(data_dir)
    (data_dir / "uploads").mkdir(parents=True, exist_ok=True)
    runner = JobRunner(pipeline or Pipeline(cfg), data_dir)
    app = FastAPI(title="LOOM perception", version=__version__)
    app.state.runner = runner

    def check_id(value: str, what: str) -> str:
        if not _ID.match(value):
            raise HTTPException(400, f"invalid {what}")
        return value

    def parse_list(v) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return [p.strip() for p in str(v).split(",") if p.strip()]

    @app.get("/healthz")
    def healthz():
        gpu = None
        try:
            import torch

            gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
        except ImportError:
            pass
        return {"status": "ok", "version": __version__, "gpu": gpu, "queued": runner.q.qsize()}

    def enqueue(path: Path, video_id, skip, prompts, force: bool) -> dict:
        skip_list = parse_list(skip)
        if set(skip_list) - set(STAGES):
            raise HTTPException(400, f"skip must be a subset of {list(STAGES)}")
        vid = check_id(video_id, "video_id") if video_id else default_video_id(path)
        job = runner.submit(Job(job_id=uuid.uuid4().hex[:12], video_id=vid, video_path=str(path), skip=skip_list, prompts=parse_list(prompts), force=force))
        return job.public()

    @app.post("/v1/jobs", status_code=202)
    async def submit_path(request: Request):
        """JSON body: {"video_path": "...", "video_id"?, "skip"?: [...], "prompts"?: [...], "force"?: bool}"""
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, 'expected JSON {"video_path": ...}; use /v1/jobs/upload for files')
        path = Path(str(body.get("video_path", "")))
        if not path.is_file():
            raise HTTPException(400, f"video_path not found: {path}")
        return enqueue(path, body.get("video_id"), body.get("skip"), body.get("prompts"), bool(body.get("force", False)))

    @app.post("/v1/jobs/upload", status_code=202)
    async def submit_upload(
        file: UploadFile = File(...),
        video_id: str | None = Form(default=None),
        skip: str | None = Form(default=None),
        prompts: str | None = Form(default=None),
        force: bool = Form(default=False),
    ):
        name = Path(file.filename or "upload.mp4").name
        dest = data_dir / "uploads" / f"{uuid.uuid4().hex[:8]}_{name}"
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)
        return enqueue(dest, video_id, skip, prompts, force)

    @app.get("/v1/jobs/{job_id}")
    def job_status(job_id: str):
        job = runner.jobs.get(job_id)
        if not job:
            raise HTTPException(404, "unknown job")
        return job.public()

    @app.get("/v1/jobs")
    def list_jobs():
        return [j.public() for j in sorted(runner.jobs.values(), key=lambda j: -j.created_at)]

    def result_file(video_id: str, *parts: str) -> Path:
        path = runner.video_dir(check_id(video_id, "video_id")).joinpath(*parts)
        if not path.is_file():
            raise HTTPException(404, "not found")
        return path

    @app.get("/v1/videos/{video_id}/concept-graph")
    def concept_graph(video_id: str):
        return JSONResponse(json.loads(result_file(video_id, "concept-graph.json").read_text(encoding="utf-8")))

    @app.get("/v1/videos/{video_id}/run")
    def run_report(video_id: str):
        return JSONResponse(json.loads(result_file(video_id, "run.json").read_text(encoding="utf-8")))

    @app.get("/v1/videos/{video_id}/masks/{object_id}")
    def masks(video_id: str, object_id: str):
        return FileResponse(result_file(video_id, "masks", f"{check_id(object_id, 'object_id')}.json"), media_type="application/json")

    return app
