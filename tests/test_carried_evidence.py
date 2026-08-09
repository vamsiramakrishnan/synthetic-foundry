"""A document carries what it was handed, and every cell it cites says something.

The three checks here exist because a corpus passed tens of thousands of them
without any of them. `validate.compiled_evidence` was written after the
finance-workbook defect — a workbook that looked its figures up at the wrong
month and rendered with every cell empty — and it closed the evaluation-set half
of that hole while leaving the document half open: it asks whether a *case's*
evidence is in some document, and one hit in one document answers it.

The tests below reproduce each surviving hole against a real corpus rather than
a fixture, because a fixture small enough to hand-build is a fixture too small to
have the defect. Each mutates a compiled world in memory and asserts the report
turns; the control in each case is the unmutated world, which must stay clean.
"""

from __future__ import annotations

import pytest

from worldloom import documents
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose


@pytest.fixture(scope="module")
def compiled():  # type: ignore[no-untyped-def]
    return RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03")).compile()


def test_the_stock_corpus_carries_everything_it_plans(compiled) -> None:  # type: ignore[no-untyped-def]
    """The control, and a claim in its own right.

    Not a tautology: before the budget-margin column and the triangle's book row
    existed, this failed on retail and on insurance. Every fact an intent lists
    reaches its own compiled document — through a table cell, a section's own
    citations, or the lineage appendix — with nothing planned into a document
    and dropped on the way in.
    """
    report = compiled.validate()
    assert report.ok, report.violations[:5]

    by_intent = {ir.intent_id: ir for ir in compiled.artifact_irs}
    for intent in compiled.artifact_intents:
        carried = set(by_intent[intent.id].fact_ids())
        assert set(intent.required_fact_ids) <= carried, intent.id


def test_a_column_that_reads_no_fact_kind_is_caught() -> None:
    """The `gross_margin_pct.budget` defect, reproduced.

    The fact was minted per category and per unit, planned into the month-end
    model by `generators/planning.py`, and read by no column of it — 114 facts a
    build, for as long as the workbook had existed. Nothing complained: the plan
    still listed them, reconciliation compared two absent numbers, and the
    evaluation set never cited them, so `compiled_evidence` had nothing to say.
    """
    measures = dict(documents._MEASURES)
    derived = dict(documents._DERIVED)
    columns = documents._pnl_columns
    compiler = documents._COMPILERS["finance_workbook"]

    def without_budget_margin(world, intent, minter):  # type: ignore[no-untyped-def]
        ir = compiler(world, intent, minter)
        for section in ir.sections:
            for chart in section.charts:
                object.__setattr__(
                    chart, "series", [k for k in chart.series if k != "gm_pct_budget"]
                )
        return ir

    documents._MEASURES.pop("gm_pct_budget")
    documents._DERIVED.pop("gm_pct_budget")
    documents._pnl_columns = lambda: [c for c in columns() if c.key != "gm_pct_budget"]
    documents._COMPILERS["finance_workbook"] = without_budget_margin
    try:
        world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03")).compile()
        report = world.validate()
    finally:
        documents._MEASURES.clear()
        documents._MEASURES.update(measures)
        documents._DERIVED.clear()
        documents._DERIVED.update(derived)
        documents._pnl_columns = columns
        documents._COMPILERS["finance_workbook"] = compiler

    assert not report.ok
    codes = {v.code for v in report.violations}
    assert "required_fact_not_carried" in codes, codes


def test_a_cell_that_cites_a_fact_and_states_nothing_is_caught() -> None:
    """The original defect's signature on the page, not in the plan.

    `ArtifactIR.fact_ids()` collects a cell's `fact_id` and never looks at its
    `value`, so a workbook whose every cell went blank while keeping its
    citations satisfies the check above exactly as it satisfied reconciliation.
    An adversarial pass over this validator did precisely this — blanked all
    17,216 values on a retail build — and got a byte-identical check count with
    no violations.
    """
    world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03")).compile()
    blanked = 0
    for ir in world.artifact_irs:
        for section in ir.sections:
            if section.table is None:
                continue
            for row in section.table.rows:
                for key, cell in row.cells.items():
                    if cell.fact_id and cell.value is not None:
                        row.cells[key] = cell.model_copy(update={"value": None})
                        blanked += 1
    assert blanked > 100, "the fixture must have cells worth blanking"

    report = world.validate()
    assert not report.ok
    assert {v.code for v in report.violations} == {"empty_cell_cites_a_fact"}
    assert len(report.violations) == blanked


def test_intents_that_never_compiled_are_counted() -> None:
    """Compiling is all-or-nothing, so a short IR list is a compiler that gave up.

    Without this the group above measures the documents that *did* compile and
    reports clean on a smaller check count nobody compares against anything —
    the same shape as every other blind spot in this file: an empty collection
    scoring zero out of zero.
    """
    world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03")).compile()
    object.__setattr__(world, "_artifact_irs", world._artifact_irs[:1])
    report = world.validate()
    assert not report.ok
    assert "compiled_fewer_than_planned" in {v.code for v in report.violations}
