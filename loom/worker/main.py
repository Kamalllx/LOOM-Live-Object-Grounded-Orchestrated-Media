"""`python -m loom.worker` — spawned per job by the gateway so CUDA memory is released when it exits.

Stage 0 provides the process contract and `--selftest` (used by `/api/ready` and `loom doctor` to prove a worker can
be spawned). Perception and render stages register here in Stages 1 and 4.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="loom.worker")
    ap.add_argument("--selftest", action="store_true", help="print a JSON health line and exit 0")
    args = ap.parse_args(argv)
    if args.selftest:
        print(
            json.dumps(
                {
                    "ok": True,
                    "pid": os.getpid(),
                    "python": platform.python_version(),
                    "executable": sys.executable,
                    "offline": os.environ.get("HF_HUB_OFFLINE") == "1",
                }
            )
        )
        return 0
    ap.print_usage(sys.stderr)
    print("loom.worker: no stage given (stages are added in Stage 1/4)", file=sys.stderr)
    return 2
