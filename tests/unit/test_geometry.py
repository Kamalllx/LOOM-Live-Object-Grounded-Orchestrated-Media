"""Construction explainers: the planner names the steps, LOOM computes them exactly (loom/agents/geometry.py)."""

from __future__ import annotations

import math

from loom.agents.geometry import ConstructionPlan, is_construction, resolve


def _plan(beats: list[dict]) -> ConstructionPlan:
    return ConstructionPlan.model_validate({"title": "Construction", "beats": beats})


ANGLE = {"narration": "Start with an angle ABC whose vertex is B.", "steps": [
    {"id": "B", "kind": "point", "x": 0, "y": 0}, {"id": "A", "kind": "point", "x": 1, "y": 3},
    {"id": "C", "kind": "point", "x": 4, "y": 0}, {"id": "BA", "kind": "ray", "a": "B", "b": "A"},
    {"id": "BC", "kind": "ray", "a": "B", "b": "C"}]}
ARC = {"narration": "Draw an arc from B that crosses both rays.", "steps": [
    {"id": "arc1", "kind": "arc", "a": "B", "radius": 2, "of": ["BA", "BC"]},
    {"id": "D", "kind": "intersect", "of": ["arc1", "BA"]}, {"id": "E", "kind": "intersect", "of": ["arc1", "BC"]}]}


def _angle(p: list[float], q: list[float]) -> float:
    return math.atan2(q[1] - p[1], q[0] - p[0])


def _by_id(draw: list[list[dict]]) -> dict[str, dict]:
    return {d["id"]: d for beat in draw for d in beat}


def test_angle_bisector_is_exact_even_when_the_planner_opens_the_compass_too_little() -> None:
    small = {"narration": "Draw two small arcs from D and E and join B to where they cross.", "steps": [
        {"id": "arcD", "kind": "arc", "a": "D", "radius": 0.3}, {"id": "arcE", "kind": "arc", "a": "E", "radius": 0.3},
        {"id": "F", "kind": "intersect", "of": ["arcD", "arcE"]}, {"id": "BF", "kind": "ray", "a": "B", "b": "F"}]}
    draw, errors = resolve(_plan([ANGLE, ARC, small]))
    assert errors == []
    d = _by_id(draw)
    b, a, c, f = d["B"]["p"], d["A"]["p"], d["C"]["p"], d["F"]["p"]
    assert abs((_angle(b, f) - _angle(b, c)) - (_angle(b, a) - _angle(b, f))) < 2e-3  # two equal halves
    assert d["arcD"]["r"] == d["arcE"]["r"]  # same compass opening for both
    # D really lies on ray BA, at the first arc's radius from B
    assert abs(math.dist(b, d["D"]["p"]) - d["arc1"]["r"]) < 2e-3


def test_points_are_computed_not_guessed_and_bad_references_are_reported() -> None:
    bad = {"narration": "Join B to a point that was never drawn.", "steps": [
        {"id": "cX", "kind": "circle", "a": "X", "radius": 1}, {"id": "Y", "kind": "intersect", "of": ["arc1", "nope"]}]}
    _, errors = resolve(_plan([ANGLE, ARC, bad]))
    assert len(errors) == 2 and "'X'" in errors[0] and "'nope'" in errors[1]


def test_unplaced_arms_of_the_given_angle_are_placed_apart() -> None:
    given = {"narration": "We start with an angle ABC whose vertex is B.", "steps": [
        {"id": "B", "kind": "point", "x": 0, "y": 0}, {"id": "BA", "kind": "ray", "a": "B", "b": "A"},
        {"id": "BC", "kind": "ray", "a": "B", "b": "C"}]}
    draw, errors = resolve(_plan([given, ARC, {"narration": "Both crossings are equally far from B.", "steps": []}]))
    assert errors == []
    d = _by_id(draw)
    assert abs(_angle(d["B"]["p"], d["BA"]["q"]) - _angle(d["B"]["p"], d["BC"]["q"])) > 0.5  # a real angle


