"""Agent runs: every orchestration LOOM performed, rebuilt from the persisted event log (nothing is thrown away).

A *run* is a contiguous stretch of one channel's events: an ingest (`ingest_*`), a woven cut (`sess_*`), or an
interactive A2A task on a lesson (`tap_*`: explainer, answer, quiz). Channels are reused (a lesson ingested twice, many
questions on one lesson), so a channel is split into runs at terminal events, at explicit starts, and at long pauses.
The player draws each run as agent lanes on a timeline, live while it runs and replayable afterwards.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from loom.gateway.state import GatewayState, get_state

router = APIRouter()

TERMINAL = {"delivered", "error"}
GAP_S = 180.0  # a pause this long between two events of one channel starts a new run
STALE_S = 900.0  # an unfinished run with no event for this long was interrupted (gateway restart)
RUN_ID = re.compile(r"^(?P<channel>[A-Za-z0-9_]+)~(?P<first>\d+)$")
STAGE_AGENT = {
    "queued": "Fetcher", "download": "Fetcher", "probe": "Fetcher", "shots": "Editor", "asr": "Listener",
    "ocr": "Reader", "ocr_reread": "Reader", "board": "Board scanner", "elements": "Segmenter",
    "vocab": "Spotter", "board_read": "Board reader", "detect": "Detector", "track": "Tracker",
    "verify": "Verifier", "fuse": "Curator", "safety": "Guardian", "quiz": "Assessment", "masks": "Segmenter",
}


# ---------------------------------------------------------------- pure helpers (unit-tested)


def _ts(e: dict[str, Any]) -> float:
    return datetime.fromisoformat(e["ts"]).timestamp()


def is_start(e: dict[str, Any]) -> bool:
    d = e["data"]
    return e["kind"] == "session_start" or (
        e["kind"] == "ingest_stage" and d.get("status") == "started" and d.get("stage") in ("queued", "download"))


def split_runs(channel: str, events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """One channel's events (id order) -> runs. Answers and quizzes end with their agent call."""
    single_call = channel.endswith(("_ask", "_quiz"))
    runs: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    for e in events:
        if cur:
            last = cur[-1]
            ended = last["kind"] in TERMINAL or (single_call and last["kind"] == "agent_done")
            # an ingest stage may run for minutes without an event (quiz writing): ingests split only at a start
            # or an end
            paused = not channel.startswith("ingest_") and _ts(e) - _ts(last) > GAP_S
            if ended or is_start(e) or paused:
                runs.append(cur)
                cur = []
        cur.append(e)
    if cur:
        runs.append(cur)
    return runs


def run_kind(channel: str) -> str:
    if channel.startswith("ingest_"):
        return "ingest"
    if channel.startswith("sess_"):
        return "session"
    if channel.endswith("_ask"):
        return "ask"
    if channel.endswith("_quiz"):
        return "quiz"
    return "explain" if channel.startswith("tap_") else "system"


def video_of(channel: str, events: list[dict[str, Any]], known: list[str]) -> str | None:
    for e in events:
        d = e["data"]
        if e["kind"] == "session_start":
            return str(d["video_id"])
        img = d.get("image") or ""
        m = re.match(r"^/media/ingest/([A-Za-z0-9_]+)/", img)
        if m:
            return m.group(1)
    if channel.startswith("tap_"):
        cands = [v for v in known if channel.startswith(f"tap_{v}_")]
        return max(cands, key=len) if cands else None
    return None


