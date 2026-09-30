import json
from pathlib import Path

from app.validation import validate_against_contract


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPOSITORY_ROOT / "fixtures"


def load_fixture(filename: str) -> dict:
    with (FIXTURES_DIR / filename).open(encoding="utf-8-sig") as fixture_file:
        return json.load(fixture_file)


def test_candidate_fixture_matches_contract_b():
    candidate = load_fixture("candidate-cut.sample.json")

    validate_against_contract(candidate, "candidate-cut.schema.json")


def test_candidate_fixture_has_all_four_agent_trace_entries():
    candidate = load_fixture("candidate-cut.sample.json")
    agents = [entry["agent"] for entry in candidate["agent_trace"]]

    assert agents == ["curator", "pedagogy", "personalizer", "assessment"]


def test_candidate_fixture_references_known_concept():
    candidate = load_fixture("candidate-cut.sample.json")
    concept_ids = {"c_01"}

    for thread in candidate["threads"]:
        assert set(thread["concept_node_ids"]).issubset(concept_ids)

    for question in candidate["quiz"]:
        assert question["concept_node_id"] in concept_ids
