"""Tests for `worldloom.compiler.style` — the style genome and layout families.

Same idiom as `test_lifetimes.py`: build the smallest case a property exists
for, assert it holds, and where a check exists to catch a real failure mode
(the contrast floor, monotonic scales, distinctness), assert on the computed
thing itself rather than on a flag the sampler sets. A sampler that could be
made to report "safe" without being safe is not tested by trusting its own
report card.
"""

from __future__ import annotations

import itertools

import pytest

from worldloom.compiler.components import component
from worldloom.compiler.style import (
    CONTRAST_FLOOR,
    contrast_ratio,
    genome,
    genomes,
    layout_for,
    relative_luminance,
)
from worldloom.rng import Rng

# A large-ish sample, per the task's own suggestion — big enough that a
# contrast or monotonicity defect reachable only occasionally would show up,
# small enough that the suite stays fast.
_SAMPLE_SIZE = 200


# ---------------------------------------------------------------------------
# 0. The colour math itself
# ---------------------------------------------------------------------------


def test_relative_luminance_of_black_and_white_are_the_formula_extremes() -> None:
    assert relative_luminance("000000") == pytest.approx(0.0, abs=1e-9)
    assert relative_luminance("FFFFFF") == pytest.approx(1.0, abs=1e-9)


def test_contrast_ratio_of_black_against_white_is_21_to_1() -> None:
    """The WCAG formula's own known extreme: (1+0.05)/(0+0.05) = 21."""
    assert contrast_ratio("000000", "FFFFFF") == pytest.approx(21.0, rel=1e-9)
    assert contrast_ratio("FFFFFF", "000000") == pytest.approx(21.0, rel=1e-9), "symmetric"


# ---------------------------------------------------------------------------
# 1. Determinism: same seed -> identical genome, different seed -> different
# ---------------------------------------------------------------------------


def test_same_seed_yields_an_identical_genome_field_by_field() -> None:
    a = genome(Rng(8128).derive("style"))
    b = genome(Rng(8128).derive("style"))

    assert a.key == b.key
    assert a.type_scale == b.type_scale
    assert a.spacing_scale == b.spacing_scale
    assert a.table_density == b.table_density
    assert a.title_alignment == b.title_alignment
    assert a.rule_weight == b.rule_weight
    assert a.whitespace_bias == b.whitespace_bias
    assert a.colour_roles == b.colour_roles
    assert a.gridline_policy == b.gridline_policy
    assert a.number_negatives == b.number_negatives
    assert a == b, "equal field-by-field must also mean equal as a dataclass"


def test_different_seed_yields_a_different_genome() -> None:
    a = genome(Rng(1).derive("style"))
    b = genome(Rng(2).derive("style"))

    assert a.key != b.key
    assert a != b


def test_genome_rejects_an_unknown_archetype() -> None:
    with pytest.raises(ValueError, match="unknown archetype"):
        genome(Rng(1).derive("style"), archetype="bespoke")


# ---------------------------------------------------------------------------
# 2. The contrast floor — the check that makes sampling safe
# ---------------------------------------------------------------------------

#: Every (fill role, text role) pair `render/docx.py`-shaped prose would
#: actually paint text on top of. Checked directly against `contrast_ratio`,
#: not against a "this genome is safe" flag the sampler could set and be
#: wrong about.
_TEXT_ON_FILL_PAIRS: tuple[tuple[str, str], ...] = (
    ("header_fill", "header_text"),
    ("subtotal_fill", "subtotal_text"),
    ("background", "body_text"),
    ("background", "negative_text"),
)


def test_every_genome_in_a_large_sample_clears_the_contrast_floor() -> None:
    for candidate in genomes(_SAMPLE_SIZE, seed=8128):
        for fill_role, text_role in _TEXT_ON_FILL_PAIRS:
            fill, text = candidate.colour_roles[fill_role], candidate.colour_roles[text_role]
            ratio = contrast_ratio(fill, text)
            assert ratio >= CONTRAST_FLOOR, (
                f"{candidate.key}: {text_role}={text!r} on {fill_role}={fill!r} "
                f"scores {ratio:.3f}, below the {CONTRAST_FLOOR} floor"
            )


