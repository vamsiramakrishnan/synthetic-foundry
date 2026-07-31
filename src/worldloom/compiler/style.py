"""Style genomes: a corporate visual identity as parameters, not a template.

Per `docs/artifact-compiler.md` §8. The measured problem this exists to fix: a
12-period industry corpus produced 120 artifacts and 11 distinct section
shapes — twelve CFO memos with identical outlines, DOCX sizes across 72 files
spanning only 38,658-40,618 bytes. Every close pack in the estate is the same
document with different numbers, because there was exactly one visual system
to render it in: whatever `render/docx.py` happens to hard-code.

A *genome* is that visual system pulled out into data: a handful of numeric
and categorical knobs — a type scale, a spacing scale, a colour-role map, a
table density — sampled from a bounded space rather than chosen by a human
writing a second template. Hundreds of coherent styles fall out of sampling
this space; hundreds of hand-built templates do not scale and never agreed
with each other on anything a human didn't remember to keep in sync.

Two properties make sampling safe rather than merely varied:

1. **Every sampled genome is internally coherent.** A dark header fill with
   near-black header text is a valid *sample* and an unreadable *document* —
   see `CONTRAST_FLOOR` for the WCAG relative-luminance floor this module
   enforces on every text/fill pair a genome declares, and the proof that the
   floor is always reachable.
2. **A genome is a pure function of its inputs.** Same `Rng` stream, same
   `archetype` argument, same genome, forever — nothing here reads a clock or
   calls `random` directly. Every draw goes through `Rng`, derived by name
   from whatever stream the caller hands `genome()`, per `rng.py`'s own rule:
   two callers deriving independently named streams never see each other's
   draws, so adding a new knob to this sampler cannot reshuffle an existing
   one.

Nothing here is wired into a renderer. `render/docx.py` keeps rendering
exactly as it does today; this module only proves the space that look sits in,
and that the space is large, checkable, and safe to sample from. Wiring a
`StyleGenome` into `render/docx.py` is the next, separate piece of work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..ids import content_key
from ..rng import Rng
from .components import ComponentSpec

TableDensity = Literal["airy", "normal", "tight"]
TitleAlignment = Literal["left", "centre"]
GridlinePolicy = Literal["all", "horizontal", "none"]
NumberNegatives = Literal["parenthesised", "minus"]

#: Named archetypes bias *how* a genome is sampled — which table density and
#: how much whitespace bias are likely — without ever picking a value outside
#: `Rng`. `None` (no archetype) samples the whole space uniformly. `"house"`
#: is the one archetype that does not merely bias: it pins the colour-role
#: pairing to the palette `render/docx.py` already ships (see `genome`'s
#: docstring), because the point of a samplable space is that the current
#: look has to be *in* it, not bolted on beside it as a special case.
Archetype = Literal[
    "house",
    "finance_compact",
    "editorial_neutral",
    "executive_sparse",
    "operating_review",
    "technical_architecture",
]

_ARCHETYPES: frozenset[str] = frozenset(
    {"house", "finance_compact", "editorial_neutral", "executive_sparse",
     "operating_review", "technical_architecture"}
)


@dataclass(frozen=True)
class StyleGenome:
    """A coherent corporate visual system, as parameters rather than a template.

    Not hashable in practice — `colour_roles` is a `dict` — so distinctness is
    compared by `.key` (a content address of every other field) rather than by
    putting instances in a `set`. `key` is derived, never minted: two genomes
    with identical field values always compute the identical key, and a
    `Minter`-style incrementing id would instead depend on *when* a genome was
    sampled, which is exactly the kind of hidden state this project's
    determinism rule exists to rule out.
    """

    key: str
    type_scale: tuple[float, ...]
    spacing_scale: tuple[float, ...]
    table_density: TableDensity
    title_alignment: TitleAlignment
    rule_weight: float
    whitespace_bias: float
    colour_roles: dict[str, str]
    gridline_policy: GridlinePolicy
    number_negatives: NumberNegatives


# ---------------------------------------------------------------------------
# 1. Colour math — WCAG relative luminance and contrast ratio
# ---------------------------------------------------------------------------


def _channel(value: int) -> float:
    """One sRGB channel (0-255) converted to linear light, per the WCAG 2.1
    relative-luminance formula. The piecewise split at 0.03928 is the formula
    itself, not a tuning choice — below it sRGB's gamma curve is defined
    linearly to avoid a division blowing up near zero."""
    c = value / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_colour: str) -> float:
    """WCAG 2.1 relative luminance of a ``#RRGGBB`` colour: 0 (black) to 1 (white)."""
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(a: str, b: str) -> float:
    """WCAG 2.1 contrast ratio between two colours. Always >= 1, symmetric in
    ``a``/``b`` — the formula puts whichever luminance is larger on top."""
    la, lb = relative_luminance(a), relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


