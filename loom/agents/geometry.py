"""Construction explainers: compass-and-straightedge geometry the planner *names* and LOOM *computes*.

A scene of glowing orbs cannot show "draw an arc from the vertex that crosses both rays": a 9B planner asked for
shapes turns every point and arc into a sphere at a guessed position. For constructions the planner instead writes
steps that refer to each other - a point, a ray from B through A, an arc centred on B with radius r that crosses both
rays, the intersection of two arcs (the one far from B) - and this module resolves them exactly, so D really lies on
the ray, both small arcs really have the same radius and the bisector really passes through their crossing. The
player draws the result on a slate with a 3-D compass and straightedge. Steps that do not resolve are reported back to
the planner (like the fact-checker's rejections), never drawn.
"""

from __future__ import annotations

import math
import re
from typing import Any, Literal

from pydantic import Field

from loom.core.contracts.common import Contract

GEOMETRY = re.compile(
    r"\b(bisect\w*|perpendicular|construct\w*|compass|straightedge|ruler and|angle\w*|arcs?|triangles?|circles?|"
    r"tangents?|chords?|radius|diameter|parallel lines?|mid-?points?|polygons?|hexagon|square|rhombus|locus|"
    r"equilateral|isosceles|circumcent\w*|incent\w*|altitude|median of)\b",
    re.I,
)

Kind = Literal[
    "point", "segment", "ray", "line", "circle", "arc", "intersect", "angle_mark", "label", "highlight", "fade"
]


class GeoStep(Contract):
    id: str = Field(min_length=1, max_length=24)
    kind: Kind
    label: str = Field("", max_length=24)
    color: str = "white"
    x: float | None = None  # point / label: position (any units; LOOM scales the drawing to the stage)
    y: float | None = None
    a: str | None = Field(None, max_length=24)  # segment/ray/line: from point a ... circle/arc: centre a
    b: str | None = Field(None, max_length=24)  # ... through point b (for a circle/arc: radius = |ab|)
    radius: float | None = None  # circle/arc: radius instead of b
    of: list[str] = Field(default=[], max_length=4)  # intersect: [curve, curve]; arc: curves it must cross;
    #                                                  angle_mark: [vertex, point, point]; highlight/fade: ids
    near: str | None = Field(None, max_length=24)  # intersect: of two candidates, the one nearer this point
    far: str | None = Field(None, max_length=24)  # ... or the one farther from this point
    side: Literal["up", "down", "left", "right"] | None = None  # ... or the upper / lower / left / right one


class GeoBeat(Contract):
    narration: str = Field(min_length=8, max_length=220)
    steps: list[GeoStep] = Field(default=[], max_length=6)


class ConstructionPlan(Contract):
    title: str = Field(min_length=2, max_length=48)
    beats: list[GeoBeat] = Field(min_length=3, max_length=14)
    takeaway: str = Field("", max_length=140)  # (90 made the model stop mid-word: "...the exact angle bis")

    @property
    def storyboard(self) -> list[str]:
        return [b.narration for b in self.beats]


def is_construction(*texts: str) -> bool:
    """A compass / straightedge / plane-geometry question: two geometry words, or one construction verb."""
    blob = " ".join(t for t in texts if t)
    hits = {m.group(0).lower() for m in GEOMETRY.finditer(blob)}
    return len(hits) >= 2 or any(h.startswith(("bisect", "construct", "perpendicular", "compass")) for h in hits)


# ---------------------------------------------------------------- exact geometry

Pt = tuple[float, float]
EPS = 1e-6


def _sub(p: Pt, q: Pt) -> Pt:
    return (p[0] - q[0], p[1] - q[1])


def _dist(p: Pt, q: Pt) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _line_line(p1: Pt, d1: Pt, p2: Pt, d2: Pt) -> list[tuple[Pt, float, float]]:
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < EPS:
        return []
    w = _sub(p2, p1)
    t = (w[0] * d2[1] - w[1] * d2[0]) / den
    u = (w[0] * d1[1] - w[1] * d1[0]) / den
    return [((p1[0] + t * d1[0], p1[1] + t * d1[1]), t, u)]


def _line_circle(p: Pt, d: Pt, c: Pt, r: float) -> list[tuple[Pt, float]]:
    f = _sub(p, c)
    A = d[0] ** 2 + d[1] ** 2
    B = 2 * (f[0] * d[0] + f[1] * d[1])
    C = f[0] ** 2 + f[1] ** 2 - r * r
    disc = B * B - 4 * A * C
    if disc < -EPS or A < EPS:
        return []
    s = math.sqrt(max(0.0, disc))
    return [((p[0] + t * d[0], p[1] + t * d[1]), t) for t in {(-B - s) / (2 * A), (-B + s) / (2 * A)}]


