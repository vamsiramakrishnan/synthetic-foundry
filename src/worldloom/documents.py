"""Intent to IR — the document compiler.

Turns an ``ArtifactIntent`` into an ``ArtifactIR``: resolved sections, resolved
tables, every reference bound, every computation declared. No prose.

Prose is absent on purpose rather than by omission. Resolving structure and data
*first* is what lets narrative later be written against numbers that already
exist, and it is why a promised appendix is always present. A section with
``body=None`` is an outline awaiting the narrative compiler at build-order step 6;
the tables around it are already final.

The finance workbook is the exception that needs no prose at all, which is why the
build order renders it first: it is a source artifact, and it carries the hard
reconciliation constraints everything else is checked against.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from .ids import Minter
from .narrative import references
from .models import (
    ArtifactIntent,
    ArtifactIR,
    ArtifactSection,
    Authority,
    CanonicalFact,
    Cell,
    Chart,
    ChartKind,
    Column,
    FormulaKind,
    Lifecycle,
    Row,
    Table,
)

if TYPE_CHECKING:  # pragma: no cover
    from .world import World

MONEY_FORMAT = "#,##0;(#,##0)"
PERCENT_FORMAT = "0.00%"
RATE_FORMAT = "0.00"

#: Authority and lifecycle by artifact type. A working note is not a report, and
#: a triage page raised before the cause is known is neither.
_STANDING: dict[str, tuple[Authority, Lifecycle]] = {
    "finance_workbook": (Authority.SYSTEM_OF_RECORD, Lifecycle.PUBLISHED),
    "close_calendar": (Authority.SYSTEM_OF_RECORD, Lifecycle.PUBLISHED),
    "servicenow_incident": (Authority.SYSTEM_OF_RECORD, Lifecycle.PUBLISHED),
    "jira_issues": (Authority.SYSTEM_OF_RECORD, Lifecycle.PUBLISHED),
    "incident_rca": (Authority.APPROVED_REPORT, Lifecycle.REVIEWED),
    "cfo_variance_memo": (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED),
    "executive_summary": (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED),
    "knowledge_article": (Authority.WORKING_DOCUMENT, Lifecycle.PUBLISHED),
    "working_note": (Authority.WORKING_DOCUMENT, Lifecycle.DRAFT),
    "confluence_page": (Authority.UNOFFICIAL_NOTE, Lifecycle.DRAFT),
}

#: How long after its newest supporting fact an artifact is written. An artifact
#: may never predate the facts it cites, so this is added rather than guessed.
_LAG: dict[str, timedelta] = {
    "confluence_page": timedelta(minutes=20),
    "working_note": timedelta(hours=18),
    "servicenow_incident": timedelta(minutes=5),
    "jira_issues": timedelta(minutes=0),
    "knowledge_article": timedelta(hours=3),
    "incident_rca": timedelta(hours=2),
    "finance_workbook": timedelta(minutes=50),
    "cfo_variance_memo": timedelta(hours=17),
    "executive_summary": timedelta(days=1, hours=15),
    "close_calendar": timedelta(hours=1),
}


def standing(artifact_type: str) -> tuple[Authority, Lifecycle]:
    """The authority and lifecycle an artifact of this type carries."""
    return _STANDING.get(artifact_type, (Authority.WORKING_DOCUMENT, Lifecycle.DRAFT))


def declared_types() -> frozenset[str]:
    """Every artifact type some module has actually declared.

    Membership is keyed on ``_STANDING`` alone, and that is the load-bearing
    choice rather than an arbitrary one. Three of the four tables have honest
    fallbacks — ``compile_intent`` falls through to ``outline``, ``outline``
    falls through to ``_DEFAULT_OUTLINE``, ``written_at`` falls through to an
    hour — so a type missing from any of them still produces a document. A
    missing *standing* also falls through, to ``(WORKING_DOCUMENT, DRAFT)``,
    but that is a modelling claim about the document's authority, and it is the
    one nothing downstream can distinguish from a decision: an artifact type
    somebody forgot to register looks exactly like an artifact type somebody
    decided was an unreviewed draft. ``distractors.py`` states the same rule
    from the other side when it registers ``routine_notice``'s standing rather
    than letting it fall through.

    So this is the set a *plan* may name. It exists because a facet can now
    imply a filing (``facets.FILING_PREFIX``), and a filing naming a type no
    module has declared would be an intent minted for a document that compiles
    into a one-section stub with an authority nobody chose — carried, cited,
    and inert, which is the failure this repository keeps finding. ``facets.
    unmet`` reports that case rather than letting the plan grow an entry for
    it.

    It is not yet exhaustive over what the engine plans, and the gap it exposes
    is worth stating: ``scenarios._personnel_notice`` mints
    ``personnel_notice`` intents and nothing has ever declared that type, so a
    succession announcement is silently an unreviewed draft. Declaring it here
    is the wrong fix — ``tests/test_thin_waist.py`` counts that name as retail
    vocabulary and this is a core module, correctly — so it wants a
    registration from whichever module owns the scenario, which is a change of
    its own.
    """
    return frozenset(_STANDING)


def register_artifact_types(
    *,
    standing: dict[str, tuple[Authority, Lifecycle]] | None = None,
    lags: dict[str, "timedelta"] | None = None,
    outlines: dict[str, tuple["SectionPlan", ...]] | None = None,
    compilers: dict[str, Any] | None = None,
) -> None:
    """Add a domain module's artifact types to the compiler's tables.

    The tables above are retail vocabulary and stay that way — a second
    vertical's types are registered from its own module rather than written
    here, so the list of what banking publishes lives beside banking's episode
    (build-order §7a). Registration happens at package import, the same
    contract as ``validate.register_domain_checks``: types that exist only when
    the right module happened to be imported would make ``compile()`` differ
    between processes, which is a determinism bug wearing a plugin's clothes.

    Re-registering the same value is harmless; changing what an existing type
    means is refused, because two modules that disagree about a type's standing
    would make an artifact's authority depend on import order.
    """
    for table, additions in (
        (_STANDING, standing),
        (_LAG, lags),
        (_OUTLINES, outlines),
        (_COMPILERS, compilers),
    ):
        for key, value in (additions or {}).items():
            if key in table and table[key] != value:
                raise ValueError(f"artifact type {key!r} is already registered differently")
            table[key] = value  # type: ignore[assignment]


def written_at(intent: ArtifactIntent, facts: dict[str, CanonicalFact]):  # type: ignore[no-untyped-def]
    """When an artifact of this intent was written.

    The newest fact it cites, plus a type-dependent lag. Derived rather than
    chosen so that ``cites_future_fact`` cannot fire: an artifact is written after
    the things it talks about.
    """
    cited = [facts[f].valid_from for f in intent.required_fact_ids if f in facts]
    if not cited:
        raise ValueError(f"{intent.id} cites no resolvable facts, so it has no date")
    return max(cited) + _LAG.get(intent.artifact_type, timedelta(hours=1))


def _money(amount: float | None, fact_id: str | None = None) -> Cell:
    return Cell(value=amount, fact_id=fact_id)


#: The seven P&L columns, and the fact kind each reads.
_MEASURES: dict[str, str] = {
    "revenue_budget": "financial.revenue.budget",
    "revenue_actual": "financial.revenue.actual",
    "revenue_variance": "financial.revenue.variance",
    "gp_budget": "financial.gross_profit.budget",
    "gp_actual": "financial.gross_profit.actual",
    "gp_variance": "financial.gross_profit.variance",
    "gm_pct_actual": "financial.gross_margin_pct.actual",
}

#: Columns computed from the two beside them, and from which. Declared once here
#: so a category row, a unit subtotal, and the group row all recompute the same
#: way — a subtotal that pasted its variance while the rows above computed theirs
#: is exactly the disagreement this project exists to prevent.
_DERIVED: dict[str, tuple[FormulaKind, list[str]]] = {
    "revenue_variance": (FormulaKind.DIFFERENCE, ["revenue_actual", "revenue_budget"]),
    "gp_variance": (FormulaKind.DIFFERENCE, ["gp_actual", "gp_budget"]),
    "gm_pct_actual": (FormulaKind.RATIO_PCT, ["gp_actual", "revenue_actual"]),
}

#: Columns a subtotal must *not* sum, because they do not add up. A margin
#: percentage is a ratio of totals, never the total of ratios; a variance, by
#: contrast, is additive, so a subtotal sums its children's variances and shows
#: which of them the group's miss came from.
_NOT_ADDITIVE = frozenset({"gm_pct_actual"})


def _pnl_columns() -> list[Column]:
    return [
        Column(key="revenue_budget", label="Revenue budget", number_format=MONEY_FORMAT),
        Column(key="revenue_actual", label="Revenue actual", number_format=MONEY_FORMAT),
        Column(key="revenue_variance", label="Revenue variance", number_format=MONEY_FORMAT),
        Column(key="gp_budget", label="GP budget", number_format=MONEY_FORMAT),
        Column(key="gp_actual", label="GP actual", number_format=MONEY_FORMAT),
        Column(key="gp_variance", label="GP variance", number_format=MONEY_FORMAT),
        Column(key="gm_pct_actual", label="GM% actual", number_format=PERCENT_FORMAT),
    ]


class _Facts:
    """The cited facts, indexed by what a sheet asks for.

    A workbook at store level cites thousands of facts and reads each of them
    several times. Scanning the list per lookup is quadratic, and the period must
    be part of the key — with a trend in the corpus, a scan for
    ``revenue.actual`` of a category finds last January first.
    """

    __slots__ = ("_by_key", "all")

    def __init__(self, facts: list[CanonicalFact]) -> None:
        self.all = facts
        self._by_key: dict[tuple[str, str, str | None], CanonicalFact] = {}
        for fact in facts:
            if not fact.is_superseded:
                self._by_key.setdefault((fact.kind, fact.subject, fact.period), fact)

    def get(self, kind: str, subject: str, period: str | None) -> CanonicalFact | None:
        return self._by_key.get((kind, subject, period))


def _measure_row(
    index: _Facts,
    *,
    key: str,
    label: str,
    subject: str,
    period: str,
    columns: list[Column],
    children: list[str] | None = None,
    emphasis: bool = False,
    extra: dict[str, Cell] | None = None,
) -> Row:
    """One P&L row: stated where the ledger states it, computed where it derives.

    ``children`` makes the row a subtotal, summing the named rows rather than
    restating a figure — so a reader who deletes a category sees the unit total
    move.
    """
    cells: dict[str, Cell] = {}
    for column in columns:
        fact = index.get(_MEASURES[column.key], subject, period)
        value = fact.value.amount if fact and fact.value else None
        fact_id = fact.id if fact else None
        derived = _DERIVED.get(column.key)
        if children and column.key not in _NOT_ADDITIVE:
            cells[column.key] = Cell(
                value=value, fact_id=fact_id, formula=FormulaKind.SUM, operands=children
            )
        elif derived is not None:
            formula, operands = derived
            cells[column.key] = Cell(value=value, fact_id=fact_id, formula=formula, operands=operands)
        else:
            cells[column.key] = _money(value, fact_id)
    # Descriptive columns a sheet carries alongside its measures — a store's
    # region and format. They are passed in rather than looked up because they
    # belong to the entity, not to the fact ledger.
    cells.update(extra or {})
    return Row(key=key, label=label, cells=cells, emphasis=emphasis)


def _sum_row(
    key: str,
    label: str,
    *,
    columns: list[Column],
    children: list[str],
    source: list[Row],
    extra: dict[str, Cell] | None = None,
) -> Row:
    """A total that reports the rows above it rather than a figure from the ledger.

    Needed where the rows present do not cover the whole parent. A store sheet in
    a world whose online division has no stores cannot carry a "Group" row citing
    the group revenue fact: the fact includes the online unit and the sheet does
    not, so the row would state a total its own formula contradicts. Caught by the
    formula evaluator in the render tests, which recomputes every cell rather than
    trusting that a declared sum sums.
    """
    lookup = {row.key: row for row in source}
    cells: dict[str, Cell] = {}
    for column in columns:
        if column.key in _NOT_ADDITIVE:
            continue
        total = sum(
            (lookup[child].cells[column.key].value or 0.0)
            for child in children
            if child in lookup and column.key in lookup[child].cells
        )
        cells[column.key] = Cell(value=total, formula=FormulaKind.SUM, operands=children)
    for column in columns:
        derived = _DERIVED.get(column.key)
        if derived is None or column.key not in _NOT_ADDITIVE:
            continue
        formula, operands = derived
        left = cells.get(operands[0])
        right = cells.get(operands[1])
        if left is None or right is None:
            continue
        if formula is FormulaKind.DIFFERENCE:
            value = (left.value or 0.0) - (right.value or 0.0)
        else:
            value = ((left.value or 0.0) / right.value * 100) if right.value else 0.0
        cells[column.key] = Cell(value=value, formula=formula, operands=operands)
    cells.update(extra or {})
    return Row(key=key, label=label, cells=cells, emphasis=True)


# ---------------------------------------------------------------------------
# The finance workbook
# ---------------------------------------------------------------------------


def finance_workbook(world: World, intent: ArtifactIntent, minter: Minter) -> ArtifactIR:
    """The month-end model.

    A source artifact, not a projection of one. Every total is declared as a sum
    of the rows above it, every variance as a difference, every margin as a ratio
    — so a reader who recalculates the sheet gets the same answer, and a renderer
    that supports formulas can emit them rather than paste values.

    The sheets follow the reporting hierarchy rather than a fixed list. A retailer
    reads its month at category level and its estate at store level, so those
    sheets exist when the world has those dimensions and are absent when it does
    not — an empty "Store Performance" tab is worse than no tab.
    """
    by_id = {fact.id: fact for fact in world._facts}
    index = _Facts([by_id[f] for f in intent.required_fact_ids if f in by_id])
    facts = index.all
    periods = sorted({f.period for f in facts if f.period})
    period = world.period or (periods[-1] if periods else "")
    units = list(world.business_units)
    company = world.company

    unit_keys = [unit.id for unit in units]
    columns = _pnl_columns()

    categories_of = {
        unit.id: [c for c in world.categories if c.business_unit_id == unit.id]
        for unit in units
    }
    # A site with no revenue fact is a site the finance generator did not book
    # turnover for — a distribution centre. It belongs on a property register, not
    # on a store P&L.
    sites_of = {
        unit.id: [
            s
            for s in world.sites
            if s.business_unit_id == unit.id
            and index.get("financial.revenue.actual", s.id, period) is not None
        ]
        for unit in units
    }

    # -- Business Unit P&L -------------------------------------------------
    rows = [
        _measure_row(index, key=unit.id, label=unit.name, subject=unit.id,
                     period=period, columns=columns)
        for unit in units
    ]
    rows.append(
        _measure_row(index, key=company.id, label="Group", subject=company.id, period=period,
                     columns=columns, children=unit_keys, emphasis=True)
    )

    pnl = Table(
        key="pnl",
        title="Business Unit P&L",
        columns=columns,
        rows=rows,
        note="Group is the sum of the business units above. Variances recompute from actual less budget.",
    )
    group_cells = rows[-1].cells

    # -- Summary -----------------------------------------------------------
    def summary_row(key: str, label: str, *, emphasis: bool = False) -> Row:
        cell = group_cells[key]
        return Row(key=key, label=label, emphasis=emphasis, cells={
            "value": Cell(value=cell.value, fact_id=cell.fact_id,
                          formula=FormulaKind.REFERENCE,
                          operands=[f"pnl:{company.id}:{key}"])})

    summary = Table(
        key="summary",
        title="Summary",
        columns=[Column(key="value", label="Value", number_format=MONEY_FORMAT)],
        rows=[
            summary_row("revenue_actual", "Revenue actual"),
            summary_row("revenue_budget", "Revenue budget"),
            summary_row("revenue_variance", "Revenue variance", emphasis=True),
            summary_row("gp_actual", "Gross profit actual"),
            summary_row("gp_variance", "Gross profit variance", emphasis=True),
        ],
        note=f"{company.name} · {period} · {company.currency} {company.currency_unit}",
    )

    sections = [
        ArtifactSection(heading="Summary", table=summary),
        ArtifactSection(
            heading="Business Unit P&L",
            table=pnl,
            # Budget beside actual, by division. The chart plots the unit rows
            # only: including the group row would put a bar four times the height
            # of the others next to them and make the comparison unreadable, and
            # including it *and* the units would draw the same money twice.
            charts=[
                Chart(
                    key="pnl_revenue",
                    title="Revenue against budget by division",
                    kind=ChartKind.COLUMN,
                    table="pnl",
                    series=["revenue_budget", "revenue_actual"],
                    rows=unit_keys,
                    category_axis="Division",
                    value_axis=f"{company.currency} {company.currency_unit}",
                ),
                Chart(
                    key="pnl_margin",
                    title="Gross margin against budget by division",
                    kind=ChartKind.COLUMN,
                    table="pnl",
                    series=["gm_pct_actual"],
                    rows=unit_keys,
                    category_axis="Division",
                    value_axis="Gross margin %",
                ),
            ],
        ),
    ]

    # -- Category P&L ------------------------------------------------------
    # The level the business is actually managed at. A unit subtotal here sums
    # its own categories, and the group row sums the subtotals — never the
    # categories directly, or every line would be counted twice.
    category_rows: list[Row] = []
    subtotal_keys: list[str] = []
    for unit in units:
        members = categories_of[unit.id]
        if not members:
            continue
        for category in members:
            category_rows.append(
                _measure_row(index, key=category.id, label=f"{unit.name} · {category.name}",
                             subject=category.id, period=period, columns=columns)
            )
        category_rows.append(
            _measure_row(index, key=unit.id, label=f"{unit.name} total", subject=unit.id,
                         period=period, columns=columns,
                         children=[c.id for c in members], emphasis=True)
        )
        subtotal_keys.append(unit.id)

    category_table: Table | None = None
    if category_rows:
        covers_group = len(subtotal_keys) == len(units)
        category_rows.append(
            _measure_row(index, key=company.id, label="Group", subject=company.id, period=period,
                         columns=columns, children=subtotal_keys, emphasis=True)
            if covers_group
            else _sum_row(company.id, "Total, categorised units", columns=columns,
                          children=subtotal_keys, source=category_rows)
        )
        category_table = Table(
            key="category",
            title="Category P&L",
            columns=columns,
            rows=category_rows,
            note=(
                "Categories sum to their business unit; the unit totals sum to group. "
                "Margin varies by category, so the group rate moves with the mix as well "
                "as with performance."
            ),
        )
        sections.append(
            ArtifactSection(
                heading="Category P&L",
                table=category_table,
                # Horizontal bars: category names are long, and there are enough
                # of them that a column chart would stack its labels vertically
                # and become unreadable at exactly the width a reader has.
                charts=[
                    Chart(
                        key="category_variance",
                        title="Gross profit against budget by category",
                        kind=ChartKind.BAR,
                        table="category",
                        series=["gp_variance"],
                        rows=[c.id for unit in units for c in categories_of[unit.id]],
                        category_axis="Category",
                        value_axis=f"{company.currency} {company.currency_unit}",
                        note="Bars left of zero are categories behind plan.",
                    )
                ],
            )
        )

    # -- Store performance -------------------------------------------------
    store_columns = [
        Column(key="region", label="Region"),
        Column(key="format", label="Format"),
        Column(key="revenue_budget", label="Revenue budget", number_format=MONEY_FORMAT),
        Column(key="revenue_actual", label="Revenue actual", number_format=MONEY_FORMAT),
        Column(key="revenue_variance", label="Revenue variance", number_format=MONEY_FORMAT),
    ]
    store_money = [c for c in store_columns if c.key in _MEASURES]

    store_rows: list[Row] = []
    store_subtotals: list[str] = []
    for unit in units:
        estate = sites_of[unit.id]
        if not estate:
            continue
        for site in estate:
            row = _measure_row(index, key=site.id, label=site.name, subject=site.id,
                               period=period, columns=store_money,
                               extra={"region": Cell(value=site.region),
                                      "format": Cell(value=site.format)})
            store_rows.append(row)
        store_rows.append(
            _measure_row(index, key=unit.id, label=f"{unit.name} total", subject=unit.id,
                         period=period, columns=store_money,
                         children=[s.id for s in estate], emphasis=True,
                         extra={"region": Cell(value=""), "format": Cell(value="")})
        )
        store_subtotals.append(unit.id)

    store_table: Table | None = None
    if store_rows:
        blank = {"region": Cell(value=""), "format": Cell(value="")}
        covers_group = len(store_subtotals) == len(units)
        store_rows.append(
            _measure_row(index, key=company.id, label="Group", subject=company.id, period=period,
                         columns=store_money, children=store_subtotals, emphasis=True, extra=blank)
            if covers_group
            else _sum_row(company.id, "Total, trading stores", columns=store_money,
                          children=store_subtotals, source=store_rows, extra=blank)
        )
        store_table = Table(
            key="stores",
            title="Store Performance",
            columns=store_columns,
            rows=store_rows,
            note=(
                "Stores decompose the same unit revenue the categories do, so both sheets "
                "reach the same unit total by different routes. Distribution centres hold "
                "stock and book no revenue, so they are not listed here."
            ),
        )
        sections.append(ArtifactSection(heading="Store Performance", table=store_table))

    # -- Revenue trend -----------------------------------------------------
    if len(periods) > 1:
        trend_columns = [
            Column(key=p, label=p, number_format=MONEY_FORMAT) for p in periods
        ]

        def trend_row(key: str, label: str, subject: str, *, children: list[str] | None = None,
                      emphasis: bool = False) -> Row:
            cells: dict[str, Cell] = {}
            for month in periods:
                fact = index.get("financial.revenue.actual", subject, month)
                cells[month] = Cell(
                    value=fact.value.amount if fact and fact.value else None,
                    fact_id=fact.id if fact else None,
                    formula=FormulaKind.SUM if children else None,
                    operands=children or [],
                )
            return Row(key=key, label=label, cells=cells, emphasis=emphasis)

        trend_rows: list[Row] = []
        trend_subtotals: list[str] = []
        for unit in units:
            members = categories_of[unit.id]
            for category in members:
                trend_rows.append(trend_row(category.id, f"{unit.name} · {category.name}", category.id))
            if members:
                trend_rows.append(
                    trend_row(unit.id, f"{unit.name} total", unit.id,
                              children=[c.id for c in members], emphasis=True)
                )
                trend_subtotals.append(unit.id)
            else:
                trend_rows.append(trend_row(unit.id, unit.name, unit.id))
                trend_subtotals.append(unit.id)
        trend_rows.append(
            trend_row(company.id, "Group", company.id, children=trend_subtotals, emphasis=True)
        )
        sections.append(
            ArtifactSection(
                heading="Revenue Trend",
                charts=[
                    Chart(
                        key="trend_units",
                        title="Revenue by division, by month",
                        kind=ChartKind.LINE,
                        table="trend",
                        series=list(periods),
                        rows=trend_subtotals,
                        # One line per division across months, not one line per
                        # month across divisions. Drawn the other way round this
                        # is twelve lines of a single point each, and it renders
                        # without complaint.
                        by_row=True,
                        category_axis="Division",
                        value_axis=f"{company.currency} {company.currency_unit}",
                        note="A line chart is only honest where the axis is ordered. It is here.",
                    )
                ],
                table=Table(
                    key="trend",
                    title="Revenue Trend",
                    columns=trend_columns,
                    rows=trend_rows,
                    note=(
                        "Actual revenue by month. Prior periods carry no budget: a trend needs "
                        "actuals, and generating budgets nobody reads would treble the ledger."
                    ),
                ),
            )
        )

    # -- Variance drivers --------------------------------------------------
    drivers: list[Row] = []
    for fact in facts:
        if fact.kind.startswith("metric.") and fact.value is not None:
            subject = (
                world.business_units.get(fact.subject)
                or (world.company if fact.subject == company.id else None)
            )
            drivers.append(
                Row(
                    key=fact.id,
                    label=fact.kind.removeprefix("metric."),
                    cells={
                        "driver": Cell(value=fact.kind.removeprefix("metric.").replace("_", " ")),
                        "scope": Cell(value=getattr(subject, "name", fact.subject)),
                        "value": Cell(value=fact.value.amount, fact_id=fact.id),
                        "unit": Cell(value=fact.value.unit),
                        "source": Cell(value=fact.id),
                    },
                )
            )

    driver_table = Table(
        key="drivers",
        title="Variance Drivers",
        columns=[
            Column(key="driver", label="Driver"),
            Column(key="scope", label="Scope"),
            Column(key="value", label="Value", number_format=RATE_FORMAT),
            Column(key="unit", label="Unit"),
            Column(key="source", label="Fact"),
        ],
        rows=drivers,
    )
    sections.append(ArtifactSection(heading="Variance Drivers", table=driver_table))

    # -- Incident impact ---------------------------------------------------
    impact_rows: list[Row] = []
    for fact in facts:
        if fact.kind in ("financial.incident_pl_impact", "close.delay"):
            impact_rows.append(
                Row(key=fact.id, label=fact.kind, cells={
                    "item": Cell(value=fact.kind.replace(".", " ").replace("_", " ")),
                    "value": Cell(value=fact.value.amount if fact.value else fact.text_value,
                                  fact_id=fact.id),
                    "unit": Cell(value=fact.value.unit if fact.value else ""),
                    "source": Cell(value=fact.id),
                })
            )

    impact = Table(
        key="incident_impact",
        title="Incident Impact",
        columns=[
            Column(key="item", label="Item"),
            Column(key="value", label="Value", number_format=RATE_FORMAT),
            Column(key="unit", label="Unit"),
            Column(key="source", label="Fact"),
        ],
        rows=impact_rows,
        note="A close delay is a calendar impact. It is not a P&L impact unless the P&L impact says so.",
    )
    sections.append(ArtifactSection(heading="Incident Impact", table=impact))

    # -- Hidden: lineage and reconciliation --------------------------------
    lineage = Table(
        key="lineage",
        title="Lineage",
        columns=[
            Column(key="fact", label="Fact"),
            Column(key="kind", label="Kind"),
            Column(key="subject", label="Subject"),
            Column(key="period", label="Period"),
            Column(key="authority", label="Authority"),
            Column(key="source_system", label="Source system"),
            Column(key="valid_from", label="Valid from"),
        ],
        rows=[
            Row(key=fact.id, label=fact.id, cells={
                "fact": Cell(value=fact.id),
                "kind": Cell(value=fact.kind),
                "subject": Cell(value=fact.subject),
                "period": Cell(value=fact.period or ""),
                "authority": Cell(value=fact.authority.value),
                "source_system": Cell(value=fact.source_system or ""),
                "valid_from": Cell(value=fact.valid_from.isoformat()),
            })
            for fact in facts
        ],
        note="Every value on this workbook traces to a fact ID here.",
    )
    sections.append(ArtifactSection(heading="Lineage", table=lineage, hidden=True))

    # Each check must net to zero, and the comparison is against the value the
    # *ledger* states — not against the sheet's own total.
    #
    # Comparing a sum of units to a group cell that is itself `=SUM(units)` is
    # tautological: it can never disagree, so it proves nothing. Comparing against
    # the group fact's literal is what makes this sheet a real check on the corpus,
    # and what would surface a generator that stated a total its parts do not
    # reach.
    #
    # Every roll-up is checked, not just units to group. Categories and stores are
    # two independent decompositions of the same unit revenue, and a corpus where
    # only one of them adds up is a corpus with two answers to one question.
    checks: list[Row] = []

    def check(key: str, label: str, table: str, column: str,
              children: list[str], stated_fact: CanonicalFact | None,
              source_rows: dict[str, Row]) -> None:
        stated = stated_fact.value.amount if stated_fact and stated_fact.value else None
        summed = sum(
            (source_rows[child].cells[column].value or 0.0)
            for child in children
            if child in source_rows
        )
        checks.append(
            Row(
                key=key,
                label=label,
                cells={
                    "summed": Cell(value=summed, formula=FormulaKind.SUM,
                                   operands=[f"{table}:{child}:{column}" for child in children]),
                    "stated": Cell(value=stated, fact_id=stated_fact.id if stated_fact else None),
                    "difference": Cell(
                        value=(summed - stated) if stated is not None else None,
                        formula=FormulaKind.DIFFERENCE,
                        operands=["summed", "stated"],
                    ),
                },
            )
        )

    pnl_rows = {row.key: row for row in pnl.rows}
    check("revenue_units_to_group", "Unit revenue sums to group revenue", "pnl", "revenue_actual",
          unit_keys, index.get("financial.revenue.actual", company.id, period), pnl_rows)
    check("gp_units_to_group", "Unit gross profit sums to group gross profit", "pnl", "gp_actual",
          unit_keys, index.get("financial.gross_profit.actual", company.id, period), pnl_rows)

    if category_table is not None:
        category_lookup = {row.key: row for row in category_table.rows}
        for unit in units:
            members = categories_of[unit.id]
            if not members:
                continue
            check(f"categories_to_{unit.id}", f"{unit.name} categories sum to the unit",
                  "category", "revenue_actual", [c.id for c in members],
                  index.get("financial.revenue.actual", unit.id, period), category_lookup)

    if store_table is not None:
        store_lookup = {row.key: row for row in store_table.rows}
        for unit in units:
            estate = sites_of[unit.id]
            if not estate:
                continue
            check(f"stores_to_{unit.id}", f"{unit.name} stores sum to the unit",
                  "stores", "revenue_actual", [s.id for s in estate],
                  index.get("financial.revenue.actual", unit.id, period), store_lookup)

    reconciliation = Table(
        key="reconciliation",
        title="Reconciliation",
        columns=[
            Column(key="summed", label="Sum of parts", number_format=MONEY_FORMAT),
            Column(key="stated", label="Stated by ledger", number_format=MONEY_FORMAT),
            Column(key="difference", label="Difference", number_format=MONEY_FORMAT),
        ],
        rows=checks,
        note=(
            "Every difference must be zero. The sum is computed by the sheet; the stated "
            "value comes from the fact ledger, so this compares the workbook against the "
            "corpus rather than against itself."
        ),
    )
    sections.append(ArtifactSection(heading="Reconciliation", table=reconciliation, hidden=True))

    return ArtifactIR(
        id=intent.id,
        intent_id=intent.id,
        title=f"{company.name} — Month-End Model",
        subtitle=f"{period} · {company.currency} {company.currency_unit} · final",
        sections=sections,
        metadata={
            "worldloom_synthetic": "true",
            "worldloom_seed": str(world.seed),
            "worldloom_period": period,
            # Derived from the world, never the clock: a document that embeds the
            # moment it was rendered cannot regenerate byte for byte.
            "worldloom_created": max(f.valid_from for f in facts).isoformat(),
            "company": company.name,
            "note": "Synthetic corpus generated by Worldloom. Not a real company.",
        },
    )



# ---------------------------------------------------------------------------
# Narrative artifacts — outline only, until step 6
# ---------------------------------------------------------------------------

#: The outline of each narrative artifact type: heading, the fact kinds that
#: section is *about*, and whose figures it uses.
#:
#: Sections partition the facts rather than all receiving the same set. That is
#: what an outline is for — a section headed "By business unit" that also restates
#: the group position is not an outline, it is a repeated list. Assigning facts per
#: section here means each narrative request is bounded to what its section is
#: actually arguing.
#:
#: ``scope`` is ``group`` (company-level subjects only), ``unit`` (business units
#: only), or ``any``.
@dataclass(frozen=True)
class SectionPlan:
    """One section of a narrative artifact, and what it is for."""

    heading: str
    kinds: tuple[str, ...]
    """Fact-kind prefixes this section is about."""
    scope: str
    """``group`` (company subjects), ``unit`` (business units), or ``any``."""
    purpose: str
    """The section's job, in the words its author would use.

    This is the field that decides whether the prose argues or lists. A writer
    told only "write the Drivers section, here are four metrics" can produce a
    correct paragraph of four sentences and nothing better. A writer told the
    section has to attribute the group margin movement and say whether it is
    structural or one-off has something to actually do.
    """


_OUTLINES: dict[str, tuple[SectionPlan, ...]] = {
    "cfo_variance_memo": (
        SectionPlan(
            "Position", ("financial.revenue.", "financial.gross_profit.", "financial.gross_margin_pct."), "group",
            "State the group result against plan and say plainly whether the period was "
            "acceptable. Lead with the number that matters most, not with the first one in "
            "the list. The CFO already knows the shape of the month; give them the "
            "sentence they will repeat to the board.",
        ),
        SectionPlan(
            "By business unit", ("financial.revenue.", "financial.gross_profit.", "financial.gross_margin_pct."), "unit",
            "Attribute the group position to divisions. Say which unit carried the miss "
            "and which held up, and do not give equal airtime to units that behaved "
            "normally. A division performing to plan warrants a clause, not a paragraph.",
        ),
        SectionPlan(
            "Drivers", ("metric.",), "any",
            "Explain what moved margin and whether it is structural or one-off. This is "
            "the section the CFO reads twice; it must connect a cause to a figure rather "
            "than list metrics. Where a driver sits inside a division rather than across "
            "the group, say so.",
        ),
        SectionPlan(
            "Close timetable", ("close.", "ops.cause", "ops.workaround", "financial.incident_pl_impact"), "any",
            "Report whether the close met its committed date and, if not, what stopped it. "
            "Distinguish a calendar impact from a P&L impact explicitly — conflating them "
            "is the most common error in this kind of memo.",
        ),
        SectionPlan(
            "Recommendation", ("ops.remediation", "ops.root_cause_classification", "ops.mapping_table_owner"), "any",
            "Say what should happen next and who has to decide. Be specific about which "
            "remediation addresses the underlying control and which addresses detection "
            "only; a reader who cannot tell them apart will approve the cheaper one.",
        ),
    ),
    "executive_summary": (
        SectionPlan(
            "In brief", ("financial.revenue.", "financial.gross_margin_pct."), "group",
            "Three sentences at most. An executive committee wants the result, the "
            "direction, and whether anything requires them. Confident register, no hedging, "
            "no methodology.",
        ),
        SectionPlan(
            "Close", ("close.", "financial.incident_pl_impact"), "any",
            "State whether the books closed on time and whether the result was affected. "
            "This paper deliberately does not raise the control failure behind the delay — "
            "write only what the facts given support.",
        ),
        SectionPlan(
            "Focus next period", ("metric.",), "any",
            "Name the one or two measures the committee should watch, and why. Forward-"
            "looking, brief, and free of operational detail.",
        ),
    ),
    "incident_rca": (
        SectionPlan(
            "Summary", ("ops.feed_status", "ops.affected_records"), "any",
            "What failed, how much was affected, and what it stopped. Written for someone "
            "who will read this section and nothing else.",
        ),
        SectionPlan(
            "Timeline", ("ops.incident_opened", "ops.valuation_status", "close."), "any",
            "The sequence, in order, with the moment the close was put at risk made "
            "explicit. Times matter here; narrative flourish does not.",
        ),
        SectionPlan(
            "Initial assessment and why it was wrong", ("ops.cause_ruled_out",), "any",
            "State the hypothesis triage recorded and why it was ruled out. Write it as a "
            "belief held at the time, not as an error — the point is what the evidence "
            "supported then, not blame now.",
        ),
        SectionPlan(
            "Root cause", ("ops.cause", "ops.root_cause_classification", "ops.mapping_table_owner"), "any",
            "The confirmed cause, and the condition that allowed it to persist. An "
            "unassigned owner is itself a finding and should be stated as one.",
        ),
        SectionPlan(
            "Contributing factors", ("ops.previous_similar_incident", "ops.workaround"), "any",
            "What made this more likely or harder to catch. Recurrence is the strongest "
            "signal available; if there is precedent, lead with it.",
        ),
        SectionPlan(
            "Actions", ("ops.remediation",), "any",
            "What is being done, by whom, and which action addresses the control rather "
            "than the symptom. Distinguish the two; a reader must not be able to mistake "
            "improved detection for a fixed control.",
        ),
    ),
    "working_note": (
        SectionPlan(
            "Where the close stands", ("close.",), "any",
            "A controller's own note, written mid-close for their own use. Terse, "
            "provisional, dated in its thinking. Not a report.",
        ),
        SectionPlan(
            "Running note", ("ops.",), "any",
            "Working observations in the order they were made, including what is still "
            "unknown. It is legitimate — and realistic — for this to read as unfinished.",
        ),
    ),
    "confluence_page": (
        SectionPlan(
            "Current position", ("ops.feed_status", "ops.incident_opened"), "any",
            "A triage status page written while the incident is open. It knows the symptom "
            "and the first guess and nothing more. Write with the confidence of the moment, "
            "which later turns out to have been misplaced.",
        ),
        SectionPlan(
            "Next steps", ("ops.cause",), "any",
            "What the team is doing about it right now. Provisional by nature. This page is "
            "never updated, so it must not hedge in a way that would age well.",
        ),
    ),
    "knowledge_article": (
        SectionPlan(
            "When to use this", ("ops.feed_status", "ops.affected_records"), "any",
            "The symptom a future reader will recognise. Written so someone hitting this at "
            "2am can tell in one sentence whether they are in the right article.",
        ),
        SectionPlan(
            "Cause", ("ops.cause", "ops.mapping_table_owner"), "any",
            "Why it happens, briefly, and who to go to. Enough that the procedure below "
            "makes sense; not a root-cause analysis.",
        ),
        SectionPlan(
            "Procedure", ("ops.workaround",), "any",
            "The steps, in order, imperative mood. A reader should be able to follow this "
            "without understanding the cause.",
        ),
    ),
    "unit_close_commentary": (
        SectionPlan(
            "Performance", ("financial.revenue.", "financial.gross_profit.", "financial.gross_margin_pct."), "unit",
            "One unit's month, argued by the person who partners it. Say what the "
            "unit delivered against plan and why, in a finance business partner's "
            "commercial register — this is the paragraph the divisional MD forwards. "
            "Do not restate the group position; the unit is the whole subject.",
        ),
        SectionPlan(
            "Watch items", ("metric.",), "any",
            "What this unit should watch next period, if the metrics given warrant "
            "anything. One or two sentences; skip gracefully if nothing does.",
        ),
    ),
    "close_calendar": (
        SectionPlan(
            "Commitment", ("close.due_date",), "any",
            "State the committed date for the period. This is a standing published "
            "document; write it as policy, not as news.",
        ),
        SectionPlan(
            "Escalation", ("close.revised_date", "close.status", "close.delay"), "any",
            "What happens when the date moves, and where the period ended up. Procedural "
            "register — this is read by people looking up a rule.",
        ),
    ),

    # ------------------------------------------------------------------
    # Conditional filings. Every type below this line is planned only when
    # something about *this* company asks for it — a claim it makes about who
    # it answers to, the size of the estate the incident ran through, or where
    # the period sits in its own trading year. See
    # `generators/planning.py`'s filing block for the gates and their
    # arguments; what belongs here is only what each document is *for*.
    #
    # They are outlines rather than dedicated compilers because none of them
    # needs a table the generic path cannot resolve: each is prose over facts
    # that already exist, partitioned by what its reader is actually there
    # for. The four owner reports below are the clearest case for keeping them
    # four types rather than one parameterised by audience — an audit
    # committee reads for *control*, a sponsor for *plan*, a member for
    # *prudence*, a minister for *the record*, and those are four different
    # partitions of the same month, not four covers on one document.
    # ------------------------------------------------------------------
    "service_impact_assessment": (
        SectionPlan(
            "What failed", ("ops.feed_status", "ops.affected_records"), "any",
            "The failure and its size, for a reader who has to decide what to do about "
            "it in the next hour. No history, no cause — this document exists because "
            "the estate is too large for anyone to hold the answer in their head, so "
            "state what is known and be precise about the scale.",
        ),
        SectionPlan(
            "What it reaches", ("ops.valuation_status",), "any",
            "What downstream is affected and what is not. The whole point of the "
            "assessment: a reader must be able to tell whether their own service is in "
            "scope without asking anybody. Say plainly where the boundary is.",
        ),
        SectionPlan(
            "Holding position", ("ops.workaround", "ops.cause"), "any",
            "What is being run in the meantime and on what basis. Provisional register — "
            "this is written while the incident is open and will be read by people "
            "deciding whether to wait.",
        ),
    ),
    "remediation_scope_review": (
        SectionPlan(
            "What the fix has to cover", ("ops.cause", "ops.affected_records"), "any",
            "The cause, and the extent of what depends on the thing that has to change. "
            "This is the section that justifies the review existing: state the reach "
            "rather than gesturing at it.",
        ),
        SectionPlan(
            "Who owns it", ("ops.mapping_table_owner",), "any",
            "Ownership of the component being changed. An unassigned owner is the "
            "finding, not a gap in the paperwork — write it as the finding, and say what "
            "follows from a change to something nobody owns.",
        ),
        SectionPlan(
            "Scope of the remediation", ("ops.remediation",), "any",
            "What the proposed work does and does not cover. Be explicit about which "
            "action addresses the control and which addresses detection; a reader who "
            "cannot tell them apart will approve the cheaper one.",
        ),
        SectionPlan(
            "Whether it has held before", ("ops.previous_similar_incident",), "any",
            "Precedent, and what it says about whether this scope is enough. If there "
            "is a prior occurrence, lead with it — a fix that did not hold is the "
            "strongest argument available for widening the scope.",
        ),
    ),
    "peak_trading_review": (
        SectionPlan(
            "The month in the year",
            ("financial.revenue.", "financial.gross_profit.", "financial.gross_margin_pct."),
            "group",
            "This is a month the year is planned around, so judge it as such. Against "
            "plan is the wrong frame on its own — the plan already contains the season. "
            "Say whether the peak delivered what a peak has to deliver.",
        ),
        SectionPlan(
            "Where the peak landed",
            ("financial.revenue.", "financial.gross_profit.", "financial.gross_margin_pct."),
            "unit",
            "Which divisions carried the peak and which did not trade through it. A "
            "commercial register, not a finance one; this is read by people who will "
            "buy differently next year because of it.",
        ),
        SectionPlan(
            "What it says about the plan", ("metric.",), "any",
            "What the peak's own measures imply for the rest of the year. Forward-"
            "looking and short; skip gracefully if the measures given say nothing.",
        ),
    ),
    "audit_committee_pack": (
        SectionPlan(
            "Result",
            ("financial.revenue.", "financial.gross_profit.", "financial.gross_margin_pct."),
            "group",
            "The group position, stated once and without commentary. The committee is "
            "not the management meeting; it needs the number to hold the rest of the "
            "pack against, not an argument about it.",
        ),
        SectionPlan(
            "Close control", ("close.",), "any",
            "Whether the close met its committed date and, if not, what moved it. This "
            "is the committee's actual business — the integrity of the reporting "
            "process, not the performance it reports.",
        ),
        SectionPlan(
            "Matters for the committee",
            ("ops.root_cause_classification", "ops.mapping_table_owner"), "any",
            "Control failures and unowned components, stated plainly and without "
            "mitigation. A pack that softens these is the document the committee exists "
            "to not receive.",
        ),
    ),
    "sponsor_pack": (
        SectionPlan(
            "Against the plan",
            ("financial.revenue.", "financial.gross_profit.", "financial.gross_margin_pct."),
            "group",
            "The month against the plan the sponsor holds. Lead with the variance, not "
            "the actual — the fund knows what it underwrote and is reading for the gap.",
        ),
        SectionPlan(
            "By division",
            ("financial.revenue.", "financial.gross_profit.", "financial.gross_margin_pct."),
            "unit",
            "Where the gap sits. Every line gets asked about, so attribute it rather "
            "than summarising it, and do not give equal space to divisions that did what "
            "they said they would.",
        ),
        SectionPlan(
            "Drivers and actions", ("metric.", "close."), "any",
            "What moved the number and what is being done. Cost discipline is the "
            "standing theme and the register is brisk; this is a monthly document read "
            "by someone with a hold period.",
        ),
    ),
    "member_report": (
        SectionPlan(
            "Result",
            ("financial.revenue.", "financial.gross_profit.", "financial.gross_margin_pct."),
            "group",
            "The result, written for the people who own the company and are not "
            "investors. Plain register, no market framing, no growth story — a mutual "
            "reports stewardship, and the reader is being told what was done with their "
            "money.",
        ),
        SectionPlan(
            "What it means for members", ("metric.", "close."), "any",
            "What follows for members from the figures given. Prudence outranks pace "
            "here; where a measure implies caution, say so rather than reframing it.",
        ),
    ),
    "ministerial_brief": (
        SectionPlan(
            "Position",
            ("financial.revenue.", "financial.gross_profit.", "financial.gross_margin_pct."),
            "group",
            "The position, briefly, for a reader who has thirty seconds and may be asked "
            "about it publicly. No jargon and no hedging that would read badly quoted "
            "back.",
        ),
        SectionPlan(
            "On the record", ("close.", "ops."), "any",
            "Everything the period put on the record, including what went wrong. This "
            "company minutes everything because everything is discoverable, so a brief "
            "that omits an operational failure is the omission somebody later finds.",
        ),
    ),
}

_DEFAULT_OUTLINE: tuple[SectionPlan, ...] = (
    SectionPlan("Summary", ("",), "any", "Summarise what the facts below establish."),
)


#: Words that title-casing gets wrong. An artifact type is a snake_case key, and
#: `.title()` turns `cfo_variance_memo` into "Cfo Variance Memo" — which no
#: finance function has ever written on a document, and which is exactly the kind
#: of tell that marks a corpus as generated.
_ACRONYMS = {"Cfo": "CFO", "Ceo": "CEO", "Cio": "CIO", "Rca": "RCA", "Kb": "KB", "It": "IT"}


def _title(artifact_type: str) -> str:
    """A human title for an artifact type."""
    words = artifact_type.replace("_", " ").title().split()
    return " ".join(_ACRONYMS.get(word, word) for word in words)


def _planned_sections(
    world: World, intent: ArtifactIntent, facts: list[CanonicalFact]
) -> list[ArtifactSection]:
    """Sections from an accepted plan, if this artifact has one.

    The hard-coded outline below is the fallback, not the default — but it stays
    the fallback rather than being replaced, because a world that was never
    planned must still compile. That is every existing corpus, the golden
    episode, and every CI step that does not run `plan accept`.

    An accepted plan lives in the generation ledger keyed by call site, which is
    what makes this replay for free: the ledger already travels with the corpus
    and is already the thing a rebuild reads instead of calling a model. Nothing
    new has to be persisted for a planned world to regenerate byte-for-byte.

    Facts are re-bound here against the artifact's own required set rather than
    trusted from the plan. The handshake already rejected any plan citing a fact
    outside that set, so this cannot narrow a legitimate plan — it is the second
    of the two checks, and the one that would catch a ledger edited by hand.
    """
    entry = next(
        (e for e in world.ledger if e.call_site == f"{intent.id}/plan"),
        None,
    )
    if entry is None:
        return []

    allowed = {fact.id for fact in facts}
    sections: list[ArtifactSection] = []
    for beat in entry.output.get("beats", ()):
        assigned = [
            reference["fact_id"]
            for reference in beat.get("evidence", ())
            if reference.get("fact_id") in allowed
        ]
        # Same rule as the outline path: a section with nothing to say does not
        # belong in the document. A plan may legitimately name a beat whose facts
        # this episode did not produce — an incident section in a clean close.
        if not assigned:
            continue
        sections.append(
            ArtifactSection(
                # `key`, not `heading`. `NarrativeBeat` has no heading field —
                # the handshake deliberately stores the author's heading *as*
                # the beat key, since a beat's identity and its title are the
                # same thing once a human has named it. Worth knowing that
                # `compose.plan_from_ir` slugifies its keys instead, so the two
                # plan sources spell keys differently; nothing joins on them
                # today, and anything that starts to must normalise first.
                heading=beat["key"],
                body=None,
                fact_ids=assigned,
                purpose=beat.get("purpose", ""),
                semantic_role=beat.get("semantic_role", ""),
                optional=bool(beat.get("optional", False)),
            )
        )
    return sections


def outline(world: World, intent: ArtifactIntent, minter: Minter) -> ArtifactIR:
    """An outline: sections and a resolved fact table, no prose.

    This is the honest output before a narrative compiler exists. Every heading
    the finished document will have is here, every fact it may cite is bound, and
    ``body`` is ``None`` — so step 6 fills prose into a shape that is already
    correct rather than inventing structure and data together.
    """
    facts = [world.facts.by_id(f) for f in intent.required_fact_ids]
    plan = _OUTLINES.get(intent.artifact_type, _DEFAULT_OUTLINE)
    unit_ids = {unit.id for unit in world.business_units}
    names = world.entity_names()

    def in_scope(fact: CanonicalFact, scope: str) -> bool:
        if scope == "group":
            return fact.subject == world.company.id
        if scope == "unit":
            return fact.subject in unit_ids
        return True

    supporting = Table(
        key="supporting_facts",
        title="Supporting facts",
        columns=[
            Column(key="subject", label="Subject"),
            Column(key="statement", label="Statement"),
            Column(key="authority", label="Authority"),
            Column(key="valid_from", label="Valid from"),
        ],
        rows=[
            # The row label is the fact ID, so a "Fact" column repeating it was a
            # column of duplicates where the subject should have been. An appendix
            # a reader cannot use to tell one revenue line from another is not an
            # appendix.
            Row(key=fact.id, label=fact.id, cells={
                "subject": Cell(value=names.get(fact.subject, fact.subject)),
                "statement": Cell(value=references.describe(fact), fact_id=fact.id),
                "authority": Cell(value=fact.authority.value),
                "valid_from": Cell(value=fact.valid_from.isoformat()),
            })
            for fact in facts
        ],
        note="Resolved before prose. A narrative may reference these and nothing else.",
    )

    author = world.people.by_id(intent.author_id)
    persona = world.personas.get(author.persona_id) if author.persona_id else None

    sections: list[ArtifactSection] = _planned_sections(world, intent, facts)
    for step in plan if not sections else ():
        assigned = [
            fact.id
            for fact in facts
            if in_scope(fact, step.scope)
            and any(fact.kind.startswith(prefix) for prefix in step.kinds)
        ]
        # A section with nothing to say does not belong in the document. The plan
        # follows the episode, so a close without an incident gets no incident
        # sections rather than an empty heading.
        if assigned:
            # The role is resolved here, at outline time, rather than inferred
            # later from the heading. The outline is the only place that knows
            # what a section is *for*; a composer reading "Commitment" downstream
            # can only guess, and guessed wrong often enough to be worth removing
            # from the path.
            from .compiler.compose import infer_semantic_role

            sections.append(
                ArtifactSection(
                    heading=step.heading,
                    body=None,
                    fact_ids=assigned,
                    purpose=step.purpose,
                    semantic_role=infer_semantic_role(step.heading, step.kinds),
                )
            )

    divisional = _divisional_summary(world, facts, intent)
    if divisional is not None:
        sections.append(divisional)

    sections.append(ArtifactSection(heading="Supporting facts", table=supporting, hidden=True))

    return ArtifactIR(
        id=intent.id,
        intent_id=intent.id,
        title=_title(intent.artifact_type),
        subtitle=f"{author.title} · {intent.audience.replace('_', ' ')}",
        sections=sections,
        metadata={
            "worldloom_synthetic": "true",
            "worldloom_seed": str(world.seed),
            # The moment the artifact was written, so a format with document
            # properties stamps that rather than the clock. Derived from the facts
            # it cites, which is the same rule the manifest date follows — the two
            # must agree or a file's own metadata would contradict the corpus.
            "worldloom_created": written_at(intent, {f.id: f for f in facts}).isoformat(),
            "company": world.company.name,
            "author": author.name,
            "author_title": author.title,
            "persona": persona.label if persona else "",
            "voice": persona.voice if persona else "",
            "awaiting_prose": "true",
            "note": "Synthetic corpus generated by Worldloom. Not a real company.",
        },
    )


#: Artifact types that carry a figure as well as prose. A variance memo without a
#: table of divisions is a memo whose reader has to hold four numbers in their
#: head while reading a paragraph about them, which is not how anyone reads one.
_TABULAR_NARRATIVE = frozenset({"cfo_variance_memo"})


def _divisional_summary(
    world: World, facts: list[CanonicalFact], intent: ArtifactIntent
) -> ArtifactSection | None:
    """The table a variance memo actually has, and a figure over it.

    Built from the facts the memo already cites rather than from the world, so it
    cannot show a division the memo was not given — the table and the prose rest
    on exactly the same set.
    """
    if intent.artifact_type not in _TABULAR_NARRATIVE:
        return None

    period = next((f.period for f in facts if f.period), world.period or "")
    index = _Facts(facts)
    units = [
        unit for unit in world.business_units
        if index.get("financial.revenue.actual", unit.id, period) is not None
    ]
    if len(units) < 2:
        return None

    columns = [
        Column(key="revenue_budget", label="Revenue budget", number_format=MONEY_FORMAT),
        Column(key="revenue_actual", label="Revenue actual", number_format=MONEY_FORMAT),
        Column(key="revenue_variance", label="Variance", number_format=MONEY_FORMAT),
        Column(key="gm_pct_actual", label="GM% actual", number_format=PERCENT_FORMAT),
    ]
    rows = [
        _measure_row(index, key=unit.id, label=unit.name, subject=unit.id,
                     period=period, columns=columns)
        for unit in units
    ]

    return ArtifactSection(
        heading="Divisional summary",
        table=Table(
            key="divisions",
            title=f"By division · {period}",
            columns=columns,
            rows=rows,
            note="The same figures the prose cites, and the workbook computes.",
        ),
        charts=[
            Chart(
                key="division_variance",
                title="Revenue against plan by division",
                kind=ChartKind.BAR,
                table="divisions",
                series=["revenue_variance"],
                rows=[unit.id for unit in units],
                category_axis="Division",
                value_axis=f"{world.company.currency} {world.company.currency_unit}",
            )
        ],
        fact_ids=[
            fact.id for fact in facts
            if fact.subject in {unit.id for unit in units}
        ],
    )


#: Artifact types whose IR is built by a dedicated function rather than the
#: generic outline. The workbook was the only entry until banking registered
#: its capital return; the dict exists so a domain module's source artifact
#: does not need a branch here naming it. Minutes and threads are core entries
#: because they are mechanism any vertical plans — a projection of an event
#: and its facts, with no domain vocabulary of their own.
from .generators.communications import MESSAGE_LAG, MINUTES_LAG, minutes_ir, thread_ir

_COMPILERS: dict[str, Any] = {
    "finance_workbook": finance_workbook,
    "meeting_minutes": minutes_ir,
    "email_thread": thread_ir,
}
_STANDING.update({
    # Circulated minutes are the approved record of the meeting; a thread is a
    # record too, but an informal one — the authority gap between them is what
    # a who-was-told-when evaluation resolves against.
    "meeting_minutes": (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED),
    "email_thread": (Authority.UNOFFICIAL_NOTE, Lifecycle.PUBLISHED),
    "unit_close_commentary": (Authority.WORKING_DOCUMENT, Lifecycle.PUBLISHED),

    # The conditional filings. Their outlines are above; these are the two
    # claims an outline cannot make — how much weight the document carries,
    # and how long after the facts it is written.
    #
    # Every lag below is at or under the executive summary's day-and-fifteen-
    # hours, and that ceiling is load-bearing rather than tidy:
    # `scenarios._period_boundary` places a departure eight business days after
    # period end, and it chose eight by brute force against the *slowest
    # artifact any episode plans*. A filing written later than that would put
    # its author's own departure before their signature and trip
    # `author_already_departed` in any world with a timeline — silently, and
    # only in some months.
    "service_impact_assessment": (Authority.WORKING_DOCUMENT, Lifecycle.PUBLISHED),
    "remediation_scope_review": (Authority.APPROVED_REPORT, Lifecycle.REVIEWED),
    "peak_trading_review": (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED),
    # Reviewed rather than merely published, and it is the one filing where
    # that is the whole point: a pack the committee has not read is not an
    # audit committee pack, it is a draft addressed to one.
    "audit_committee_pack": (Authority.APPROVED_REPORT, Lifecycle.REVIEWED),
    "sponsor_pack": (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED),
    "member_report": (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED),
    "ministerial_brief": (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED),
})
_LAG.update({
    # The same constants the communications compilers stamp into their IR
    # metadata — see the coupling note beside them.
    "meeting_minutes": MINUTES_LAG,
    "email_thread": MESSAGE_LAG,
    "unit_close_commentary": timedelta(hours=20),
    # Written while the incident is still open — it is an input to the
    # decision, not a record of one.
    "service_impact_assessment": timedelta(minutes=90),
    "remediation_scope_review": timedelta(hours=6),
    "peak_trading_review": timedelta(days=1),
    "sponsor_pack": timedelta(days=1, hours=4),
    "ministerial_brief": timedelta(days=1, hours=8),
    "audit_committee_pack": timedelta(days=1, hours=10),
    "member_report": timedelta(days=1, hours=12),
})


def compile_intent(world: World, intent: ArtifactIntent, minter: Minter) -> ArtifactIR:
    """Compile one intent into an IR."""
    builder = _COMPILERS.get(intent.artifact_type)
    if builder is not None:
        return builder(world, intent, minter)
    return outline(world, intent, minter)
