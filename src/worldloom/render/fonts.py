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

__all__ = ["TYPEFACES", "Typeface", "named"]


@dataclass(frozen=True)
class Typeface:
    """One family's concrete faces, per format.

    ``display``/``body`` are OOXML font names or ``None`` for the theme
    default; ``pdf_display``/``pdf_body`` are base-14 family *prefixes* a
    renderer composes ``"-Bold"``/``"-Oblique"`` onto (base-14 ships no other
    weights, and embedding TTFs would put a licence question inside a corpus
    build); ``html_display``/``html_body`` are CSS stacks or ``None`` to leave
    the user-agent font alone.
    """

    display: str | None
    body: str | None
    pdf_display: str
    pdf_body: str
    html_display: str | None
    html_body: str | None


#: Keyed ``str`` rather than ``TypefaceFamily`` so the unknown-name refusal in
#: `named` is a runtime check on real input, not a type error the checker
#: already prevents — the same posture as every registry that accepts a name
#: that may have come from a document.
TYPEFACES: dict[str, Typeface] = {
    # Entry 0 by contract: the shipped look, every format. See the module
    # docstring for why "the shipped look" is *no* font name in the two
    # theme-bearing formats and the user-agent stack in HTML.
    "house_sans": Typeface(
        display=None, body=None,
        pdf_display="Helvetica", pdf_body="Helvetica",
        html_display=None, html_body=None,
    ),
    # Serif throughout. Heritage, insurance, legal — the corpus that reads
    # like it has been filing reports since before the rebrand.
    "editorial_serif": Typeface(
        display="Georgia", body="Georgia",
        pdf_display="Times", pdf_body="Times",
        html_display='Georgia, "Times New Roman", serif',
        html_body='Georgia, "Times New Roman", serif',
    ),
    # Monospaced. Logistics, engineering, operations — the corpus whose
    # reports came out of a terminal culture.
    "engineering_mono": Typeface(
        display="Consolas", body="Consolas",
        pdf_display="Courier", pdf_body="Courier",
        html_display='Consolas, ui-monospace, "Courier New", monospace',
        html_body='Consolas, ui-monospace, "Courier New", monospace',
    ),
    # Serif display over sans body: the annual-report hybrid, where the cover
    # and the headings carry the heritage and the body stays plain. The body
    # faces stay ``None``/Helvetica so the *body* of a director_serif document
    # is the house body — the hybrid, not a second full-serif identity.
    "director_serif": Typeface(
        display="Georgia", body=None,
        pdf_display="Times", pdf_body="Helvetica",
        html_display='Georgia, "Times New Roman", serif',
        html_body=None,
    ),
}


def named(family: str) -> Typeface:
    """The family's faces. Unknown names are refused, never defaulted.

    A genome sampled by one version of ``style.py`` and resolved by a later
    ``fonts.py`` that dropped a family must fail loudly here rather than
    quietly render as house — a silent fallback would make a corpus's recorded
    genome key lie about what it looks like.
    """
    try:
        return TYPEFACES[family]
    except KeyError:
        raise KeyError(
            f"unknown typeface family {family!r}; known: {sorted(TYPEFACES)}."
            " Families are sampled by compiler.style and resolved here, so a"
            " name unknown to this table means the two halves of the contract"
            " have drifted."
        ) from None
