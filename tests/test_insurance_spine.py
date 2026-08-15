"""The insurer's organisation, held to being load-bearing.

The measured defect these tests close. On a one-period build the insurance
vertical produced 62 facts and four documents, and *every* entity of its
organisational spine reached nothing: three business units, twenty branches,
three claims centres, six underwriting offices, five systems and two cost
centres were declared by the archetype, minted into the world, named by no
fact, and carried by no compiled document. The estate was scenery.

So the tests here are not "the generator produces facts". They are the two
halves of *reaching* something — a fact names it, and a compiled document's own
**table cell** carries that fact — plus the arithmetic that makes the cut worth
carrying: sites sum to their unit and units to the group, exactly, at every
measure that decomposes.

The table-cell half is deliberate and is the whole difference between this
suite and one that cannot fail. `documents.outline` appends a hidden
"Supporting facts" appendix citing every fact a document was given, whatever
its prose says — so counting appendix citations as "carried" would make every
entity in every corpus reach something and these assertions decorative. The
same "two absent things agree" argument `validate.carried_evidence`'s docstring
records, one layer along.
"""

from __future__ import annotations

import pytest

from worldloom import InsuranceWorld, QuarterlyReserving, World

PERIOD = "2026-06"
SEED = 8128


@pytest.fixture(scope="module")
def world() -> World:
    return InsuranceWorld(seed=SEED).build().run(QuarterlyReserving(period=PERIOD))


@pytest.fixture(scope="module")
def compiled(world: World) -> World:
    return world.compile()


def _amounts(world: World, kind: str) -> dict[str, float]:
    return {
        f.subject: f.value.amount
        for f in world.facts
        if f.kind == kind and f.value is not None and not f.is_superseded
    }


def _cell_subjects(compiled: World) -> set[str]:
    """Subjects of every fact a compiled table cell actually names.

    Table cells only — see this module's docstring for why the appendix does
    not count.
    """
    subject_of = {f.id: f.subject for f in compiled.facts}
    reached: set[str] = set()
    for ir in compiled.artifact_irs:
        for section in ir.sections:
            if section.table is None:
                continue
            for row in section.table.rows:
                for cell in row.cells.values():
                    if cell.fact_id in subject_of:
                        reached.add(subject_of[cell.fact_id])
    return reached


# ---------------------------------------------------------------------------
# Reaching something
# ---------------------------------------------------------------------------


def test_every_declared_entity_is_named_by_a_fact(world: World) -> None:
    named = {f.subject for f in world.facts}
    for label, members in (
        ("business unit", world.business_units),
        ("site", world.sites),
        ("system", world.systems),
        ("cost centre", world.cost_centres),
        ("line of business", world.categories),
    ):
        unreached = sorted(m.id for m in members if m.id not in named)
        assert not unreached, f"{label}s named by no fact: {unreached}"


def test_every_declared_entity_is_carried_by_a_table_cell(compiled: World) -> None:
    reached = _cell_subjects(compiled)
    for label, members in (
        ("business unit", compiled.business_units),
        ("site", compiled.sites),
        ("system", compiled.systems),
        ("cost centre", compiled.cost_centres),
        ("line of business", compiled.categories),
    ):
        unreached = sorted(m.id for m in members if m.id not in reached)
        assert not unreached, f"{label}s in no compiled table cell: {unreached}"


def test_a_rendered_workbook_carries_the_estate(world: World, tmp_path) -> None:
    """The end of the chain, on a file rather than on an IR.

    A fact carried by an ``ArtifactIR`` that no renderer emits is still a fact
    nobody can open, so this reads the actual XLSX off disk and requires every
    branch, underwriting office and claims centre to appear in it by name.
    """
    openpyxl = pytest.importorskip("openpyxl")
    from worldloom.narrative import DeterministicProvider

    out = world.narrate(DeterministicProvider()).render("xlsx").export(tmp_path / "c")
    pack = next((out / "artifacts").glob("*underwriting-performance-pack.xlsx"))
    book = openpyxl.load_workbook(pack)
    printed = {
        str(value)
        for sheet in book.worksheets
        for row in sheet.iter_rows(values_only=True)
        for value in row
        if value is not None
    }

    for site in world.sites:
        assert site.name in printed, f"{site.name} is in no cell of the rendered pack"
    for centre in world.cost_centres:
        assert centre.name in printed
    for system in world.systems:
        assert system.name in printed
    for unit in world.business_units:
        assert any(unit.name in text for text in printed)


