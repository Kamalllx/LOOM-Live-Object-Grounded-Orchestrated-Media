"""Dependency-free SVG charts for the reports (crisp on GitHub, scalable for print). Each function returns SVG text;
`save` writes it. A white card background keeps them readable in light and dark README themes."""

from __future__ import annotations

from html import escape
from pathlib import Path

INK, DIM, GRID = "#1f2933", "#66788a", "#e3e8ee"
PALETTE = ["#ff9f78", "#8b6cf6", "#2bb79a", "#4ea8de", "#f2b33d", "#ef5d7a", "#7a8a99", "#c06ad8", "#5cc2c9", "#9bbf4b"]
FONT = "font-family='Segoe UI, Helvetica, Arial, sans-serif'"


def _card(w: int, h: int, title: str, sub: str = "") -> list[str]:
    return [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' viewBox='0 0 {w} {h}' {FONT}>",
        f"<rect x='0.5' y='0.5' width='{w - 1}' height='{h - 1}' rx='14' fill='#ffffff' stroke='{GRID}'/>",
        f"<text x='24' y='34' font-size='17' font-weight='700' fill='{INK}'>{escape(title)}</text>",
        f"<text x='24' y='54' font-size='12.5' fill='{DIM}'>{escape(sub)}</text>" if sub else "",
    ]


def _nice(v: float) -> float:
    if v <= 0:
        return 1.0
    for m in (1, 2, 2.5, 5, 10):
        for e in range(-3, 7):
            step = m * 10**e
            if step * 5 >= v:
                return step * 5
    return v


def hbar(
    rows: list[tuple[str, float]],
    title: str,
    sub: str = "",
    unit: str = "",
    w: int = 860,
    colors: list[str] | None = None,
    fmt: str = "{:.0f}",
    vmax: float | None = None,
) -> str:
    """Horizontal bars, one per row (label, value)."""
    lab_w, top, row_h = 230, 74, 26
    h = top + row_h * len(rows) + 34
    vmax = vmax or _nice(max((v for _, v in rows), default=1))
    plot = w - lab_w - 80
    out = _card(w, h, title, sub)
    for k in range(6):
        x = lab_w + plot * k / 5
        out.append(f"<line x1='{x:.1f}' y1='{top - 6}' x2='{x:.1f}' y2='{h - 28}' stroke='{GRID}'/>")
        out.append(
            f"<text x='{x:.1f}' y='{h - 12}' font-size='11' fill='{DIM}' text-anchor='middle'>{fmt.format(vmax * k / 5)}{escape(unit)}</text>"
        )
    for i, (label, v) in enumerate(rows):
        y = top + i * row_h
        c = (colors or PALETTE)[i % len(colors or PALETTE)]
        bw = max(1.5, plot * min(v, vmax) / vmax)
        out.append(
            f"<text x='{lab_w - 10}' y='{y + 15}' font-size='12.5' fill='{INK}' text-anchor='end'>{escape(label[:34])}</text>"
        )
        out.append(f"<rect x='{lab_w}' y='{y + 3}' width='{bw:.1f}' height='{row_h - 8}' rx='4' fill='{c}'/>")
        out.append(
            f"<text x='{lab_w + bw + 6:.1f}' y='{y + 15}' font-size='11.5' fill='{INK}'>{fmt.format(v)}{escape(unit)}</text>"
        )
    out.append("</svg>")
    return "\n".join(x for x in out if x)


def stacked(
    rows: list[tuple[str, dict[str, float]]],
    keys: list[str],
    title: str,
    sub: str = "",
    unit: str = "s",
    w: int = 900,
    normalise: bool = False,
) -> str:
    """Horizontal stacked bars (e.g. perception time per stage per video), with a legend."""
    lab_w, top, row_h = 230, 104, 22
    h = top + row_h * len(rows) + 36
    totals = [sum(d.get(k, 0) for k in keys) for _, d in rows]
    vmax = 1.0 if normalise else _nice(max(totals, default=1))
    plot = w - lab_w - 70
    out = _card(w, h, title, sub)
    lx = 24
    for i, k in enumerate(keys):  # legend
        out.append(f"<rect x='{lx}' y='66' width='11' height='11' rx='2' fill='{PALETTE[i % len(PALETTE)]}'/>")
        out.append(f"<text x='{lx + 15}' y='76' font-size='11.5' fill='{INK}'>{escape(k)}</text>")
        lx += 22 + 7.2 * len(k)
    for k in range(6):
        x = lab_w + plot * k / 5
        out.append(f"<line x1='{x:.1f}' y1='{top - 6}' x2='{x:.1f}' y2='{h - 28}' stroke='{GRID}'/>")
        lbl = f"{int(100 * k / 5)}%" if normalise else f"{vmax * k / 5:.0f}{unit}"
        out.append(f"<text x='{x:.1f}' y='{h - 12}' font-size='11' fill='{DIM}' text-anchor='middle'>{lbl}</text>")
    for i, (label, d) in enumerate(rows):
        y = top + i * row_h
        out.append(
            f"<text x='{lab_w - 10}' y='{y + 13}' font-size='11.5' fill='{INK}' text-anchor='end'>{escape(label[:34])}</text>"
        )
        x = float(lab_w)
        tot = totals[i] or 1
        for j, k in enumerate(keys):
            v = d.get(k, 0) / (tot if normalise else 1)
            bw = plot * v / vmax
            if bw > 0.2:
                out.append(
                    f"<rect x='{x:.1f}' y='{y + 2}' width='{bw:.1f}' height='{row_h - 6}' fill='{PALETTE[j % len(PALETTE)]}'/>"
                )
            x += bw
        if not normalise:
            out.append(f"<text x='{x + 6:.1f}' y='{y + 13}' font-size='11' fill='{DIM}'>{totals[i]:.0f}{unit}</text>")
    out.append("</svg>")
    return "\n".join(x for x in out if x)


