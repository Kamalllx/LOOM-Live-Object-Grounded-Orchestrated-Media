"""Validation against the shared contracts, plus stricter checks of the item shapes.

The repo contracts only pin the top level. The item shapes other people build against are the ones in
fixtures/*.sample.json and in the delivery client's types, so, like the perception service, we encode those
shapes here and check both our input (Contract B) and our output (Contract C) against them. The shared
contract files are never modified.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

import jsonschema

_num = {"type": "number"}
_unit = {"type": "number", "minimum": 0, "maximum": 1}
_bbox = {"type": "array", "minItems": 4, "maxItems": 4, "items": _unit}
_str_list = {"type": "array", "items": {"type": "string"}}

# Contract B as we consume it: exactly what the fixture shows, extra fields allowed.
CANDIDATE_ITEMS = {
    "type": "object",
    "properties": {
        "threads": {"type": "array", "items": {
            "type": "object", "required": ["thread_id", "start", "end"],
            "properties": {"thread_id": {"type": "string"}, "start": _num, "end": _num,
                           "concept_node_ids": _str_list, "action": {"type": "string"}}}},
        "redaction_requests": {"type": "array", "items": {
            "type": "object", "required": ["object_id"],
            "properties": {"object_id": {"type": "string"}, "reason": {"type": "string"}}}},
        "explainer_requests": {"type": "array", "items": {
            "type": "object", "required": ["concept_node_id"],
            "properties": {"concept_node_id": {"type": "string"}, "trigger": {"type": "string"}}}},
        "quiz": {"type": "array", "items": {
            "type": "object", "required": ["question", "concept_node_id"],
            "properties": {"question": {"type": "string"}, "concept_node_id": {"type": "string"},
                           "options": _str_list, "answer_index": {"type": "integer", "minimum": 0}}}},
        "agent_trace": {"type": "array", "items": {"type": "object", "required": ["agent"]}},
    },
}

# Contract C as we produce it: every field of the fixture, plus the fields the delivery client marks as
# required in its types (pass_count, critic_score, the three lists) and the additive fields it asked for
# (services/delivery/web/CONTRACT-NOTES.md).
VERIFIED_ITEMS = {
    "type": "object",
    "required": ["pass_count", "critic_score", "redaction_masks", "explainer_clips", "quiz"],
    "properties": {
        "pass_count": {"type": "integer", "minimum": 0},
        "critic_score": {"type": "object", "required": ["factuality", "coherence", "safety"],
                         "properties": {"factuality": _unit, "coherence": _unit, "safety": _unit}},
        "final_threads": {"type": "array", "items": {
            "type": "object", "required": ["thread_id", "start", "end"],
            "properties": {"thread_id": {"type": "string"}, "start": _num, "end": _num,
                           "concept_node_ids": _str_list, "label": {"type": "string"}}}},
        "redaction_masks": {"type": "array", "items": {
            "type": "object", "required": ["object_id", "mask_url", "start", "end"],
            "properties": {"object_id": {"type": "string"}, "mask_url": {"type": "string"}, "start": _num, "end": _num,
                           "reason": {"type": "string"}, "fallback_bbox": _bbox}}},
        "explainer_clips": {"type": "array", "items": {
            "type": "object", "required": ["concept_node_id", "clip_url", "cached"],
            "properties": {"concept_node_id": {"type": "string"}, "clip_url": {"type": "string"},
                           "cached": {"type": "boolean"}, "title": {"type": "string"},
                           "anchor_seconds": _num, "duration_seconds": {"type": "number", "minimum": 0}}}},
        "quiz": {"type": "array", "items": {
            "type": "object", "required": ["question", "concept_node_id"],
            "properties": {"question": {"type": "string"}, "concept_node_id": {"type": "string"},
                           "options": _str_list, "answer_index": {"type": "integer", "minimum": 0}}}},
    },
}


def find_contracts_dir() -> Path:
    env = os.environ.get("LOOM_CONTRACTS_DIR")
    if env:
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        if (parent / "contracts" / "verified-cut.schema.json").is_file():
            return parent / "contracts"
    raise FileNotFoundError("contracts/verified-cut.schema.json not found; set LOOM_CONTRACTS_DIR")


def read_json(path: Path) -> dict:
    # utf-8-sig: the shared contract and fixture files are saved with a byte-order mark.
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


@lru_cache(maxsize=None)
def contract_schema(name: str) -> dict:
    return read_json(find_contracts_dir() / f"{name}.schema.json")


def _errors(schema: dict, doc: dict, prefix: str = "") -> list[str]:
    return [f"{prefix}{'/'.join(map(str, e.path)) or '<root>'}: {e.message}"
            for e in jsonschema.Draft7Validator(schema).iter_errors(doc)]


def _span_errors(items, key: str) -> list[str]:
    return [f"{key}[{i}]: ends before it starts ({x['start']} > {x['end']})"
            for i, x in enumerate(items or []) if isinstance(x, dict) and x.get("end", 0) < x.get("start", 0)]


def validate_candidate(doc: dict) -> list[str]:
    """Problems with an incoming candidate-cut.json; empty means usable."""
    errs = _errors(contract_schema("candidate-cut"), doc, "contract: ") + _errors(CANDIDATE_ITEMS, doc)
    return errs + _span_errors(doc.get("threads"), "threads")


def validate_verified(doc: dict, graph: dict | None = None) -> list[str]:
    """Problems with an outgoing verified-cut.json; empty means it matches Contract C and the sample shapes."""
    errs = _errors(contract_schema("verified-cut"), doc, "contract: ") + _errors(VERIFIED_ITEMS, doc)
    errs += _span_errors(doc.get("final_threads"), "final_threads") + _span_errors(doc.get("redaction_masks"), "redaction_masks")
    if graph is not None:
        objects = {o["object_id"] for o in graph.get("objects", [])}
        nodes = {n["node_id"] for n in graph.get("concept_nodes", [])}
        errs += [f"redaction_masks: unknown object {m['object_id']}" for m in doc.get("redaction_masks", [])
                 if m.get("object_id") not in objects]
        errs += [f"explainer_clips: unknown concept {c['concept_node_id']}" for c in doc.get("explainer_clips", [])
                 if c.get("concept_node_id") not in nodes]
    return errs