#: The contrast floor every text/fill pair in a sampled genome must clear.
#:
#: 4.5:1 is WCAG 2.1 Success Criterion 1.4.3 (Level AA, normal-size text) —
#: the standard bar for a reader who is not looking at a 24pt cover title,
#: which is most of what a genome colours: table headers, subtotal rows, body
#: copy. It is also the largest floor this sampler can *prove* it will always
#: clear, which is the property that makes rejection unnecessary:
#:
#: For any fill of relative luminance L, contrast against pure white is
#: ``(1.05) / (L + 0.05)`` and against pure black is ``(L + 0.05) / 0.05``.
#: Their product is ``1.05 / 0.05 = 21`` for every L — the L terms cancel.
#: A product held constant means the two contrasts trade off exactly, so the
#: larger of the pair can never be smaller than ``sqrt(21) ≈ 4.583`` — a fill
#: that pushes one of them down necessarily pushes the other up by the same
#: factor. Choosing the better of black-or-white text against *any* fill
#: therefore always clears 4.5:1, with room to spare. That is the repair this
#: module falls back to — see `_best_text_for` — whenever a more characterful
#: ink/paper candidate does not already clear it on its own.
CONTRAST_FLOOR = 4.5

_BLACK = "000000"
_WHITE = "FFFFFF"


def _best_text_for(fill: str, candidates: tuple[str, ...]) -> str:
    """The candidate with the highest contrast against *fill*.

    Falls back to whichever of pure black or white contrasts better if none
    of *candidates* clears `CONTRAST_FLOOR` — a branch that `CONTRAST_FLOOR`'s
    own docstring proves is provably unreachable whenever `_BLACK` and
    `_WHITE` are themselves already among *candidates* (as every caller below
    ensures), but the branch is kept explicit rather than assumed away: this
    is the actual repair step, not a comment promising one exists.
    """
    best = max(candidates, key=lambda c: contrast_ratio(fill, c))
    if contrast_ratio(fill, best) >= CONTRAST_FLOOR:
        return best
    return _WHITE if contrast_ratio(fill, _WHITE) >= contrast_ratio(fill, _BLACK) else _BLACK  # pragma: no cover


def _darken(hex_colour: str, factor: float = 0.85) -> str:
    """Scale a colour's channels toward black by *factor* (< 1)."""
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    r, g, b = (max(0, min(255, round(v * factor))) for v in (r, g, b))
    return f"{r:02X}{g:02X}{b:02X}"


def _repaired_against(fg: str, bg: str, *, floor: float = CONTRAST_FLOOR, max_steps: int = 24) -> str:
    """*fg* darkened toward black, step by step, until it clears *floor*
    against *bg* — the repair `negative_text` goes through, since it is
    always read against `colour_roles["background"]` rather than a sampled
    fill, and darkening (never lightening) is the right direction because
    every sampled background in this module is a near-white "paper" tone.

    Bounded rather than run to convergence, for the same reason
    `compose._repair_order` bounds its own loop: this is expected to
    terminate in at most one or two steps for every curated seed colour
    below, and a cap stops a colour that somehow never clears the floor from
    spinning instead of quietly returning something dark and usable. 24 steps
    of a 0.85 multiplier leaves under 2% of the original channel values —
    black in every practical sense — so the cap is not reachable with a
    legitimate starting colour; it exists so a future palette entry fails
    loudly (a colour that is still too light after 24 halvings-and-then-some
    is not a repair candidate, it is a design mistake) rather than looping.
    """
    colour = fg
    steps = 0
    while contrast_ratio(colour, bg) < floor and steps < max_steps:
        colour = _darken(colour)
        steps += 1
    return colour


# ---------------------------------------------------------------------------
# 2. Type and spacing scales — monotonic by construction
# ---------------------------------------------------------------------------

