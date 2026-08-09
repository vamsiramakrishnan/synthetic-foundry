"""Tests for the content primitives added on top of the thin waist —
`Cell.band`, `FlowDiagram`/`FlowNode`/`FlowEdge`, and `Quotation` — and the two
layers built on them: `required_inputs`/`optional_inputs` enforcement in
`compiler/compose.py`, and identity dispatch in `render/markdown.py` and
`render/pdf.py`.

Organised in the same order the task was: models first (can a section even
carry the primitive), then the registry and the composer (does declaring a
required input actually gate anything), then the renderers (does a component
that declared something get a different presentation from one that did not).

A recurring shape below is a hand-built, single-component registry
monkeypatched over `components.REGISTRY`. That is deliberate, not a shortcut
taken because the real one was inconvenient: `finance.heatmap`,
`mgmt.risk_matrix` and `ops.process_flow` are — pinned by
`test_the_three_required_input_components_are_unreachable_via_the_shipped_registry`
below — never actually selected by `compose()` against the shipped registry,
because an earlier, rowless, full-density component always wins their role
first. Proving `required_inputs` gates `compose()` at all therefore needs a
registry where the component under test is reachable, which the shipped one
does not offer for these three by construction (see each component's own
comment in `components.py` for why that is safe rather than a defect).
"""

from __future__ import annotations

import re

import pytest

from worldloom.compiler import components as components_module
from worldloom.compiler.compose import (
    CompositionError,
    compose,
    plan_from_ir,
    section_components,
)
from worldloom.compiler.components import REGISTRY, ComponentSpec, roles_for
from worldloom.compiler.plan import DENSITY_POINTS, ArtifactPlan, NarrativeBeat
from worldloom.models import (
    ArtifactIR,
    ArtifactSection,
    Cell,
    Column,
    FlowDiagram,
    FlowEdge,
    FlowNode,
    MagnitudeBand,
    Quotation,
    Row,
    Table,
)
from worldloom.render import markdown
from worldloom.render import pdf as pdf_renderer

# ---------------------------------------------------------------------------
# 1. Models — can a section carry the primitive at all
# ---------------------------------------------------------------------------


def test_cell_band_is_additive_and_defaults_to_none() -> None:
    """A cell built exactly the way every existing cell in this corpus is
    built — no ``band`` keyword at all — keeps behaving as one. This is the
    whole "additive and optional, defaulting to today's behaviour" contract,
    stated as a model-level assertion rather than only argued in a comment."""
    plain = Cell(value=100.0, fact_id="FACT-0001")
    assert plain.band is None


def test_cell_band_accepts_every_magnitude() -> None:
    for band in MagnitudeBand:
        assert Cell(value=1.0, band=band).band is band


def test_flow_diagram_rejects_an_edge_to_an_undeclared_node() -> None:
    """The same discipline `Cell._formula_needs_operands` already holds a
    formula to: a structural reference has to resolve inside the model that
    carries it, not be trusted to a renderer to notice is dangling."""
    with pytest.raises(ValueError, match="never declared"):
        FlowDiagram(
            nodes=[FlowNode(key="a", label="Step one")],
            edges=[FlowEdge(source="a", target="missing")],
        )


def test_flow_diagram_accepts_edges_between_declared_nodes() -> None:
    flow = FlowDiagram(
        nodes=[FlowNode(key="a", label="Job failed"), FlowNode(key="b", label="Control missed it")],
        edges=[FlowEdge(source="a", target="b", label="should have caught it")],
    )
    assert [node.key for node in flow.nodes] == ["a", "b"]
    assert flow.edges[0].label == "should have caught it"


def test_quotation_carries_text_attribution_and_its_own_fact_ids() -> None:
    quote = Quotation(text="Sales held despite the outage.", attribution="Group Controller",
                       fact_ids=["FACT-0001"])
    assert quote.text == "Sales held despite the outage."
    assert quote.attribution == "Group Controller"
    assert quote.fact_ids == ["FACT-0001"]


