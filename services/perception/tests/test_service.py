from __future__ import annotations

import time

from fastapi.testclient import TestClient

from conftest import fake_components
from loom_perception.pipeline import Pipeline
from loom_perception.service import create_app


def _wait(client, job_id, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/v1/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.2)
    raise TimeoutError(job)


def test_submit_poll_and_fetch(tmp_path, lesson_video, cfg):
    app = create_app(data_dir=tmp_path, pipeline=Pipeline(cfg, fake_components()))
    with TestClient(app) as client:
        assert client.get("/healthz").json()["status"] == "ok"
        r = client.post("/v1/jobs", json={"video_path": str(lesson_video), "video_id": "vid_test"})
        assert r.status_code == 202
        job = _wait(client, r.json()["job_id"])
        assert job["status"] == "succeeded", job
        assert job["concept_graph_url"] == "/v1/videos/vid_test/concept-graph"

        graph = client.get(job["concept_graph_url"]).json()
        assert graph["video_id"] == "vid_test" and graph["objects"]
        oid = graph["objects"][0]["object_id"]
        masks = client.get(f"/v1/videos/vid_test/masks/{oid}").json()
        assert masks["object_id"] == oid
        assert client.get("/v1/videos/vid_test/run").json()["counts"]["objects"] == 2
        assert client.get("/v1/jobs").json()[0]["job_id"] == job["job_id"]


def test_upload(tmp_path, lesson_video, cfg):
    app = create_app(data_dir=tmp_path, pipeline=Pipeline(cfg, fake_components()))
    with TestClient(app) as client:
        with open(lesson_video, "rb") as f:
            r = client.post("/v1/jobs/upload", files={"file": ("lesson.mp4", f, "video/mp4")}, data={"skip": "sam"})
        job = _wait(client, r.json()["job_id"])
        assert job["status"] == "succeeded" and job["video_id"].startswith("vid_")
        assert client.get(f"/v1/videos/{job['video_id']}/concept-graph").json()["objects"] == []


def test_errors(tmp_path, lesson_video, cfg):
    app = create_app(data_dir=tmp_path, pipeline=Pipeline(cfg, fake_components()))
    with TestClient(app) as client:
        assert client.post("/v1/jobs", json={"video_path": "nope.mp4"}).status_code == 400
        assert client.post("/v1/jobs", json={"video_path": str(lesson_video), "skip": ["bogus"]}).status_code == 400
        assert client.post("/v1/jobs", json={"video_path": str(lesson_video), "video_id": "../etc"}).status_code == 400
        assert client.get("/v1/jobs/unknown").status_code == 404
        assert client.get("/v1/videos/vid_none/concept-graph").status_code == 404