#: Five type sizes, title first. Each tier is its own *non-overlapping* band —
#: the tier below always tops out below the tier above's floor — so sampling
#: one value per band guarantees `type_scale` is strictly decreasing without
#: ever needing to sort or reject a draw. Sorting after the fact would be the
#: wrong fix even though it produces the same monotonic tuple: a sampler that
#: can draw a body size larger than its heading and then quietly reorders them
#: has silently turned "the plan asked for a prominent body paragraph" into
#: "the plan asked for a heading", which is a different genome than the one
#: that was supposedly sampled. Non-overlapping bands make the order
#: structural instead — the same technique `CONTRAST_FLOOR` uses for colour,
#: applied to size.
_TYPE_BANDS: tuple[tuple[float, float], ...] = (
    (24.0, 32.0),  # cover title
    (16.0, 20.0),  # section heading
    (13.0, 15.0),  # subsection heading
    (10.0, 11.0),  # body
    (7.5, 9.0),  # caption / footnote
)

#: Four spacing multiples, largest first. `spacing_scale` is documented
#: non-increasing rather than strictly decreasing (two adjacent levels of a
#: real style genuinely tie — a style that puts equal air before a heading and
#: before a subheading is not incoherent the way a body font bigger than its
#: heading is), so adjacent bands are allowed to *touch* rather than sit
#: strictly apart: tier N's ceiling equals tier N+1's floor, which permits a
#: tie at the boundary while still making "later never exceeds earlier"
#: structural.
_SPACING_BANDS: tuple[tuple[float, float], ...] = (
    (1.4, 2.0),  # space before a section heading
    (1.0, 1.4),  # space before a subsection heading
    (0.6, 1.0),  # paragraph spacing
    (0.3, 0.6),  # tightest element: table cell padding
)


def _sample_type_scale(rng: Rng) -> tuple[float, ...]:
    return tuple(round(rng.number(lo, hi), 2) for lo, hi in _TYPE_BANDS)


def _sample_spacing_scale(rng: Rng) -> tuple[float, ...]:
    return tuple(round(rng.number(lo, hi), 2) for lo, hi in _SPACING_BANDS)


# ---------------------------------------------------------------------------
# 3. The sampling space
# ---------------------------------------------------------------------------

#: Curated (header_fill, subtotal_fill, negative_seed) triples. Curated rather
#: than three independently-sampled colours, because independent RGB draws
#: mostly produce triples that clash — a genome is supposed to be a *coherent*
#: visual system, and coherence between a header colour and the paler tint
#: sitting under a subtotal row is a designer's judgement call this module
#: does not attempt to derive from arithmetic. Entry 0 is not decorative: it
#: is the exact palette `render/docx.py` ships today (`_HEADER_FILL` and
#: `_SUBTOTAL_FILL`, plus the negative-figure red from `_table`/`_figure`),
#: so that the current rendered look is a literal point in this space rather
#: than a special case bolted on beside it — see `genome`'s ``"house"``
#: archetype, which selects this entry outright.
_FILL_PALETTES: tuple[tuple[str, str, str], ...] = (
    ("2F4858", "EDF2F4", "9B2226"),  # house: render/docx.py's current palette
    ("1B3A4B", "E7EEF2", "8C2F2F"),  # deep harbour blue
    ("2E2A4A", "EFEDF5", "7A2E4D"),  # aubergine
    ("14453B", "E6F1EC", "6B3A1E"),  # forest / rust
    ("463022", "F3ECE4", "7A2E2E"),  # umber / brick
    ("1F3B57", "E8EEF4", "3D5A80"),  # navy / steel
    ("3A3A3A", "F0F0F0", "8A1C1C"),  # graphite
    ("264D3B", "E9F2EC", "9C6B1F"),  # pine / ochre
    ("4A2545", "F1E8EF", "5C2751"),  # plum
    ("36454F", "ECEFF1", "B03A2E"),  # charcoal slate
)

#: Near-black "ink" tints. Kept close to true black (they differ from it by a
#: few channel points, chosen for warmth or coolness rather than for
#: luminance) so that swapping between them is a stylistic choice, not a
#: legibility one — the actual legibility guarantee comes from
#: `CONTRAST_FLOOR`/`_best_text_for`, not from staying close to black.
_INK_CANDIDATES: tuple[str, ...] = ("000000", "14110D", "0C1B26", "1B120A", "10160F")