def test_the_contrast_floor_holds_across_every_curated_fill_palette_too() -> None:
    """`genomes` samples palettes with `Rng`, which does not promise to visit
    every entry in a sample of 200 — this pins down each curated fill
    directly, including the archetypes that bias away from a uniform pick,
    so a palette entry added later that happens to be rare under `Rng.choice`
    cannot go unchecked."""
    from worldloom.compiler.style import (
        _FILL_PALETTES,  # the module's own data, not re-derived
    )

    for index in range(len(_FILL_PALETTES)):
        # Force each palette by sampling until `Rng.choice` lands on it —
        # bounded, and only exercised in a test, never in `genome` itself.
        found = None
        for attempt in range(200):
            candidate = genome(Rng(attempt).derive("style"))
            if candidate.colour_roles["header_fill"] == _FILL_PALETTES[index][0]:
                found = candidate
                break
        assert found is not None, f"palette {index} ({_FILL_PALETTES[index]}) never sampled in 200 seeds"
        for fill_role, text_role in _TEXT_ON_FILL_PAIRS:
            ratio = contrast_ratio(found.colour_roles[fill_role], found.colour_roles[text_role])
            assert ratio >= CONTRAST_FLOOR


# ---------------------------------------------------------------------------
# 3. Monotonic scales
# ---------------------------------------------------------------------------


def test_type_scale_is_strictly_decreasing_in_every_sampled_genome() -> None:
    for candidate in genomes(_SAMPLE_SIZE, seed=42):
        sizes = candidate.type_scale
        assert all(a > b for a, b in itertools.pairwise(sizes)), (candidate.key, sizes)


def test_spacing_scale_is_non_increasing_in_every_sampled_genome() -> None:
    for candidate in genomes(_SAMPLE_SIZE, seed=42):
        spacing = candidate.spacing_scale
        assert all(a >= b for a, b in itertools.pairwise(spacing)), (candidate.key, spacing)


# ---------------------------------------------------------------------------
# 4. genomes(n) yields n distinct genomes
# ---------------------------------------------------------------------------


def test_genomes_of_50_yields_50_distinct_genomes() -> None:
    sampled = genomes(50, seed=8128)

    assert len(sampled) == 50
    assert len({g.key for g in sampled}) == 50, "distinctness asserted on computed keys, not assumed"
    # Belt and braces: distinct keys should mean distinct genomes, since the
    # key is a content address of every other field.
    for i, a in enumerate(sampled):
        for b in sampled[i + 1 :]:
            assert a != b


def test_genomes_is_itself_deterministic() -> None:
    assert genomes(20, seed=99) == genomes(20, seed=99)


# ---------------------------------------------------------------------------
# 5. The current docx palette is a reachable point in the space
# ---------------------------------------------------------------------------


def test_house_archetype_reproduces_the_shipped_docx_palette() -> None:
    """`render/docx.py` hard-codes `_HEADER_FILL`, `_SUBTOTAL_FILL`, white
    header text, and a `9B2226` negative-figure red. This is not an
    approximation of that look — every one of those hex values, plus the
    black-on-white body/subtotal text Word's own defaults produce, comes out
    of `genome()` exactly, proving the current renderer's look is one point
    in this space rather than a separate thing this module coexists with."""
    from worldloom.render.docx import _HEADER_FILL, _SUBTOTAL_FILL

    house = genome(Rng(8128).derive("style"), archetype="house")

    assert house.colour_roles["header_fill"] == _HEADER_FILL
    assert house.colour_roles["header_text"] == "FFFFFF"
    assert house.colour_roles["subtotal_fill"] == _SUBTOTAL_FILL
    assert house.colour_roles["subtotal_text"] == "000000"
    assert house.colour_roles["background"] == "FFFFFF"
    assert house.colour_roles["body_text"] == "000000"
    assert house.colour_roles["negative_text"] == "9B2226"
    assert house.colour_roles["accent"] == _HEADER_FILL

    assert house.table_density == "normal"
    assert house.title_alignment == "left"
    assert house.gridline_policy == "all"
    assert house.number_negatives == "parenthesised"


