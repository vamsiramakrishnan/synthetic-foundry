"""Exporting a derived world as a pack: what survives, and what is admitted to.

Two claims, and both need proving rather than asserting in a docstring:

* **The round trip holds.** A variant's physics and trading year go out through
  files, come back through ``packs.load``, build a real corpus, and land in that
  corpus's own recipe unchanged. Asserted against the recipe rather than against
  the export's return value, because the export agreeing with itself proves
  nothing about whether a build honoured it.
* **The gaps are named.** A pack cannot carry physics, an org shape, an estate,
  a company name, a unit's books or lore. The skeleton path must therefore leave
  findable holes rather than plausible nouns — so ``packs.lint`` naming them is
  the test, not a nicety.
"""

from __future__ import annotations

import json

import pytest

from worldloom import mosaic, pack_export, packs, probe
from worldloom.parameters import DEFAULT, overrides_from
from worldloom.probe import Answer, Interval, Question
from worldloom.recipe import rebuild
from worldloom.retail import MonthEndClose, RetailWorld

INSURER = "examples/packs/regional-insurer.json"
MUTUAL = "examples/packs/mutual-bank.json"


@pytest.fixture(scope="module")
def variant():
    # World 2 of 3 rather than world 1: the first pick of a farthest-first
    # traversal is a corner of the space, and a corner is the candidate most
    # likely to have a degenerate estate or calendar.
    return mosaic.field(3)[1]


def settled_probe() -> probe.Resolution:
    graph = probe.open_graph(
        "A specialty apparel retailer, 180 stores.",
        [Question(key="m", asks="what is gross margin?", unit="fraction",
                  domain=Interval(0.0, 1.0), depth=0)],
    )
    graph = probe.accept(graph, Answer(
        question="m", claim="specialty apparel gross margin",
        low=0.5, high=0.58, binds="retail.margin.budget",
    )).graph
    assert graph is not None
    return probe.resolve(graph)


def test_a_variant_round_trips_through_files_into_a_built_corpus(tmp_path, variant):
    """Export, load, build — the same physics and the same trading year.

    Through the real seams: `Derived.write` writes what `--pack`/`--physics`
    read, and the assertion is against `world.recipe`, which is what a corpus
    rebuilds itself from. An export that agreed with itself but not with the
    recipe would rebuild as a different company and report success.
    """
    derived = pack_export.from_variant(variant)
    written = derived.write(tmp_path / "bundle")

    loaded = packs.load(written["pack"])
    physics = json.loads(written["physics"].read_text(encoding="utf-8"))["overrides"]
    shape = json.loads(written["shape"].read_text(encoding="utf-8"))

    spec = pack_export.Derived(
        pack=loaded,
        physics=physics,
        role_table=tuple(tuple(row) for row in shape["role_table"]),
        estate=shape.get("estate"),
    ).apply(RetailWorld.from_pack(loaded, seed=variant.seed))

    assert spec.physics == variant.physics
    assert spec.seasonality == variant.seasonality

    world = spec.build().run(MonthEndClose(
        period="2026-03", physics=spec.physics, seasonality=spec.seasonality,
    ))
    recipe = world.recipe
    assert recipe["physics"] == derived.physics
    assert recipe["seasonality"] == variant.seasonality.as_dict()
    assert recipe["estate"] == variant.estate
    assert len(recipe["role_table"]) == len(variant.role_table())

    # The corpus is coherent, and it rebuilds from its own recipe with no pack
    # file on hand — the property a pack exists to give a derived world.
    assert world.validate().ok
    assert rebuild(recipe).company.name == world.company.name


def test_a_skeleton_marks_what_it_could_not_derive_and_the_lint_names_it(variant):
    """The deliverable: the holes are findable, not filled with plausible nouns."""
    derived = pack_export.from_variant(variant)
    marked = packs.placeholders(derived.pack)

    # Identity — the things neither a coordinate nor an interval graph knows.
    assert {"company_name", "industry", "description"} <= set(marked)
    assert any(path.endswith(".name") and path.startswith("units[") for path in marked)

    findings = packs.lint(derived.pack)
    assert all(any(path in finding for finding in findings) for path in marked)
    assert any("carries no lore" in finding for finding in findings)

    # And the parts a pack may not hold at all are stated rather than dropped.
    joined = " ".join(derived.unfilled)
    assert "physics" in joined and "role_table" in joined and "lore" in joined
    # The trap this names: a mosaic's headcount is the role table's size, not a
    # payroll, and writing it into `employees` would be a fabricated scale.
    assert derived.pack.employees != variant.headcount


def test_a_base_pack_keeps_its_own_identity_and_takes_the_derived_calendar(variant):
    """The other shape: apply, do not skeleton. Nothing is placeheld, and the
    one field both sides can hold changes hands with a note saying so."""
    base = packs.load(INSURER)
    derived = pack_export.from_variant(variant, onto=base)

    assert not packs.placeholders(derived.pack)
    assert derived.pack.company_name == base.company_name
    assert derived.pack.units == base.units
    assert derived.pack.lore == base.lore
    assert derived.pack.seasonality == variant.calendar
    # Applied to a pack, the sidecars are still sidecars — that is the point.
    assert derived.physics and derived.role_table


def test_a_derivation_for_another_engine_is_refused_rather_than_left_inert(variant):
    # The registry is one namespace, so retail parameters on a banking pack
    # would validate and simply never be read: a pack that looks derived and
    # behaves default.
    with pytest.raises(ValueError, match="engine"):
        pack_export.from_variant(variant, onto=packs.load(MUTUAL))


def test_a_probe_exports_its_physics_and_admits_it_has_nothing_else():
    resolution = settled_probe()
    derived = pack_export.from_probe(
        resolution, engine="retail", premise="A specialty apparel retailer.")

    assert DEFAULT.with_overrides(overrides_from(derived.physics)) == resolution.parameters()
    # Provenance survives the file: the span says which question settled it.
    assert derived.physics["retail.margin.budget"]["source"] == "probe: m"
    # A probe knows nothing about the company or its calendar, and says so.
    assert derived.pack.seasonality is None
    assert any("seasonality" in entry for entry in derived.unfilled)
    assert packs.placeholders(derived.pack)


def test_an_unsettled_probe_cannot_be_kept():
    """Same refusal as `probe resolve`, and for a stronger reason: a shareable
    artifact whose physics came from reasoning nobody finished travels."""
    graph = probe.open_graph(
        "unfinished", [Question(key="a", asks="?", unit="", domain=Interval(0.0, 1.0), depth=0)])
    with pytest.raises(ValueError, match="cannot produce physics"):
        pack_export.from_probe(probe.resolve(graph), engine="retail")


def test_an_unbound_leaf_survives_the_export():
    """`probe.Unbound` is evidence for adding a parameter to the registry, and
    evidence that stops at an export boundary is evidence nobody acts on."""
    graph = probe.open_graph(
        "A specialty apparel retailer.",
        [Question(key="returns", asks="return rate?", unit="fraction of units sold",
                  domain=Interval(0.0, 1.0), depth=0)],
    )
    graph = probe.accept(graph, Answer(
        question="returns", claim="online apparel return rate", low=0.28, high=0.34)).graph
    assert graph is not None

    derived = pack_export.from_probe(probe.resolve(graph), engine="retail")
    assert not derived.physics
    assert any("returns" in note for note in derived.notes)