def grouped(
    cats: list[str],
    series: dict[str, list[float]],
    title: str,
    sub: str = "",
    w: int = 860,
    vmax: float = 1.0,
    fmt: str = "{:.2f}",
    h: int = 340,
) -> str:
    """Vertical grouped bars: one group per category, one bar per series (e.g. precision / recall per rule)."""
    left, top, bottom = 56, 92, 74
    plot_w, plot_h = w - left - 24, h - top - bottom
    out = _card(w, h, title, sub)
    lx = 24
    for i, name in enumerate(series):
        out.append(f"<rect x='{lx}' y='64' width='11' height='11' rx='2' fill='{PALETTE[i]}'/>")
        out.append(f"<text x='{lx + 15}' y='74' font-size='11.5' fill='{INK}'>{escape(name)}</text>")
        lx += 26 + 7 * len(name)
    for k in range(6):
        y = top + plot_h * (1 - k / 5)
        out.append(f"<line x1='{left}' y1='{y:.1f}' x2='{w - 24}' y2='{y:.1f}' stroke='{GRID}'/>")
        out.append(
            f"<text x='{left - 8}' y='{y + 4:.1f}' font-size='11' fill='{DIM}' text-anchor='end'>{fmt.format(vmax * k / 5)}</text>"
        )
    gw = plot_w / max(1, len(cats))
    n = len(series)
    bw = min(34, (gw - 18) / max(1, n))
    for ci, cat in enumerate(cats):
        gx = left + gw * ci + (gw - bw * n) / 2
        for si, (_name, vals) in enumerate(series.items()):
            v = vals[ci]
            bh = plot_h * min(v, vmax) / vmax
            x, y = gx + si * bw, top + plot_h - bh
            out.append(
                f"<rect x='{x:.1f}' y='{y:.1f}' width='{bw - 3:.1f}' height='{max(0.5, bh):.1f}' rx='3' fill='{PALETTE[si]}'/>"
            )
            out.append(
                f"<text x='{x + (bw - 3) / 2:.1f}' y='{y - 4:.1f}' font-size='10' fill='{INK}' text-anchor='middle'>{fmt.format(v)}</text>"
            )
        words, lines, cur = cat.split(), [], ""
        for wd in words:
            if len(cur) + len(wd) > 16 and cur:
                lines.append(cur)
                cur = wd
            else:
                cur = f"{cur} {wd}".strip()
        lines.append(cur)
        for li, ln in enumerate(lines[:3]):
            out.append(
                f"<text x='{left + gw * ci + gw / 2:.1f}' y='{top + plot_h + 18 + 13 * li}' font-size='11' fill='{INK}' text-anchor='middle'>{escape(ln)}</text>"
            )
    out.append("</svg>")
    return "\n".join(x for x in out if x)