def _circle_circle(c1: Pt, r1: float, c2: Pt, r2: float) -> list[Pt]:
    d = _dist(c1, c2)
    if d < EPS or d > r1 + r2 + EPS or d < abs(r1 - r2) - EPS:
        return []
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(0.0, r1 * r1 - a * a))
    mx, my = c1[0] + a * (c2[0] - c1[0]) / d, c1[1] + a * (c2[1] - c1[1]) / d
    return list(
        {
            (round(mx + h * (c2[1] - c1[1]) / d, 9), round(my - h * (c2[0] - c1[0]) / d, 9)),
            (round(mx - h * (c2[1] - c1[1]) / d, 9), round(my + h * (c2[0] - c1[0]) / d, 9)),
        }
    )


class Board:
    """The construction so far: points by id, curves by id ('line' with its extent, or 'circle')."""

    def __init__(self) -> None:
        self.points: dict[str, Pt] = {}
        self.curves: dict[str, dict[str, Any]] = {}
        self.on_arc: dict[str, list[Pt]] = {}  # arc id -> points its drawn part must pass through
        self.placed: list[str] = []  # given points LOOM had to place itself
        self.prims: dict[str, dict[str, Any]] = {}  # point id -> its drawn primitive (a given point may be moved)
        self.used: set[str] = set()  # point ids something else was built from

    def _curve(self, cid: str) -> dict[str, Any]:
        if cid not in self.curves:
            raise ValueError(f"'{cid}' is not a line, ray, segment, circle or arc defined earlier")
        return self.curves[cid]

    def _point(self, pid: str | None, what: str) -> Pt:
        if not pid or pid not in self.points:
            raise ValueError(f"{what} '{pid}' is not a point defined earlier")
        return self.points[pid]

    def given(self, pid: str | None, frm: str | None) -> Pt:
        """A line's end the planner never placed (the arms of "the given angle"): any position shows the
        construction, so it is placed 3.5 units from the line's other end, in a direction no other line from that point
        uses (or at the origin when neither end exists yet). Recorded in `placed`."""
        if pid and pid in self.points:
            return self.points[pid]
        if not pid:
            raise ValueError("a line needs two points")
        if frm and frm in self.points:
            o = self.points[frm]
            used = [
                math.atan2(k["d"][1], k["d"][0]) for k in self.curves.values() if k["type"] == "line" and k["p"] == o
            ]
            for deg in (65, 5, 125, -40, 175, -100):
                t = math.radians(deg)
                if all(abs(math.remainder(t - u, 2 * math.pi)) > math.radians(25) for u in used):
                    break
            p = (o[0] + 3.5 * math.cos(t), o[1] + 3.5 * math.sin(t))
        else:
            p = (0.0, 0.0)
        self.points[pid] = p
        self.placed.append(pid)
        return p

    def intersections(self, i1: str, i2: str) -> list[Pt]:
        k1, k2 = self._curve(i1), self._curve(i2)
        if k1["type"] == "circle" and k2["type"] == "line":
            k1, k2 = k2, k1
        if k1["type"] == "line" and k2["type"] == "line":
            out = [
                p
                for p, t, u in _line_line(
                    k1["p"],
                    k1["d"],
                    k2["p"],
                    k2["d"],
                )
                if _on(k1, t) and _on(k2, u)
            ]
        elif k1["type"] == "line":
            out = [p for p, t in _line_circle(k1["p"], k1["d"], k2["c"], k2["r"]) if _on(k1, t)]
        else:
            out = _circle_circle(k1["c"], k1["r"], k2["c"], k2["r"])
        return out


def _open_angle(bd: Board, o: str, b: str, p: Pt, q: Pt) -> Pt:
    """The second arm of a given angle lying (almost) on the first one, or straight opposite it (a planner placing A
    and C symmetrically), has no angle to work with: its point is turned to 70 degrees from the other arm, at the same
    distance. Only a point nothing has been built from yet is moved."""
    d = _sub(q, p)
    t = math.atan2(d[1], d[0])
    for k in bd.curves.values():
        if k["type"] != "line" or k["kind"] != "ray" or _dist(k["p"], p) > EPS:
            continue
        u = math.atan2(k["d"][1], k["d"][0])
        gap = abs(math.remainder(t - u, 2 * math.pi))
        if gap < math.radians(20) or gap > math.radians(160):
            n = math.hypot(*d)
            t2 = u + math.radians(70)
            nq = (p[0] + n * math.cos(t2), p[1] + n * math.sin(t2))
            bd.points[b] = nq
            if b in bd.prims:
                bd.prims[b]["p"] = nq
            return nq
    return q