# ---------------------------------------------------------------------------
# The arithmetic that makes the cut worth carrying
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", [
    "financial.revenue.budget",
    "financial.revenue.actual",
    "financial.revenue.variance",
    "portfolio.policies_in_force",
    "claims_ops.notified_count",
    "claims_ops.settled_count",
])
def test_sites_sum_to_their_unit_exactly(world: World, kind: str) -> None:
    """Exactly, not nearly. ``finance.allocate``'s largest remainder is what
    makes this an equality rather than a tolerance — a residual of half a unit
    per row over twenty-six offices is a reconciliation failure the validator
    would (correctly) refuse."""
    stated = _amounts(world, kind)
    checked = 0
    for unit in world.business_units:
        parts = [stated[s.id] for s in world.sites
                 if s.business_unit_id == unit.id and s.id in stated]
        if not parts or unit.id not in stated:
            continue
        checked += 1
        assert sum(parts) == stated[unit.id], f"{kind} does not reconcile for {unit.name}"
    assert checked, f"no unit decomposes {kind}; the test proved nothing"


@pytest.mark.parametrize("kind", [
    "financial.revenue.budget",
    "financial.revenue.actual",
    "financial.revenue.variance",
    "portfolio.policies_in_force",
    "claims_ops.notified_count",
    "claims_ops.settled_count",
])
def test_units_sum_to_the_group_exactly(world: World, kind: str) -> None:
    stated = _amounts(world, kind)
    parts = [stated[u.id] for u in world.business_units if u.id in stated]
    assert parts, f"no unit states {kind}"
    assert sum(parts) == stated[world.company.id]


def test_lines_of_business_sum_to_their_unit_exactly(world: World) -> None:
    """The second, independent decomposition of the same unit total. Two
    decompositions that each reach the unit are a real cross-check; two
    independently *drawn* ones would be two contradictions."""
    for kind in ("financial.revenue.budget", "financial.revenue.actual",
                 "financial.revenue.variance"):
        stated = _amounts(world, kind)
        for unit in world.business_units:
            parts = [stated[c.id] for c in world.categories
                     if c.business_unit_id == unit.id and c.id in stated]
            if not parts:
                continue
            assert sum(parts) == stated[unit.id], f"{kind} / {unit.name}"


def test_cost_centres_sum_to_group_operating_expense(world: World) -> None:
    stated = _amounts(world, "expense.operating")
    parts = [stated[c.id] for c in world.cost_centres if c.id in stated]
    assert len(parts) == len(list(world.cost_centres))
    assert sum(parts) == stated[world.company.id]


def test_a_broken_roll_up_trips_the_organisation_check(world: World) -> None:
    """The check shown firing, not merely passing — the tamper convention
    `tests/test_insurance.py` states."""
    from dataclasses import replace as dc_replace

    target = next(f for f in world.facts
                  if f.kind == "expense.operating" and f.subject == world.company.id)
    tampered = dc_replace(world, _facts=tuple(
        f.model_copy(update={"value": f.value.model_copy(update={"amount": 1.0})})
        if f.id == target.id else f
        for f in world.facts
    ))
    codes = {v.code for v in tampered.validate().violations}
    assert "organisation_does_not_reconcile" in codes


# ---------------------------------------------------------------------------
# A place owns the measure it actually owns
# ---------------------------------------------------------------------------


def test_a_claims_centre_writes_no_premium(world: World) -> None:
    """The archetype gives a claims centre ``revenue_weight=0.0`` to say it
    processes claims rather than selling cover. A premium row of zero beside
    twenty branches would read as an office that tried and failed to sell."""
    premium = _amounts(world, "financial.revenue.actual")
    centres = [s for s in world.sites if s.revenue_weight == 0.0]
    assert centres, "the archetype no longer declares a zero-weight site"
    for centre in centres:
        assert centre.id not in premium
        assert centre.id not in _amounts(world, "portfolio.policies_in_force")