def boxes(
    groups: list[tuple[str, list[float]]], title: str, sub: str = "", unit: str = "s", w: int = 860, log: bool = False
) -> str:
    """Horizontal box plots (median, quartiles, min-max whiskers) with every observation as a dot."""
    import math
    import statistics

    lab_w, top, row_h = 210, 76, 46
    h = top + row_h * len(groups) + 34
    allv = [v for _, xs in groups for v in xs] or [1.0]
    lo, hi = (min(allv), max(allv))
    if log:
        lo, hi = math.log10(max(0.01, lo) / 1.5), math.log10(hi * 1.5)
    else:
        lo, hi = 0.0, _nice(hi)
    plot = w - lab_w - 40

    def X(v: float) -> float:
        t = (math.log10(max(0.01, v)) - lo) / (hi - lo) if log else (v - lo) / (hi - lo or 1)
        return lab_w + plot * t

    out = _card(w, h, title, sub)
    ticks = (
        [10**e for e in range(math.floor(lo), math.ceil(hi) + 1)] if log else [lo + (hi - lo) * k / 5 for k in range(6)]
    )
    for tv in ticks:
        x = X(tv)
        if lab_w - 1 <= x <= lab_w + plot + 1:
            out.append(f"<line x1='{x:.1f}' y1='{top - 8}' x2='{x:.1f}' y2='{h - 28}' stroke='{GRID}'/>")
            out.append(
                f"<text x='{x:.1f}' y='{h - 12}' font-size='11' fill='{DIM}' text-anchor='middle'>{tv:g}{escape(unit)}</text>"
            )
    for i, (label, xs) in enumerate(groups):
        y = top + i * row_h + 12
        c = PALETTE[i % len(PALETTE)]
        out.append(
            f"<text x='{lab_w - 12}' y='{y + 5}' font-size='12.5' fill='{INK}' text-anchor='end'>{escape(label)}</text>"
        )
        out.append(
            f"<text x='{lab_w - 12}' y='{y + 20}' font-size='10.5' fill='{DIM}' text-anchor='end'>n = {len(xs)}</text>"
        )
        if not xs:
            continue
        s = sorted(xs)
        q1, med, q3 = statistics.quantiles(s, n=4) if len(s) >= 4 else [s[0], statistics.median(s), s[-1]]
        out.append(f"<line x1='{X(s[0]):.1f}' y1='{y}' x2='{X(s[-1]):.1f}' y2='{y}' stroke='{c}' stroke-width='2'/>")
        out.append(
            f"<rect x='{X(q1):.1f}' y='{y - 10}' width='{max(2, X(q3) - X(q1)):.1f}' height='20' rx='4' fill='{c}' fill-opacity='0.28' stroke='{c}'/>"
        )
        out.append(
            f"<line x1='{X(med):.1f}' y1='{y - 12}' x2='{X(med):.1f}' y2='{y + 12}' stroke='{INK}' stroke-width='2.5'/>"
        )
        out.append(
            f"<text x='{X(med):.1f}' y='{y - 15}' font-size='10.5' fill='{INK}' text-anchor='middle'>{med:.1f}{escape(unit)}</text>"
        )
        for k, v in enumerate(s):
            out.append(
                f"<circle cx='{X(v):.1f}' cy='{y + (k % 3 - 1) * 4}' r='2.6' fill='{c}' stroke='#fff' stroke-width='0.8'/>"
            )
    out.append("</svg>")
    return "\n".join(x for x in out if x)


def timeline(
    duration: float,
    lanes: list[tuple[str, list[tuple[float, float]], str]],
    title: str,
    sub: str = "",
    w: int = 900,
    marks: list[tuple[float, str]] | None = None,
) -> str:
    """Interval lanes over a lesson's time axis (ground-truth hazard vs what each configuration masked)."""
    lab_w, top, row_h = 230, 76, 30
    h = top + row_h * len(lanes) + 40
    plot = w - lab_w - 30

    def X(t: float) -> float:
        return lab_w + plot * t / duration

    out = _card(w, h, title, sub)
    step = 10 if duration <= 120 else 30
    t = 0.0
    while t <= duration + 1e-6:
        out.append(f"<line x1='{X(t):.1f}' y1='{top - 6}' x2='{X(t):.1f}' y2='{h - 30}' stroke='{GRID}'/>")
        out.append(
            f"<text x='{X(t):.1f}' y='{h - 14}' font-size='11' fill='{DIM}' text-anchor='middle'>{t:.0f}s</text>"
        )
        t += step
    for i, (label, ivs, color) in enumerate(lanes):
        y = top + i * row_h
        out.append(
            f"<text x='{lab_w - 10}' y='{y + 15}' font-size='12' fill='{INK}' text-anchor='end'>{escape(label)}</text>"
        )
        out.append(f"<rect x='{lab_w}' y='{y + 4}' width='{plot}' height='{row_h - 10}' rx='3' fill='#f4f6f8'/>")
        for a, b in ivs:
            out.append(
                f"<rect x='{X(a):.1f}' y='{y + 4}' width='{max(1.2, X(b) - X(a)):.1f}' height='{row_h - 10}' rx='3' fill='{color}'/>"
            )
    for t, lbl in marks or []:
        out.append(
            f"<text x='{X(t):.1f}' y='{top - 10}' font-size='10.5' fill='{DIM}' text-anchor='middle'>{escape(lbl)}</text>"
        )
    out.append("</svg>")
    return "\n".join(x for x in out if x)


def save(svg: str, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")
    return path.name
