"""Data-driven TikZ figures for the paper (no screenshots):

* fig_construct.tex - the angle-bisector construction exactly as the solver resolved it (scene 1d1bad...), with the
  two half-angles measured from the coordinates;
* fig_cuts.tex - the three viewers' verified cuts of the demo lesson (from /api/videos/<id>/weaves, saved in
  weaves_demo.json), drawn for black-and-white print.

    uv run python paper/gen_tikz.py
"""

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).parent
SCENE = ROOT / "data" / "media" / "scenes" / "1d1bad4d9a82aca791562e79" / "scene.json"


def construct() -> str:
    items = {d["id"]: d for b in json.loads(SCENE.read_text(encoding="utf-8"))["beats"] for d in b["draw"]}
    P = lambda i: items[i]["p"]  # noqa: E731
    B, D, E, F = P("B"), P("D"), P("E"), P("F")
    ang = lambda p, q: math.atan2(q[1] - p[1], q[0] - p[0])  # noqa: E731
    a_bc, a_bf, a_ba = ang(B, items["rayBC"]["q"]), ang(B, F), ang(B, items["rayBA"]["q"])
    half1, half2 = math.degrees(a_bf - a_bc), math.degrees(a_ba - a_bf)
    out = [r"\begin{tikzpicture}[scale=0.92, line cap=round, font=\small]"]
    out.append(r"\tikzset{ray/.style={thick, -{Stealth[length=2.2mm]}}, arc/.style={thick, dashed, black!60},"
               r" pt/.style={circle, fill=black, inner sep=1.15pt}}")
    for rid, style in (("rayBA", "ray"), ("rayBC", "ray"), ("bisector", "ray, very thick")):
        p, q = items[rid]["p"], items[rid]["q"]
        out.append(rf"\draw[{style}] ({p[0]:.3f},{p[1]:.3f}) -- ({q[0]:.3f},{q[1]:.3f});")
    for aid in ("arc1", "arcD", "arcE"):
        a = items[aid]
        c, r, a0, a1 = a["c"], a["r"], math.degrees(a["a0"]), math.degrees(a["a1"])
        sx, sy = c[0] + r * math.cos(math.radians(a0)), c[1] + r * math.sin(math.radians(a0))
        out.append(rf"\draw[arc] ({sx:.3f},{sy:.3f}) arc[start angle={a0:.2f}, end angle={a1:.2f}, radius={r:.3f}];")
    # the two half-angles, measured from the solved coordinates
    for lo, hi, rad, lab in ((a_bc, a_bf, 0.75, rf"${half1:.2f}^\circ$"), (a_bf, a_ba, 1.05, rf"${half2:.2f}^\circ$")):
        sx, sy = B[0] + rad * math.cos(lo), B[1] + rad * math.sin(lo)
        mid = (lo + hi) / 2
        out.append(rf"\draw[thin] ({sx:.3f},{sy:.3f}) arc[start angle={math.degrees(lo):.2f}, end angle={math.degrees(hi):.2f}, radius={rad}];")
        lx, ly = B[0] + (rad + 0.55) * math.cos(mid), B[1] + (rad + 0.55) * math.sin(mid)
        out.append(rf"\node[font=\scriptsize] at ({lx:.3f},{ly:.3f}) {{{lab}}};")
    for pid, anchor in (("B", "south west"), ("D", "south east"), ("E", "north west"), ("F", "south east")):
        p = P(pid)
        out.append(rf"\node[pt, label={{[font=\small]{anchor.replace('south', 'below').replace('north', 'above').split()[0]} {anchor.split()[1].replace('west', 'left').replace('east', 'right')}:${pid}$}}] at ({p[0]:.3f},{p[1]:.3f}) {{}};")
    qa, qc = items["rayBA"]["q"], items["rayBC"]["q"]
    out.append(rf"\node[font=\small, above] at ({qa[0]:.3f},{qa[1]:.3f}) {{$A$}};")
    out.append(rf"\node[font=\small, right] at ({qc[0]:.3f},{qc[1]:.3f}) {{$C$}};")
    q = items["bisector"]["q"]
    out.append(rf"\node[font=\small, right] at ({q[0]:.3f},{q[1]:.3f}) {{bisector $BF$}};")
    out.append(r"\end{tikzpicture}")
    print(f"half-angles {half1:.4f} {half2:.4f}")
    return "\n".join(out)


