"""Scene plans -> valid Manim code (FR-GEN-01, reliability fix).

A local 9B model invents Manim APIs when it writes free-form code (S1 finding: 4/4 drafts failed on calls such as
`VGroup.clear`, `CENTER`, `Mobject + Mobject`). Instead the `brain` writes a *scene plan*: beats with labelled
shapes, positions and a small set of actions, plus one narrated sentence per beat. This module compiles the plan into
Manim code that only uses known-good calls, so rendering is deterministic; the plan stays agent-authored and every
narrated line is still fact-checked.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import Field

from loom.core.contracts.common import Contract

COLORS = {"blue": "BLUE", "red": "RED", "green": "GREEN", "yellow": "YELLOW", "white": "WHITE", "teal": "TEAL",
          "orange": "ORANGE", "purple": "PURPLE", "pink": "PINK", "grey": "GREY", "gray": "GREY"}


class Element(Contract):
    id: str = Field(min_length=1, max_length=24)
    kind: Literal["circle", "box", "pill", "text", "arrow", "image"] = "circle"
    label: str = Field("", max_length=28)
    color: str = "blue"
    x: float = 0.0
    y: float = 0.0
    size: Literal["s", "m", "l"] = "m"
    to_x: float | None = None  # arrows only: end point
    to_y: float | None = None
    image: str | None = Field(None, max_length=24)  # images only: a visual id offered to the planner


class Action(Contract):
    kind: Literal["appear", "move", "merge", "split", "transform", "highlight", "fade", "connect"]
    ids: list[str] = Field(min_length=1, max_length=6)
    x: float | None = None
    y: float | None = None
    label: str | None = Field(None, max_length=28)  # merge/transform: the resulting label
    color: str | None = None


class Beat(Contract):
    narration: str = Field(min_length=8, max_length=220)
    elements: list[Element] = Field(default=[], max_length=8)
    actions: list[Action] = Field(default=[], max_length=6)


class ScenePlan(Contract):
    title: str = Field(min_length=2, max_length=48)
    beats: list[Beat] = Field(min_length=3, max_length=14)
    takeaway: str = Field("", max_length=90)

    @property
    def storyboard(self) -> list[str]:
        return [b.narration for b in self.beats]


def _c(name: str | None) -> str:
    return COLORS.get((name or "blue").lower().strip(), "BLUE")


def _xy(x: float | None, y: float | None) -> tuple[float, float]:
    return (max(-5.6, min(5.6, float(x or 0.0))), max(-2.1, min(2.0, float(y or 0.0))))


MIN_GAP = 2.2
SLOTS = [(0, 0), (2.4, 0), (-2.4, 0), (0, -1.9), (0, 1.9), (4.8, 0), (-4.8, 0), (2.4, -1.9), (-2.4, -1.9),
         (2.4, 1.9), (-2.4, 1.9), (4.8, -1.9), (-4.8, -1.9)]


def free_spot(x: float, y: float, taken: dict[str, tuple[float, float]], me: str | None = None) -> tuple[float, float]:
    """Nearest position to (x, y) that keeps MIN_GAP from every other visible shape (compile-time layout)."""
    others = [p for k, p in taken.items() if k != me]
    best = _xy(x, y)
    for dx, dy in SLOTS:
        cx, cy = _xy(x + dx, y + dy)
        if all(((cx - ox) ** 2 + (cy - oy) ** 2) ** 0.5 >= MIN_GAP for ox, oy in others):
            return (round(cx, 2), round(cy, 2))
    return best


def _s(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def compile_plan(plan: ScenePlan, seconds_per_word: float = 0.42) -> str:
    """ScenePlan -> Manim source. Only Text/Circle/RoundedRectangle/Arrow/VGroup and standard animations are used."""
    radius = {"s": 0.55, "m": 0.85, "l": 1.15}
    out = [
        "from manim import *",
        "",
        "",
        "def _shape(kind, label, color, x, y, size):",
        "    r = {'s': 0.55, 'm': 0.85, 'l': 1.15}[size]",
        "    if kind == 'circle':",
        "        body = Circle(radius=r, color=color, fill_opacity=0.35, stroke_width=4)",
        "    elif kind == 'box':",
        "        body = RoundedRectangle(corner_radius=0.2, width=2.6 * r, height=1.6 * r, color=color, fill_opacity=0.3, stroke_width=4)",
        "    elif kind == 'pill':",
        "        body = RoundedRectangle(corner_radius=0.5 * r, width=3.0 * r, height=1.0 * r, color=color, fill_opacity=0.3, stroke_width=4)",
        "    else:",
        "        body = None",
        "    if body is None:",
        "        g = VGroup(Text(label or ' ', font_size=34, color=color))",
        "    else:",
        "        t = Text(label or ' ', font_size=30, color=WHITE)",
        "        if t.width > body.width * 0.86:",
        "            t.scale_to_fit_width(body.width * 0.86)",
        "        g = VGroup(body, t)",
        "    g.move_to([x, y, 0])",
        "    return g",
        "",
        "",
        "class Explainer(Scene):",
        "    def construct(self):",
        f"        title = Text({_s(plan.title)}, font_size=40).to_edge(UP)",
        "        if title.width > 12.5:",
        "            title.scale_to_fit_width(12.5)",
        "        self.play(Write(title), run_time=1.0)",
        "        caption = Text(' ', font_size=26).to_edge(DOWN)",
        "        live = {}",
    ]
    del radius
    pos: dict[str, tuple[float, float]] = {}
    for n, beat in enumerate(plan.beats, start=1):
        words = max(6, len(beat.narration.split()))
        hold = round(max(2.5, words * seconds_per_word), 2)
        out.append(f"        # beat {n}")
        cap = beat.narration if len(beat.narration) <= 90 else beat.narration[:87] + "..."
        out += [
            f"        new_caption = Text({_s(cap)}, font_size=24).to_edge(DOWN)",
            "        if new_caption.width > 12.8:",
            "            new_caption.scale_to_fit_width(12.8)",
            "        self.play(ReplacementTransform(caption, new_caption), run_time=0.5)",
            "        caption = new_caption",
        ]
        spent = 0.5
        for el in beat.elements:
            x, y = _xy(el.x, el.y)
            if el.kind == "arrow":
                tx, ty = _xy(el.to_x if el.to_x is not None else x + 2, el.to_y if el.to_y is not None else y)
                out += [f"        live[{_s(el.id)}] = Arrow([{x}, {y}, 0], [{tx}, {ty}, 0], buff=0.1, color={_c(el.color)}, stroke_width=6)",
                        f"        self.play(GrowArrow(live[{_s(el.id)}]), run_time=0.6)"]
            else:
                pos.pop(el.id, None)
                x, y = free_spot(x, y, pos)
                pos[el.id] = (x, y)
                out += [f"        if {_s(el.id)} in live:",
                        f"            self.play(FadeOut(live.pop({_s(el.id)})), run_time=0.2)",
                        f"        live[{_s(el.id)}] = _shape({_s(el.kind)}, {_s(el.label)}, {_c(el.color)}, {x}, {y}, {_s(el.size)})",
                        f"        self.play(GrowFromCenter(live[{_s(el.id)}]), run_time=0.6)"]
            spent += 0.6
        for act in beat.actions:
            ids = [i for i in act.ids]
            refs = ", ".join(f"live[{_s(i)}]" for i in ids)
            have = " and ".join(f"{_s(i)} in live" for i in ids)
            x, y = _xy(act.x, act.y)
            if act.kind == "appear":
                out += [f"        if {have}:", f"            self.play(*[Indicate(m) for m in [{refs}]], run_time=0.8)"]
            elif act.kind == "move":
                # moves keep their target: bringing things together is the point of many beats
                for i in ids:
                    if i in pos:
                        pos[i] = (x, y)
                out += [f"        if {have}:", f"            self.play(*[m.animate.move_to([{x}, {y}, 0]) for m in [{refs}]], run_time=1.2)"]
            elif act.kind == "highlight":
                out += [f"        if {have}:", f"            self.play(*[Circumscribe(m, color=YELLOW) for m in [{refs}]], run_time=1.0)"]
            elif act.kind == "fade":
                for i in ids:
                    pos.pop(i, None)
                out += [f"        if {have}:", f"            self.play(*[FadeOut(live.pop(i)) for i in {json.dumps(ids)}], run_time=0.6)"]
            elif act.kind in ("merge", "transform", "split", "connect"):
                label = act.label or (ids[0] if act.kind != "connect" else "")
                if act.kind == "connect" and len(ids) >= 2:
                    a, b = ids[0], ids[1]
                    out += [f"        if {_s(a)} in live and {_s(b)} in live:",
                            f"            _arr = Arrow(live[{_s(a)}].get_center(), live[{_s(b)}].get_center(), buff=0.9, color={_c(act.color)}, stroke_width=6)",
                            "            self.play(GrowArrow(_arr), run_time=0.8)",
                            f"            live[{_s(a + '_to_' + b)}] = _arr"]
                else:
                    for i in ids:
                        pos.pop(i, None)
                    x, y = free_spot(x, y, pos)
                    pos[ids[0]] = (x, y)
                    out += [f"        if {have}:",
                            f"            _target = _shape('circle', {_s(label)}, {_c(act.color)}, {x}, {y}, 'l')",
                            f"            self.play(*[m.animate.move_to([{x}, {y}, 0]) for m in [{refs}]], run_time=1.0)",
                            f"            self.play(*[FadeOut(live.pop(i)) for i in {json.dumps(ids)}], GrowFromCenter(_target), run_time=0.9)",
                            f"            live[{_s(ids[0])}] = _target"]
            spent += 1.2
        out.append(f"        self.wait({round(max(0.8, hold - spent), 2)})")
    take = plan.takeaway or plan.beats[-1].narration
    out += [
        "        if live:",
        "            self.play(*[FadeOut(m) for m in live.values()], run_time=0.8)",
        f"        final = Text({_s(take[:90])}, font_size=32, color=YELLOW)",
        "        if final.width > 12.5:",
        "            final.scale_to_fit_width(12.5)",
        "        self.play(FadeOut(caption), Write(final), run_time=1.2)",
        "        self.wait(2.5)",
    ]
    return "\n".join(out) + "\n"
