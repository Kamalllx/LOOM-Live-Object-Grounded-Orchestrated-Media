"""Agent runs rebuilt from the event log: splitting channels into runs, agent lanes, status."""

from __future__ import annotations

from loom.gateway.routes.runs import lanes, split_runs, summarize


def ev(i: int, event_kind: str, t: float, **data: object) -> dict[str, object]:
    return {"id": i, "kind": event_kind, "ts": f"2026-11-15T10:{int(t // 60):02d}:{t % 60:06.3f}+00:00", "data": data}


def test_ingest_channel_splits_at_end_and_start_but_not_on_long_stages() -> None:
    events = [
        ev(1, "ingest_stage", 0, stage="queued", status="started", detail="Cells"),
        ev(2, "ingest_stage", 1, stage="probe", status="started"),
        ev(3, "ingest_stage", 2, stage="probe", status="done", detail="1 s"),
        ev(4, "ingest_stage", 3, stage="quiz", status="started"),
        ev(5, "ingest_stage", 400, stage="quiz", status="done"),  # quiz writing: minutes without an event
        ev(6, "delivered", 401, status="approved", pass_count=1),
        ev(7, "ingest_stage", 900, stage="queued", status="started", detail="Cells"),  # processed again later
    ]
    runs = split_runs("ingest_up_abc", events)
    assert [[e["id"] for e in r] for r in runs] == [[1, 2, 3, 4, 5, 6], [7]]


def test_ask_channel_splits_per_answer() -> None:
    events = [ev(1, "agent_call", 0, agent="loom-retriever", skill="answer", status="started"),
              ev(2, "agent_done", 3, agent="loom-retriever", skill="answer", status="ok", latency_ms=3000),
              ev(3, "agent_call", 5, agent="loom-retriever", skill="answer", status="started")]
    assert [len(r) for r in split_runs("tap_vid_ask", events)] == [2, 1]


def test_lanes_pair_calls_and_map_stages_to_agents() -> None:
    events = [ev(1, "ingest_stage", 0, stage="queued", status="started"),
              ev(2, "ingest_stage", 1, stage="asr", status="started"),
              ev(3, "ingest_stage", 9, stage="asr", status="done", detail="8 s"),
              ev(4, "agent_call", 10, agent="loom-critic", skill="score_cut", status="started"),
              ev(5, "agent_note", 10.5, agent="loom-critic", text="scoring", kind="thinking"),
              ev(6, "agent_done", 11, agent="loom-critic", skill="score_cut", status="ok", latency_ms=1000)]
    ls = {ln["agent"]: ln for ln in lanes(events)}
    assert set(ls) == {"Listener", "loom-critic"}  # "queued" names the run, it is not work
    assert ls["Listener"]["spans"][0]["status"] == "ok"
    sp = ls["loom-critic"]["spans"][0]
    assert sp["end"] - sp["start"] == 1.0 and ls["loom-critic"]["notes"] == 1


def test_status_running_interrupted_failed() -> None:
    base = [ev(1, "ingest_stage", 0, stage="queued", status="started", detail="Cells"),
            ev(2, "ingest_stage", 1, stage="asr", status="started")]
    t_last = 1_700_000_000.0
    import datetime as dt

    now = dt.datetime.fromisoformat(base[-1]["ts"]).timestamp()  # type: ignore[arg-type]
    s = summarize("ingest_up_x", base, {}, now + 5, set())
    assert s["status"] == "running" and s["subtitle"] == "Cells" and s["progress"]["current"] == "asr"
    assert summarize("ingest_up_x", base, {}, now + 3600, set())["status"] == "interrupted"
    assert summarize("ingest_up_x", base, {}, now + 3600, {"ingest_up_x"})["status"] == "running"
    failed = summarize("ingest_up_x", [*base, ev(3, "error", 2, message="boom", where="ingest")], {}, t_last, set())
    assert failed["status"] == "failed" and failed["error"] == "boom"
