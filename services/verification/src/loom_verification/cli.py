"""Command line: verify a candidate cut, validate a verified cut, render one explainer, or run the service."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import Config, load_dotenv_if_present
from .contracts import read_json, validate_verified


def main(argv: list[str] | None = None) -> None:
    load_dotenv_if_present()
    parser = argparse.ArgumentParser(prog="loom-verification",
                                     description="LOOM verification: candidate-cut.json -> verified-cut.json")
    parser.add_argument("--no-llm", action="store_true", help="use the deterministic fallbacks only")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ver = sub.add_parser("verify", help="run the bounded loop on one candidate-cut.json")
    ver.add_argument("candidate", type=Path)
    ver.add_argument("-o", "--out", type=Path, help="where to write verified-cut.json (default: stdout)")
    ver.add_argument("--graph", type=Path, help="concept-graph.json to use instead of looking it up by video_id")
    ver.add_argument("--profile", type=Path, help="learner-profile.json to use instead of looking it up")

    val = sub.add_parser("validate", help="check a verified-cut.json against Contract C and the sample's item shapes")
    val.add_argument("verified", type=Path)
    val.add_argument("--graph", type=Path, help="also check object / concept references against this graph")

    exp = sub.add_parser("explain", help="render and fact-check one explainer")
    exp.add_argument("--video-id", required=True)
    exp.add_argument("--concept", required=True)
    exp.add_argument("--level")

    srv = sub.add_parser("serve", help="run the HTTP service")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8003)

    a = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    cfg = Config()
    if a.no_llm:
        cfg.llm_provider = "none"

    if a.cmd == "validate":
        graph = read_json(a.graph) if a.graph else None
        errs = validate_verified(read_json(a.verified), graph)
        print("\n".join(errs) if errs else f"ok: {a.verified} matches Contract C")
        sys.exit(1 if errs else 0)

    if a.cmd == "serve":
        import uvicorn

        from .service import create_app
        uvicorn.run(create_app(cfg), host=a.host, port=a.port)
        return

    from .llm import get_llm
    from .loop import Verifier
    from .sources import GraphSource

    verifier = Verifier(cfg, get_llm(cfg))
    if a.cmd == "explain":
        print(json.dumps(verifier.explain(a.video_id, a.concept, a.level), indent=2))
        return

    candidate = read_json(a.candidate)
    src = GraphSource(read_json(a.graph), base_dir=a.graph.parent) if a.graph else None
    profile = read_json(a.profile) if a.profile else None
    doc = verifier.verify(candidate, graph_source=src, profile=profile)
    text = json.dumps(doc, indent=2)
    if a.out:
        a.out.write_text(text + "\n", encoding="utf-8")
        print(f"{doc['status']} after {doc['pass_count']} pass(es) -> {a.out}", file=sys.stderr)
    else:
        print(text)
