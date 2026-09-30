import json
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

from .models import ConceptGraph, LearnerProfile


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_DIR = REPOSITORY_ROOT / "contracts"


def _load_schema(filename: str) -> dict[str, Any]:
    schema_path = CONTRACTS_DIR / filename
    # Some shared contract files were saved by Windows tools with a UTF-8 BOM.
    # utf-8-sig accepts both BOM and non-BOM JSON files.
    with schema_path.open(encoding="utf-8-sig") as schema_file:
        return json.load(schema_file)


def validate_against_contract(document: dict[str, Any], filename: str) -> None:
    schema = _load_schema(filename)
    errors = sorted(Draft7Validator(schema).iter_errors(document), key=str)
    if errors:
        messages = "; ".join(error.message for error in errors)
        raise ValueError(f"{filename} validation failed: {messages}")


def parse_concept_graph(document: dict[str, Any]) -> ConceptGraph:
    validate_against_contract(document, "concept-graph.schema.json")
    graph = ConceptGraph.model_validate(document)
    _validate_concept_references(graph)
    return graph


def parse_learner_profile(document: dict[str, Any]) -> LearnerProfile:
    validate_against_contract(document, "learner-profile.schema.json")
    return LearnerProfile.model_validate(document)


def _validate_concept_references(graph: ConceptGraph) -> None:
    object_ids = {item.object_id for item in graph.objects}
    for node in graph.concept_nodes:
        unknown_objects = set(node.object_ids) - object_ids
        if unknown_objects:
            unknown = ", ".join(sorted(unknown_objects))
            raise ValueError(
                f"Concept node {node.node_id} references unknown object IDs: {unknown}"
            )
