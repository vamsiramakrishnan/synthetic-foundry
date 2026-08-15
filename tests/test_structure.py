"""Outline derivation — the genome, the mask, and the byte-identity floor."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from worldloom import structure
from worldloom.structure import CLASSIC, StructuralGenome


@dataclass(frozen=True)
class Sec:
    """A minimal `structure.Section` — the protocol is two attributes wide."""

    heading: str
    required: bool = True


def outline(*headings: str, required: tuple[str, ...] = ()) -> tuple[Sec, ...]:
    return tuple(Sec(h, h in required) for h in headings)


ALL_OPTIONAL = outline("Position", "By unit", "Drivers", "Outlook", "Actions")


def test_classic_genome_is_the_identity() -> None:
    """The whole compatibility story in one assertion.

    Every corpus in the repo is built without a genome, CI byte-diffs them, and
    the only reason that is safe is that `CLASSIC` cannot drop a section.
    """
    for key in ("a", "b", "artifact-0007", ""):
        assert structure.derive(ALL_OPTIONAL, key=key) == ALL_OPTIONAL
        assert structure.derive(ALL_OPTIONAL, key=key, genome=CLASSIC) == ALL_OPTIONAL


def test_required_sections_are_never_dropped() -> None:
    """A genome may not strip a section a fact depends on.

    This is what makes omission safe to enable globally: a type nobody has
    annotated has no optional sections, so turning the knob on cannot silently
    produce a document that trips ``required_fact_omitted`` at narration.
    """
    plan = outline("Position", "Drivers", "Actions", required=("Position", "Actions"))
    total = StructuralGenome(omission=structure.SCALE)
    for index in range(200):
        got = structure.derive(plan, key=f"doc-{index}", genome=total)
        assert [s.heading for s in got] == ["Position", "Actions"]


def test_omission_actually_omits() -> None:
    """Half-omission over 500 documents must produce a spread of shapes, not one."""
    genome = StructuralGenome(omission=500)
    shapes = {
        tuple(s.heading for s in structure.derive(ALL_OPTIONAL, key=f"doc-{i}", genome=genome))
        for i in range(500)
    }
    # Five optional sections, floor 1: 31 reachable shapes. Anything much below
    # that would mean the hash is correlating headings that should be
    # independent, which is the failure mode a stream-based mask would have.
    assert len(shapes) >= 25
    assert tuple(s.heading for s in ALL_OPTIONAL) in shapes


def test_derivation_is_deterministic() -> None:
    genome = StructuralGenome(omission=400)
    first = [structure.derive(ALL_OPTIONAL, key=f"d{i}", genome=genome) for i in range(50)]
    second = [structure.derive(ALL_OPTIONAL, key=f"d{i}", genome=genome) for i in range(50)]
    assert first == second


def test_a_section_s_fate_does_not_move_when_a_neighbour_is_added() -> None:
    """The reason the mask is a per-heading hash and not an `Rng` stream.

    Successive draws from one stream would mean that inserting a section into a
    type reshuffles every section after it, in every already-minted document, at
    every seed — the exact class of bug `rng.py`'s docstring exists to prevent.
    Hashing each heading independently means a new section changes only itself.

    Asserted on `keep` rather than on `derive`, because the floor is a
    whole-outline constraint and legitimately breaks this: a three-section type
    whose mask drops everything restores its first section, and the same mask
    over a four-section type may have kept the newcomer and restored nothing.
    The independence claim is about the *mask*; the floor is the one thing
    allowed to read the outline as a whole, and `test_floor_restores_in_outline_order`
    is where that is pinned.
    """
    genome = StructuralGenome(omission=500)
    before = outline("Position", "Drivers", "Actions")
    after = outline("Position", "Interlude", "Drivers", "Actions")
    for index in range(200):
        key = f"doc-{index}"
        kept_before = {s.heading for s in before if structure.keep(key, s, genome)}
        kept_after = {s.heading for s in after if structure.keep(key, s, genome)}
        assert kept_before == kept_after - {"Interlude"}


def test_floor_restores_in_outline_order() -> None:
    genome = StructuralGenome(omission=structure.SCALE, floor=2)
    for index in range(100):
        got = structure.derive(ALL_OPTIONAL, key=f"doc-{index}", genome=genome)
        assert [s.heading for s in got] == ["Position", "By unit"]


def test_floor_above_the_outline_length_keeps_everything() -> None:
    genome = StructuralGenome(omission=structure.SCALE, floor=99)
    assert structure.derive(ALL_OPTIONAL, key="d", genome=genome) == ALL_OPTIONAL


def test_order_is_never_changed() -> None:
    genome = StructuralGenome(omission=600)
    positions = {h: i for i, h in enumerate(s.heading for s in ALL_OPTIONAL)}
    for index in range(200):
        got = [s.heading for s in structure.derive(ALL_OPTIONAL, key=f"d{index}", genome=genome)]
        assert got == sorted(got, key=lambda h: positions[h])


def test_empty_outline() -> None:
    assert structure.derive((), key="d", genome=StructuralGenome(omission=500)) == ()
    assert structure.space(()) == 0


def test_duplicate_headings_at_different_scopes_survive_the_floor() -> None:
    """`doctypes.lint` permits two sections to share a heading; `_position` must
    not put the second one back in the first's place."""
    plan = (Sec("Position", False), Sec("Detail", False), Sec("Position", False))
    genome = StructuralGenome(omission=structure.SCALE, floor=3)
    assert structure.derive(plan, key="d", genome=genome) == plan


