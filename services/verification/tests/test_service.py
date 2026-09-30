"""HTTP API: the paths the agent mesh and the delivery client use."""

import pytest
from fastapi.testclient import TestClient

from loom_verification.loop import Verifier
from loom_verification.service import create_app

from .conftest import FakeAnimator, lesson_graph


@pytest.fixture
def client(cfg, tmp_path):
    graph_dir = tmp_path / "graphs"
    (graph_dir / "vid_00123").mkdir(parents=True)
    import json
    (graph_dir / "vid_00123" / "concept-graph.json").write_text(json.dumps(lesson_graph()))
    cfg.graph_dirs = [graph_dir]
    v = Verifier(cfg, None)
    v.animator = FakeAnimator()
    return TestClient(create_app(cfg, v))


def test_verify_then_fetch_like_the_delivery_client(client, candidate):
    r = client.post("/v1/verify", json=candidate)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    got = client.get("/verified-cut/sess_88a1")          # VERIFIED_CUT_URL=http://localhost:8003/verified-cut/<id>
    assert got.status_code == 200 and got.json() == r.json()
    assert client.get("/v1/sessions/sess_88a1/report").json()["status"] == "approved"


def test_bad_input_and_unknown_session(client):
    assert client.post("/v1/verify", json={"session_id": "x"}).status_code == 422
    assert client.get("/verified-cut/nope").status_code == 404
    assert client.get("/verified-cut/..%2Fetc").status_code in (400, 404)


def test_agent_cards_and_a2a(client, candidate):
    card = client.get("/a2a/verifier/.well-known/agent.json").json()
    assert card["name"] == "loom-verifier" and {s["id"] for s in card["skills"]} == {"verify_cut", "explain_concept"}
    rpc = {"jsonrpc": "2.0", "id": "1", "method": "message/send",
           "params": {"message": {"role": "user", "messageId": "m", "parts": [{"kind": "data", "data": candidate}],
                                  "metadata": {"skill": "verify_cut"}}}}
    out = client.post("/a2a/verifier/", json=rpc).json()
    assert out["result"]["parts"][0]["data"]["status"] == "approved"


def test_healthz(client):
    assert client.get("/healthz").json()["ok"] is True
