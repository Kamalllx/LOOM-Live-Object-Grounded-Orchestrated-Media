"""Validation against the shared contract, plus a stricter check of item shapes.

The repo contract (contracts/concept-graph.schema.json) only pins the top level; the item
shapes other teams build against are the ones in fixtures/concept-graph.sample.json.
ITEM_SCHEMA encodes those shapes so our output can never drift from the sample.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import jsonschema

_span = {"type": "object", "required": ["start", "end"], "properties": {"start": {"type": "number"}, "end": {"type": "number"}}}

ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "objects": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["object_id", "label", "confidence", "instances"],
                "properties": {
                    "object_id": {"type": "string", "pattern": "^obj_[0-9]{3,}$"},
                    "label": {"type": "string", "minLength": 1},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "instances": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["start", "end", "bbox"],
                            "properties": {
                                "start": {"type": "number"},
                                "end": {"type": "number"},
                                "bbox": {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "number", "minimum": 0, "maximum": 1}},
                            },
                        },
                    },
                },
            },
        },
        "transcript": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["start", "end", "speaker", "text"],
                "properties": {"start": {"type": "number"}, "end": {"type": "number"}, "speaker": {"type": "string"}, "text": {"type": "string"}},
            },
        },
        "on_screen_text": {
            "type": "array",
            "items": {"type": "object", "required": ["start", "end", "text"], "properties": {"start": {"type": "number"}, "end": {"type": "number"}, "text": {"type": "string"}}},
        },
        "concept_nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["node_id", "object_ids", "transcript_refs", "on_screen_text_refs", "label"],
                "properties": {
                    "node_id": {"type": "string", "pattern": "^c_[0-9]{2,}$"},
                    "object_ids": {"type": "array", "items": {"type": "string"}},
                    "transcript_refs": {"type": "array", "items": _span},
                    "on_screen_text_refs": {"type": "array", "items": _span},
                    "label": {"type": "string", "minLength": 1},
                },
            },
        },
    },
}


def find_contracts_dir() -> Path:
    env = os.environ.get("LOOM_CONTRACTS_DIR")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "contracts" / "concept-graph.schema.json"
        if candidate.is_file():
            return candidate.parent
    raise FileNotFoundError("contracts/concept-graph.schema.json not found; set LOOM_CONTRACTS_DIR")


def contract_schema() -> dict:
    # utf-8-sig: the shared contract files are saved with a byte-order mark.
    return json.loads((find_contracts_dir() / "concept-graph.schema.json").read_text(encoding="utf-8-sig"))


def validate(graph: dict) -> list[str]:
    """Returns a list of problems; empty means valid against the contract and the sample's item shapes."""
    errors = [f"contract: {e.message}" for e in jsonschema.Draft7Validator(contract_schema()).iter_errors(graph)]
    errors += [f"{'/'.join(map(str, e.path))}: {e.message}" for e in jsonschema.Draft7Validator(ITEM_SCHEMA).iter_errors(graph)]
    errors += _referential_errors(graph)
    return errors


def _referential_errors(graph: dict) -> list[str]:
    errs = []
    ids = {o["object_id"] for o in graph.get("objects", [])}
    for n in graph.get("concept_nodes", []):
        for oid in n.get("object_ids", []):
            if oid not in ids:
                errs.append(f"concept node {n.get('node_id')} references unknown object {oid}")
    for key in ("objects", "transcript", "on_screen_text"):
        for item in graph.get(key, []):
            spans = item.get("instances", [item]) if key == "objects" else [item]
            for s in spans:
                if s["end"] < s["start"]:
                    errs.append(f"{key}: span ends before it starts ({s['start']} > {s['end']})")
    return errs