def test_side_picks_which_of_two_crossings() -> None:
    seg = {"narration": "Take a segment PQ and draw equal arcs from both ends.", "steps": [
        {"id": "P", "kind": "point", "x": -3, "y": 0}, {"id": "Q", "kind": "point", "x": 3, "y": 0},
        {"id": "aP", "kind": "arc", "a": "P", "radius": 4}, {"id": "aQ", "kind": "arc", "a": "Q", "radius": 4},
        {"id": "X", "kind": "intersect", "of": ["aP", "aQ"], "side": "up"},
        {"id": "Y", "kind": "intersect", "of": ["aP", "aQ"], "side": "down"}]}
    rest = {"narration": "The line through both crossings halves PQ at a right angle.", "steps": [
        {"id": "PQ", "kind": "segment", "a": "P", "b": "Q"}, {"id": "XY", "kind": "line", "a": "X", "b": "Y"},
        {"id": "M", "kind": "intersect", "of": ["XY", "PQ"]}]}
    draw, errors = resolve(_plan([seg, rest, {"narration": "That is the perpendicular bisector.", "steps": []}]))
    assert errors == []
    d = _by_id(draw)
    assert d["X"]["p"][1] > d["Y"]["p"][1]
    m, p, q = d["M"]["p"], d["P"]["p"], d["Q"]["p"]
    assert abs(math.dist(m, p) - math.dist(m, q)) < 2e-3  # the midpoint


def test_arcs_are_drawn_through_their_crossings_and_fit_the_stage() -> None:
    draw, _ = resolve(_plan([ANGLE, ARC, {"narration": "These two points are equally far from B.", "steps": []}]))
    d = _by_id(draw)
    arc = d["arc1"]
    for pid in ("D", "E"):
        a = _angle(arc["c"], d[pid]["p"]) % (2 * math.pi)
        lo, hi = arc["a0"] % (2 * math.pi), arc["a0"] % (2 * math.pi) + (arc["a1"] - arc["a0"])
        assert lo <= a <= hi or lo <= a + 2 * math.pi <= hi
    xs = [v["p"][0] for v in d.values() if "p" in v]
    assert max(abs(x) for x in xs) <= 5.7


def test_router_sends_constructions_to_the_geometry_planner() -> None:
    assert is_construction("Explain the angle bisector construction arc step by step")
    assert is_construction("how do I bisect a line segment")
    assert is_construction("why is the radius perpendicular to the tangent")
    assert not is_construction("what does chlorophyll do in photosynthesis")
    assert not is_construction("explain merge sort")


def test_a_straight_given_angle_is_opened_and_arcs_that_only_touch_at_the_vertex_are_widened() -> None:
    """The planner put A and C opposite each other and opened the compass to exactly |BD|: F used to land on B."""
    given = {"narration": "We start with an angle formed by rays BA and BC meeting at vertex B.", "steps": [
        {"id": "B", "kind": "point", "x": 0, "y": 0}, {"id": "A", "kind": "point", "x": -4, "y": 3},
        {"id": "C", "kind": "point", "x": 4, "y": -3}, {"id": "BA", "kind": "ray", "a": "B", "b": "A"},
        {"id": "BC", "kind": "ray", "a": "B", "b": "C"}]}
    arcs = {"narration": "Draw equal arcs from D and E and join B to where they cross.", "steps": [
        {"id": "arc1", "kind": "arc", "a": "B", "radius": 3.5, "of": ["BA", "BC"]},
        {"id": "D", "kind": "intersect", "of": ["arc1", "BA"]}, {"id": "E", "kind": "intersect", "of": ["arc1", "BC"]},
        {"id": "aD", "kind": "arc", "a": "D", "radius": 3.5, "of": ["BC"]},
        {"id": "aE", "kind": "arc", "a": "E", "radius": 3.5, "of": ["BC"]},
        {"id": "F", "kind": "intersect", "of": ["aD", "aE"], "side": "up"}]}
    ray = {"narration": "The ray from B through F bisects the angle.", "steps": [{"id": "BF", "kind": "ray", "a": "B", "b": "F"}]}
    draw, errors = resolve(_plan([given, arcs, ray]))
    assert errors == []
    d = _by_id(draw)
    b, a, c, f = d["B"]["p"], d["A"]["p"], d["C"]["p"], d["F"]["p"]
    assert math.dist(b, f) > 0.5
    assert abs((_angle(b, f) - _angle(b, c)) % (2 * math.pi) - (_angle(b, a) - _angle(b, f)) % (2 * math.pi)) < 2e-3