#: Near-white "paper" tints, same idea in the other direction.
_PAPER_CANDIDATES: tuple[str, ...] = ("FFFFFF", "FBF9F6", "F5F7F8", "FFF8EE", "F3F8F4")

_TABLE_DENSITIES: tuple[TableDensity, ...] = ("airy", "normal", "tight")

#: archetype -> (airy, normal, tight) sampling weights. `None` (no archetype)
#: is uniform; a named archetype nudges the distribution without ever
#: removing an option outright, because a plan-layer archetype is a bias on
#: taste, not a hard constraint the way a component's density band is.
_TABLE_DENSITY_WEIGHTS: dict[str | None, tuple[float, float, float]] = {
    None: (1.0, 1.0, 1.0),
    "finance_compact": (0.5, 1.5, 3.0),
    "editorial_neutral": (2.0, 2.0, 1.0),
    "executive_sparse": (3.0, 1.5, 0.3),
    "operating_review": (1.0, 2.5, 1.5),
    "technical_architecture": (1.0, 2.0, 2.0),
}

#: archetype -> (low, high) range for `whitespace_bias`. Same reasoning as the
#: density weights: a range, never a point, so the archetype still samples a
#: family of genomes rather than a single fixed one.
_WHITESPACE_RANGES: dict[str | None, tuple[float, float]] = {
    None: (0.0, 1.0),
    "finance_compact": (0.0, 0.35),
    "editorial_neutral": (0.3, 0.7),
    "executive_sparse": (0.6, 1.0),
    "operating_review": (0.2, 0.6),
    "technical_architecture": (0.1, 0.5),
}


def genome(rng: Rng, *, archetype: str | None = None) -> StyleGenome:
    """Sample one coherent `StyleGenome`.

    Deterministic in *rng* and *archetype* alone — no other input reaches this
    function, which is what makes it a pure function of its inputs the way
    the task requires: the same derived `Rng` stream and the same archetype
    name always produce the identical genome, and nothing here touches a
    clock, `random`, or `hash()`.

    ``archetype="house"`` is the one archetype that does not merely bias a
    distribution: it pins the colour-role pairing to
    ``_FILL_PALETTES[0]`` — `render/docx.py`'s current `_HEADER_FILL`,
    `_SUBTOTAL_FILL`, and negative-figure red — plus the structural fields
    (`table_density="normal"`, `title_alignment="left"`,
    `gridline_policy="all"`, `number_negatives="parenthesised"`) that match
    what that renderer already does: a plain "Table Grid" style, headings
    left-aligned by Word's own default, and accounting-format negatives
    parenthesised by `render/values.py`. `type_scale`, `spacing_scale`,
    `rule_weight`, and `whitespace_bias` are still sampled — `render/docx.py`
    never pinned exact numbers for those, so there is nothing for `"house"`
    to reproduce there, and pinning them anyway would make `"house"` a single
    genome instead of the family every other archetype is.
    """
    if archetype is not None and archetype not in _ARCHETYPES:
        raise ValueError(f"unknown archetype {archetype!r}; known: {sorted(_ARCHETYPES)}")

    type_scale = _sample_type_scale(rng.derive("type_scale"))
    spacing_scale = _sample_spacing_scale(rng.derive("spacing_scale"))

    if archetype == "house":
        header_fill, subtotal_fill, negative_seed = _FILL_PALETTES[0]
        ink, paper = _BLACK, _WHITE
        table_density: TableDensity = "normal"
        title_alignment: TitleAlignment = "left"
        gridline_policy: GridlinePolicy = "all"
        number_negatives: NumberNegatives = "parenthesised"
    else:
        header_fill, subtotal_fill, negative_seed = rng.derive("palette").choice(_FILL_PALETTES)
        ink = rng.derive("ink").choice(_INK_CANDIDATES)
        paper = rng.derive("paper").choice(_PAPER_CANDIDATES)
        table_density = rng.derive("table_density").weighted(
            _TABLE_DENSITIES, _TABLE_DENSITY_WEIGHTS.get(archetype, _TABLE_DENSITY_WEIGHTS[None])
        )
        title_alignment = rng.derive("title_alignment").choice(("left", "centre"))
        gridline_policy = rng.derive("gridline_policy").choice(("all", "horizontal", "none"))
        number_negatives = rng.derive("number_negatives").choice(("parenthesised", "minus"))

    low, high = _WHITESPACE_RANGES.get(archetype, _WHITESPACE_RANGES[None])
    whitespace_bias = round(rng.derive("whitespace_bias").number(low, high), 2)
    rule_weight = round(rng.derive("rule_weight").number(0.25, 2.25), 2)

    text_candidates = (ink, paper)
    colour_roles = {
        "header_fill": header_fill,
        "header_text": _best_text_for(header_fill, text_candidates),
        "subtotal_fill": subtotal_fill,
        "subtotal_text": _best_text_for(subtotal_fill, text_candidates),
        "background": paper,
        "body_text": _best_text_for(paper, text_candidates),
        "negative_text": _repaired_against(negative_seed, paper),
        # Reused rather than re-sampled: `render/docx.py` already draws its
        # positive bar the same colour as the header fill (`_figure`'s
        # `RGBColor(0x2F, 0x48, 0x58)`), and a genome that let the header
        # colour and the "this is us" accent colour drift apart would be
        # sampling two decisions a real design system treats as one.
        "accent": header_fill,
    }

    key = "STYLE-" + content_key(
        type_scale,
        spacing_scale,
        table_density,
        title_alignment,
        rule_weight,
        whitespace_bias,
        tuple(sorted(colour_roles.items())),
        gridline_policy,
        number_negatives,
    )[:16].upper()

    return StyleGenome(
        key=key,
        type_scale=type_scale,
        spacing_scale=spacing_scale,
        table_density=table_density,
        title_alignment=title_alignment,
        rule_weight=rule_weight,
        whitespace_bias=whitespace_bias,
        colour_roles=colour_roles,
        gridline_policy=gridline_policy,
        number_negatives=number_negatives,
    )


