"""Pre-download the open-weight models of spec/03 §2.2 into the Hugging Face cache (one-time setup, needs network).

    uv run --group setup python setup/fetch_weights.py            # download
    uv run --group setup python setup/fetch_weights.py --verify   # offline check only

Only the files LOOM loads are fetched (allow-patterns), not every variant in a repo.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from loom.core.weights import WEIGHTS  # single list shared with `loom doctor`


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="check the cache only (HF offline)")
    ap.add_argument("--tries", type=int, default=5)
    args = ap.parse_args()
    if args.verify:
        os.environ["HF_HUB_OFFLINE"] = "1"
    from huggingface_hub import snapshot_download

    failed = 0
    for repo, patterns in WEIGHTS.items():
        for attempt in range(1, args.tries + 1):
            try:
                path = snapshot_download(repo_id=repo, allow_patterns=patterns)
                print(f"OK   {repo} -> {path}", flush=True)
                break
            except Exception as exc:  # network hiccups: retry with back-off, then report
                if args.verify or attempt == args.tries:
                    print(f"FAIL {repo}: {type(exc).__name__}: {exc}", flush=True)
                    failed += 1
                    break
                wait = min(60, 10 * attempt)
                print(f"     {repo}: {type(exc).__name__}, retry {attempt}/{args.tries} in {wait}s", flush=True)
                time.sleep(wait)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
