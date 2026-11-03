"""Normalize OCR output to plain Unicode text (spec/03 §5.5: "H₂O, →").

`glm-ocr` returns formulas as LaTeX (`$$ \\mathrm{H}_{2}\\mathrm{O} \\rightarrow ... $$`) — found in the Stage 0 spike.
This turns that into the on-screen text a viewer reads: `H₂O →`. Pure function; no model calls.
"""

from __future__ import annotations

import re
import unicodedata

_SUB = str.maketrans("0123456789+-=()aeoxhklmnpst", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓₕₖₗₘₙₚₛₜ")
_SUP = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")

_SYMBOLS = {
    r"\rightleftharpoons": "⇌",
    r"\leftrightharpoons": "⇌",
    r"\longrightarrow": "→",
    r"\rightarrow": "→",
    r"\Rightarrow": "⇒",
    r"\leftarrow": "←",
    r"\leftrightarrow": "↔",
    r"\to": "→",
    r"\cdot": "·",
    r"\times": "×",
    r"\div": "÷",
    r"\pm": "±",
    r"\geq": "≥",
    r"\leq": "≤",
    r"\ge": "≥",
    r"\le": "≤",
    r"\neq": "≠",
    r"\approx": "≈",
    r"\degree": "°",
    r"\circ": "°",
    r"\Delta": "Δ",
    r"\alpha": "α",
    r"\beta": "β",
    r"\gamma": "γ",
    r"\lambda": "λ",
    r"\mu": "μ",
    r"\pi": "π",
    r"\%": "%",
}
_WRAPPERS = re.compile(r"\\(?:mathrm|text|textrm|mathbf|mathit|operatorname|mathsf)\s*\{")
_MATH = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$|\\\[(.+?)\\\]|\\\((.+?)\\\)", re.DOTALL)
_SCRIPT = re.compile(r"([_^])\s*(\{([^{}]*)\}|\\?[A-Za-z0-9+\-=()])")
_OPERATORS = re.compile(r"\s*([+=→⇌⇒←↔])\s*")


def _unwrap(s: str) -> str:
    """Replace `\\mathrm{...}`-style wrappers by their content (handles nesting)."""
    while m := _WRAPPERS.search(s):
        depth, i = 1, m.end()
        while i < len(s) and depth:
            depth += {"{": 1, "}": -1}.get(s[i], 0)
            i += 1
        s = s[: m.start()] + s[m.end() : i - 1] + s[i:]
    return s


def _script(m: re.Match[str]) -> str:
    kind, body = m.group(1), (m.group(3) if m.group(3) is not None else m.group(2))
    body = body.replace(" ", "")
    if body in (r"\circ", "°"):
        return "°"
    table = _SUB if kind == "_" else _SUP
    converted = body.translate(table)
    if all(ch != orig or not ch.isalnum() for ch, orig in zip(converted, body, strict=True)) or len(body) == 0:
        return converted
    # a character with no sub/superscript form: keep a readable fallback
    return ("_" if kind == "_" else "^") + body


def _math(segment: str) -> str:
    s = _unwrap(segment)
    for cmd in sorted(_SYMBOLS, key=len, reverse=True):
        s = re.sub(re.escape(cmd) + r"(?![A-Za-z])", _SYMBOLS[cmd], s)
    s = _SCRIPT.sub(_script, s)
    s = s.replace("{", "").replace("}", "").replace("\\,", "").replace("\\;", "").replace("\\ ", " ")
    s = re.sub(r"\s+", "", s)  # spaces are not rendered in LaTeX math
    s = _OPERATORS.sub(r" \1 ", s)  # ...but on screen the operators are spaced
    return s.strip()


def latex_to_unicode(text: str) -> str:
    """Convert LaTeX math (delimited or bare) in OCR output to Unicode; leave plain text alone."""
    if "\\" not in text and "$" not in text and "_" not in text and "^" not in text:
        return unicodedata.normalize("NFC", text.strip())
    had_delimiters = bool(_MATH.search(text))
    if had_delimiters:
        out = _MATH.sub(lambda m: _math(next(g for g in m.groups() if g is not None)), text)
    else:
        out = _math(text) if "\\" in text or "_" in text or "^" in text else text
    out = _OPERATORS.sub(r" \1 ", out)
    out = re.sub(r"[ \t]+", " ", out.replace("\n", " "))
    return unicodedata.normalize("NFC", out.strip())


def compact(text: str) -> str:
    """Whitespace-insensitive form used to compare OCR text with ground truth."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text))
