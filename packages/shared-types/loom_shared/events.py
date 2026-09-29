"""In-process event bus: agents publish progress, the web player streams it over SSE."""
import json
import threading
import time
from collections import defaultdict

from .config import SESSIONS_DIR

_events = defaultdict(list)
_cond = threading.Condition()


def publish(session_id, kind, **data):
    ev = {"t": round(time.time(), 3), "kind": kind, **data}
    with _cond:
        _events[session_id].append(ev)
        _cond.notify_all()
    d = SESSIONS_DIR / session_id
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "events.jsonl", "a") as f:
        f.write(json.dumps(ev) + "\n")
    return ev


def since(session_id, index, timeout=15.0):
    """Block until there are events after `index` (or timeout); returns the new events."""
    with _cond:
        if len(_events[session_id]) <= index:
            _cond.wait(timeout)
        return _events[session_id][index:]
