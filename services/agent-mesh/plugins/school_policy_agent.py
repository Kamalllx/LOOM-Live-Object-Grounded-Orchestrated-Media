"""Example THIRD-PARTY agent: a school's own policy agent that joins the mesh via its A2A Agent Card.

It runs as a separate process on its own port, shares no code with the orchestrator except the
protocol, and advertises the `policy_review` skill. Once registered (POST /api/agents/register), the
orchestrator discovers it and includes its redaction requests - which the Critic still verifies.

    .venv/bin/python -m uvicorn school_policy_agent:app --app-dir services/agent-mesh/plugins --port 8100

Policy used here (configurable via POLICY_MASK_LABELS): request a mask for any object whose label is on
the school's list.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "packages" / "shared-types"))

from fastapi import FastAPI  # noqa: E402

from loom_shared import a2a  # noqa: E402

PORT = int(os.getenv("POLICY_AGENT_PORT", "8100"))
MASK_LABELS = [s.strip() for s in os.getenv("POLICY_MASK_LABELS", "safety goggles").split(",") if s.strip()]


def handle(skill, data):
    graph = data["concept_graph"]
    return {"redaction_requests": [
        {"object_id": o["object_id"], "reason": f"school policy: '{o['label']}' must not be shown"}
        for o in graph["objects"] if o["label"].lower() in MASK_LABELS]}


card = a2a.agent_card("school-policy-agent", "A school's compliance agent: requests masks required by school policy",
                      f"http://127.0.0.1:{PORT}", [{"id": "policy_review", "input": ["concept_graph", "viewer_profile"],
                                                    "output": ["redaction_requests"]}])
app = FastAPI(title="school-policy-agent")
app.include_router(a2a.a2a_router(card, handle))
