"""The detail layer — transaction rows under the ledger, measured.

Three claims pinned, matching what `detail.py` promises:

1. **The sum-to-fact rule holds by construction.** Every column allocated
   from a fact sums back to it exactly at the declared precision — largest
   remainder, compared in scaled integers so float accumulation over a
   thousand rows cannot manufacture a cent.
2. **A recipe naming a fact the registry does not know is refused** at lint,
   with the reason — never generated around. Same for a pool that does not
   exist and a reference that points forward.
3. **Detail rows are corpus data** — export/load/export round-trips
   byte-identically, and a spec with no detail recipe produces no rows and
   no file, so every existing corpus keeps its exact bytes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from worldloom import ProcureToPayWorld, episodes
from worldloom import detail
from worldloom.ids import Minter
from worldloom.locales import DEFAULT as CALENDAR
from worldloom.models import Authority, CanonicalFact, Quantity
from worldloom.rng import Rng

SPEC_PATH = Path(__file__).parent.parent / "examples" / "episodes" / "procure-to-pay.json"


@pytest.fixture(scope="module")
def spec() -> episodes.EpisodeSpec:
    specs = episodes.load(SPEC_PATH)
    episodes.install(specs)
    return specs[0]


@pytest.fixture(scope="module")
def world(spec: episodes.EpisodeSpec):
    built = ProcureToPayWorld(seed=8128).build()
    return built.run(episodes.AuthoredEpisode(episode=spec.name, period="2026-03"))


def _fact(kind: str, amount: float, unit: str = "AUD_thousands") -> CanonicalFact:
    # A fixed id, not hash(kind): hash() is per-process-randomised, and even a
    # test file keeps the no-hash() discipline the ledger's keys demand.
    return CanonicalFact(
        id="FACT-9001", kind=kind, subject="CO-0001",
        value=Quantity(amount=amount, unit=unit),
        valid_from=datetime(2026, 3, 3, 9, 0, tzinfo=timezone.utc),
        authority=Authority.SYSTEM_OF_RECORD,
    )


# ---------------------------------------------------------------------------
# 1. The rule
# ---------------------------------------------------------------------------


def test_allocation_sums_exactly_at_declared_decimals() -> None:
    """Largest remainder in fixed point: whatever the weights, the parts sum
    to the total exactly — the discipline `rollup` guarantees for whole units,
    extended to cents."""
    rng = Rng(8128).derive("test/allocation")
    weights = detail._lognormal_weights(rng, 1_148, 0.6)
    parts = detail.allocate_scaled(1_921.75, weights, decimals=2)
    assert round(sum(round(p * 100) for p in parts)) == 192_175
    units = detail.allocate_scaled(1_148, [1.0] * 1_148, decimals=0)
    assert sum(units) == 1_148 and set(units) == {1.0}


def test_rows_sum_to_the_fact_by_construction(world) -> None:
    """The P2P proof: every fact-backed column of every generated table sums
    to its fact to the cent, and every count-from-fact table has exactly the
    declared number of lines."""
    facts = {f.id: f for f in world.facts}
    tables = list(world.detail_tables)
    assert len(tables) == 3
    checked = 0
    for table in tables:
        assert int(facts[table.count_fact_id].value.amount) == len(table.rows)
        for column in table.columns:
            if not column.fact_id:
                continue
            scale = 10 ** column.decimals
            summed = sum(round(float(row[column.name]) * scale) for row in table.rows)
            assert summed == round(facts[column.fact_id].value.amount * scale), (
                table.name, column.name,
            )
            checked += 1
    assert checked == 6  # qty + value on each of the three tables


def test_a_drawn_spread_still_sums_to_the_fact() -> None:
    """The lognormal spread (synthkit's money shape) only shapes the split;
    the sum stays the ledger's. Run through `generate` itself so the whole
    path is exercised, not just the allocator."""
    table = detail.TableSpec(
        name="mixed_basket", rows=200,
        columns=[
            detail.ColumnSpec(name="line", kind="sequence", prefix="MB-"),
            detail.ColumnSpec(name="amount", kind="from_fact",
                              fact_kind="p2p.ordered_value", spread="lognormal",
                              sigma=0.9, decimals=2),
        ],
    )
    fact = _fact("p2p.ordered_value", 1_921.75)
    (made,) = detail.generate(
        [table], episode="Test", period="2026-03", cadence="month",
        facts=(fact,), intents=(), rng=Rng(8128).derive("test/detail"),
        minter=Minter(), calendar=CALENDAR,
    )
    amounts = [row["amount"] for row in made.rows]
    assert sum(round(a * 100) for a in amounts) == 192_175
    # The spread is real: a mixed basket, not one rate photocopied.
    assert len({round(a, 2) for a in amounts}) > 20


# ---------------------------------------------------------------------------
# 2. The refusals
# ---------------------------------------------------------------------------


def test_a_recipe_naming_an_unknown_fact_kind_is_refused() -> None:
    """The non-negotiable lint: a fact kind the registry does not know cannot
    anchor detail rows — the invented-kind defect factkinds exists to refuse."""
    table = detail.TableSpec(
        name="ghost", count_from_fact="p2p.imagined_kind",
        columns=[detail.ColumnSpec(name="amount", kind="from_fact",
                                   fact_kind="p2p.another_invention")],
    )
    findings = detail.lint([table])
    assert len(findings) == 2
    assert all("fact-kind registry" in finding for finding in findings)


def test_the_lint_refuses_the_rest_of_the_recipe_mistakes() -> None:
    tables = [
        detail.TableSpec(  # unknown pool, and both row sources set
            name="lines", rows=10, count_from_fact="p2p.ordered_quantity",
            columns=[detail.ColumnSpec(name="item", kind="choice", pool="no_such_pool")],
        ),
        detail.TableSpec(  # forward reference — referents must exist first
            name="early", rows=5,
            columns=[detail.ColumnSpec(name="late_ref", kind="ref",
                                       table="later", column="line")],
        ),
        detail.TableSpec(
            name="later", rows=5,
            columns=[detail.ColumnSpec(name="line", kind="sequence", prefix="L-")],
        ),
    ]
    findings = detail.lint(tables)
    assert any("exactly one of" in f for f in findings)
    assert any("not a vendored pool" in f for f in findings)
    assert any("point backwards" in f for f in findings)


def test_the_episode_lint_carries_detail_findings(spec: episodes.EpisodeSpec) -> None:
    """A kind that is registry-known but not minted by the episode is refused
    too — a step's detail may only expand the step's own facts. Checked
    through `episodes.lint`, the surface an author actually reads."""
    bad = spec.model_copy(update={"detail_tables": [
        detail.TableSpec(
            name="capital_lines", rows=10,
            columns=[detail.ColumnSpec(name="amount", kind="from_fact",
                                       fact_kind="capital.rwa_total")],
        ),
    ]})
    findings = episodes.lint([bad], base="procurement")
    assert any("not minted by this episode" in f for f in findings)
    # And the shipped spec itself is clean, detail included.
    assert episodes.lint([spec], base="procurement") == []


def test_an_aligned_ref_may_be_short_but_never_long() -> None:
    """A receipt shorter than its order is the shortfall, and is legal; a
    table referencing more referent rows than exist is refused at run."""
    tables = [
        detail.TableSpec(name="orders", rows=5, columns=[
            detail.ColumnSpec(name="line", kind="sequence", prefix="O-")]),
        detail.TableSpec(name="receipts", rows=8, columns=[
            detail.ColumnSpec(name="order_line", kind="ref", table="orders",
                              column="line", align=True)]),
    ]
    with pytest.raises(ValueError, match="cannot align"):
        detail.generate(
            tables, episode="Test", period="2026-03", cadence="month",
            facts=(), intents=(), rng=Rng(8128).derive("test/detail"),
            minter=Minter(), calendar=CALENDAR,
        )


# ---------------------------------------------------------------------------
# 3. Corpus data
# ---------------------------------------------------------------------------


def test_detail_round_trips_byte_identically(world, tmp_path) -> None:
    from worldloom import World

    first = tmp_path / "first"
    world.export(first)
    loaded = World.load(first)
    assert tuple(loaded.detail_tables) == tuple(world.detail_tables)
    again = tmp_path / "again"
    loaded.export(again)
    assert (first / "detail.jsonl").read_bytes() == (again / "detail.jsonl").read_bytes()
    # And the loaded corpus is held to the rule the generator constructed:
    # the detail check group runs and passes on what came off disk.
    report = loaded.validate()
    assert report.ok, report.violations[:5]


def test_a_spec_without_detail_changes_nothing(spec, tmp_path) -> None:
    """Opt-in, measured: the same episode with its detail recipe stripped
    mints no tables and writes no file — absent recipes leave every corpus
    byte-identical to what it was."""
    bare = spec.model_copy(update={"name": "ProcureToPayBare", "detail_tables": []})
    episodes.install([bare])
    world = ProcureToPayWorld(seed=8128).build().run(
        episodes.AuthoredEpisode(episode="ProcureToPayBare", period="2026-03"))
    assert len(world.detail_tables) == 0
    out = tmp_path / "bare"
    world.export(out)
    assert not (out / "detail.jsonl").exists()


def test_the_receipt_references_close_and_the_missing_tail_is_the_shortfall(world) -> None:
    """The referential-closure claim, plus its point: every receipt line names
    a real order line, and the order lines nothing receipts are exactly the
    open shortfall the ledger carries."""
    tables = {t.name: t for t in world.detail_tables}
    order_lines = [row["line"] for row in tables["order_lines"].rows]
    receipted = [row["order_line"] for row in tables["receipt_lines"].rows]
    assert set(receipted) <= set(order_lines)
    shortfall = world.authoritative(
        "p2p.open_shortfall_quantity", world.company.id, period="2026-03")
    assert len(order_lines) - len(receipted) == int(shortfall.value.amount)


def test_edge_cases_are_recorded_and_never_touch_the_rule() -> None:
    """synthkit's seeded edge injection, under Worldloom's contract: a declared
    fraction of choice values goes messy, every injected row is recorded, and
    the protected columns — ids, refs, fact-backed amounts — hold exactly."""
    table = detail.TableSpec(
        name="messy_lines", rows=400, edge_case_rate=0.05,
        columns=[
            detail.ColumnSpec(name="line", kind="sequence", prefix="ML-"),
            detail.ColumnSpec(name="item", kind="choice", pool="plant_hire_items"),
            detail.ColumnSpec(name="amount", kind="from_fact",
                              fact_kind="p2p.ordered_value", decimals=2),
        ],
    )
    fact = _fact("p2p.ordered_value", 500.00)
    (made,) = detail.generate(
        [table], episode="Test", period="2026-03", cadence="month",
        facts=(fact,), intents=(), rng=Rng(8128).derive("test/detail"),
        minter=Minter(), calendar=CALENDAR,
    )
    assert made.edge_rows, "a 5% rate over 400 rows injected nothing"
    for entry in made.edge_rows:
        index, column, kind = entry.split(":")
        assert column == "item"  # only the choice column is eligible
        assert kind in ("unicode_variant", "near_duplicate")
    assert sum(round(row["amount"] * 100) for row in made.rows) == 50_000
    assert [row["line"] for row in made.rows] == [
        f"ML-{i + 1:04d}" for i in range(400)
    ]


def test_detail_reaches_the_workbook_as_a_real_sheet(world) -> None:
    """Hundreds of literal rows plus a computed total per fact-backed column —
    the sheet a system export would have, with the workbook's own discipline
    (the total is a formula, and what it sums to is the ledger's figure)."""
    openpyxl = pytest.importorskip("openpyxl")
    from io import BytesIO

    rendered = world.render("xlsx")
    order = next(r for r in rendered._rendered if "purchase-order" in r.path)
    book = openpyxl.load_workbook(BytesIO(order.payload))
    sheet = book["Order line detail"]
    table = next(t for t in world.detail_tables if t.name == "order_lines")
    first, total_row = 4, 4 + len(table.rows)
    assert sheet.max_row >= total_row
    assert sheet.cell(row=total_row, column=1).value == "Total"
    assert sheet.cell(row=total_row, column=6).value == f"=SUM(F{first}:F{total_row - 1})"


def test_markdown_shows_the_head_and_states_the_count(world) -> None:
    from worldloom.render import markdown

    staged = world if world._artifact_irs else world.compile()
    table = next(t for t in staged.detail_tables if t.name == "order_lines")
    ir = next(i for i in staged.artifact_irs if i.intent_id == table.artifact_id)
    text = markdown.render(ir, detail=[table]).decode("utf-8")
    assert "Order line detail" in text
    assert f"First 10 of {len(table.rows):,} lines" in text
    assert text.count("POL-") == 10