def test_an_underwriting_office_handles_no_claims(world: World) -> None:
    """The other half: an underwriting office and a claims centre are different
    kinds of place and do not own the same measure."""
    notified = _amounts(world, "claims_ops.notified_count")
    offices = [s for s in world.sites if s.revenue_weight > 0]
    assert offices
    for office in offices:
        assert office.id not in notified


def test_reserving_is_not_re_cut_by_site(world: World) -> None:
    """`reserves.*` is already cut by accident quarter over a cohort axis. A
    second cut by site would put two incompatible decompositions on one
    vocabulary and make "which quarter is this" ambiguous on every reserve."""
    places = {s.id for s in world.sites} | {c.id for c in world.cost_centres}
    trespassing = sorted(
        f.id for f in world.facts
        if f.kind.startswith(("reserves.", "claims.")) and f.subject in places
    )
    assert not trespassing, f"reserving facts cut by site: {trespassing}"


def test_no_rate_is_minted_at_a_level_that_would_have_to_sum(world: World) -> None:
    """A margin, a loss ratio and an expense ratio are ratios of totals and are
    never the total of ratios — `columns.not_summable` and
    `documents._RATE_KINDS` are the rule this repository has paid for twice.
    The book keeps it by not minting the figure, rather than by remembering to
    mark the column."""
    places = (
        {s.id for s in world.sites}
        | {c.id for c in world.cost_centres}
        | {c.id for c in world.categories}
    )
    rates = sorted(
        f"{f.kind}/{f.subject}" for f in world.facts
        if f.subject in places and f.value is not None
        and f.value.unit in ("percent", "pct", "bps")
    )
    assert not rates, f"a rate stated at a level a subtotal would add up: {rates}"


# ---------------------------------------------------------------------------
# The documents the book warrants
# ---------------------------------------------------------------------------


def test_the_commentary_fans_out_with_the_company(world: World) -> None:
    """One page per division, authored inside the division. Those managing
    director posts were minted for every unit by ``insurance_org._UNIT_ROLES``
    and authored nothing at all before this."""
    commentaries = [i for i in world.artifact_intents
                    if i.artifact_type == "underwriting_result_commentary"]
    assert len(commentaries) == len(list(world.business_units))
    authors = {world.people.by_id(i.author_id).title for i in commentaries}
    assert authors == {f"Managing Director, {u.name}" for u in world.business_units}
    # Signed one level up, and never by the author — `validate.approvals` fails
    # a document somebody countersigned for themselves.
    ceo = world._roles["ceo"]
    for intent in commentaries:
        assert intent.approver_id == ceo
        assert intent.approver_id != intent.author_id


def test_the_pack_is_planned_after_the_valuation_documents(world: World) -> None:
    """ART order is identity. The four the valuation warrants keep ids 1-4, so
    the checked-in narration and the evaluation cases that cite them by id are
    unmoved by anything the book adds."""
    ordered = [(i.id, i.artifact_type) for i in world.artifact_intents]
    assert [t for _, t in ordered[:4]] == [
        "reserve_triangle_workbook", "claims_emergence_note",
        "actuarial_valuation_report", "margin_decision_memo",
    ]
    assert ordered[4][1] == "underwriting_performance_pack"


def test_the_book_is_recorded_at_the_close_not_at_the_valuation(world: World) -> None:
    """The valuation reads a closed quarter, so the quarter's own book position
    is a fact of the close. Dating it to the valuation would make the
    performance pack a document written a month after the numbers it reports."""
    close = next(e for e in world.events if e.kind == "close_finalised")
    strengthened = next(e for e in world.events if e.kind == "reserves_strengthened")
    recorded = next(e for e in world.events if e.kind == "book_position_recorded")
    assert close.occurred_at < recorded.occurred_at < strengthened.occurred_at
    assert close.id in recorded.caused_by


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_the_book_is_a_pure_function_of_the_seed(world: World) -> None:
    again = InsuranceWorld(seed=SEED).build().run(QuarterlyReserving(period=PERIOD))
    book_kinds = ("financial.revenue.", "portfolio.", "claims_ops.", "expense.", "data.")
    mine = [f.model_dump() for f in world.facts if f.kind.startswith(book_kinds)]
    theirs = [f.model_dump() for f in again.facts if f.kind.startswith(book_kinds)]
    assert mine and mine == theirs