def cuts() -> str:
    ws = json.loads((HERE / "weaves_demo.json").read_text(encoding="utf-8"))
    dur, W = 68.733, 12.6
    X = lambda t: t / dur * W  # noqa: E731
    out = [r"\begin{tikzpicture}[font=\scriptsize]"]
    out.append(r"\tikzset{keep/.style={fill=black!30, draw=black!70}, condense/.style={pattern=north east lines, draw=black!70},"
               r" expand/.style={fill=black!65, draw=black}, skipped/.style={draw=black!45, dashed},"
               r" mask/.style={pattern=crosshatch, pattern color=black!80, draw=black}}")
    for k in range(0, 70, 10):
        out.append(rf"\draw[black!15] ({X(k):.3f},0.35) -- ({X(k):.3f},-2.02); \node[black!60] at ({X(k):.3f},-2.2) {{{k}\,s}};")
    for i, w in enumerate(ws):
        y = -i * 0.9
        c = w["cut"]
        kept = sum(t["end"] - t["start"] for t in c["final_threads"])
        facts = (f"{round(100 * kept / dur)}\\% of source, {len(c['explainer_clips'])} explainers, "
                 f"{len(c['redaction_masks'])} mask{'s' if len(c['redaction_masks']) != 1 else ''}")
        out.append(rf"\node[anchor=east, align=right, font=\scriptsize\bfseries] at (-0.15,{y:.2f}) {{{w['learner'].replace('+', r'+')}}};")
        out.append(rf"\node[anchor=west, font=\tiny, black!70] at ({W + 0.15:.2f},{y:.2f}) {{{facts}}};")
        for s in c["skipped"]:
            out.append(rf"\draw[skipped] ({X(s['start']):.3f},{y - 0.17:.2f}) rectangle ({X(s['end']):.3f},{y + 0.17:.2f});")
        for t in c["final_threads"]:
            out.append(rf"\draw[{t['action']}] ({X(t['start']):.3f},{y - 0.17:.2f}) rectangle ({X(t['end']):.3f},{y + 0.17:.2f});")
        for m in c["redaction_masks"]:
            out.append(rf"\draw[mask] ({X(m['start']):.3f},{y + 0.2:.2f}) rectangle ({X(m['end']):.3f},{y + 0.32:.2f});")
        for e in c["explainer_clips"]:
            out.append(rf"\node[draw, fill=white, diamond, inner sep=1.4pt] at ({X(e['anchor_seconds']):.3f},{y + 0.26:.2f}) {{}};")
    ly = -2.75
    legend = [("keep", "kept"), ("condense", "condensed"), ("expand", "expanded"), ("skipped", "skipped"), ("mask", "masked object")]
    x = 0.0
    for style, name in legend:
        out.append(rf"\draw[{style}] ({x:.2f},{ly - 0.1:.2f}) rectangle ({x + 0.45:.2f},{ly + 0.1:.2f}); \node[anchor=west] at ({x + 0.5:.2f},{ly:.2f}) {{{name}}};")
        x += 2.0
    out.append(rf"\node[draw, fill=white, diamond, inner sep=1.4pt] at ({x + 0.2:.2f},{ly:.2f}) {{}}; \node[anchor=west] at ({x + 0.4:.2f},{ly:.2f}) {{explainer}};")
    out.append(r"\end{tikzpicture}")
    return "\n".join(out)


if __name__ == "__main__":
    (HERE / "fig_construct.tex").write_text(construct(), encoding="utf-8")
    (HERE / "fig_cuts.tex").write_text(cuts(), encoding="utf-8")
    print("ok")
