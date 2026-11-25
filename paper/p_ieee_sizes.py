"""Figure sizes for the two-column paper so it fits in 8 pages."""
import sys
from pathlib import Path

p = Path(__file__).parent / "main.tex"
s = p.read_text(encoding="utf-8")
SIZES = {
    r"\resizebox{0.86\textwidth}{!}{\input{fig_pipeline.tex}}": r"\resizebox{0.8\textwidth}{!}{\input{fig_pipeline.tex}}",
    r"\includegraphics[width=\columnwidth]{fig/narration-checks.jpg}": r"\includegraphics[width=0.9\columnwidth]{fig/narration-checks.jpg}",
    r"\includegraphics[width=\columnwidth]{fig/extension.jpg}": r"\includegraphics[width=0.86\columnwidth]{fig/extension.jpg}",
    r"\includegraphics[width=0.49\textwidth]{fig/chart-critic-faults.png}": r"\includegraphics[width=0.43\textwidth]{fig/chart-critic-faults.png}",
    r"\includegraphics[width=0.49\textwidth]{fig/chart-latency.png}": r"\includegraphics[width=0.43\textwidth]{fig/chart-latency.png}",
}
extra = dict(a.split("=>") for a in sys.argv[1:])  # optional further "old=>new" pairs
for a, b in {**SIZES, **extra}.items():
    if a in s:
        s = s.replace(a, b)
    else:
        print("not found:", a)
p.write_text(s, encoding="utf-8")
print("ok")