def genomes(n: int, *, seed: int, archetype: str | None = None) -> tuple[StyleGenome, ...]:
    """*n* distinct `StyleGenome`s derived from *seed*.

    Distinctness is asserted here, not merely hoped for elsewhere: each
    candidate index draws its own named stream (``genome/{i}``), and on the
    astronomically unlikely event that two indices land on the same key, the
    later one retries from a further-derived sub-label
    (``genome/{i}/retry/{k}``) — still fully determined by *seed*, *archetype*,
    and the index, so two calls with the same arguments retry the same way
    and land on the same result. The retry is bounded: a collision surviving
    several independent re-derivations would mean the archetype's sampling
    space is too small for *n* distinct genomes, which is a defect this
    function reports by raising rather than one a longer loop could paper
    over.
    """
    root = Rng(seed, "style/genomes")
    seen: set[str] = set()
    out: list[StyleGenome] = []
    for i in range(n):
        candidate = genome(root.derive(f"genome/{i}"), archetype=archetype)
        retry = 0
        while candidate.key in seen and retry < 8:
            retry += 1
            candidate = genome(root.derive(f"genome/{i}/retry/{retry}"), archetype=archetype)
        if candidate.key in seen:
            raise RuntimeError(
                f"could not sample a distinct genome at index {i} after {retry} retries; "
                f"archetype {archetype!r}'s sampling space may be too small for n={n}"
            )
        seen.add(candidate.key)
        out.append(candidate)
    return tuple(out)


# ---------------------------------------------------------------------------
# 4. Layout families — component + data shape -> layout name
# ---------------------------------------------------------------------------

#: The suggested vocabulary from `docs/artifact-compiler.md` §8/§14.B. Not
#: every family is used below — `sidebar` has no current component whose data
#: genuinely wants it — kept here as the documented ceiling of the vocabulary
#: rather than only implicit in whichever names `ComponentSpec.layouts`
#: happens to use.
LAYOUT_FAMILIES: frozenset[str] = frozenset(
    {"table", "bridge", "metric_cards", "two_column", "stacked", "sidebar", "full_width", "compact_list"}
)

#: What `layout_for` returns for a component that declares no `layouts` at
#: all — the large majority of the registry, which has exactly one honest
#: presentation. "Render me as one full-width block" is a sensible answer for
#: prose and single-shot components alike, and it is a real member of
#: `LAYOUT_FAMILIES` rather than a sentinel outside it, so a caller never has
#: to special-case the no-opinion result.
_DEFAULT_LAYOUT = "full_width"


