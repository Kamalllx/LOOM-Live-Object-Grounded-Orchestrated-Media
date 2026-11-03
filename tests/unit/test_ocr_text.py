from __future__ import annotations

import pytest

from loom.perception.ocr_text import compact, latex_to_unicode

# Inputs are the actual glm-ocr replies recorded in the Stage 0 spike.
CASES = [
    (
        "$$\n\\mathrm {N a O H} + \\mathrm {H C l} \\rightarrow "
        "\\mathrm {N a C l} + \\mathrm {H} _ {2} \\mathrm {O}\n$$",
        "NaOH + HCl → NaCl + H₂O",
    ),
    (
        "$$\n2 \\mathrm {H} _ {2} + \\mathrm {O} _ {2} \\rightarrow 2 \\mathrm {H} _ {2} \\mathrm {O}\n$$",
        "2H₂ + O₂ → 2H₂O",
    ),
    ("Acid + Base $ \\rightarrow $ Salt + Water", "Acid + Base → Salt + Water"),
    ("$ \\mathrm{H_{2} S O_{4}} $ (aq)", "H₂SO₄ (aq)"),
    ("CH $ _{3} $COOH", "CH₃COOH"),
    ("Mg+2HCl→MgCl_{2}+H_{2}", "Mg + 2HCl → MgCl₂ + H₂"),
    ("E=mc²", "E = mc²"),
    ("pH 7 = neutral", "pH 7 = neutral"),
    ("$\\mathrm{CH_3COOH} \\rightleftharpoons \\mathrm{CH_3COO^-} + \\mathrm{H^+}$", "CH₃COOH ⇌ CH₃COO⁻ + H⁺"),
    ("$25 ^ {\\circ} \\mathrm{C}$", "25°C"),
]


@pytest.mark.parametrize(("raw", "expected"), CASES)
def test_latex_to_unicode(raw: str, expected: str) -> None:
    assert compact(latex_to_unicode(raw)) == compact(expected)


def test_operators_are_spaced_and_plain_text_untouched() -> None:
    assert latex_to_unicode("Mg+2HCl→MgCl_{2}+H_{2}") == "Mg + 2HCl → MgCl₂ + H₂"
    assert latex_to_unicode("  Safety goggles  ") == "Safety goggles"


def test_unmappable_script_keeps_a_readable_fallback() -> None:
    assert latex_to_unicode("$x_{q}$") == "x_q"