def _widen(bd: Board, i1: str, i2: str, force: bool = False) -> list[Pt]:
    """Two compass arcs that must meet but do not: open the compass wider, as a teacher would ("more than half the
    distance"): both get the same radius, 0.75 x the distance between their centres (or keep a bigger one)."""
    k1, k2 = bd._curve(i1), bd._curve(i2)
    if k1["type"] != "circle" or k2["type"] != "circle":
        return []
    d = _dist(k1["c"], k2["c"])
    if d < EPS:
        return []
    r = max(0.75 * d, min(k1["r"], k2["r"]))
    if force:
        r = max(r, 0.75 * d, 1.2 * max(k1["r"], k2["r"]))
    if r * 2 <= d:
        return []
    for k in (k1, k2):
        k["r"] = r
        if k.get("prim") is not None:
            k["prim"]["r"] = r
    return bd.intersections(i1, i2)


def _on(line: dict[str, Any], t: float) -> bool:
    if line["kind"] == "segment":
        return -EPS <= t <= 1 + EPS
    if line["kind"] == "ray":
        return t >= -EPS
    return True


def _ang(c: Pt, p: Pt) -> float:
    return math.atan2(p[1] - c[1], p[0] - c[0])


def _cover(angles: list[float], pad: float) -> tuple[float, float]:
    """Smallest arc (start, end), end > start, that covers every angle, padded on both sides."""
    a = sorted(x % (2 * math.pi) for x in angles)
    if len(a) == 1:
        return (a[0] - pad, a[0] + pad)
    gaps = [(a[(i + 1) % len(a)] - a[i]) % (2 * math.pi) for i in range(len(a))]
    k = max(range(len(a)), key=lambda i: gaps[i])  # leave out the biggest gap
    start = a[(k + 1) % len(a)]
    span = 2 * math.pi - gaps[k]
    return (start - pad, start + span + pad)


def resolve(plan: ConstructionPlan) -> tuple[list[list[dict[str, Any]]], list[str]]:
    """Plan -> per-beat drawing primitives in stage coordinates, and the steps that failed (with why)."""
    bd = Board()
    errors: list[str] = []
    raw: list[list[dict[str, Any]]] = []
    arcs: dict[str, dict[str, Any]] = {}
    for bi, beat in enumerate(plan.beats):
        out: list[dict[str, Any]] = []
        for s in beat.steps:
            try:
                out.append(_step(bd, s, arcs))
            except ValueError as e:
                errors.append(f"beat {bi + 1}, step '{s.id}' ({s.kind}): {e}")
        raw.append(out)
    # each arc is drawn over the part that matters: through its crossings and every point later found on it
    for aid, arc in arcs.items():
        c = arc["c"]
        pts = bd.on_arc.get(aid, [])
        if arc.get("hint") is not None and not pts:
            pts = [arc["hint"]]
        a0, a1 = _cover([_ang(c, p) for p in pts], math.radians(16)) if pts else (0.0, 2 * math.pi)
        arc["a0"], arc["a1"] = a0, a1
    return _to_stage(raw), errors