def test_variant_choice_is_stable_and_biasable() -> None:
    variants = (outline("A"), outline("B"), outline("C"))
    keys = [f"artifact-{i:04d}" for i in range(300)]
    plain = [structure.choose(variants, key=k)[0].heading for k in keys]
    again = [structure.choose(variants, key=k)[0].heading for k in keys]
    assert plain == again
    assert set(plain) == {"A", "B", "C"}

    biased = [
        structure.choose(variants, key=k, genome=StructuralGenome(variant_bias=1))[0].heading
        for k in keys
    ]
    # A bias of one rotates every document by one variant, so no document keeps
    # its shape. That is the property a mosaic needs: two tenants built from one
    # engine must not agree on which variant each document got.
    assert all(a != b for a, b in zip(plain, biased, strict=True))


def test_choose_refuses_an_empty_variant_list() -> None:
    with pytest.raises(ValueError, match="at least one variant"):
        structure.choose((), key="d")


@pytest.mark.parametrize(
    ("omission", "floor", "bias"),
    [(-1, 1, 0), (structure.SCALE + 1, 1, 0), (0, 0, 0), (0, 1, -1)],
)
def test_genome_refuses_incoherent_values(omission: int, floor: int, bias: int) -> None:
    with pytest.raises(ValueError):
        StructuralGenome(omission=omission, floor=floor, variant_bias=bias)


def test_space_counts_reachable_shapes() -> None:
    genome = StructuralGenome(omission=500)
    assert structure.space(ALL_OPTIONAL, genome) == 31  # 2**5 - the empty one
    # Floor 3 over five optional sections: C(5,3) + C(5,4) + C(5,5) = 16.
    assert structure.space(ALL_OPTIONAL, StructuralGenome(omission=500, floor=3)) == 16
    assert structure.space(ALL_OPTIONAL, CLASSIC) == 1

    plan = outline("Position", "Drivers", "Actions", required=("Position",))
    assert structure.space(plan, genome) == 4  # two optional sections, floor 1


def test_space_agrees_with_enumeration() -> None:
    """The headline figure has to be the truth, so derive it twice."""
    genome = StructuralGenome(omission=500, floor=2)
    reachable = {
        tuple(s.heading for s in structure.derive(ALL_OPTIONAL, key=f"k{i}", genome=genome))
        for i in range(20000)
    }
    assert len(reachable) == structure.space(ALL_OPTIONAL, genome)


def test_varies_is_the_single_branch() -> None:
    assert not CLASSIC.varies
    assert StructuralGenome(omission=1).varies
    assert StructuralGenome(variant_bias=1).varies
    assert not StructuralGenome(floor=4).varies
