"""`loom contracts export`: Pydantic -> JSON Schema files -> TypeScript types (spec/05 header, rule 4 of CLAUDE.md).

Writes `contracts/<name>.schema.json` per top-level contract, plus one bundle schema with shared `$defs` that
`packages/contracts-ts/scripts/generate.mjs` compiles into `packages/contracts-ts/src/index.ts`.
`--check` regenerates in memory and fails if anything on disk is stale.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pydantic.json_schema import models_json_schema

from loom.core.config import PROJECT_ROOT
from loom.core.contracts import EXPORTED
from loom.core.contracts.common import SCHEMA_VERSION

CONTRACTS_DIR = PROJECT_ROOT / "contracts"
TS_DIR = PROJECT_ROOT / "packages" / "contracts-ts"
BUNDLE = "loom.bundle.schema.json"


def _dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _strip_titles(node: Any, keep: bool = False) -> Any:
    """Drop Pydantic's per-property titles so TS gets inline types instead of `Options2`-style aliases."""
    if isinstance(node, dict):
        out = {k: _strip_titles(v) for k, v in node.items() if keep or k != "title" or not isinstance(v, str)}
        if "$defs" in node:
            out["$defs"] = {name: _strip_titles(d, keep=True) for name, d in node["$defs"].items()}
        return out
    if isinstance(node, list):
        return [_strip_titles(v) for v in node]
    return node


def build_schemas() -> dict[str, str]:
    """Return {filename: content} for every schema file."""
    out: dict[str, str] = {}
    for name, model in EXPORTED.items():
        schema = model.model_json_schema(by_alias=True)
        schema["$id"] = f"https://loom.local/contracts/{name}.schema.json"
        schema["x-loom-schema-version"] = SCHEMA_VERSION
        out[f"{name}.schema.json"] = _dumps(schema)

    _, defs = models_json_schema([(m, "validation") for m in EXPORTED.values()], by_alias=True)
    bundle: dict[str, Any] = {
        "$id": "https://loom.local/contracts/loom.bundle.schema.json",
        "title": "LoomContracts",
        "x-loom-schema-version": SCHEMA_VERSION,
        "type": "object",
        "additionalProperties": False,
        "properties": {m.__name__: {"$ref": f"#/$defs/{m.__name__}"} for m in EXPORTED.values()},
        "$defs": defs.get("$defs", {}),
    }
    out[BUNDLE] = _dumps(_strip_titles(bundle, keep=True))
    return out


def _generate_ts(bundle_path: Path) -> str:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is not on PATH; needed to generate TypeScript types")
    if not (TS_DIR / "node_modules").exists():
        raise RuntimeError(f"run `npm install` in {TS_DIR} first")
    res = subprocess.run(
        [node, str(TS_DIR / "scripts" / "generate.mjs"), str(bundle_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(f"TypeScript generation failed: {res.stderr.strip()}")
    return res.stdout


def export(check: bool = False) -> list[str]:
    """Write (or, with check=True, compare) all generated files. Returns the list of stale/changed paths."""
    files = {CONTRACTS_DIR / name: content for name, content in build_schemas().items()}
    changed: list[str] = []
    if not check:
        CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
        for stale in CONTRACTS_DIR.glob("*.schema.json"):
            if stale not in files:
                stale.unlink()
                changed.append(str(stale))
    for path, content in files.items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current != content:
            changed.append(str(path.relative_to(PROJECT_ROOT)))
            if not check:
                path.write_text(content, encoding="utf-8", newline="\n")

    ts_path = TS_DIR / "src" / "index.ts"
    if check:
        tmp = TS_DIR / ".bundle-check.json"
        tmp.write_text(files[CONTRACTS_DIR / BUNDLE], encoding="utf-8", newline="\n")
        try:
            ts = _generate_ts(tmp)
        finally:
            tmp.unlink(missing_ok=True)
    else:
        ts = _generate_ts(CONTRACTS_DIR / BUNDLE)
    current_ts = ts_path.read_text(encoding="utf-8") if ts_path.exists() else None
    if current_ts != ts:
        changed.append(str(ts_path.relative_to(PROJECT_ROOT)))
        if not check:
            ts_path.parent.mkdir(parents=True, exist_ok=True)
            ts_path.write_text(ts, encoding="utf-8", newline="\n")
    return changed