def test_house_archetype_is_itself_still_deterministic_and_seed_varying() -> None:
    """`"house"` pins the palette and the structural fields, not the whole
    genome — `type_scale`/`spacing_scale`/`rule_weight`/`whitespace_bias`
    still vary by seed, so `"house"` is a family, not a single frozen
    genome."""
    a = genome(Rng(1).derive("style"), archetype="house")
    b = genome(Rng(1).derive("style"), archetype="house")
    c = genome(Rng(2).derive("style"), archetype="house")

    assert a == b
    assert a.colour_roles == c.colour_roles, "the pinned palette does not vary"
    assert a.type_scale != c.type_scale or a.spacing_scale != c.spacing_scale, (
        "a family, not one frozen genome"
    )


# ---------------------------------------------------------------------------
# 6. layout_for — deterministic and shape-driven
# ---------------------------------------------------------------------------


def test_layout_for_is_deterministic() -> None:
    spec = component("finance.variance_table")
    a = layout_for(spec, rows=3, columns=2, density=0.4, rng=Rng(8128))
    b = layout_for(spec, rows=3, columns=2, density=0.4, rng=Rng(8128))
    assert a == b


def test_layout_for_gives_a_3_row_and_a_40_row_table_different_layouts() -> None:
    spec = component("finance.variance_table")
    small = layout_for(spec, rows=3, columns=2, density=0.4, rng=Rng(1))
    large = layout_for(spec, rows=40, columns=2, density=0.4, rng=Rng(1))

    assert small == "compact_list"
    assert large == "table"
    assert small != large


@pytest.mark.parametrize(
    ("component_id", "rows", "columns", "expected"),
    [
        ("finance.metric_strip", 4, 4, "metric_cards"),
        ("finance.metric_strip", 6, 6, "compact_list"),
        ("finance.variance_bridge", 5, 1, "bridge"),
        ("finance.variance_bridge", 9, 1, "table"),
        ("finance.comparative_trend", 12, 4, "stacked"),
        ("finance.comparative_trend", 12, 8, "table"),
        ("core.schedule", 2, 2, "compact_list"),
        ("core.schedule", 10, 2, "table"),
        ("ops.incident_timeline", 5, 1, "stacked"),
        ("ops.incident_timeline", 20, 1, "table"),
        ("mgmt.decision_panel", 15, 2, "two_column"),
        ("mgmt.decision_panel", 15, 3, "stacked"),
        ("mgmt.risk_matrix", 3, 1, "full_width"),
        ("mgmt.risk_matrix", 12, 1, "table"),
    ],
)
def test_layout_for_is_shape_driven(component_id: str, rows: int, columns: int, expected: str) -> None:
    spec = component(component_id)
    assert layout_for(spec, rows=rows, columns=columns, density=0.5, rng=Rng(1)) == expected


def test_layout_for_breaks_a_genuine_tie_with_rng_but_stays_deterministic() -> None:
    """`mgmt.risk_matrix` at 5-8 rows has no shape-driven answer — both of its
    declared layouts are legible — so the choice comes from `rng` alone. It
    still has to be reproducible for the same `rng`, and it must never pick
    a layout the component did not declare."""
    spec = component("mgmt.risk_matrix")

    first = layout_for(spec, rows=6, columns=1, density=0.5, rng=Rng(5))
    second = layout_for(spec, rows=6, columns=1, density=0.5, rng=Rng(5))
    assert first == second
    assert first in spec.layouts

    # A different rng stream is free to break the same tie the other way —
    # otherwise it would not be a tie broken by rng at all.
    outcomes = {layout_for(spec, rows=6, columns=1, density=0.5, rng=Rng(s)) for s in range(20)}
    assert outcomes <= {"full_width", "table"}