def test_a_quote_exempts_a_section_from_prose_and_a_flow_does_not() -> None:
    """The asymmetry, and the defect that established it.

    Extending `awaiting_prose`'s exemption from `table` to `flow` by analogy
    was the obvious reading and it is wrong, because the two are not the same
    kind of thing. A table *is* the content of its section. A flow is a
    *diagram of* an argument, and the RCA's root-cause section is the
    conclusion of the document.

    The symptom was silent: declaring a causal chain withdrew the section from
    `narrate requests`, no prose was ever written, nothing reported a problem,
    and the rendered RCA showed seven boxes and an arrow under "Root cause"
    with the finding itself missing. Found by reading the rendered file, which
    is the only place it was visible.

    A quotation keeps the exemption for `table`'s reason: it is the content,
    and narrating around it would produce a paragraph whose job is to
    introduce a sentence.
    """
    flow_section = ArtifactSection(
        heading="Root cause",
        flow=FlowDiagram(nodes=[FlowNode(key="a", label="Step")]),
    )
    quote_section = ArtifactSection(
        heading="Context", quote=Quotation(text="A pulled line."),
    )
    empty_section = ArtifactSection(heading="Nothing yet")

    assert flow_section.awaiting_prose, "a diagram is not the argument it draws"
    assert not quote_section.awaiting_prose
    assert empty_section.awaiting_prose


def test_artifact_ir_fact_ids_collects_quote_and_flow_fact_ids() -> None:
    """`ArtifactIR.fact_ids()` already walked into a table's cells for
    ``fact_id``; a quotation and a flow node are exactly as citable and were
    invisible to every caller of this method (the narrative escape check in
    `documents.py`, the availability check in `compiler/handshake.py`) until
    now."""
    ir = ArtifactIR(
        id="ART-1", intent_id="ART-1", title="t",
        sections=[
            ArtifactSection(
                heading="Context",
                quote=Quotation(text="A pulled line.", fact_ids=["FACT-0001"]),
            ),
            ArtifactSection(
                heading="Root cause",
                flow=FlowDiagram(nodes=[FlowNode(key="a", label="Step", fact_id="FACT-0002")]),
            ),
        ],
    )
    assert ir.fact_ids() == ["FACT-0001", "FACT-0002"]


def test_a_cell_band_never_appears_where_a_number_would() -> None:
    """The one invariant every primitive in this file is held to: nothing
    shown may be a figure the IR did not already carry. `MagnitudeBand` is a
    `StrEnum` — there is no numeric member to accidentally reach for."""
    for band in MagnitudeBand:
        assert isinstance(band.value, str)
        assert not any(ch.isdigit() for ch in band.value)


# ---------------------------------------------------------------------------
# 2. The registry — what each component actually declared
# ---------------------------------------------------------------------------

_BY_ID: dict[str, ComponentSpec] = {spec.component_id: spec for spec in REGISTRY}


def test_required_and_optional_inputs_are_declared_on_exactly_the_intended_components() -> None:
    """Pins the design decision in full, so a future edit to any of these six
    shows up in a diff rather than silently drifting: three components got a
    hard `required_inputs` gate because they are provably unreachable via
    `compose()` today (see the reachability test below) and three got a
    non-gating `optional_inputs` because they are the components `compose()`
    actually selects in a real corpus and gating them would change today's
    output.
    """
    assert _BY_ID["finance.heatmap"].required_inputs == frozenset({"cell_band"})
    assert _BY_ID["mgmt.risk_matrix"].required_inputs == frozenset({"cell_band"})
    assert _BY_ID["ops.process_flow"].required_inputs == frozenset({"flow"})

    assert _BY_ID["ops.causal_chain"].required_inputs == frozenset()
    assert _BY_ID["ops.causal_chain"].optional_inputs == frozenset({"flow"})
    assert _BY_ID["editorial.pull_quote"].required_inputs == frozenset()
    assert _BY_ID["editorial.pull_quote"].optional_inputs == frozenset({"quote"})
    assert _BY_ID["editorial.callout"].required_inputs == frozenset()
    assert _BY_ID["editorial.callout"].optional_inputs == frozenset({"quote"})

    declared = {
        cid for cid, spec in _BY_ID.items()
        if spec.required_inputs or spec.optional_inputs
    }
    assert declared == {
        "finance.heatmap", "mgmt.risk_matrix", "ops.process_flow",
        "ops.causal_chain", "editorial.pull_quote", "editorial.callout",
    }


