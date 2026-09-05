"""One table: a genome's typeface family, resolved to each format's faces.

``compiler/style.py`` samples *which family* a world's documents wear and
never names a format's font — the compiler layer does not know there is such a
thing as PDF. This module is the render package's half of that contract: every
renderer resolves the family through this one table, so one genome means the
same visual identity in every format, which is the same argument
``render/docx.py`` and ``render/pptx.py`` already make for ``_genome_for``
applied to faces.

House is deliberately inert. ``None`` is the instruction to set no font name
at all, which is exactly what the OOXML renderers did before typefaces existed
(the theme's own defaults) and what HTML's user-agent stylesheet does — so a
house genome renders byte-identically to the look that shipped. Resolving
house to a literal name instead ("Calibri") would freeze one platform's
default into the file and break that identity. PDF is the exception that
proves the rule: reportlab has no theme, so house must name a face there, and
names the base-14 Helvetica the renderer has always drawn with.

The curated set is four families, not a combinatorial space of display×body
pairs, for the same reason ``style.py``'s fill palettes are curated triples:
which display face belongs over which body face is a designer's judgement
call, and a family is one identity rather than two independent draws.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["TYPEFACES", "Typeface", "named", "pdf_italic"]


@dataclass(frozen=True)
class Typeface:
    """One family's concrete faces, per format.

    ``display``/``body`` are OOXML font names or ``None`` for the theme
    default; ``pdf_display``/``pdf_body`` are base-14 family *prefixes* a
    renderer composes weight/style variants onto; ``html_display``/``html_body``
    are CSS stacks or ``None`` to leave the user-agent font alone.
    """

    display: str | None
    body: str | None
    pdf_display: str
    pdf_body: str
    html_display: str | None
    html_body: str | None


TYPEFACES: dict[str, Typeface] = {
    "house_sans": Typeface(
        display=None, body=None,
        pdf_display="Helvetica", pdf_body="Helvetica",
        html_display=None, html_body=None,
    ),
    "editorial_serif": Typeface(
        display="Georgia", body="Georgia",
        pdf_display="Times", pdf_body="Times",
        html_display='Georgia, "Times New Roman", serif',
        html_body='Georgia, "Times New Roman", serif',
    ),
    "engineering_mono": Typeface(
        display="Consolas", body="Consolas",
        pdf_display="Courier", pdf_body="Courier",
        html_display='Consolas, ui-monospace, "Courier New", monospace',
        html_body='Consolas, ui-monospace, "Courier New", monospace',
    ),
    "director_serif": Typeface(
        display="Georgia", body=None,
        pdf_display="Times", pdf_body="Helvetica",
        html_display='Georgia, "Times New Roman", serif',
        html_body=None,
    ),
}


def named(family: str) -> Typeface:
    """The family's faces. Unknown names are refused, never defaulted."""
    try:
        return TYPEFACES[family]
    except KeyError:
        raise KeyError(
            f"unknown typeface family {family!r}; known: {sorted(TYPEFACES)}."
            " Families are sampled by compiler.style and resolved here, so a"
            " name unknown to this table means the two halves of the contract"
            " have drifted."
        ) from None


def pdf_italic(family: str) -> str:
    """Return the valid base-14 italic face for a PDF font family.

    Helvetica and Courier call their slanted faces ``Oblique``. Times calls its
    face ``Italic``. Treating all base-14 families as suffix-compatible stayed
    hidden while the default style used Helvetica; ecology's deterministic
    style variation correctly exposed the invalid ``Times-Oblique`` name.
    """
    return "Times-Italic" if family == "Times" else f"{family}-Oblique"
