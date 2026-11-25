"""Add the pipeline flowchart and the fault/latency charts to the two-column paper (main.tex)."""
from pathlib import Path

p = Path(__file__).parent / "main.tex"
s = p.read_text(encoding="utf-8")


def sub(a: str, b: str) -> None:
    global s
    assert a in s, a[:70]
    s = s.replace(a, b, 1)


# pipeline flowchart: cited in the perception text, placed as a wide figure
sub(r"""After probing and shot detection (PySceneDetect \cite{pyscenedetect}), speech is transcribed with Whisper""",
    r"""\fig{fig:pipe} lists the stages. After probing and shot detection (PySceneDetect \cite{pyscenedetect}), speech is transcribed with Whisper""")
sub(r"""\subsection{Hazard verification and masking}""",
    r"""\begin{figure*}[t]
\centering
\resizebox{0.86\textwidth}{!}{\input{fig_pipeline.tex}}
\caption{Perception stages, run once per lesson (grey: GPU; double border: local language model), and the
hazard-verification rule. Rejected tracks never reach SAM\,2.1.}
\label{fig:pipe}
\end{figure*}

\subsection{Hazard verification and masking}""")
# fault-injection and latency charts, side by side
sub(r"""seven families (\tab{tab:faults}), and require the expected issue.""",
    r"""seven families (\tab{tab:faults}, \fig{fig:charts}a), and require the expected issue.""")
sub(r"""\subsection{Explainers}""",
    r"""\begin{figure*}[t]
\centering
\panel{a}{\includegraphics[width=0.49\textwidth]{fig/chart-critic-faults.png}}\hfill
\panel{b}{\includegraphics[width=0.49\textwidth]{fig/chart-latency.png}}
\caption{(a) Critic fault injection by family: faults planted, detected, and repaired inside the loop. (b) Interactive
latency over repeated runs, every request a new question (box: quartiles; bar: median; dots: runs; log scale).}
\label{fig:charts}
\end{figure*}

\subsection{Explainers}""")
sub(r"""Every request asks a new question so that no answer comes from the cache.""",
    r"""Every request asks a new question so that no answer comes from the cache (\fig{fig:charts}b).""")
p.write_text(s, encoding="utf-8")
print("ok")