def test_fits_defaults_available_to_empty_and_gates_a_required_input() -> None:
    """`ComponentSpec.fits` grew one more dimension; every caller that never
    heard of `required_inputs` — the static audit chief among them — keeps
    asking exactly the question it always asked."""
    heatmap = _BY_ID["finance.heatmap"]
    density = DENSITY_POINTS["balanced"]

    # Density and rows both satisfied; only the new dimension is missing.
    assert not heatmap.fits(fmt="markdown", density=density, rows=6)
    assert not heatmap.fits(fmt="markdown", density=density, rows=6, available=frozenset())
    assert heatmap.fits(fmt="markdown", density=density, rows=6, available=frozenset({"cell_band"}))
    # A different primitive present is not the one asked for.
    assert not heatmap.fits(fmt="markdown", density=density, rows=6, available=frozenset({"flow"}))


def test_fits_never_gates_on_an_optional_input() -> None:
    """The distinguishing behaviour `optional_inputs` exists for: presence or
    absence of the primitive must not change whether the component fits — see
    `ops.causal_chain`'s own comment in `components.py` for why that
    difference from `required_inputs` is load-bearing rather than cosmetic."""
    causal_chain = _BY_ID["ops.causal_chain"]
    density = DENSITY_POINTS["balanced"]
    assert causal_chain.fits(fmt="markdown", density=density, rows=0, available=frozenset())
    assert causal_chain.fits(fmt="markdown", density=density, rows=0, available=frozenset({"flow"}))


def test_the_three_required_input_components_are_unreachable_via_the_shipped_registry() -> None:
    """Why `required_inputs` was safe to make a hard gate on these three
    specifically: at every format, every shipped density point, and a spread
    of row counts, something *else* always wins the role first — checked here
    with every primitive granted (``available`` carries all three input
    names), which isolates registry-order dominance from the gate itself. If
    this test ever starts failing, the registry changed under it and the
    hard-gate decision for whichever component newly became reachable needs a
    second look before it ships, exactly as the comment beside each of the
    three in `components.py` says.
    """
    dead_by_role = {
        "evidence": "finance.heatmap",
        "management": "mgmt.risk_matrix",
        "explanation": "ops.process_flow",
    }
    every_input = frozenset({"cell_band", "flow", "quote"})
    for fmt in ("markdown", "docx", "pptx", "xlsx", "pdf"):
        for density in DENSITY_POINTS.values():
            for rows in (0, 1, 2, 3, 4, 5, 8, 12, 20):
                for role, dead in dead_by_role.items():
                    candidates = roles_for(role, fmt=fmt)
                    fitting = [
                        c for c in candidates
                        if c.fits(fmt=fmt, density=density, rows=rows, available=every_input)
                    ]
                    if fitting:
                        assert fitting[0].component_id != dead, (
                            f"{dead} would now be selected for {role!r}/{fmt} at "
                            f"density={density}, rows={rows} — the dominance this test "
                            "pins no longer holds"
                        )


def test_ops_causal_chain_editorial_pull_quote_and_callout_are_reachable() -> None:
    """The flip side of the test above: these three are exactly the
    components `compose()` selects for their roles in a real corpus today,
    which is *why* their new input is declared optional rather than
    required — see each one's own comment in `components.py`."""
    density = DENSITY_POINTS["balanced"]
    assert roles_for("explanation", fmt="markdown")[0].fits(fmt="markdown", density=density, rows=0)
    assert roles_for("explanation", fmt="markdown")[0].component_id == "ops.causal_chain"
    assert roles_for("context", fmt="markdown")[0].component_id == "editorial.pull_quote"
    # `comparison` needs a row count under `finance.comparative_trend`'s floor
    # of 3 for `editorial.callout` to be the one that actually fits.
    comparison_candidates = roles_for("comparison", fmt="markdown")
    fitting = [c for c in comparison_candidates if c.fits(fmt="markdown", density=density, rows=1)]
    assert fitting[0].component_id == "editorial.callout"


# ---------------------------------------------------------------------------
# 3. The composer — enforcement, not decoration
# ---------------------------------------------------------------------------


def _single_component_registry(**overrides) -> tuple[ComponentSpec, ...]:
    fields = dict(
        component_id="test.subject",
        semantic_roles=frozenset({"evidence"}),
        supported_formats=frozenset({"markdown"}),
    )
    fields.update(overrides)
    return (ComponentSpec(**fields),)


def _bare_plan(available_inputs: frozenset[str] = frozenset()) -> ArtifactPlan:
    beat = NarrativeBeat(
        key="beat", purpose="p", evidence=[], semantic_role="evidence",
        available_inputs=available_inputs,
    )
    return ArtifactPlan(
        intent_id="ART-TEST", artifact_type="unit_test_no_grammar", audience="",
        intent="i", beats=[beat], size_class="small", density_profile="balanced",
    )


