"""Our input and output line up with the team's contracts and fixtures (the integration guarantee)."""

from loom_verification.contracts import VERIFIED_ITEMS, read_json, validate_candidate, validate_verified

from .conftest import FIXTURES


def test_candidate_fixture_is_valid_input():
    assert validate_candidate(read_json(FIXTURES / "candidate-cut.sample.json")) == []


def test_verified_fixture_matches_our_output_shape():
    assert validate_verified(read_json(FIXTURES / "verified-cut.sample.json")) == []


def test_delivery_fixture_matches_our_output_shape():
    """The copy the delivery client builds against (services/delivery/web/fixtures) must also pass."""
    web = FIXTURES.parent / "services" / "delivery" / "web" / "fixtures" / "verified-cut.sample.json"
    assert validate_verified(read_json(web)) == []


def test_bad_candidate_is_rejected():
    errs = validate_candidate({"schema_version": "1.0", "session_id": "s", "video_id": "v", "learner_id": "l",
                               "threads": [{"thread_id": "t1", "start": 5.0, "end": 2.0}]})
    assert any("ends before it starts" in e for e in errs)
    assert validate_candidate({"session_id": "s"})


def test_verified_run_output_is_valid(verifier, candidate, graph_source, family_profile):
    doc = verifier.verify(candidate, graph_source=graph_source, profile=family_profile)
    assert validate_verified(doc, graph_source.graph) == []
    # everything the delivery client's types require, and the additive fields it asked for
    for key in VERIFIED_ITEMS["required"] + ["schema_version", "session_id", "status", "final_threads"]:
        assert key in doc
    assert all("label" in t and "concept_node_ids" in t for t in doc["final_threads"])
    assert all({"reason", "fallback_bbox", "mask_url"} <= set(m) for m in doc["redaction_masks"])
    assert all({"title", "anchor_seconds", "duration_seconds", "cached"} <= set(c) for c in doc["explainer_clips"])
    assert all(m["mask_url"].startswith("s3://loom-masks/") for m in doc["redaction_masks"])
    assert all(c["clip_url"].startswith("s3://loom-clips/") for c in doc["explainer_clips"])