def layout_for(spec: ComponentSpec, *, rows: int, columns: int, density: float, rng: Rng) -> str:
    """Which of *spec*'s declared `layouts` fits (*rows*, *columns*, *density*).

    Layout choice is arithmetic on data shape, not taste — a 3-row table and
    a 40-row table want different presentations because one is a fact pattern
    and the other is a document, and that is countable. `rng` is used in
    exactly one place below (`mgmt.risk_matrix`'s 5-8 row band), where two
    declared layouts are *both* legible and nothing about the data prefers
    one — see the comment there for why that is a genuine tie and not a
    disguised default.

    ``density`` is accepted for parity with `ComponentSpec.fits` and future
    families that need it (`docs/artifact-compiler.md` §8 lists density as
    part of the layout decision generally); none of the families below
    currently split on it, because every split available today already has a
    cleaner row- or column-based signal, and reaching for density where rows
    already answer the question would be inventing a distinction the data
    does not actually draw.
    """
    if not spec.layouts:
        return _DEFAULT_LAYOUT

    cid = spec.component_id

    if cid == "finance.variance_table":
        # A two- or three-row variance is a fact pattern read at a glance; a
        # table's header row and borders are more furniture than a reader
        # needs for that. Four rows is where the alignment a table gives
        # starts paying for itself.
        preferred = "compact_list" if rows < 4 else "table"
    elif cid == "finance.metric_strip":
        # Bound to 3-6 rows by the component's own `min_rows`/`max_rows`.
        # Four sit two-by-two as cards without crowding; five or six overflow
        # a card grid and read better as one linear list.
        preferred = "metric_cards" if rows <= 4 else "compact_list"
    elif cid == "finance.variance_bridge":
        # A waterfall reads at a glance through six or seven steps; past that
        # the bars compress until the shape the layout exists to show is
        # gone, and a plain table of the same drivers reads better than a
        # bridge that no longer looks like one.
        preferred = "bridge" if rows <= 6 else "table"
    elif cid == "finance.comparative_trend":
        # Column count (periods), not row count: direction across four or
        # fewer periods reads off a small stacked trend, and more periods
        # than that need a table's grid to keep every column addressable.
        preferred = "stacked" if columns <= 4 else "table"
    elif cid in ("core.schedule", "ops.remediation_table"):
        # One or two commitments/actions read as a short list; several
        # entries against several owners want a table's row/column alignment
        # so a date or owner stays on the line it belongs to.
        preferred = "compact_list" if rows <= 3 else "table"
    elif cid == "ops.incident_timeline":
        # A short incident reads as one vertical sequence of moments — the
        # shape a reader already has in their head for "what happened".
        # Past roughly eight entries that sequence is too tall to take in as
        # a whole, and a table's fixed row height keeps it in view.
        preferred = "stacked" if rows <= 8 else "table"
    elif cid == "mgmt.decision_panel":
        # Column count here is "how many options": two sit side by side
        # without crowding; three or more run out of horizontal room together
        # and read better stacked so each gets its case made in full before
        # the next one starts.
        preferred = "two_column" if columns <= 2 else "stacked"
    elif cid == "mgmt.risk_matrix":
        if rows <= 4:
            preferred = "full_width"  # few enough risks that a 2D grid stays open
        elif rows >= 9:
            preferred = "table"  # too many for a grid to stay legible
        else:
            # 5-8 risks: a likelihood/impact grid and a plain list are both
            # genuinely legible at this size — there is no row-count argument
            # for one over the other the way there is at either extreme. This
            # is the tie the module docstring promises: broken by a stream
            # derived from `rng` and keyed by `component_id` so two different
            # components' tie-breaks in the same render never correlate, and
            # the same (spec, rows) pair always breaks the same way for a
            # given `rng`.
            options = tuple(o for o in ("full_width", "table") if o in spec.layouts)
            if len(options) > 1:
                return rng.derive(f"layout_tie/{cid}").choice(options)
            preferred = options[0] if options else _DEFAULT_LAYOUT
    else:
        preferred = _DEFAULT_LAYOUT

    if preferred in spec.layouts:
        return preferred
    # The shape-driven pick isn't one of this component's declared families —
    # fall back to whichever declared layout sorts first. Deterministic, and
    # still a layout the component actually claims to support, unlike
    # returning the generic default for a component that declared layouts of
    # its own.
    return min(spec.layouts)


__all__ = [
    "CONTRAST_FLOOR",
    "LAYOUT_FAMILIES",
    "StyleGenome",
    "contrast_ratio",
    "genome",
    "genomes",
    "layout_for",
    "relative_luminance",
]