def lanes(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Agent lanes: [{agent, spans: [{start, end|None, skill, status, latency_ms}], notes}] in first-seen order.
    Ingest stages become spans of the stage's agent (Listener, Reader, Board scanner...)."""
    out: dict[str, dict[str, Any]] = {}

    def lane(name: str) -> dict[str, Any]:
        return out.setdefault(name, {"agent": name, "spans": [], "notes": 0})

    for e in events:
        d, t = e["data"], _ts(e)
        if e["kind"] in ("agent_call", "agent_done"):
            ln = lane(d["agent"])
            if e["kind"] == "agent_call":
                ln["spans"].append({"start": t, "end": None, "skill": d["skill"], "status": "running"})
            else:
                open_ = next((s for s in reversed(ln["spans"]) if s["end"] is None and s["skill"] == d["skill"]), None)
                if open_ is None:
                    open_ = {"start": t - (d.get("latency_ms") or 0) / 1000, "skill": d["skill"]}
                    ln["spans"].append(open_)
                open_.update(end=t, status=d["status"], latency_ms=d.get("latency_ms"))
        elif e["kind"] == "ingest_stage":
            if d["stage"] == "queued":  # names the run; not work
                continue
            ln = lane(STAGE_AGENT.get(d["stage"], d["stage"]))
            if d["status"] == "started":
                ln["spans"].append({"start": t, "end": None, "skill": d["stage"], "status": "running"})
            elif d["status"] in ("done", "failed", "skipped"):
                open_ = next((s for s in reversed(ln["spans"]) if s["end"] is None and s["skill"] == d["stage"]), None)
                if open_ is not None:
                    status = "ok" if d["status"] == "done" else d["status"]
                    open_.update(end=t, status=status, detail=d.get("detail", ""))
        elif e["kind"] == "agent_note":
            lane(d["agent"])["notes"] += 1
    return list(out.values())


def summarize(channel: str, events: list[dict[str, Any]], titles: dict[str, str], now: float,
              live_channels: set[str]) -> dict[str, Any]:
    first, last = events[0], events[-1]
    kind = run_kind(channel)
    vid = video_of(channel, events, list(titles))
    terminal = next((e for e in reversed(events) if e["kind"] in TERMINAL), None)
    if terminal is not None:
        status = "failed" if terminal["kind"] == "error" else "done"
    elif kind in ("ask", "quiz") and last["kind"] == "agent_done":
        status = "failed" if last["data"].get("status") == "failed" else "done"
    elif channel in live_channels or now - _ts(last) < STALE_S:
        status = "running"
    else:
        status = "interrupted"
    subtitle = ""
    for e in events:
        d = e["data"]
        if e["kind"] == "ingest_stage" and d.get("stage") == "queued":
            subtitle = d.get("detail", "")
            break
        if e["kind"] == "agent_note" and d.get("text", "").startswith("Searching the video for everything about:"):
            subtitle = d["text"].split(":", 1)[1].strip()
            break
        if e["kind"] == "session_start":
            subtitle = f"cut for {d['learner_id'].removeprefix('learner_')}"
            break
    ls = lanes(events)
    progress = None
    if kind == "ingest":
        stages = [e["data"] for e in events if e["kind"] == "ingest_stage"]
        done = {s["stage"] for s in stages if s["status"] == "done"}
        current = next((s["stage"] for s in reversed(stages) if s["status"] in ("started", "progress")
                        and s["stage"] not in done), None)
        total = len(STAGE_AGENT) - 1 - (0 if any(s["stage"] == "download" for s in stages) else 1)  # link ingests download
        progress = {"done": len(done), "total": total, "current": current}
    return {
        "run_id": f"{channel}~{first['id']}", "channel": channel, "kind": kind, "video_id": vid,
        "title": titles.get(vid or "", "") or subtitle or channel, "subtitle": subtitle, "status": status,
        "started": first["ts"], "ended": last["ts"], "duration_s": round(_ts(last) - _ts(first), 1),
        "first_id": first["id"], "last_id": last["id"], "agents": [ln["agent"] for ln in ls],
        "calls": sum(len(ln["spans"]) for ln in ls), "notes": sum(ln["notes"] for ln in ls), "progress": progress,
        "error": terminal["data"].get("message") if terminal is not None and terminal["kind"] == "error" else None,
    }


# ---------------------------------------------------------------- data access

_titles: dict[str, Any] = {"mtime": -1.0, "map": {}}


def video_titles(data: Path) -> dict[str, str]:
    """video_id -> title, re-read only when a graph file changes (graphs are large)."""
    d = data / "graphs"
    files = sorted(d.glob("*.json")) if d.exists() else []
    mtime = max((p.stat().st_mtime for p in files), default=0.0) + len(files)
    if mtime != _titles["mtime"]:
        out = {}
        for p in files:
            head = p.read_text(encoding="utf-8")[:4000]
            m = re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', head)
            out[p.stem] = json.loads(f'"{m.group(1)}"') if m else p.stem
        _titles.update(mtime=mtime, map=out)
    return dict(_titles["map"])


def _rows(rows: list[Any]) -> list[dict[str, Any]]:
    return [{"id": r["id"], "channel": r["channel"], "kind": r["kind"], "data": json.loads(r["payload"]),
             "ts": r["ts"]} for r in rows]


def _all_events(state: GatewayState) -> list[dict[str, Any]]:
    return _rows(state.store.query(
        "SELECT id, channel, kind, payload, ts FROM events WHERE channel != 'system' AND channel NOT LIKE 'system_%' "
        "ORDER BY id"))


def _channel_events(state: GatewayState, channel: str, first: int) -> list[dict[str, Any]]:
    return _rows(state.store.query(
        "SELECT id, channel, kind, payload, ts FROM events WHERE channel = ? AND id >= ? ORDER BY id",
        (channel, first)))


def _live(state: GatewayState) -> set[str]:
    from loom.gateway.routes import app_api

    return {c for c, t in {**app_api._ingesting, **app_api._rendering}.items() if not t.done()}


def all_runs(state: GatewayState) -> list[dict[str, Any]]:
    by_channel: dict[str, list[dict[str, Any]]] = {}
    for e in _all_events(state):
        by_channel.setdefault(e["channel"], []).append(e)
    titles, now, live = video_titles(state.cfg.data_dir), time.time(), _live(state)
    out = []
    for ch, evs in by_channel.items():
        parts = split_runs(ch, evs)
        for i, run in enumerate(parts):
            s = summarize(ch, run, titles, now, live if i == len(parts) - 1 else set())
            if s["status"] == "running" and i < len(parts) - 1:
                s["status"] = "interrupted"
            out.append(s)
    out.sort(key=lambda r: r["first_id"], reverse=True)
    return out


@router.get("/api/runs")
def runs(active: bool = False, kind: str | None = None, channel: str | None = None, limit: int = 80,
         state: GatewayState = Depends(get_state)) -> list[dict[str, Any]]:
    out = [r for r in all_runs(state) if (not active or r["status"] == "running") and (not kind or r["kind"] == kind)
           and (not channel or r["channel"] == channel)]
    return out[:max(1, min(limit, 500))]


@router.get("/api/runs/{run_id}")
def run(run_id: str, state: GatewayState = Depends(get_state)) -> dict[str, Any]:
    m = RUN_ID.match(run_id)
    if not m:
        raise HTTPException(400, "bad run id")
    channel, first = m.group("channel"), int(m.group("first"))
    evs = _channel_events(state, channel, first)
    parts = split_runs(channel, evs)
    if not parts or parts[0][0]["id"] != first:
        raise HTTPException(404, "no such run")
    events = parts[0]
    live = _live(state) if len(parts) == 1 else set()
    summary = summarize(channel, events, video_titles(state.cfg.data_dir), time.time(), live)
    return {"summary": summary, "lanes": lanes(events), "events": events}
