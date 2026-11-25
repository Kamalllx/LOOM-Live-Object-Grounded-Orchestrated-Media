"""Build the Word version of the paper from main_hr.tex, in the Hinweis Research template: A4, margins 3.25/3.25/3/2.5 cm,
Times New Roman 9 pt single spaced with no indent, 20 pt title, "I. INTRODUCTION" headings (10 pt small caps),
"A. Title" subheadings (9 pt italic), "Figure N." captions below figures, "TABLE N." captions above boxed tables.

The converter handles the LaTeX this paper uses (sections, paragraphs, inline math, emphasis, tables, figures, the
algorithm, the equation, references). TikZ figures, Algorithm 1 and Eq. (1) come from render_standalone.py.

    python render_standalone.py && python build_docx.py      # -> LOOM_AIDE2026_camera_ready.docx
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

HERE = Path(__file__).parent
SRC = HERE / "main_hr.tex"
OUT = HERE / "LOOM_AIDE2026_camera_ready.docx"
FONT = "Times New Roman"
ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
TEXT_W = 15.5  # cm

# ---------------------------------------------------------------- numbering (labels -> numbers, like LaTeX)


def numbering(body: str) -> dict[str, str]:
    refs: dict[str, str] = {}
    fig = tab = alg = sec = sub = 0
    for m in re.finditer(r"\\begin\{(figure|table|algorithm)\}|\\section\{|\\subsection\{|\\label\{([^}]*)\}", body):
        tok = m.group(0)
        if tok == r"\section{":
            sec, sub = sec + 1, 0
            last = ROMAN[sec]
        elif tok == r"\subsection{":
            sub += 1
            last = chr(64 + sub)
        elif m.group(1) == "figure":
            fig += 1
            last = str(fig)
        elif m.group(1) == "table":
            tab += 1
            last = ROMAN[tab]
        elif m.group(1) == "algorithm":
            alg += 1
            last = str(alg)
        elif m.group(2):
            refs[m.group(2)] = last
    return refs


# ---------------------------------------------------------------- inline LaTeX -> runs

SYM = {r"\in": "∈", r"\geq": "≥", r"\leq": "≤", r"\times": "×", r"\pm": "±", r"\rightarrow": "→", r"\setminus": "∖",
       r"\cap": "∩", r"\cup": "∪", r"\circ": "°", r"\emptyset": "∅", r"\sim": "~", r"\gets": "←", r"\qquad": "    ",
       r"\quad": "  ", r"\{": "{", r"\}": "}", r"\cdot": "·", r"\ldots": "…", r"\dots": "…"}
TEXT_ESC = {r"\%": "%", r"\&": "&", r"\_": "_", r"\$": "$", r"\{": "{", r"\}": "}", r"\#": "#"}


class Inline:
    """A tiny recursive reader for the inline LaTeX of this paper -> [(text, fmt)]."""

    def __init__(self, refs: dict[str, str]) -> None:
        self.refs = refs

    def group(self, s: str, i: int) -> tuple[str, int]:
        assert s[i] == "{", s[i:i + 30]
        depth, j = 0, i
        while True:
            if s[j] == "\\":
                j += 2
                continue
            if s[j] == "{":
                depth += 1
            elif s[j] == "}":
                depth -= 1
                if depth == 0:
                    return s[i + 1:j], j + 1
            j += 1

    def runs(self, s: str, fmt: dict | None = None, math: bool = False) -> list[tuple[str, dict]]:
        fmt = dict(fmt or {})
        out: list[tuple[str, dict]] = []
        i = 0

        def add(t: str, f: dict | None = None) -> None:
            if t:
                out.append((t, dict(f if f is not None else fmt)))

        while i < len(s):
            c = s[i]
            if c == "$":
                j = s.index("$", i + 1)
                out += self.runs(s[i + 1:j], fmt, math=True)
                i = j + 1
            elif c == "\\":
                m = re.match(r"\\([A-Za-z]+|.)", s[i:])
                cmd = m.group(0)
                i += len(cmd)
                name = m.group(1)
                if name in ("emph", "textit"):
                    g, i = self.group(s, i)
                    out += self.runs(g, {**fmt, "italic": not fmt.get("italic")}, math)
                elif name == "textbf":
                    g, i = self.group(s, i)
                    out += self.runs(g, {**fmt, "bold": True}, math)
                elif name == "textsc":
                    g, i = self.group(s, i)
                    out += self.runs(g, {**fmt, "smallcaps": True}, math)
                elif name in ("mathrm", "text", "textrm", "operatorname"):
                    g, i = self.group(s, i)
                    out += self.runs(g, {**fmt, "upright": True}, False if name != "mathrm" else True)
                elif name == "url":
                    g, i = self.group(s, i)
                    add(g)
                elif name in ("ref",):
                    g, i = self.group(s, i)
                    add(self.refs.get(g, "?"))
                elif name in ("fig", "tab"):
                    g, i = self.group(s, i)
                    add(("Fig.\u00a0" if name == "fig" else "Table\u00a0") + self.refs.get(g, "?"))
                elif name == "label":
                    _, i = self.group(s, i)
                elif name in ("relax", "noindent", "centering"):
                    pass
                elif name == ",":
                    add("\u2009")
                elif name == " ":
                    add(" ")
                elif cmd in TEXT_ESC:
                    add(TEXT_ESC[cmd])
                elif cmd in SYM:
                    add(SYM[cmd], {k: v for k, v in fmt.items() if k != "italic"})
                elif name == "\\":
                    add("\n")
                else:
                    raise ValueError(f"unknown command {cmd} near {s[max(0, i - 30):i + 30]!r}")
            elif math and c in "^_":
                i += 1
                if s[i] == "{":
                    g, i = self.group(s, i)
                elif s[i] == "\\":
                    g = re.match(r"\\[A-Za-z]+", s[i:]).group(0)
                    i += len(g)
                else:
                    g, i = s[i], i + 1
                key = "superscript" if c == "^" else "subscript"
                out += self.runs(g, {**fmt, key: True}, True)
            elif c == "{":
                g, i = self.group(s, i)
                out += self.runs(g, fmt, math)
            elif c == "~":
                add("\u00a0")
                i += 1
            elif s.startswith("---", i):
                add("—")
                i += 3
            elif s.startswith("--", i):
                add("–")
                i += 2
            elif s.startswith("``", i):
                add("“")
                i += 2
            elif s.startswith("''", i):
                add("”")
                i += 2
            elif c == "`":
                add("‘")
                i += 1
            elif c == "'" and not math:
                add("’")
                i += 1
            elif c == "\n":
                add(" ")
                i += 1
            else:
                j = i
                while j < len(s) and s[j] not in "$\\{}~-`'\n^_" :
                    j += 1
                if j == i:
                    j = i + 1
                chunk = s[i:j]
                if math and not fmt.get("upright"):
                    for part in re.split(r"([A-Za-z]+)", chunk):
                        if not part:
                            continue
                        add(part, {**fmt, "italic": bool(re.fullmatch(r"[A-Za-z]+", part))})
                else:
                    add(chunk)
                i = j
        return out


def emit(p, runs: list[tuple[str, dict]], size: float | None = None, bold: bool | None = None) -> None:
    for text, f in runs:
        for k, piece in enumerate(text.split("\n")):
            if k:
                p.add_run().add_break(WD_BREAK.LINE)
            if not piece:
                continue
            r = p.add_run(re.sub(r"[ \t]+", " ", piece))
            r.font.name = FONT
            if size:
                r.font.size = Pt(size)
            r.bold = bool(f.get("bold")) or bool(bold)
            r.italic = bool(f.get("italic"))
            r.font.small_caps = bool(f.get("smallcaps"))
            r.font.superscript = bool(f.get("superscript"))
            r.font.subscript = bool(f.get("subscript"))


def para(doc, align=WD_ALIGN_PARAGRAPH.JUSTIFY, before=0, after=0, left=0.0, right=0.0, keep=False):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.alignment = align
    pf.space_before, pf.space_after = Pt(before), Pt(after)
    pf.line_spacing = 1.0
    pf.first_line_indent = Cm(0)
    if left:
        pf.left_indent = Cm(left)
    if right:
        pf.right_indent = Cm(right)
    if keep:
        pf.keep_with_next = True
    return p


# ---------------------------------------------------------------- blocks

FIGMAP = {"fig_arch.tex": ("fig/docx-arch.png", 15.5), "fig_pipeline.tex": ("fig/docx-pipeline.png", 15.0),
          "fig_construct.tex": ("fig/docx-construct.png", 6.8), "fig_cuts.tex": ("fig/docx-cuts.png", 15.5)}


def caption(doc, kind: str, num: str, text: str, inl: Inline) -> None:
    if kind == "figure":
        p = para(doc, WD_ALIGN_PARAGRAPH.CENTER, before=3, after=9)
        emit(p, [(f"Figure {num}. ", {})] + inl.runs(text), size=8)
    else:
        p = para(doc, WD_ALIGN_PARAGRAPH.CENTER, before=6, after=3, keep=True)
        emit(p, [(f"TABLE {num}. ", {})] + inl.runs(text, {"smallcaps": True}), size=8)


def figure(doc, block: str, num: str, inl: Inline) -> None:
    imgs = []
    for m in re.finditer(r"\\includegraphics\[([^\]]*)\]\{([^}]*)\}|\\input\{([^}]*)\}", block):
        if m.group(3):
            imgs.append(FIGMAP[m.group(3)])
        else:
            w = re.search(r"width=([0-9.]+)\\textwidth", m.group(1))
            imgs.append((m.group(2), TEXT_W * float(w.group(1)) if w else TEXT_W))
    cap = Inline.group(inl, block, block.index(r"\caption") + len(r"\caption"))[0]
    if len(imgs) == 1:
        p = para(doc, WD_ALIGN_PARAGRAPH.CENTER, before=6, keep=True)
        p.add_run().add_picture(str(HERE / imgs[0][0]), width=Cm(imgs[0][1]))
    else:  # side by side in a borderless table
        t = doc.add_table(rows=1, cols=len(imgs))
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for k, (path, w) in enumerate(imgs):
            cell = t.rows[0].cells[k]
            cp = cell.paragraphs[0]
            cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            cp.add_run().add_picture(str(HERE / path), width=Cm(min(w, TEXT_W / len(imgs) - 0.2)))
    caption(doc, "figure", num, cap, inl)


def split_cells(row: str) -> list[str]:
    cells, depth, cur, i = [], 0, "", 0
    while i < len(row):
        ch = row[i]
        if ch == "\\" and i + 1 < len(row):
            cur += row[i:i + 2]
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == "&" and depth == 0:
            cells.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    cells.append(cur)
    return [c.strip() for c in cells]


def set_borders(table) -> None:
    tbl = table._tbl
    pr = tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), "000000")
        borders.append(el)
    pr.append(borders)


def table(doc, block: str, num: str, inl: Inline) -> None:
    cap = Inline.group(inl, block, block.index(r"\caption") + len(r"\caption"))[0]
    caption(doc, "table", num, cap, inl)
    spec_m = re.search(r"\\begin\{tabular\}\{", block)
    spec, k = Inline.group(inl, block, spec_m.end() - 1)
    widths = [float(w) for w in re.findall(r"[Lp]\{([0-9.]+)cm\}", spec)]
    ncol = len(re.findall(r"[Llcrp]", re.sub(r"\{[^}]*\}", "", spec)))
    body = block[k:block.index(r"\end{tabular}")]
    rows = [r.strip() for r in re.split(r"\\\\", body.replace(r"\hline", "")) if r.strip()]
    t = doc.add_table(rows=0, cols=ncol)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_borders(t)
    for ri, row in enumerate(rows):
        cells = split_cells(row)
        cells_out = t.add_row().cells
        col = 0
        for c in cells:
            mc = re.match(r"\\multicolumn\{(\d+)\}\{[^}]*\}\{(.*)\}$", c, re.S)
            span, text = (int(mc.group(1)), mc.group(2)) if mc else (1, c)
            cell = cells_out[col]
            if span > 1:
                cell = cell.merge(cells_out[col + span - 1])
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = p.paragraph_format.space_after = Pt(0)
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            text = re.sub(r"\\footnotesize\s*", "", text)
            emit(p, inl.runs(text), size=8, bold=(ri == 0))
            col += span
    if not widths or len(widths) != ncol:  # size columns by their longest cell text (Word would split evenly)
        plain = [[re.sub(r"\\[A-Za-z]+|[{}$]", "", c) for c in split_cells(r)] for r in rows]
        longest = [max((len(r[k]) for r in plain if len(r) == ncol), default=4) for k in range(ncol)]
        need = [min(30, max(4, n)) for n in longest]
        cm = [n * 0.19 + 0.3 for n in need]
        scale = min(1.0, TEXT_W * 0.98 / sum(cm))
        widths = [w * scale for w in cm]
    t.autofit = False
    for row in t.rows:
        for c, w in zip(row.cells, widths):
            c.width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def heading(doc, text: str, level: int, num: str | None, inl: Inline) -> None:
    if level == 1:
        p = para(doc, WD_ALIGN_PARAGRAPH.LEFT, before=12, after=6, keep=True)
        emit(p, ([(f"{num}. ", {})] if num else []) + inl.runs(text, {"smallcaps": True}), size=10)
    else:
        p = para(doc, WD_ALIGN_PARAGRAPH.LEFT, before=6, after=3, keep=True)
        emit(p, [(f"{num}. ", {"italic": True})] + inl.runs(text, {"italic": True}), size=9)


def main() -> None:
    src = SRC.read_text(encoding="utf-8")
    body = src[src.index(r"\begin{document}") + len(r"\begin{document}"):src.index(r"\end{document}")]
    refs = numbering(body)
    inl = Inline(refs)
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name, st.font.size = FONT, Pt(9)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.top_margin = sec.bottom_margin = Cm(3.25)
    sec.left_margin, sec.right_margin = Cm(3.0), Cm(2.5)
    sec.header_distance, sec.footer_distance = Cm(1.27), Cm(2.89)

    # title block
    title = re.search(r"\\fontsize\{20\}\{24\}\\selectfont (.*?)\\par", body, re.S).group(1)
    p = para(doc, WD_ALIGN_PARAGRAPH.CENTER, before=6, after=6)
    emit(p, inl.runs(title.replace("\\\\", " ")), size=20)
    authors = re.search(r"\\fontsize\{10\}\{12\}\\selectfont (.*?)\\par", body, re.S).group(1)
    p = para(doc, WD_ALIGN_PARAGRAPH.CENTER, after=2)
    emit(p, inl.runs(authors), size=10)
    aff = re.search(r"\\fontsize\{9\}\{11\}\\selectfont (.*?)\\par", body, re.S).group(1)
    p = para(doc, WD_ALIGN_PARAGRAPH.CENTER, after=10)
    emit(p, inl.runs(aff), size=9)
    # abstract and index terms
    abs_block = body[body.index(r"\begin{list}"):body.index(r"\end{list}")]
    abstract = re.search(r"\\textbf\{\\textit\{Abstract\}---(.*?)\}\s*\\vspace", abs_block, re.S).group(1)
    p = para(doc, before=0, after=6, left=1.1, right=1.1)
    emit(p, [("Abstract", {"italic": True, "bold": True}), ("—", {"bold": True})] + inl.runs(abstract, {"bold": True}))
    terms = re.search(r"Index Terms\}---(.*?)\}\s*$", abs_block.strip(), re.S).group(1)
    p = para(doc, after=6, left=1.1, right=1.1)
    emit(p, [("Index Terms", {"italic": True, "bold": True}), ("—", {"bold": True})] + inl.runs(terms, {"bold": True}))

    rest = body[body.index(r"\end{list}") + len(r"\end{list}"):]
    pattern = re.compile(r"\\section\*?\{|\\subsection\{|\\begin\{(figure|table|algorithm|equation)\}|"
                         r"\{\\fontsize\{8\.5\}\{10\}\\selectfont|\n\s*\n")
    pos, sec_n, sub_n, fig_n, tab_n = 0, 0, 0, 0, 0
    buf = ""

    def flush() -> None:
        nonlocal buf
        text = re.sub(r"\\label\{[^}]*\}", "", buf).strip()
        if text:
            p = para(doc)
            emit(p, inl.runs(text))
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
            pos = m.end()
        elif tok.startswith(r"\section"):
            flush()
            g, pos = inl.group(rest, m.end() - 1)
            if tok == r"\section{":
                sec_n, sub_n = sec_n + 1, 0
                heading(doc, g, 1, ROMAN[sec_n], inl)
            else:
                heading(doc, g, 1, None, inl)
        elif tok == r"\subsection{":
            flush()
            g, pos = inl.group(rest, m.end() - 1)
            sub_n += 1
            heading(doc, g, 2, chr(64 + sub_n), inl)
        elif tok.startswith(r"{\fontsize{8.5}"):
            flush()
            end = rest.index(r"\end{enumerate}", m.end())
            for item in re.split(r"\\item\s+", rest[m.end():end])[1:]:
                p = para(doc, WD_ALIGN_PARAGRAPH.JUSTIFY, after=1, left=0.6)
                p.paragraph_format.first_line_indent = Cm(-0.6)
                n = len([1 for _ in doc.paragraphs if _.text.startswith("[")]) + 1
                emit(p, [(f"[{n}]\t", {})] + inl.runs(item.strip()), size=8.5)
            pos = rest.index("}", end + len(r"\end{enumerate}")) + 1
        else:
            flush()
            env = m.group(1)
            end = rest.index(rf"\end{{{env}}}", m.end())
            block = rest[m.end():end]
            pos = end + len(rf"\end{{{env}}}")
            if env == "figure":
                fig_n += 1
                figure(doc, block, str(fig_n), inl)
            elif env == "table":
                tab_n += 1
                table(doc, block, ROMAN[tab_n], inl)
            elif env == "algorithm":
                p = para(doc, WD_ALIGN_PARAGRAPH.LEFT, before=6, keep=True)
                emit(p, [("Algorithm 1. ", {"bold": True}), ("Verify-before-deliver loop", {})], size=9)
                p = para(doc, WD_ALIGN_PARAGRAPH.LEFT, after=8)
                p.add_run().add_picture(str(HERE / "fig/docx-algorithm.png"), width=Cm(15.0))
            elif env == "equation":
                t = doc.add_table(rows=1, cols=2)
                t.alignment = WD_TABLE_ALIGNMENT.CENTER
                a, b = t.rows[0].cells
                a.width, b.width = Cm(13.5), Cm(2.0)
                pa = a.paragraphs[0]
                pa.alignment = WD_ALIGN_PARAGRAPH.CENTER
                pa.add_run().add_picture(str(HERE / "fig/docx-equation.png"), width=Cm(5.4))
                pb = b.paragraphs[0]
                pb.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                emit(pb, [("(1)", {})])
    flush()
    doc.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
