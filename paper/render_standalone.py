"""Render the TikZ diagrams, Algorithm 1 and Eq. (1) of main_hr.tex as 300-dpi PNGs for the Word version
(paper/fig/docx-*.png), with the same fonts as the PDF.  Run from paper/:  python render_standalone.py"""

import subprocess
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "fig"
PRE = r"""\documentclass[border=3pt]{standalone}
\usepackage[T1]{fontenc}
\usepackage{newtxtext,newtxmath}
\usepackage{amsmath,xcolor,tikz,algpseudocode}
\usetikzlibrary{arrows.meta,positioning,fit,calc,backgrounds,patterns,shapes.geometric}
\definecolor{lsky}{HTML}{2F7FC1}\definecolor{lmint}{HTML}{1E9E7E}\definecolor{lpeach}{HTML}{E07A45}
\definecolor{llilac}{HTML}{7B5CD6}\definecolor{lcoral}{HTML}{D6455F}\definecolor{lgrey}{HTML}{5B6B78}
\renewcommand{\algorithmicrequire}{\textbf{Input:}}\renewcommand{\algorithmicensure}{\textbf{Output:}}
\begin{document}
"""
ALGO = r"""\begin{minipage}{15.4cm}\small
\begin{algorithmic}[1]
\Require lesson graph $G$, viewer $v$, budget $B=3$
\Ensure a verified pair $(C,M)$, or the fallback cut
\State $T\gets$ \textsc{Pedagogy}(\textsc{Curator}$(G)$, $v$);\quad $C\gets$ \textsc{Personalize}$(T,v)$
\State $C.quiz\gets$ \textsc{Assessment}$(C,G,v)$;\quad $F\gets\emptyset$ \Comment{masks forced by the Critic}
\For{$p=1$ \textbf{to} $B$}
  \State $M\gets$ \textsc{Guardian}$(G,v,C)\cup F$
  \State $I\gets$ \textsc{Critic}$(C,M,G,v)$
  \If{$I=\emptyset$} \Return $(C,M)$ \Comment{approved}
  \EndIf
  \State $F\gets F\cup\{o : \text{object } o \text{ is an unmasked hazard in } I\}$
  \State $C\gets$ \textsc{Revise}$(C, \{i\in I: i \text{ is routed to the mesh}\})$
\EndFor
\State \Return \textsc{Fallback}$(G,v)$ \Comment{whole lesson, nothing generated, every object masked}
\end{algorithmic}\end{minipage}"""
EQ = r"""$\displaystyle \mathrm{prec}=\frac{|P\cap H|}{|P|}, \qquad \mathrm{rec}=\frac{|P\cap H|}{|H|},$"""
JOBS = {
    "docx-arch": r"\resizebox{16cm}{!}{\input{fig_arch.tex}}",
    "docx-pipeline": r"\resizebox{15.5cm}{!}{\input{fig_pipeline.tex}}",
    "docx-construct": r"\input{fig_construct.tex}",
    "docx-cuts": r"\input{fig_cuts.tex}",
    "docx-algorithm": ALGO,
    "docx-equation": EQ,
}


def main() -> None:
    build = HERE / "standalone_build"
    build.mkdir(exist_ok=True)
    for name, body in JOBS.items():
        tex = build / f"{name}.tex"
        # only the algorithm needs a page width (it is text); diagrams keep their natural bounding box
        pre = PRE.replace("[border=3pt]", "[border=3pt,varwidth=16cm]") if name == "docx-algorithm" else PRE
        tex.write_text(pre + body + "\n\\end{document}\n", encoding="utf-8")
        r = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", f"-output-directory={build}",
                            str(tex)], cwd=HERE, capture_output=True, text=True, errors="replace")
        if r.returncode:
            raise SystemExit(f"{name} failed:\n{r.stdout[-1500:]}")
        subprocess.run(["pdftoppm", "-png", "-r", "300", "-singlefile", str(build / f"{name}.pdf"), str(OUT / name)],
                       check=True)
        print(name)


if __name__ == "__main__":
    main()
