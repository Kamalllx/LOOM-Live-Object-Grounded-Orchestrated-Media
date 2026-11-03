from __future__ import annotations

import ast

import pytest
from pydantic import ValidationError

from loom.agents.animator import check_code
from loom.agents.scene_dsl import ScenePlan, compile_plan

PLAN = {
    "title": "How H⁺ and OH⁻ make water",
    "takeaway": "Acid + base → salt + water",
    "beats": [
        {"narration": "An acid releases hydrogen ions in water.",
         "elements": [{"id": "h", "kind": "circle", "label": "H⁺", "color": "red", "x": -3, "y": 1}]},
        {"narration": "A base releases hydroxide ions in water.",
         "elements": [{"id": "oh", "kind": "circle", "label": "OH⁻", "color": "blue", "x": 3, "y": 1},
                      {"id": "a", "kind": "arrow", "x": -1, "y": -1, "to_x": 1, "to_y": -1}],
         "actions": [{"kind": "connect", "ids": ["h", "oh"]}]},
        {"narration": "Each hydrogen ion joins a hydroxide ion to form water.",
         "actions": [{"kind": "merge", "ids": ["h", "oh"], "label": "H₂O", "color": "teal", "x": 0, "y": 1},
                     {"kind": "highlight", "ids": ["missing_id"]}, {"kind": "fade", "ids": ["a"]}]},
    ],
}


def test_compiled_plan_parses_and_passes_the_safety_gate() -> None:
    code = compile_plan(ScenePlan.model_validate(PLAN))
    ast.parse(code)
    check_code(code, 400)
    assert code.count("# beat") == 3 and "class Explainer(Scene)" in code


def test_positions_are_clamped_inside_the_frame() -> None:
    plan = dict(PLAN, beats=[dict(PLAN["beats"][0], elements=[{"id": "x", "label": "far", "x": 99, "y": -99}])] * 3)
    code = compile_plan(ScenePlan.model_validate(plan))
    assert "5.6, -2.1" in code and "99" not in code.replace("beat", "")


def test_unknown_colour_falls_back_and_untrusted_text_is_quoted() -> None:
    plan = dict(PLAN, title='x"); import os #', beats=[dict(b, elements=[]) for b in PLAN["beats"]])
    code = compile_plan(ScenePlan.model_validate(plan))
    ast.parse(code)
    check_code(code, 400)  # the injected text stays inside a string literal


def test_plan_needs_three_beats() -> None:
    with pytest.raises(ValidationError):
        ScenePlan.model_validate(dict(PLAN, beats=PLAN["beats"][:2]))


def test_layout_solver_keeps_shapes_apart() -> None:
    from loom.agents.scene_dsl import MIN_GAP, free_spot

    taken = {"a": (0.0, 0.0)}
    x, y = free_spot(0.0, 0.0, taken)
    assert ((x - 0) ** 2 + (y - 0) ** 2) ** 0.5 >= MIN_GAP
    assert free_spot(0.0, 0.0, taken, me="a") == (0.0, 0.0)  # moving itself is fine