def test_compose_refuses_a_component_missing_its_required_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The end-to-end proof `components.py`'s comments only argue: a
    component that declares `required_inputs` and does not get one is refused
    at compose time, not silently substituted or rendered as a fallback shape.
    """
    monkeypatch.setattr(
        components_module, "REGISTRY",
        _single_component_registry(required_inputs=frozenset({"flow"})),
    )
    with pytest.raises(CompositionError) as excinfo:
        compose(_bare_plan(available_inputs=frozenset()), fmt="markdown")
    assert excinfo.value.code == "no_fitting_component"


def test_compose_accepts_the_same_beat_once_the_input_is_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        components_module, "REGISTRY",
        _single_component_registry(required_inputs=frozenset({"flow"})),
    )
    composition = compose(_bare_plan(available_inputs=frozenset({"flow"})), fmt="markdown")
    assert composition.components == ("test.subject",)


def test_compose_never_gates_on_an_optional_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        components_module, "REGISTRY",
        _single_component_registry(optional_inputs=frozenset({"flow"})),
    )
    # Composes whether or not the optional input is there.
    composition = compose(_bare_plan(available_inputs=frozenset()), fmt="markdown")
    assert composition.components == ("test.subject",)
    composition = compose(_bare_plan(available_inputs=frozenset({"flow"})), fmt="markdown")
    assert composition.components == ("test.subject",)


def test_plan_from_ir_derives_available_inputs_from_the_sections_own_content() -> None:
    """`compose.plan_from_ir` is the one place that reads an already-resolved
    `ArtifactSection` — this is where `available_inputs` actually gets
    populated for a real IR, rather than left at the empty default every
    hand-built `NarrativeBeat` above started from."""
    banded_table = Table(
        key="t", title="Values",
        columns=[Column(key="v", label="Value")],
        rows=[
            Row(key="r1", label="Row 1", cells={"v": Cell(value=1.0, band=MagnitudeBand.HIGH)}),
            Row(key="r2", label="Row 2", cells={"v": Cell(value=2.0)}),
        ],
    )
    plain_table = Table(
        key="t2", title="Plain",
        columns=[Column(key="v", label="Value")],
        rows=[Row(key="r1", label="Row 1", cells={"v": Cell(value=1.0)})],
    )
    ir = ArtifactIR(
        id="ART-1", intent_id="ART-1", title="t",
        sections=[
            ArtifactSection(heading="Banded", table=banded_table, semantic_role="evidence"),
            ArtifactSection(heading="Plain", table=plain_table, semantic_role="evidence"),
            ArtifactSection(
                heading="Flow", semantic_role="explanation",
                flow=FlowDiagram(nodes=[FlowNode(key="a", label="Step")]),
            ),
            ArtifactSection(
                heading="Quote", semantic_role="context",
                quote=Quotation(text="A line."),
            ),
            ArtifactSection(heading="Nothing", semantic_role="evidence"),
        ],
    )
    plan = plan_from_ir(ir, artifact_type="unit_test_no_grammar")
    by_key = {beat.key: beat for beat in plan.beats}

    assert by_key["banded"].available_inputs == frozenset({"cell_band"})
    assert by_key["plain"].available_inputs == frozenset()
    assert by_key["flow"].available_inputs == frozenset({"flow"})
    assert by_key["quote"].available_inputs == frozenset({"quote"})
    assert by_key["nothing"].available_inputs == frozenset()


# ---------------------------------------------------------------------------
# 4. Render dispatch — Markdown
# ---------------------------------------------------------------------------


def _flow_ir() -> ArtifactIR:
    return ArtifactIR(
        id="ART-FLOW", intent_id="ART-FLOW", title="Incident review",
        sections=[
            ArtifactSection(
                heading="Root cause",
                semantic_role="explanation",
                flow=FlowDiagram(
                    nodes=[
                        FlowNode(key="job", label="Nightly batch job"),
                        FlowNode(key="control", label="Reconciliation control"),
                    ],
                    edges=[FlowEdge(source="job", target="control",
                                     label="should have caught it")],
                ),
            ),
        ],
    )


def _quote_ir() -> ArtifactIR:
    return ArtifactIR(
        id="ART-QUOTE", intent_id="ART-QUOTE", title="Status update",
        sections=[
            ArtifactSection(
                heading="Context", semantic_role="context",
                quote=Quotation(text="Sales held despite the outage.",
                                 attribution="Group Controller"),
            ),
            ArtifactSection(
                heading="Watch items", semantic_role="comparison",
                quote=Quotation(text="Freight rates trending up."),
            ),
        ],
    )


def test_markdown_composes_the_flow_section_as_ops_causal_chain() -> None:
    ir = _flow_ir()
    identities = section_components(ir, artifact_type="unit_test_no_grammar", fmt="markdown")
    assert identities["Root cause"] == "ops.causal_chain"


def test_markdown_renders_a_declared_flow_as_an_ordered_chain_not_a_table_or_paragraph() -> None:
    payload = markdown.render(_flow_ir(), artifact_type="unit_test_no_grammar").decode()
    assert "Nightly batch job" in payload
    assert "Reconciliation control" in payload
    assert "should have caught it" in payload
    assert "→" in payload
    assert "Awaiting narrative" not in payload
    assert "| " not in payload  # not rendered as a table


def test_markdown_composes_the_quote_sections_as_pull_quote_and_callout() -> None:
    ir = _quote_ir()
    identities = section_components(ir, artifact_type="unit_test_no_grammar", fmt="markdown")
    assert identities["Context"] == "editorial.pull_quote"
    assert identities["Watch items"] == "editorial.callout"


def test_markdown_renders_a_pull_quote_as_a_blockquote_with_attribution() -> None:
    payload = markdown.render(_quote_ir(), artifact_type="unit_test_no_grammar").decode()
    assert "> Sales held despite the outage." in payload
    assert "> — Group Controller" in payload


def test_markdown_renders_a_callout_with_its_own_watch_prefix() -> None:
    payload = markdown.render(_quote_ir(), artifact_type="unit_test_no_grammar").decode()
    assert "> **Watch:** Freight rates trending up." in payload


def test_markdown_draws_a_declared_flow_beside_the_prose_rather_than_instead_of_it() -> None:
    """A causal chain accompanies the finding; it does not replace it.

    The first version of this dispatch was a plain `elif` chain, so prose won
    and the diagram was silently dropped — and its sibling defect in
    `awaiting_prose` meant that when the diagram *did* draw, the prose was
    missing instead. Between them a section could show its argument or its
    shape and never both, which is the one combination an RCA actually needs.

    A flow is the only additive branch here. A quote and a table remain
    alternatives, because each of those *is* the content of its section.
    """
    ir = ArtifactIR(
        id="ART-BOTH", intent_id="ART-BOTH", title="Incident review",
        sections=[
            ArtifactSection(
                heading="Root cause", semantic_role="explanation",
                body="The batch job failed and the control caught it on retry.",
                flow=FlowDiagram(nodes=[FlowNode(key="a", label="Both appear")]),
            ),
        ],
    )
    payload = markdown.render(ir, artifact_type="unit_test_no_grammar").decode()
    assert "The batch job failed and the control caught it on retry." in payload
    assert "Both appear" in payload, "the diagram must accompany the prose"
    assert payload.index("The batch job failed") < payload.index("Both appear"), (
        "the argument comes first, then the shape of it"
    )


def test_markdown_a_declared_cell_band_changes_nothing_when_the_registry_never_selects_a_banded_component() -> None:
    """`finance.heatmap` is pinned unreachable above; this is what that means
    for a real render — a table with real magnitude bands still renders as
    the ordinary table `finance.variance_table` (or whatever wins the role
    first) always produced, byte for byte, because identity dispatch only
    changes anything when the *selected* component asked for the primitive.
    """
    table = Table(
        key="t", title="Values",
        columns=[Column(key="v", label="Value")],
        rows=[Row(key="r1", label="Row 1", cells={"v": Cell(value=1.0, band=MagnitudeBand.HIGH)}),
              Row(key="r2", label="Row 2", cells={"v": Cell(value=2.0, band=MagnitudeBand.LOW)})],
    )
    ir = ArtifactIR(
        id="ART-BAND", intent_id="ART-BAND", title="t",
        sections=[ArtifactSection(heading="Evidence", semantic_role="evidence", table=table)],
    )
    identities = section_components(ir, artifact_type="unit_test_no_grammar", fmt="markdown")
    assert identities["Evidence"] != "finance.heatmap"

    with_identity = markdown.render(ir, artifact_type="unit_test_no_grammar")
    without_identity = markdown.render(ir)  # no artifact_type at all — today's call shape
    assert with_identity == without_identity
    assert b"(high)" not in with_identity
    assert b"(low)" not in with_identity


def test_markdown_table_shows_band_markers_when_asked_directly() -> None:
    """`finance.heatmap`/`mgmt.risk_matrix` can never be reached through
    `compose()` against the shipped registry (pinned above), so the marker
    path is proven the way `test_style.py` already proves `layout_for` for
    the same two components: by calling the rendering primitive directly with
    the component's own `show_bands` flag, rather than through a pipeline
    that cannot currently produce it.
    """
    table = Table(
        key="t", title="Values",
        columns=[Column(key="v", label="Value")],
        rows=[Row(key="r1", label="Row 1", cells={"v": Cell(value=1.0, band=MagnitudeBand.HIGH)}),
              Row(key="r2", label="Row 2", cells={"v": Cell(value=2.0, band=MagnitudeBand.LOW)}),
              Row(key="r3", label="Row 3", cells={"v": Cell(value=3.0)})],
    )
    banded = markdown._table(table, show_bands=True)
    assert "(high)" in banded
    assert "(low)" in banded
    unbanded = markdown._table(table, show_bands=False)
    assert "(high)" not in unbanded
    assert "(low)" not in unbanded


# ---------------------------------------------------------------------------
# 5. Render dispatch — PDF
# ---------------------------------------------------------------------------

#: A minimal PDF text recovery — see `tests/test_pdf.py`'s identical helper,
#: which this duplicates rather than imports: it is six lines tied to
#: `render/pdf.py`'s own `pageCompression=0` choice, not shared library code.
_TJ = re.compile(rb"\(((?:[^()\\]|\\.)*)\)\s*Tj")
_TJ_ARRAY = re.compile(rb"\[((?:[^\[\]]|\\.)*)\]\s*TJ")
_TJ_ARRAY_STRING = re.compile(rb"\(((?:[^()\\]|\\.)*)\)")


def _pdf_text(payload: bytes) -> str:
    parts: list[bytes] = [m.group(1) for m in _TJ.finditer(payload)]
    for array in _TJ_ARRAY.finditer(payload):
        parts.extend(s.group(1) for s in _TJ_ARRAY_STRING.finditer(array.group(1)))
    text = b" ".join(parts)
    text = text.replace(rb"\(", b"(").replace(rb"\)", b")").replace(rb"\\", b"\\")
    return text.decode("latin1")


def test_pdf_renders_a_declared_flow_as_an_ordered_chain() -> None:
    payload = pdf_renderer.render(_flow_ir(), artifact_type="unit_test_no_grammar")
    text = _pdf_text(payload)
    assert "Nightly batch job" in text
    assert "Reconciliation control" in text
    assert "should have caught it" in text
    assert "Awaiting narrative" not in text


def test_pdf_renders_a_pull_quote_and_a_callout_distinctly() -> None:
    payload = pdf_renderer.render(_quote_ir(), artifact_type="unit_test_no_grammar")
    text = _pdf_text(payload)
    assert "Sales held despite the outage." in text
    assert "Group Controller" in text
    assert "Freight rates trending up." in text
    assert "Watch:" in text


def test_pdf_draws_a_declared_flow_beside_the_prose_rather_than_instead_of_it() -> None:
    """The Markdown property above, in the fixed-page renderer.

    Both formats have to agree about this or one artifact renders as two
    different documents — the invariant `render/values` exists to protect, one
    layer up from the figures it protects it for.
    """
    ir = ArtifactIR(
        id="ART-BOTH", intent_id="ART-BOTH", title="Incident review",
        sections=[
            ArtifactSection(
                heading="Root cause", semantic_role="explanation",
                body="The batch job failed and the control caught it on retry.",
                flow=FlowDiagram(nodes=[FlowNode(key="a", label="Both appear")]),
            ),
        ],
    )
    text = _pdf_text(pdf_renderer.render(ir, artifact_type="unit_test_no_grammar"))
    assert "The batch job failed and the control caught it on retry." in text
    assert "Both appear" in text, "the diagram must accompany the prose"


def test_pdf_a_declared_cell_band_changes_nothing_when_the_registry_never_selects_a_banded_component() -> None:
    table = Table(
        key="t", title="Values",
        columns=[Column(key="v", label="Value")],
        rows=[Row(key="r1", label="Row 1", cells={"v": Cell(value=1.0, band=MagnitudeBand.HIGH)}),
              Row(key="r2", label="Row 2", cells={"v": Cell(value=2.0, band=MagnitudeBand.LOW)})],
    )
    ir = ArtifactIR(
        id="ART-BAND", intent_id="ART-BAND", title="t",
        sections=[ArtifactSection(heading="Evidence", semantic_role="evidence", table=table)],
    )
    with_identity = pdf_renderer.render(ir, artifact_type="unit_test_no_grammar")
    without_identity = pdf_renderer.render(ir)
    assert with_identity == without_identity


def test_pdf_table_flowable_shades_banded_cells_when_asked_directly() -> None:
    """Same reasoning as `test_markdown_table_shows_band_markers_when_asked_directly`:
    `_table_flowable`'s `show_bands` flag is the mechanism `finance.heatmap`
    and `mgmt.risk_matrix` would use if `compose()` could ever reach them
    against the shipped registry; proven directly since it cannot.
    """
    styles = pdf_renderer._styles()
    table = Table(
        key="t", title="Values",
        columns=[Column(key="v", label="Value")],
        rows=[Row(key="r1", label="Row 1", cells={"v": Cell(value=1.0, band=MagnitudeBand.HIGH)})],
    )
    from reportlab.lib import colors

    grid = pdf_renderer._table_flowable(table, 400.0, styles, show_bands=True)
    fills = {cmd[3] for cmd in grid._bkgrndcmds}
    assert colors.HexColor(f"#{pdf_renderer._BAND_FILL[MagnitudeBand.HIGH]}") in fills

    unbanded = pdf_renderer._table_flowable(table, 400.0, styles, show_bands=False)
    unbanded_fills = {cmd[3] for cmd in unbanded._bkgrndcmds}
    assert colors.HexColor(f"#{pdf_renderer._BAND_FILL[MagnitudeBand.HIGH]}") not in unbanded_fills


# ---------------------------------------------------------------------------
# DOCX and HTML draw the same primitives
# ---------------------------------------------------------------------------
#
# These two formats declared support for `ops.causal_chain` and the quote
# components in `compiler/components.py` and drew neither: the dispatch in each
# renderer was body → table → awaiting, so a section carrying only a flow or a
# quote printed the awaiting notice while markdown and PDF printed the content.
# Measured on a three-period incident build before the fix: 21 nodes and 18
# edges per RCA in markdown and PDF, zero in DOCX and HTML. Nothing failed,
# because this file covered only markdown and PDF — which is the coverage gap
# these tests close, not just the rendering one.


def _docx_xml(ir: ArtifactIR) -> str:
    import io
    import zipfile

    from worldloom.render import docx as docx_renderer

    payload = docx_renderer.render(ir, {})
    return zipfile.ZipFile(io.BytesIO(payload)).read("word/document.xml").decode()


def _html_text(ir: ArtifactIR) -> str:
    from worldloom.render import html as html_renderer

    return html_renderer.render(ir, {}).decode()


def test_docx_renders_a_declared_flow_and_not_the_awaiting_notice() -> None:
    xml = _docx_xml(_flow_ir())
    assert "Nightly batch job" in xml
    assert "Reconciliation control" in xml
    assert "should have caught it" in xml
    assert "Awaiting narrative" not in xml


def test_docx_renders_a_quote_with_attribution() -> None:
    xml = _docx_xml(_quote_ir())
    assert "Sales held despite the outage." in xml
    assert "Group Controller" in xml
    assert "Awaiting narrative" not in xml


def test_html_renders_a_declared_flow_and_not_the_awaiting_notice() -> None:
    text = _html_text(_flow_ir())
    assert "Nightly batch job" in text
    assert "Reconciliation control" in text
    assert "should have caught it" in text
    assert '<ul class="flow">' in text
    assert "Awaiting narrative" not in text


def test_html_renders_a_quote_as_a_blockquote() -> None:
    text = _html_text(_quote_ir())
    assert "<blockquote>" in text
    assert "Sales held despite the outage." in text
    assert "Group Controller" in text
    assert "Awaiting narrative" not in text