def test_layout_for_a_component_with_no_declared_layouts_returns_a_sensible_default() -> None:
    """`core.narrative` declares no `layouts` — most of the registry does not —
    and must get a usable answer back rather than an exception."""
    spec = component("core.narrative")
    assert spec.layouts == frozenset()

    result = layout_for(spec, rows=0, columns=0, density=0.5, rng=Rng(1))

    assert result == "full_width"


def test_layout_for_never_returns_a_layout_the_component_did_not_declare() -> None:
    for candidate_id in (
        "finance.variance_table",
        "finance.metric_strip",
        "finance.variance_bridge",
        "finance.comparative_trend",
        "core.schedule",
        "ops.incident_timeline",
        "ops.remediation_table",
        "mgmt.decision_panel",
        "mgmt.risk_matrix",
    ):
        spec = component(candidate_id)
        for rows in (0, 1, 2, 3, 5, 8, 12, 40):
            for columns in (1, 2, 4, 8):
                result = layout_for(spec, rows=rows, columns=columns, density=0.5, rng=Rng(rows + columns))
                assert result in spec.layouts, (candidate_id, rows, columns, result)


# ---------------------------------------------------------------------------
# 7. The typeface axis and its render-side resolution
# ---------------------------------------------------------------------------


def test_house_pins_the_typeface_the_shipped_renderers_used() -> None:
    """The family half of the palette pin above. The look that shipped was
    Helvetica in PDF, the theme defaults in Word and PowerPoint, and the
    user-agent stack in HTML — which is `house_sans` resolved per format, so
    `"house"` must select exactly that entry and not a family that would
    restyle every existing corpus."""
    house = genome(Rng(8128).derive("style"), archetype="house")
    assert house.typeface == "house_sans"


def test_every_family_the_sampler_draws_resolves_in_the_render_table() -> None:
    """`compiler.style` names families; `render.fonts` resolves them. A family
    one half knows and the other does not is drift between the two halves of
    one contract, and the refusal in `fonts.named` is where it would surface —
    so every sampled genome is resolved here, not just one."""
    from worldloom.render import fonts

    for candidate in genomes(_SAMPLE_SIZE, seed=7):
        fonts.named(candidate.typeface)


def test_the_house_family_names_no_face_a_theme_already_decides() -> None:
    """House is inert in the theme-bearing formats: `None` means "set no font
    name", which is exactly what the OOXML renderers did before typefaces
    existed and what HTML's user-agent stylesheet does. Resolving house to a
    literal name there would freeze one platform's default into the file and
    break the byte-identity of an un-restyled corpus. PDF is the exception
    that proves the rule — reportlab has no theme, so house names the base-14
    Helvetica the renderer always drew with."""
    from worldloom.render import fonts

    house = fonts.named("house_sans")
    assert house.display is None and house.body is None
    assert house.html_display is None and house.html_body is None
    assert house.pdf_display == "Helvetica" and house.pdf_body == "Helvetica"


def test_an_unknown_family_is_refused_rather_than_defaulted_to_house() -> None:
    """A silent fallback would make a recorded genome key lie about what the
    corpus looks like — same posture as every registry that accepts a name."""
    from worldloom.render import fonts

    with pytest.raises(KeyError, match="unknown typeface family"):
        fonts.named("bespoke")


def test_the_typeface_axis_varies_across_seeds() -> None:
    """A fourth axis that every seed drew identically would add a field and no
    diversity. Across a sample, more than one family must appear."""
    seen = {candidate.typeface for candidate in genomes(_SAMPLE_SIZE, seed=8128)}
    assert len(seen) > 1, seen