def _step(bd: Board, s: GeoStep, arcs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    base = {"id": s.id, "kind": s.kind, "label": s.label, "color": s.color}
    if s.kind == "point":
        if s.x is None or s.y is None:
            raise ValueError("a point needs x and y")
        bd.points[s.id] = (float(s.x), float(s.y))
        prim = {**base, "p": bd.points[s.id]}
        bd.prims[s.id] = prim
        return prim
    if s.kind in ("segment", "ray", "line"):
        p = bd.given(s.a, s.b)
        q = bd.given(s.b, s.a)
        if _dist(p, q) < EPS:
            raise ValueError("its two points are the same point")
        if s.kind == "ray" and s.b not in bd.used:
            q = _open_angle(bd, s.a or "", s.b or "", p, q)
        bd.used.update(x for x in (s.a, s.b) if x)
        d = _sub(q, p)
        bd.curves[s.id] = {"type": "line", "kind": s.kind, "p": p, "d": d, "q": q}
        if s.kind == "ray":  # drawn on past its through point
            p, q = p, (p[0] + 1.35 * d[0], p[1] + 1.35 * d[1])
        elif s.kind == "line":
            p, q = (p[0] - 0.3 * d[0], p[1] - 0.3 * d[1]), (q[0] + 0.3 * d[0], q[1] + 0.3 * d[1])
        return {**base, "p": p, "q": q}
    if s.kind in ("circle", "arc"):
        c = bd._point(s.a, "centre")
        r = _dist(c, bd._point(s.b, "through point")) if s.b else s.radius
        if not r or r <= EPS:
            raise ValueError("a circle or arc needs a radius or a through point b")
        prim = {**base, "c": c, "r": float(r)}
        bd.curves[s.id] = {"type": "circle", "c": c, "r": float(r), "prim": prim}
        if s.kind == "arc":
            crossings = []
            for cid in s.of:  # where it should cross something it misses, it is still drawn (around its centre)
                if cid in bd.curves:
                    crossings += bd.intersections(s.id, cid)
            bd.on_arc[s.id] = crossings
            prim["hint"] = bd.points.get(s.b) if s.b else None
            arcs[s.id] = prim
        return prim
    if s.kind == "intersect":
        if len(s.of) != 2:
            raise ValueError("an intersection needs exactly two curves in 'of'")
        cands = bd.intersections(s.of[0], s.of[1]) or _widen(bd, s.of[0], s.of[1])
        known = list(bd.points.values())
        fresh = [p for p in cands if all(_dist(p, k) > 1e-3 for k in known)]
        if not fresh and cands:  # they only meet at a point already drawn (arcs that just touch at the vertex)
            fresh = [p for p in _widen(bd, s.of[0], s.of[1], force=True) if all(_dist(p, k) > 1e-3 for k in known)]
        fresh = fresh or cands
        if not fresh:
            raise ValueError(f"'{s.of[0]}' and '{s.of[1]}' do not cross")
        if s.side:
            key = {"up": lambda q: q[1], "down": lambda q: -q[1], "right": lambda q: q[0], "left": lambda q: -q[0]}
            p = max(fresh, key=key[s.side])
        elif s.near:
            ref = bd._point(s.near, "near point")
            p = min(fresh, key=lambda q: _dist(q, ref))
        elif s.far:
            ref = bd._point(s.far, "far point")
            p = max(fresh, key=lambda q: _dist(q, ref))
        else:  # no hint: the crossing away from everything drawn so far (not the one back near the vertex)
            p = max(fresh, key=lambda q: min((_dist(q, k) for k in known), default=0.0))
        bd.points[s.id] = p
        for cid in s.of:
            if bd.curves[cid]["type"] == "circle":
                bd.on_arc.setdefault(cid, []).append(p)
        return {**base, "kind": "point", "p": p, "via": list(s.of)}
    if s.kind == "angle_mark":
        if len(s.of) != 3:
            raise ValueError("an angle mark needs [vertex, point, point] in 'of'")
        v, p, q = (bd._point(i, "angle point") for i in s.of)
        a0, a1 = _ang(v, p), _ang(v, q)
        if (a1 - a0) % (2 * math.pi) > math.pi:
            a0, a1 = a1, a0
        return {**base, "c": v, "a0": a0, "a1": a0 + (a1 - a0) % (2 * math.pi), "r": None}
    if s.kind == "label":
        if s.x is None or s.y is None:
            raise ValueError("a label needs x and y")
        return {**base, "p": (float(s.x), float(s.y))}
    known_ids = set(bd.points) | set(bd.curves)
    missing = [i for i in s.of if i not in known_ids]
    if missing or not s.of:
        raise ValueError(f"nothing to {s.kind}: {missing or 'no ids'}")
    return {**base, "ids": list(s.of)}


STAGE_X, STAGE_Y0, STAGE_Y1 = 5.6, -1.7, 2.7  # world units the drawing is fitted into (the captions sit below)


def _to_stage(raw: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
    xs: list[float] = []
    ys: list[float] = []
    for beat in raw:
        for p in beat:
            for k in ("p", "q", "c"):
                if p.get(k) is not None:
                    xs.append(p[k][0])
                    ys.append(p[k][1])
            if p["kind"] in ("circle", "arc") and p.get("a0") is not None:
                for t in [p["a0"] + (p["a1"] - p["a0"]) * k / 8 for k in range(9)]:
                    xs.append(p["c"][0] + p["r"] * math.cos(t))
                    ys.append(p["c"][1] + p["r"] * math.sin(t))
    if not xs:
        return raw
    w, h = max(xs) - min(xs) or 1.0, max(ys) - min(ys) or 1.0
    s = min(2 * STAGE_X / w, (STAGE_Y1 - STAGE_Y0) / h)
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    ty = (STAGE_Y0 + STAGE_Y1) / 2

    def m(p: Pt) -> list[float]:
        return [round((p[0] - cx) * s, 3), round((p[1] - cy) * s + ty, 3)]

    out = []
    for beat in raw:
        nb = []
        for p in beat:
            q = {k: v for k, v in p.items() if k != "hint"}
            for k in ("p", "q", "c"):
                if q.get(k) is not None:
                    q[k] = m(q[k])
            if q.get("r"):
                q["r"] = round(q["r"] * s, 3)
            for k in ("a0", "a1"):
                if q.get(k) is not None:
                    q[k] = round(q[k], 4)
            nb.append(q)
        out.append(nb)
    return out
