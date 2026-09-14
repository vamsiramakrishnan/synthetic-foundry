"""One authored step, a section per business unit; and a map for the writers.

`plan.py` promised that "one beat becoming three sections in a long artifact
is normal" and nothing could do it: an outline step was one section, and the
only way to a division-by-division review was a section per division written
by an author who knew how many divisions the company had. `repeat: "unit"`
is the expansion, from facts: a unit with figures gets a section, a unit
without gets none, and each section is its own narration request. Past eight
visible sections a document's writers are also handed its outline, so the
ninth section stops restating the first.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from worldloom import MonthEndClose, RetailWorld, World, doctypes, packs, registries
from worldloom.models import ArtifactIR, ArtifactSection
from worldloom.narrative import compiler as narrative_compiler
from worldloom.narrative import handshake

EXAMPLES = pathlib.Path(__file__).resolve().parents[1] / "examples" / "artifact-types"
AUTHORED = EXAMPLES / "franchise-network.json"
STATEMENT = "franchisee_trading_statement"
PERIOD = "2026-03"


@pytest.fixture(autouse=True)
def _restore_the_registries():
    with registries.scoped():
        yield


def _pack(*, repeat: bool, heading: str = "{{var:unit.name}} in the period", extra: int = 0) -> dict:
    document = json.loads(AUTHORED.read_text(encoding="utf-8"))
    sections = document["artifact_types"][0]["sections"]
    if repeat:
        sections[1]["repeat"] = "unit"
        sections[1]["heading"] = heading
        sections[1]["purpose"] = "What {{var:unit.name}} delivered against plan, and why."
    for i in range(extra):
        sections.append({
            "heading": f"{'Further ' * (i + 1)}note", "kinds": ["financial.revenue."],
            "scope": "unit", "repeat": "unit",
            "purpose": "One more thing about {{var:unit.name}}.",
        })
    return document


def _world(document: dict) -> World:
    return RetailWorld.from_pack(packs.load(document), seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    ).compile()


def _statement(world: World) -> ArtifactIR:
    intent = next(i for i in world.artifact_intents if i.artifact_type == STATEMENT)
    return next(ir for ir in world.artifact_irs if ir.intent_id == intent.id)


def test_an_unset_repeat_stays_off_the_wire_and_the_outline_is_what_it_was() -> None:
    types = doctypes.load(_pack(repeat=False)["artifact_types"])
    section = doctypes.to_document(types)["artifact_types"][0]["sections"][1]
    assert "repeat" not in section and section["required"] is True
    assert types[0].sections[1].repeat == ""
    assert [s.heading for s in _statement(_world(_pack(repeat=False))).sections if not s.hidden] == [
        "Network position", "By trading division", "Basis of this statement",
    ]


def test_a_repeated_step_becomes_a_section_per_unit_with_that_units_facts() -> None:
    world = _world(_pack(repeat=True))
    ir = _statement(world)
    units = {unit.id: unit.name for unit in world.business_units}
    repeated = [s for s in ir.sections if s.heading.endswith(" in the period")]

    assert len(repeated) == len(units) >= 2, [s.heading for s in ir.sections]
    assert [s.heading for s in repeated] == [f"{name} in the period" for name in units.values()]
    for section, (unit_id, name) in zip(repeated, units.items(), strict=True):
        assert section.purpose == f"What {name} delivered against plan, and why."
        subjects = {world.facts.by_id(fact_id).subject for fact_id in section.fact_ids}
        inside = {unit_id} | {c.id for c in world.categories if c.business_unit_id == unit_id}
        inside |= {site.id for site in world.sites if site.business_unit_id == unit_id}
        assert section.fact_ids and subjects <= inside, (name, subjects - inside)
    # The unit's facts are partitioned, never shared: no fact sits in two units.
    seen: list[str] = [fact_id for s in repeated for fact_id in s.fact_ids]
    assert len(seen) == len(set(seen))

    # Each expanded section is its own narration request with its own facts.
    requests = [r for r in handshake.pending(world) if r.artifact_id == ir.id]
    assert {r.section for r in requests} >= {s.heading for s in repeated}


def test_the_lint_refuses_a_repeated_step_that_never_names_the_unit() -> None:
    nameless = doctypes.load(_pack(repeat=True, heading="By division")["artifact_types"])
    findings = doctypes.lint(nameless, base="retail")
    assert any("never names the unit" in f for f in findings), findings

    named = doctypes.load(_pack(repeat=True)["artifact_types"])
    clean = doctypes.lint(named, base="retail")
    assert not any("never names the unit" in f or "unknown variable" in f for f in clean), clean

    # The unit variable is legal only where a unit is in hand.
    stray = _pack(repeat=False)
    stray["artifact_types"][0]["sections"][0]["heading"] = "{{var:unit.name}} position"
    findings = doctypes.lint(doctypes.load(stray["artifact_types"]), base="retail")
    assert any("unknown variable" in f and "unit.name" in f for f in findings), findings


def test_writers_of_a_long_document_are_handed_its_outline() -> None:
    """Past `FRAMED_FROM` visible sections, every request carries the outline
    and the section's place in it; a short document's requests are exactly
    what they were, digest included."""
    # Each world in its own scope: the same key installed with a different
    # outline is refused as a redefinition, which is `install`'s rule.
    with registries.scoped():
        short = _world(_pack(repeat=True))
    short_ir = _statement(short)
    assert len([s for s in short_ir.sections if not s.hidden]) <= narrative_compiler.FRAMED_FROM
    for request in handshake.pending(short):
        assert not any(line.startswith("This document's sections") for line in request.background)

    with registries.scoped():
        long_world = _world(_pack(repeat=True, extra=3))
    ir = _statement(long_world)
    visible = [s for s in ir.sections if not s.hidden]
    assert len(visible) > narrative_compiler.FRAMED_FROM
    requests = [r for r in handshake.pending(long_world) if r.artifact_id == ir.id]
    assert requests
    order = "; ".join(s.heading for s in visible)
    for request in requests:
        assert f"This document's sections, in order: {order}." in request.background
        place = next(line for line in request.background if line.startswith("This section "))
        assert "never restated" in place
    first = next(r for r in requests if r.section == visible[0].heading)
    assert any(line.startswith("This section opens the document") for line in first.background)


def test_outline_context_is_empty_for_short_or_hidden_sections() -> None:
    sections = [ArtifactSection(heading=f"Section {c}", purpose="p") for c in "ABCDEFGHIJ"]
    ir = ArtifactIR(id="ART-1", intent_id="ART-1", title="T", sections=sections)
    assert narrative_compiler.outline_context(ir, sections[0]) == [
        "This document's sections, in order: " + "; ".join(s.heading for s in sections) + ".",
        'This section opens the document, before "Section B". Cover only its own purpose;'
        " what another section establishes is referred to by its heading, never restated.",
    ]
    assert narrative_compiler.outline_context(ir, sections[-1])[1].startswith(
        'This section closes the document, after "Section I".'
    )
    assert narrative_compiler.outline_context(ir, sections[4])[1].startswith(
        'This section follows "Section D" and precedes "Section F".'
    )
    hidden = ArtifactSection(heading="Appendix", purpose="p", hidden=True)
    assert narrative_compiler.outline_context(ir, hidden) == []
    short = ArtifactIR(id="ART-2", intent_id="ART-2", title="T", sections=sections[:8])
    assert narrative_compiler.outline_context(short, sections[0]) == []
