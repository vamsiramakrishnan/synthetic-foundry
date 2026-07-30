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

from datetime import timedelta
from typing import TYPE_CHECKING

from .ids import Minter
from .models import (
    ArtifactIntent,
    ArtifactIR,
    ArtifactSection,
    Authority,
    CanonicalFact,
    Cell,
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


def _lookup(facts: list[CanonicalFact], kind: str, subject: str) -> CanonicalFact | None:
    for fact in facts:
        if fact.kind == kind and fact.subject == subject and not fact.is_superseded:
            return fact
    return None


# ---------------------------------------------------------------------------
# The finance workbook
# ---------------------------------------------------------------------------


def finance_workbook(world: World, intent: ArtifactIntent, minter: Minter) -> ArtifactIR:
    """The month-end model.

    A source artifact, not a projection of one. Every total is declared as a sum
    of the rows above it, every variance as a difference, every margin as a ratio
    — so a reader who recalculates the sheet gets the same answer, and a renderer
    that supports formulas can emit them rather than paste values.
    """
    facts = [world.facts.by_id(f) for f in intent.required_fact_ids]
    period = next((f.period for f in facts if f.period), world.period or "")
    units = list(world.business_units)
    company = world.company

    unit_keys = [unit.id for unit in units]

    # -- Business Unit P&L -------------------------------------------------
    columns = [
        Column(key="revenue_budget", label="Revenue budget", number_format=MONEY_FORMAT),
        Column(key="revenue_actual", label="Revenue actual", number_format=MONEY_FORMAT),
        Column(key="revenue_variance", label="Revenue variance", number_format=MONEY_FORMAT),
        Column(key="gp_budget", label="GP budget", number_format=MONEY_FORMAT),
        Column(key="gp_actual", label="GP actual", number_format=MONEY_FORMAT),
        Column(key="gp_variance", label="GP variance", number_format=MONEY_FORMAT),
        Column(key="gm_pct_actual", label="GM% actual", number_format=PERCENT_FORMAT),
    ]

    def measure(subject: str, kind: str) -> CanonicalFact | None:
        return _lookup(facts, kind, subject)

    rows: list[Row] = []
    for unit in units:
        revenue_budget = measure(unit.id, "financial.revenue.budget")
        revenue_actual = measure(unit.id, "financial.revenue.actual")
        gp_budget = measure(unit.id, "financial.gross_profit.budget")
        gp_actual = measure(unit.id, "financial.gross_profit.actual")
        gm_actual = measure(unit.id, "financial.gross_margin_pct.actual")
        variance = measure(unit.id, "financial.revenue.variance")
        gp_var = measure(unit.id, "financial.gross_profit.variance")
        rows.append(
            Row(
                key=unit.id,
                label=unit.name,
                cells={
                    "revenue_budget": _money(revenue_budget.value.amount if revenue_budget else None,
                                             revenue_budget.id if revenue_budget else None),
                    "revenue_actual": _money(revenue_actual.value.amount if revenue_actual else None,
                                             revenue_actual.id if revenue_actual else None),
                    # Declared as a difference, not pasted: the sheet recomputes it.
                    "revenue_variance": Cell(
                        value=variance.value.amount if variance else None,
                        fact_id=variance.id if variance else None,
                        formula=FormulaKind.DIFFERENCE,
                        operands=["revenue_actual", "revenue_budget"],
                    ),
                    "gp_budget": _money(gp_budget.value.amount if gp_budget else None,
                                        gp_budget.id if gp_budget else None),
                    "gp_actual": _money(gp_actual.value.amount if gp_actual else None,
                                        gp_actual.id if gp_actual else None),
                    "gp_variance": Cell(
                        value=gp_var.value.amount if gp_var else None,
                        fact_id=gp_var.id if gp_var else None,
                        formula=FormulaKind.DIFFERENCE,
                        operands=["gp_actual", "gp_budget"],
                    ),
                    "gm_pct_actual": Cell(
                        value=gm_actual.value.amount if gm_actual else None,
                        fact_id=gm_actual.id if gm_actual else None,
                        formula=FormulaKind.RATIO_PCT,
                        operands=["gp_actual", "revenue_actual"],
                    ),
                },
            )
        )

    group_cells: dict[str, Cell] = {}
    for column in columns:
        group_fact = {
            "revenue_budget": measure(company.id, "financial.revenue.budget"),
            "revenue_actual": measure(company.id, "financial.revenue.actual"),
            "revenue_variance": measure(company.id, "financial.revenue.variance"),
            "gp_budget": measure(company.id, "financial.gross_profit.budget"),
            "gp_actual": measure(company.id, "financial.gross_profit.actual"),
            "gp_variance": measure(company.id, "financial.gross_profit.variance"),
            "gm_pct_actual": measure(company.id, "financial.gross_margin_pct.actual"),
        }[column.key]
        if column.key == "gm_pct_actual":
            # Group margin is a ratio of group totals, not an average of unit margins.
            group_cells[column.key] = Cell(
                value=group_fact.value.amount if group_fact else None,
                fact_id=group_fact.id if group_fact else None,
                formula=FormulaKind.RATIO_PCT,
                operands=["gp_actual", "revenue_actual"],
            )
        else:
            group_cells[column.key] = Cell(
                value=group_fact.value.amount if group_fact else None,
                fact_id=group_fact.id if group_fact else None,
                formula=FormulaKind.SUM,
                operands=unit_keys,
            )

    rows.append(Row(key=company.id, label="Group", cells=group_cells, emphasis=True))

    pnl = Table(
        key="pnl",
        title="Business Unit P&L",
        columns=columns,
        rows=rows,
        note="Group is the sum of the business units above. Variances recompute from actual less budget.",
    )

    # -- Summary -----------------------------------------------------------
    summary = Table(
        key="summary",
        title="Summary",
        columns=[Column(key="value", label="Value", number_format=MONEY_FORMAT)],
        rows=[
            Row(key="revenue_actual", label="Revenue actual", cells={
                "value": Cell(value=group_cells["revenue_actual"].value,
                              fact_id=group_cells["revenue_actual"].fact_id,
                              formula=FormulaKind.REFERENCE,
                              operands=[f"pnl:{company.id}:revenue_actual"])}),
            Row(key="revenue_budget", label="Revenue budget", cells={
                "value": Cell(value=group_cells["revenue_budget"].value,
                              fact_id=group_cells["revenue_budget"].fact_id,
                              formula=FormulaKind.REFERENCE,
                              operands=[f"pnl:{company.id}:revenue_budget"])}),
            Row(key="revenue_variance", label="Revenue variance", emphasis=True, cells={
                "value": Cell(value=group_cells["revenue_variance"].value,
                              fact_id=group_cells["revenue_variance"].fact_id,
                              formula=FormulaKind.REFERENCE,
                              operands=[f"pnl:{company.id}:revenue_variance"])}),
            Row(key="gp_actual", label="Gross profit actual", cells={
                "value": Cell(value=group_cells["gp_actual"].value,
                              fact_id=group_cells["gp_actual"].fact_id,
                              formula=FormulaKind.REFERENCE,
                              operands=[f"pnl:{company.id}:gp_actual"])}),
            Row(key="gp_variance", label="Gross profit variance", emphasis=True, cells={
                "value": Cell(value=group_cells["gp_variance"].value,
                              fact_id=group_cells["gp_variance"].fact_id,
                              formula=FormulaKind.REFERENCE,
                              operands=[f"pnl:{company.id}:gp_variance"])}),
        ],
        note=f"{company.name} · {period} · {company.currency} {company.currency_unit}",
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

    # -- Hidden: lineage and reconciliation --------------------------------
    lineage = Table(
        key="lineage",
        title="Lineage",
        columns=[
            Column(key="fact", label="Fact"),
            Column(key="kind", label="Kind"),
            Column(key="subject", label="Subject"),
            Column(key="authority", label="Authority"),
            Column(key="source_system", label="Source system"),
            Column(key="valid_from", label="Valid from"),
        ],
        rows=[
            Row(key=fact.id, label=fact.id, cells={
                "fact": Cell(value=fact.id),
                "kind": Cell(value=fact.kind),
                "subject": Cell(value=fact.subject),
                "authority": Cell(value=fact.authority.value),
                "source_system": Cell(value=fact.source_system or ""),
                "valid_from": Cell(value=fact.valid_from.isoformat()),
            })
            for fact in facts
        ],
        note="Every value on this workbook traces to a fact ID here.",
    )

    # Each check must net to zero, and the comparison is against the value the
    # *ledger* states — not against the sheet's own total.
    #
    # Comparing a sum of units to a group cell that is itself `=SUM(units)` is
    # tautological: it can never disagree, so it proves nothing. Comparing against
    # the group fact's literal is what makes this sheet a real check on the corpus,
    # and what would surface a generator that stated a total its parts do not
    # reach.
    checks: list[Row] = []
    for key, label, column_key, fact in (
        ("revenue_units_to_group", "Unit revenue sums to group revenue",
         "revenue_actual", measure(company.id, "financial.revenue.actual")),
        ("gp_units_to_group", "Unit gross profit sums to group gross profit",
         "gp_actual", measure(company.id, "financial.gross_profit.actual")),
    ):
        stated = fact.value.amount if fact and fact.value else None
        summed = sum(
            row.cells[column_key].value or 0.0
            for row in rows
            if not row.emphasis and column_key in row.cells
        )
        checks.append(
            Row(
                key=key,
                label=label,
                cells={
                    "summed": Cell(value=summed, formula=FormulaKind.SUM, operands=unit_keys),
                    "stated": Cell(value=stated, fact_id=fact.id if fact else None),
                    "difference": Cell(
                        value=(summed - stated) if stated is not None else None,
                        formula=FormulaKind.DIFFERENCE,
                        operands=["summed", "stated"],
                    ),
                },
            )
        )

    reconciliation = Table(
        key="reconciliation",
        title="Reconciliation",
        columns=[
            Column(key="summed", label="Sum of units", number_format=MONEY_FORMAT),
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

    return ArtifactIR(
        id=intent.id,
        intent_id=intent.id,
        title=f"{company.name} — Month-End Model",
        subtitle=f"{period} · {company.currency} {company.currency_unit} · final",
        sections=[
            ArtifactSection(heading="Summary", table=summary),
            ArtifactSection(heading="Business Unit P&L", table=pnl),
            ArtifactSection(heading="Variance Drivers", table=driver_table),
            ArtifactSection(heading="Incident Impact", table=impact),
            ArtifactSection(heading="Lineage", table=lineage, hidden=True),
            ArtifactSection(heading="Reconciliation", table=reconciliation, hidden=True),
        ],
        metadata={
            "worldloom_synthetic": "true",
            "worldloom_seed": str(world.seed),
            "worldloom_period": period,
            "company": company.name,
            "note": "Synthetic corpus generated by Worldloom. Not a real company.",
        },
    )


# ---------------------------------------------------------------------------
# Narrative artifacts — outline only, until step 6
# ---------------------------------------------------------------------------

#: Section headings per narrative artifact type. Ordering is the document's
#: argument, so it is decided here rather than left to a prompt.
_OUTLINES: dict[str, tuple[str, ...]] = {
    "cfo_variance_memo": ("Position", "By business unit", "Close timetable", "Recommendation"),
    "executive_summary": ("In brief", "Close", "Focus next period"),
    "incident_rca": ("Summary", "Timeline", "Initial assessment and why it was wrong",
                     "Root cause", "Contributing factors", "Actions"),
    "working_note": ("Checklist", "Running note", "Points to carry"),
    "confluence_page": ("Current position", "Next steps"),
    "knowledge_article": ("When to use this", "Cause", "Procedure", "Important"),
    "close_calendar": ("Commitment", "This period", "Escalation"),
}


def outline(world: World, intent: ArtifactIntent, minter: Minter) -> ArtifactIR:
    """An outline: sections and a resolved fact table, no prose.

    This is the honest output before a narrative compiler exists. Every heading
    the finished document will have is here, every fact it may cite is bound, and
    ``body`` is ``None`` — so step 6 fills prose into a shape that is already
    correct rather than inventing structure and data together.
    """
    facts = [world.facts.by_id(f) for f in intent.required_fact_ids]
    headings = _OUTLINES.get(intent.artifact_type, ("Summary", "Detail"))

    supporting = Table(
        key="supporting_facts",
        title="Supporting facts",
        columns=[
            Column(key="fact", label="Fact"),
            Column(key="statement", label="Statement"),
            Column(key="authority", label="Authority"),
            Column(key="valid_from", label="Valid from"),
        ],
        rows=[
            Row(key=fact.id, label=fact.id, cells={
                "fact": Cell(value=fact.id),
                "statement": Cell(
                    value=fact.text_value
                    if fact.text_value
                    else f"{fact.kind} = {fact.value.amount:,g} {fact.value.unit}"
                    if fact.value
                    else fact.kind,
                    fact_id=fact.id,
                ),
                "authority": Cell(value=fact.authority.value),
                "valid_from": Cell(value=fact.valid_from.isoformat()),
            })
            for fact in facts
        ],
        note="Resolved before prose. A narrative may reference these and nothing else.",
    )

    author = world.people.by_id(intent.author_id)
    persona = world.personas.get(author.persona_id) if author.persona_id else None

    sections = [
        ArtifactSection(heading=heading, body=None, fact_ids=[f.id for f in facts])
        for heading in headings
    ]
    sections.append(ArtifactSection(heading="Supporting facts", table=supporting, hidden=True))

    return ArtifactIR(
        id=intent.id,
        intent_id=intent.id,
        title=intent.artifact_type.replace("_", " ").title(),
        subtitle=f"{author.title} · {intent.audience.replace('_', ' ')}",
        sections=sections,
        metadata={
            "worldloom_synthetic": "true",
            "worldloom_seed": str(world.seed),
            "author": author.name,
            "author_title": author.title,
            "persona": persona.label if persona else "",
            "voice": persona.voice if persona else "",
            "awaiting_prose": "true",
            "note": "Synthetic corpus generated by Worldloom. Not a real company.",
        },
    )


def compile_intent(world: World, intent: ArtifactIntent, minter: Minter) -> ArtifactIR:
    """Compile one intent into an IR."""
    if intent.artifact_type == "finance_workbook":
        return finance_workbook(world, intent, minter)
    return outline(world, intent, minter)
