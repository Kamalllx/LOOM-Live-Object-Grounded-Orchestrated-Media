"""Build the Word version of the two-column IEEE paper (main.tex), with its screenshots.

IEEE conference layout on A4: margins 1.9 / 4.3 cm (top / bottom) and 1.43 cm (sides), two 8.86 cm columns, Times New
Roman 10 pt, 24 pt title, "I. INTRODUCTION" headings, booktabs-style tables (rules, no vertical lines), "Fig. N."
captions below figures and "TABLE N" captions above tables. Wide figures (figure*) sit in a one-column section, as in
the IEEE Word template. Panel letters are drawn into copies of the screenshots (fig/docx-ieee/).

Algorithm 1 and Eq. (1) are rendered from main.tex with pdflatex; the TikZ diagrams come from render_standalone.py.

    python render_standalone.py && python build_docx_ieee.py   # -> LOOM_AIDE2026_IEEE_two_column_with_screenshots.docx
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from PIL import Image, ImageDraw, ImageFont

import build_docx as bd

HERE = Path(__file__).parent
SRC = HERE / "main.tex"
OUT = HERE / "LOOM_AIDE2026_IEEE_two_column_with_screenshots.docx"
PANELS = HERE / "fig" / "docx-ieee"
FONT = bd.FONT
ROMAN = bd.ROMAN
SIDE, GAP = 1.43, 0.43  # cm
TEXT_W = 21.0 - 2 * SIDE
COL_W = (TEXT_W - GAP) / 2
# Word has no floats: a figure or table that does not fit at the foot of a column leaves a gap and moves on. These
# are emitted that many paragraphs after their place in main.tex, so the text fills the column first.
DEFER = {"alg:loop": 1, "fig:ui": 1, "tab:rules": 1, "fig:timelines": 1, "fig:charts": 3, "tab:alts": 1}
FIGMAP = {"fig_arch.tex": "fig/docx-arch.png", "fig_pipeline.tex": "fig/docx-pipeline.png"}
bd.SYM.update({r"\to": "→", r"\approx": "≈", r"\le": "≤", r"\ge": "≥", r"\checkmark": "✓", r"\mid": "|"})

# ---------------------------------------------------------------- standalone renders (Algorithm 1, Eq. 1)

PRE = r"""\documentclass[border=2pt]{standalone}
\usepackage[T1]{fontenc}
\usepackage{newtxtext,newtxmath}
\usepackage{amsmath,algpseudocode}
\renewcommand{\algorithmicrequire}{\textbf{Input:}}\renewcommand{\algorithmicensure}{\textbf{Output:}}
\begin{document}
"""


def render(name: str, body: str) -> Path:
    build = HERE / "standalone_build"
    build.mkdir(exist_ok=True)
    tex = build / f"{name}.tex"
    tex.write_text(PRE + body + "\n\\end{document}\n", encoding="utf-8")
    r = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", f"-output-directory={build}",
                        str(tex)], cwd=HERE, capture_output=True, text=True, errors="replace")
    if r.returncode:
        raise SystemExit(f"{name} failed:\n{r.stdout[-1500:]}")
    out = HERE / "fig" / name
    subprocess.run(["pdftoppm", "-png", "-r", "300", "-singlefile", str(build / f"{name}.pdf"), str(out)], check=True)
    return out.with_suffix(".png")


def natural_cm(path: Path) -> float:
    """Width in cm of a 300-dpi render."""
    with Image.open(path) as im:
        return im.width / 300 * 2.54


# ---------------------------------------------------------------- word helpers


def set_cols(section, n: int) -> None:
    cols = section._sectPr.find(qn("w:cols"))
    if cols is None:
        cols = OxmlElement("w:cols")
        section._sectPr.append(cols)
    cols.set(qn("w:num"), str(n))
    cols.set(qn("w:space"), str(round(GAP / 2.54 * 1440)))


def new_section(doc, ncols: int) -> None:
    sec = doc.add_section(WD_SECTION.CONTINUOUS)
    set_cols(sec, ncols)


def border(el_pr, edges: dict[str, int], tag: str) -> None:
    """Add <w:pBdr>/<w:tcBorders> lines: {edge: size in eighths of a point}."""
    box = OxmlElement(tag)
    for edge, sz in edges.items():
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), "single")
        e.set(qn("w:sz"), str(sz))
        e.set(qn("w:space"), "1" if tag == "w:pBdr" else "0")
        e.set(qn("w:color"), "000000")
        box.append(e)
    el_pr.append(box)


def para(doc, align=WD_ALIGN_PARAGRAPH.JUSTIFY, before=0.0, after=0.0, indent=0.0, keep=False):
    p = bd.para(doc, align, before, after, keep=keep)
    p.paragraph_format.first_line_indent = Cm(indent)
    return p


# ---------------------------------------------------------------- numbering and citations


def numbering(body: str) -> dict[str, str]:
    refs: dict[str, str] = {}
    fig = tab = alg = eq = sec = sub = 0
    last = ""
    for m in re.finditer(r"\\begin\{(figure\*?|table\*?|algorithm|equation)\}|\\section\{|\\subsection\{|"
                         r"\\label\{([^}]*)\}", body):
        tok, env = m.group(0), (m.group(1) or "").rstrip("*")
        if tok == r"\section{":
            sec, sub = sec + 1, 0
            last = ROMAN[sec]
        elif tok == r"\subsection{":
            sub += 1
            last = chr(64 + sub)
        elif env == "figure":
            fig += 1
            last = str(fig)
        elif env == "table":
            tab += 1
            last = ROMAN[tab]
        elif env == "algorithm":
            alg += 1
            last = str(alg)
        elif env == "equation":
            eq += 1
            last = str(eq)
        elif m.group(2):
            refs[m.group(2)] = last
    return refs


def cite(body: str) -> str:
    keys = re.findall(r"\\bibitem\{([^}]*)\}", body)
    num = {k: i + 1 for i, k in enumerate(keys)}
    return re.sub(r"\\cite\{([^}]*)\}",
                  lambda m: ", ".join(f"[{num[k.strip()]}]" for k in m.group(1).split(",")), body)


def mathspace(body: str) -> str:
    """Thin spaces around relations in inline math, as LaTeX sets them."""
    def one(m: re.Match) -> str:
        t = re.sub(r"(?<![\\{<>])=", r"\\,=\\,", m.group(1))
        t = re.sub(r"\\(geq|leq|in|gets|cup|cap|setminus|rightarrow|to)(?![A-Za-z])", r"\\,\\\1\\,", t)
        return "$" + t + "$"
    return re.sub(r"\$([^$]+)\$", one, body)


STRIP = re.compile(r"\\(footnotesize|scriptsize|small|centering|balance|label\{[^}]*\})\s*")


# ---------------------------------------------------------------- figures


def panel_copy(path: str, letter: str, width_cm: float) -> str:
    """A copy of the image with the panel letter in a white box at the top-left, as \\panel draws it."""
    src = HERE / path
    PANELS.mkdir(exist_ok=True)
    dst = PANELS / f"{src.stem}-{letter}{src.suffix}"
    with Image.open(src) as im:
        im = im.convert("RGB")
        px_cm = im.width / width_cm
        font = ImageFont.truetype("C:/Windows/Fonts/timesbd.ttf", max(10, round(0.26 * px_cm)))
        d = ImageDraw.Draw(im)
        off, pad = round(0.053 * px_cm), round(0.045 * px_cm)
        x0, y0, x1, y1 = d.textbbox((0, 0), letter, font=font)
        box = (off, off, off + (x1 - x0) + 2 * pad, off + (y1 - y0) + 2 * pad)
        d.rectangle(box, fill="white", outline=(173, 181, 187), width=max(1, round(0.01 * px_cm)))
        d.text((off + pad - x0, off + pad - y0), letter, font=font, fill="black")
        im.save(dst, quality=93)
    return str(dst.relative_to(HERE))


ITEM = re.compile(
    r"\\panel\{(?P<pl>\w)\}\{\\includegraphics\[(?P<po>[^\]]*)\]\{(?P<pp>[^}]*)\}\}"
    r"|\{\\scriptsize\\bfseries (?P<ol>\w)\}\\enspace\\raisebox\{-\\height\}\{\\includegraphics\[(?P<oo>[^\]]*)\]"
    r"\{(?P<op>[^}]*)\}\}"
    r"|\\includegraphics\[(?P<io>[^\]]*)\]\{(?P<ip>[^}]*)\}"
    r"|\\resizebox\{(?P<rf>[0-9.]*)\\textwidth\}\{!\}\{\\input\{(?P<rt>[^}]*)\}\}")


def width_of(opts: str, path: str) -> float:
    m = re.search(r"width=([0-9.]*)\\(textwidth|columnwidth)", opts)
    if m:
        return float(m.group(1) or 1) * (TEXT_W if m.group(2) == "textwidth" else COL_W)
    h = float(re.search(r"height=([0-9.]+)cm", opts).group(1))
    with Image.open(HERE / path) as im:
        return h * im.width / im.height


def figure(doc, block: str, num: str, wide: bool, inl: bd.Inline) -> None:
    multi_row = "\\\\" in block[:block.index(r"\caption")]  # stacked panels: slightly smaller than in the PDF
    avail = TEXT_W if wide else COL_W * (0.88 if multi_row else 1.0)
    cap = inl.group(block, block.index(r"\caption") + len(r"\caption"))[0]
    art = block[:block.index(r"\caption")]
    rows = re.split(r"\\\\(?:\[[^\]]*\])?", art)
    for r_i, row in enumerate(rows):
        items = []  # (path, width, outside-letter or "")
        for m in ITEM.finditer(row):
            if m.group("pl"):
                w = width_of(m.group("po"), m.group("pp"))
                items.append((panel_copy(m.group("pp"), m.group("pl"), w), w, ""))
            elif m.group("ol"):
                items.append((m.group("op"), width_of(m.group("oo"), m.group("op")), m.group("ol")))
            elif m.group("ip"):
                items.append((m.group("ip"), width_of(m.group("io"), m.group("ip")), ""))
            else:
                items.append((FIGMAP[m.group("rt")], float(m.group("rf") or 1) * TEXT_W, ""))
        if not items:
            continue
        gap = 0.25
        total = sum(w for _, w, _ in items) + gap * (len(items) - 1) + 0.35 * sum(1 for *_, o in items if o)
        scale = min(1.0, (avail - 0.05) / total)
        p = para(doc, WD_ALIGN_PARAGRAPH.CENTER, before=4 if r_i == 0 else 1, keep=True)
        for k, (path, w, outside) in enumerate(items):
            if k:
                p.add_run("\u2003" if len(items) < 3 else "\u2002").font.size = Pt(7)
            if outside:
                r = p.add_run(f"{outside}\u2002")
                r.bold, r.font.size, r.font.name = True, Pt(7), FONT
            p.add_run().add_picture(str(HERE / path), width=Cm(w * scale))
    p = para(doc, WD_ALIGN_PARAGRAPH.JUSTIFY, before=3, after=6)
    bd.emit(p, [(f"Fig.\u00a0{num}.\u2002", {})] + inl.runs(STRIP.sub("", cap)), size=8)


# ---------------------------------------------------------------- tables (booktabs look)

CELL_PAD = 0.1  # cm, left and right of every cell
_TIMES = ImageFont.truetype("C:/Windows/Fonts/times.ttf", 80)


def text_cm(s: str) -> float:
    """Width of s set in Times 8 pt."""
    return _TIMES.getlength(s) / 10 / 72 * 2.54


def table(doc, block: str, num: str, inl: bd.Inline) -> None:
    cap = inl.group(block, block.index(r"\caption") + len(r"\caption"))[0]
    p = para(doc, WD_ALIGN_PARAGRAPH.CENTER, before=4, keep=True)
    bd.emit(p, [(f"TABLE {num}", {})], size=8)
    p = para(doc, WD_ALIGN_PARAGRAPH.CENTER, after=4, keep=True)
    bd.emit(p, inl.runs(STRIP.sub("", cap), {"smallcaps": True}), size=8)

    start = block.index(r"\begin{tabular}") + len(r"\begin{tabular}")
    spec, k = inl.group(block, start)
    spec = re.sub(r"@\{[^}]*\}", "", spec)
    cols = re.findall(r"[LPp]\{([0-9.]+)cm\}|([lcr])", spec)
    ncol = len(cols)
    body = block[k:block.index(r"\end{tabular}")]
    raw = re.split(r"\\\\", body)
    rows, rule_above, bottom = [], [], False
    for chunk in raw:
        rule = 8 if r"\bottomrule" in chunk else 4 if r"\midrule" in chunk else 0
        text = re.sub(r"\\(toprule|midrule|bottomrule)", "", chunk).strip()
        if text:
            rows.append(text)
            rule_above.append(rule if len(rows) > 1 else 0)
        elif rule:
            bottom = True
    t = doc.add_table(rows=0, cols=ncol)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for ri, row in enumerate(rows):
        cells_out = t.add_row().cells
        col = 0
        for c in bd.split_cells(row):
            span, text = 1, c
            if c.startswith(r"\multicolumn"):
                n, j = inl.group(c, len(r"\multicolumn"))
                _, j = inl.group(c, j)
                text, _ = inl.group(c, j)
                span = int(n)
            cell = cells_out[col]
            if span > 1:
                cell = cell.merge(cells_out[col + span - 1])
            cp = cell.paragraphs[0]
            cp.paragraph_format.space_before = cp.paragraph_format.space_after = Pt(0)
            letter = cols[col][1] if col < ncol else "l"
            cp.alignment = {"r": WD_ALIGN_PARAGRAPH.RIGHT, "c": WD_ALIGN_PARAGRAPH.CENTER}.get(
                letter, WD_ALIGN_PARAGRAPH.LEFT)
            bd.emit(cp, inl.runs(STRIP.sub("", text)), size=7 if span > 1 else 8)
            edges = {}
            if ri == 0:
                edges["top"] = 8
            elif rule_above[ri]:
                edges["top"] = rule_above[ri]
            if ri == len(rows) - 1 and bottom:
                edges["bottom"] = 8
            if edges:
                border(cell._tc.get_or_add_tcPr(), edges, "w:tcBorders")
            col += span
    # widths: fixed columns keep their LaTeX size, the others fit their longest cell (measured in Times 8 pt);
    # if the table is too wide, only the wrapping text columns give way
    plain = [["" if c.startswith(r"\multicolumn") else "".join(t for t, _ in inl.runs(STRIP.sub("", c)))
              for c in bd.split_cells(r)] for r in rows]
    widths, wraps = [], []
    for ci, (fixed, _) in enumerate(cols):
        if fixed:
            widths.append(float(fixed) + 2 * CELL_PAD)
            wraps.append(True)
        else:
            longest = max((text_cm(r[ci]) for r in plain if len(r) == ncol), default=0.5)
            widths.append(longest + 2 * CELL_PAD + 0.08)
            wraps.append(ci == 0 and len(cols) > 3 and cols[0][1] == "l")
    over = sum(widths) - COL_W * 0.99
    fixed_w = sum(w for w, (f, _) in zip(widths, cols) if f)
    if over < 0 and fixed_w:  # p{} columns take the room LaTeX gives to \tabcolsep, so fewer lines wrap
        widths = [w - over * w / fixed_w if f else w for w, (f, _) in zip(widths, cols)]
    elif over > 0:
        flex = sum(w for w, f in zip(widths, wraps) if f) or sum(widths)
        widths = [w - over * w / flex if (f or not any(wraps)) else w for w, f in zip(widths, wraps)]
    pad = OxmlElement("w:tblCellMar")
    for edge in ("left", "right"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:w"), str(round(CELL_PAD / 2.54 * 1440)))
        e.set(qn("w:type"), "dxa")
        pad.append(e)
    t._tbl.tblPr.append(pad)
    for ri, row in enumerate(t.rows):
        trpr = row._tr.get_or_add_trPr()
        trpr.append(OxmlElement("w:cantSplit"))
        for c, w in zip(row.cells, widths):
            c.width = Cm(w)
            if ri < len(t.rows) - 1:  # keep the table in one piece
                for cp in c.paragraphs:
                    cp.paragraph_format.keep_with_next = True
    para(doc, after=3).paragraph_format.line_spacing = Pt(3)


# ---------------------------------------------------------------- headings, abstract, references


def heading(doc, text: str, level: int, num: str | None, inl: bd.Inline) -> None:
    if level == 1:
        p = para(doc, WD_ALIGN_PARAGRAPH.CENTER, before=6, after=3, keep=True)
        bd.emit(p, ([(f"{num}.\u2002", {})] if num else []) + inl.runs(text, {"smallcaps": True}), size=10)
    else:
        p = para(doc, WD_ALIGN_PARAGRAPH.LEFT, before=4, after=2, keep=True)
        bd.emit(p, [(f"{num}.\u2002", {"italic": True})] + inl.runs(text, {"italic": True}), size=10)


def main() -> None:
    src = SRC.read_text(encoding="utf-8")
    doc_body = src[src.index(r"\begin{document}"):src.index(r"\end{document}")]
    doc_body = mathspace(cite(doc_body))
    refs = numbering(doc_body)
    inl = bd.Inline(refs)

    doc = Document()
    st = doc.styles["Normal"]
    st.font.name, st.font.size = FONT, Pt(10)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    hyph = OxmlElement("w:autoHyphenation")
    doc.settings.element.append(hyph)
    doc.core_properties.title = "LOOM: A Verified Multi-Agent System for Object-Level Personalization of Instructional Video"
    doc.core_properties.author = "Kamal Karteek U, Manya Ravishankar, Jeevika R, Sangeetha J"
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.top_margin, sec.bottom_margin = Cm(1.9), Cm(4.3)
    sec.left_margin = sec.right_margin = Cm(SIDE)
    set_cols(sec, 1)

    # title block (one column)
    title = inl.group(doc_body, doc_body.index(r"\title") + len(r"\title"))[0]
    p = para(doc, WD_ALIGN_PARAGRAPH.CENTER, after=10)
    bd.emit(p, inl.runs(title), size=24)
    names = inl.group(doc_body, doc_body.index(r"\IEEEauthorblockN") + len(r"\IEEEauthorblockN"))[0]
    aff = inl.group(doc_body, doc_body.index(r"\IEEEauthorblockA") + len(r"\IEEEauthorblockA"))[0]
    p = para(doc, WD_ALIGN_PARAGRAPH.CENTER, after=2)
    bd.emit(p, inl.runs(names), size=11)
    p = para(doc, WD_ALIGN_PARAGRAPH.CENTER, after=12)
    bd.emit(p, inl.runs(aff), size=10)
    new_section(doc, 2)

    # abstract and index terms
    abstract = doc_body[doc_body.index(r"\begin{abstract}") + 16:doc_body.index(r"\end{abstract}")].strip()
    p = para(doc, after=4, indent=0.36)
    bd.emit(p, [("Abstract", {"italic": True, "bold": True}), ("—", {"bold": True})] + inl.runs(abstract, {"bold": True}),
            size=9)
    terms = doc_body[doc_body.index(r"\begin{IEEEkeywords}") + 20:doc_body.index(r"\end{IEEEkeywords}")].strip()
    p = para(doc, after=6, indent=0.36)
    bd.emit(p, [("Index Terms", {"italic": True, "bold": True}), ("—", {"bold": True})] + inl.runs(terms, {"bold": True}),
            size=9)

    rest = doc_body[doc_body.index(r"\end{IEEEkeywords}") + len(r"\end{IEEEkeywords}"):]
    pattern = re.compile(r"\\section\*?\{|\\subsection\{|\\begin\{(figure\*?|table\*?|algorithm|equation|"
                         r"thebibliography)\}|\n\s*\n")
    pos, sec_n, sub_n, fig_n, tab_n, eq_n = 0, 0, 0, 0, 0, 0
    buf, cont = "", False
    pending: list[list] = []  # floats waiting DEFER paragraphs: [paragraphs left, env, block, number]

    def place(env: str, block: str, num: str) -> None:
        if env.startswith("figure"):
            wide = env.endswith("*")
            if wide:
                new_section(doc, 1)
            figure(doc, block, num, wide, inl)
            if wide:
                new_section(doc, 2)
        elif env.startswith("table"):
            table(doc, block, num, inl)
        else:
            cap = inl.group(block, block.index(r"\caption") + len(r"\caption"))[0]
            algo = block[block.index(r"\begin{algorithmic}"):block.index(r"\end{algorithmic}") + 17]
            png = render("docx-ieee-algorithm", r"\begin{minipage}{8.5cm}\footnotesize" + "\n" + algo +
                         r"\end{minipage}")
            p = para(doc, WD_ALIGN_PARAGRAPH.LEFT, before=4, keep=True)
            border(p._p.get_or_add_pPr(), {"top": 8, "bottom": 4}, "w:pBdr")
            bd.emit(p, [(f"Algorithm {num} ", {"bold": True})] + inl.runs(cap), size=9)
            p = para(doc, WD_ALIGN_PARAGRAPH.LEFT, after=8)
            border(p._p.get_or_add_pPr(), {"bottom": 8}, "w:pBdr")
            p.add_run().add_picture(str(png), width=Cm(min(COL_W, natural_cm(png))))

    def flush() -> None:
        nonlocal buf
        text = STRIP.sub("", buf).strip()
        if text:
            p = para(doc, indent=0 if cont else 0.36)
            bd.emit(p, inl.runs(text))
            for f in pending:
                f[0] -= 1
            while pending and pending[0][0] <= 0:
                place(*pending.pop(0)[1:])
        buf = ""

    while pos < len(rest):
        m = pattern.search(rest, pos)
        if not m:
            buf += rest[pos:]
            break
        buf += rest[pos:m.start()]
        tok = m.group(0)
        if tok.strip() == "":
            flush()
            cont = False
            pos = m.end()
        elif tok.startswith(r"\section"):
            flush()
            cont = False
            g, pos = inl.group(rest, m.end() - 1)
            if tok == r"\section{":
                sec_n, sub_n = sec_n + 1, 0
                heading(doc, g, 1, ROMAN[sec_n], inl)
            else:
                heading(doc, g, 1, None, inl)
        elif tok == r"\subsection{":
            flush()
            cont = False
            g, pos = inl.group(rest, m.end() - 1)
            sub_n += 1
            heading(doc, g, 2, chr(64 + sub_n), inl)
        else:
            flush()
            env = m.group(1)
            end = rest.index(rf"\end{{{env}}}", m.end())
            block = rest[m.end():end]
            pos = end + len(rf"\end{{{env}}}")
            cont = True
            if env.startswith(("figure", "table", "algorithm")):
                if env.startswith("figure"):
                    fig_n += 1
                    num = str(fig_n)
                elif env.startswith("table"):
                    tab_n += 1
                    num = ROMAN[tab_n]
                else:
                    num = "1"
                label = re.search(r"\\label\{([^}]*)\}", block)
                later = DEFER.get(label.group(1) if label else "", 0)
                if later:
                    pending.append([later, env, block, num])
                else:
                    place(env, block, num)
            elif env == "equation":
                eq_n += 1
                png = render(f"docx-ieee-eq{eq_n}", "$\\displaystyle " + STRIP.sub("", block).strip() + "$")
                t = doc.add_table(rows=1, cols=2)
                t.alignment = WD_TABLE_ALIGNMENT.CENTER
                a, b = t.rows[0].cells
                a.width, b.width = Cm(COL_W - 1.0), Cm(1.0)
                pa = a.paragraphs[0]
                pa.alignment = WD_ALIGN_PARAGRAPH.CENTER
                pa.add_run().add_picture(str(png), width=Cm(min(COL_W - 1.2, natural_cm(png))))
                pb = b.paragraphs[0]
                pb.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                bd.emit(pb, [(f"({eq_n})", {})])
            elif env == "thebibliography":
                heading(doc, "References", 1, None, inl)
                items = re.split(r"\\bibitem\{[^}]*\}", block)[1:]
                for n, item in enumerate(items, 1):
                    p = para(doc, WD_ALIGN_PARAGRAPH.LEFT, after=0)
                    p.paragraph_format.left_indent = Cm(0.6)
                    p.paragraph_format.first_line_indent = Cm(-0.6)
                    p.paragraph_format.tab_stops.add_tab_stop(Cm(0.6))
                    bd.emit(p, [(f"[{n}]\t", {})] + inl.runs(item.strip()), size=8)
    flush()
    for f in pending:
        place(*f[1:])
    doc.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
