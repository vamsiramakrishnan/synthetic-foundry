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

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from . import columns as columns_module
from . import recipe as recipe_module
from . import structure
from .ids import Minter
from .narrative import references
from .models import (
    FlowNode,
    FlowEdge,
    FlowDiagram,
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
    # A history page is written once the dust of its newest entry has settled,
    # not within the hour of it — and `written_at` derives the page's date from
    # that newest milestone, so this lag is the only thing standing between
    # "the replatform happened" and "somebody wrote it up".
    "company_timeline": timedelta(days=5),
    # Extracts are cut the morning the close calendar goes out — same anchor
    # fact, an hour behind it, so the archive shows the calendar first.
    "service_register": timedelta(hours=2),
    "reference_data_extract": timedelta(hours=2),
}


@dataclass(frozen=True)
class FilingPlan:
    """How a *declaratively* authored artifact type gets planned into an episode.

    The fourth table, and the one the three above did not need. ``_STANDING``,
    ``_LAG`` and ``_OUTLINES`` describe a document that something already
    decided to write; nothing describes the deciding. For the engine's own
    types that decision is code — ``generators/planning.py`` names each type in
    a call that also chooses its author, its reader and its facts — and code is
    the right shape for it, because those choices are arguments about the
    episode rather than about the document.

    An authored type has no such code and cannot get any: the whole premise is
    that a model adds a document type without editing Python. So the *same four
    choices* are stated here as data, and ``planning``'s filing block reads this
    table for the types it does not name itself. The gate is unchanged — lore at
    ``facets.FILING_PREFIX + key`` still decides *whether* the company files it
    — so this says only what the document is when it is filed, never that it is.

    ``facts`` is a closed vocabulary of *bundles the planner already computes*,
    not fact ids and not fact kinds. That boundary is the same one lore draws:
    an author picks from what the episode produced, and cannot reach past the
    planner into the ledger. It also means a bundle that this episode left empty
    simply contributes nothing, rather than naming a fact that does not exist.
    """

    author_role: str
    """The engine role key that signs it. Resolved through the world's own role
    table at plan time, so a role this build did not mint falls through to
    ``fallback_role`` rather than raising."""

    fallback_role: str = ""
    """Who signs it when ``author_role`` was not minted. The
    ``ministerial_brief``'s ``roles.get("public_accountability") or
    roles["ceo"]`` is the precedent: a filing whose author role exists only
    when some facet was claimed must still be filed, by somebody, in a build
    where it was not."""

    domain: str = "finance"
    audience: str = "all_staff"
    """The document's access class, *not* its literal reader. ``world.
    _policy_for`` maps this onto an access policy and falls back to the most
    restrictive one, so an audience nobody minted a policy for locks the
    author out of their own document and trips
    ``author_cannot_see_own_artifact``. The filing block in ``planning`` states
    this at length; the lint restates it, because an authored type is exactly
    where somebody will write ``audience: "franchisees"``."""

    size: str = "medium"
    rationale: str = ""
    facts: tuple[str, ...] = ()
    """Which of the planner's fact bundles this document is given. See
    ``generators/planning.FILING_BUNDLES`` for the closed set and what each
    one is."""


#: Artifact type names a scenario mints and no module declares. See
#: ``reserve_artifact_types``, which is the only way in.
_RESERVED: set[str] = set()

#: Filing plans for declaratively authored types. Written by
#: ``doctypes.install``; read by ``generators.planning``. Empty in every build
#: that loads no authored type, which is every build this repository ships.
_FILINGS: dict[str, FilingPlan] = {}


def standing(artifact_type: str) -> tuple[Authority, Lifecycle]:
    """The authority and lifecycle an artifact of this type carries."""
    return _STANDING.get(artifact_type, (Authority.WORKING_DOCUMENT, Lifecycle.DRAFT))


def reserve_artifact_types(*names: str) -> None:
    """Claim *names* as artifact types a scenario mints without declaring.

    The sixth registration seam, and the narrowest. ``declared_types``' docstring
    already names the case it exists for: ``scenarios._personnel_notice`` mints
    ``personnel_notice`` intents and nothing declares that type, so a succession
    announcement is silently an unreviewed draft. Declaring it in core is the
    wrong fix — ``tests/test_thin_waist.py`` counts the name as retail
    vocabulary and this is a core module — and the right one is a registration
    from whichever module owns the scenario, which is a change of its own.

    What made the gap worth naming *now* is that artifact types became
    authorable. The compiler's tables are process-global, so a pack claiming one
    of these names would set the standing of a document in some *other* world
    built by the same process — and ``register_artifact_types`` cannot refuse it,
    because nothing registered the name for it to disagree with. Reserving it
    says "this name is spoken for" without making a modelling claim about the
    authority, which is precisely the claim nobody is in a position to make yet.

    Called at package import, the same contract every seam here follows.
    """
    _RESERVED.update(names)


def reserved_types() -> frozenset[str]:
    """Every reserved artifact type name.

    Kept honest by ``tests/test_doctypes.py``, which scans the modules the
    package imports for every artifact type name a planner mints and requires
    each one to be either declared or reserved. A name that becomes declared
    stops needing a reservation; a name that appears in a new scenario and gets
    neither is a test failure rather than a silent draft.
    """
    return frozenset(_RESERVED)


def filing_plan(artifact_type: str) -> FilingPlan | None:
    """How to plan a filing of *artifact_type*, or ``None`` for the engine's own.

    ``None`` is the answer for all thirty types this repository declares, and
    that is what keeps the generic filing block in ``generators/planning`` a
    no-op on every build that loads no authored type: the block iterates the
    lore's filing asks and skips every one whose type plans itself in code.
    """
    return _FILINGS.get(artifact_type)


def narrated_kinds() -> frozenset[str]:
    """Every fact-kind prefix some declared artifact type is written about.

    The lint's evidence for "this outline cites a kind no generator produces",
    and it is deliberately the *narrated* set rather than a hand-kept registry
    of what the generators emit. There is no such registry — fact kinds are
    string literals spread across four generator modules — and a hand-kept copy
    of them would go stale in the one direction that matters, reporting a real
    kind as invented on the day somebody adds a generator.

    Derived from ``_OUTLINES`` instead, so it moves when the engine moves. The
    claim it supports is therefore narrower than "no generator produces this"
    and has to be read as what it is: *no document this engine ships is about
    this*. That is a necessary condition rather than a sufficient one, and it
    is enough to catch the two failures worth catching — a typo
    (``financail.revenue.``) and an invented vocabulary (``esg.scope_three.``),
    both of which resolve to zero facts and compile into an empty document.

    The empty prefix is dropped. ``routine_notice`` cites ``("",)`` — "every
    fact I was given" — which is a legitimate outline and a useless membership
    test, since every kind starts with it.
    """
    return frozenset(
        kind
        for plans in _OUTLINES.values()
        for plan in plans
        for kind in plan.kinds
        if kind
    )


def scoped_kinds() -> frozenset[str]:
    """The fact-kind prefixes declared outlines use with a ``group``/``unit`` scope.

    Every one of them is a ``financial.`` prefix today, and that is not an
    accident of taste: ``outline``'s ``in_scope`` filters on the *subject* of a
    fact, and only the financial generators state one figure per company and
    another per business unit. An ``ops.`` or ``close.`` fact is about the
    episode, so a section that asks for ``close.`` facts scoped to ``unit``
    resolves to nothing and disappears — silently, because a section with no
    facts is deliberately dropped rather than left empty.

    Published so the lint can say that from the registry rather than from a
    literal list of financial prefixes that would be wrong the moment a vertical
    generated a unit-scoped operational measure.
    """
    return frozenset(
        kind
        for plans in _OUTLINES.values()
        for plan in plans
        if plan.scope != "any"
        for kind in plan.kinds
        if kind
    )


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
    filings: dict[str, FilingPlan] | None = None,
    variants: dict[str, tuple[tuple["SectionPlan", ...], ...]] | None = None,
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

    ``filings`` is the same seam for a type whose *planning* is data rather than
    code — see ``FilingPlan``. It rides this function rather than a second one
    so there stays exactly one door into these tables, and so the conflict rule
    below covers it too: two sources disagreeing about who signs a document is
    the same class of import-order bug as two disagreeing about its authority.
    """
    for table, additions in (
        (_STANDING, standing),
        (_LAG, lags),
        (_OUTLINES, outlines),
        (_COMPILERS, compilers),
        (_FILINGS, filings),
        (_OUTLINE_VARIANTS, variants),
    ):
        for key, value in (additions or {}).items():
            if key in table and table[key] != value:
                raise ValueError(f"artifact type {key!r} is already registered differently")
            table[key] = value  # type: ignore[assignment]


#: Marker attribute a compiler sets on itself to say it *composes* the outline
#: rather than replacing it.
#:
#: The distinction is real and `tests/test_doctypes.py` holds the line on it. A
#: compiler like `finance_workbook` builds its IR from nothing, so an outline
#: registered beside it would be dead data nobody reads and an author would be
#: editing a section list with no effect. A compiler like
#: `policies._provisions` calls `outline` and inserts one block into what comes
#: back, so its outline is live data and is the only place a policy's sections
#: are stated. Marked rather than inferred, because the two are the same
#: callable shape and nothing about a function signature can tell them apart.
EXTENDS_OUTLINE = "worldloom_extends_outline"


def extends_outline(compiler: Any) -> bool:
    """Whether *compiler* reads the registered outline rather than replacing it."""
    return bool(getattr(compiler, EXTENDS_OUTLINE, False))


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


#: How a column's declared unit is spelled to a spreadsheet. The `columns`
#: module says whether a figure is an amount or a rate — which is what decides
#: whether it adds up — and this module says how that is written, because a
#: number format is a rendering decision and the sheet spec is not a renderer.
_UNIT_FORMAT: dict[str, str] = {"money": MONEY_FORMAT, "percent": PERCENT_FORMAT}


def _columns(sheet: columns_module.Sheet) -> list[Column]:
    """A declared sheet as the IR's column list."""
    return [
        Column(key=column.key, label=column.label,
               number_format=_UNIT_FORMAT[column.unit])
        for column in sheet.columns
    ]


# The four tables below were four hand-written constants that had to agree with
# each other and with three `Column` lists — seven places, and the repo has
# already paid twice for them disagreeing (`columns.py`'s docstring records both
# defects with their counts). They are now projections of one declaration,
# computed at import.
#
# They stay module globals, and are not replaced by calls into `columns`, for
# two reasons. `_measure_row` reads them once per column per row over thousands
# of rows, so a dict is the right lookup structure and building it once is what
# "declared spec, compiled table" means. And `tests/test_carried_evidence.py`
# reproduces the `gm_pct_budget` defect by *mutating* `_MEASURES` and `_DERIVED`
# in place — the one test that proves a column reading no fact kind is caught —
# so these names are load-bearing, not vestigial. `Sheet`'s projections return
# fresh containers on every call precisely so that mutation cannot reach the
# spec.

#: ``column key -> the fact kind it reads``.
_MEASURES: dict[str, str] = columns_module.PNL.kinds()

#: Columns computed from the two beside them, and from which. Declared once so
#: a category row, a unit subtotal, and the group row all recompute the same
#: way — a subtotal that pasted its variance while the rows above computed
#: theirs is exactly the disagreement this project exists to prevent.
_DERIVED: dict[str, tuple[FormulaKind, list[str]]] = columns_module.PNL.derivations()

#: Columns a subtotal must *not* sum, because they do not add up. A margin
#: percentage is a ratio of totals, never the total of ratios; a variance, by
#: contrast, is additive, so a subtotal sums its children's variances and shows
#: which of them the group's miss came from.
_NOT_ADDITIVE = columns_module.PNL.not_summable()

#: The same rule stated over fact *kinds* rather than column keys, for the trend
#: sheets — which are laid out by period rather than by measure, so they cannot
#: look a column up in `_NOT_ADDITIVE`.
_RATE_KINDS = columns_module.PNL.rate_kinds()


def _pnl_columns() -> list[Column]:
    return _columns(columns_module.PNL)


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
    # The workbook's *own* facts decide which month it reports, and the world's
    # current period is only the fallback for a document whose facts carry none.
    #
    # It read the other way round, and the defect that hid behind it is the
    # worst this repository has had. `compile()` compiles every intent against
    # the world as it stands *now*, so in a two-period corpus March's workbook
    # was looked up at April: every `index.get(kind, subject, period)` missed,
    # and the month-end model — the corpus's system of record, the document
    # every other one reconciles against — rendered with **every cell empty**.
    # Measured: a one-period build's Business Unit P&L carries 28 of 28 values;
    # a two-period build's carries 0 of 28, and `validate` passed both, because
    # a reconciliation check compares a cell against a fact and two absent
    # numbers agree.
    #
    # Single-period builds are byte-identical either way — `world.period` and
    # `periods[-1]` are the same string — which is why this survived: every
    # fixture, every example and every default build has exactly one period.
    periods = sorted({f.period for f in facts if f.period})
    period = (periods[-1] if periods else "") or world.period or ""
    company = world.company

    # A business unit the finance generator booked no month for does not get a
    # P&L row. This is the same rule `sites_of` applies below, for the same
    # reason, and it was missing here: `world.business_units` unfiltered meant a
    # unit added by a `StructuralChange` after the close it was measured for
    # rendered as a row of empty cells, and a `Group` row that named it as
    # a child of a sum it contributed nothing to. Measured on a retail build
    # with one added unit: 3 of 15 P&L rows fully blank, `validate` clean across
    # 21,601 checks — because a reconciliation check compares a cell to a fact
    # and two absent numbers agree. That is the finance-workbook defect
    # recurring one function later.
    #
    # The predicate is "any measured column resolves", not "revenue resolves":
    # a unit carried on gross profit alone is still a unit that closed.
    def measured(unit_id: str) -> bool:
        return any(index.get(kind, unit_id, period) is not None for kind in _MEASURES.values())

    units = [unit for unit in world.business_units if measured(unit.id)]
    # A workbook whose every unit fails the test is a workbook with no month in
    # it at all. Falling back to the full list keeps that case rendering exactly
    # as it did before rather than emitting a sheet with only a `Group` row on
    # it, which would be a second way to be silently empty.
    if not units:
        units = list(world.business_units)

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
                    # The title said "against budget" while the chart plotted one
                    # series. It could not plot two: the budget-margin column did
                    # not exist, though the fact behind it did.
                    series=["gm_pct_budget", "gm_pct_actual"],
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
    # Region and format describe the *site*, not its month, so they are built
    # here rather than declared on the sheet: they read no fact, carry no
    # `fact_id`, and a subtotal leaves them blank. `columns.STORES` is the money
    # half — the P&L's first three columns narrowed, not a second declaration of
    # them.
    store_columns = [
        Column(key="region", label="Region"),
        Column(key="format", label="Format"),
        *_columns(columns_module.STORES),
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

    # -- Trend, by measure -------------------------------------------------
    # Three sheets, not one, and the second and third are not decoration. The
    # planner hands this workbook actuals for every comparative month across
    # *all three* measures; the trend sheet read revenue and only revenue, so a
    # four-month grocery build planned 234 gross-profit and margin facts into
    # the model and carried none of them — the same defect as the missing
    # budget-margin column, at a different scale, and equally invisible until
    # `validate.carried_evidence` compared the plan against the compiled sheet.
    #
    # They also answer a question the revenue trend cannot. A category whose
    # revenue climbs every month while its margin rate slides is the most
    # ordinary story in retail and the one a revenue-only trend hides
    # completely.
    _TRENDS: tuple[tuple[str, str, str, str], ...] = (
        ("trend", "Revenue Trend", "financial.revenue.actual", MONEY_FORMAT),
        ("trend_gp", "Gross Profit Trend", "financial.gross_profit.actual", MONEY_FORMAT),
        ("trend_margin", "Margin Trend", "financial.gross_margin_pct.actual", PERCENT_FORMAT),
    )
    if len(periods) > 1:

        def trend_row(kind: str, key: str, label: str, subject: str, *,
                      children: list[str] | None = None, emphasis: bool = False) -> Row:
            cells: dict[str, Cell] = {}
            for month in periods:
                fact = index.get(kind, subject, month)
                cells[month] = Cell(
                    value=fact.value.amount if fact and fact.value else None,
                    fact_id=fact.id if fact else None,
                    # A margin rate is a ratio of totals and never the total of
                    # ratios — the same rule `_NOT_ADDITIVE` states for the P&L
                    # columns. A subtotal row on the margin sheet therefore
                    # states its own fact and declares no formula, while the
                    # money sheets sum their children.
                    formula=(FormulaKind.SUM if children and kind not in _RATE_KINDS else None),
                    operands=(children or [] if kind not in _RATE_KINDS else []),
                )
            return Row(key=key, label=label, cells=cells, emphasis=emphasis)

        for table_key, heading, kind, number_format in _TRENDS:
            trend_columns = [
                Column(key=p, label=p, number_format=number_format) for p in periods
            ]
            trend_rows: list[Row] = []
            trend_subtotals: list[str] = []
            for unit in units:
                members = categories_of[unit.id]
                for category in members:
                    trend_rows.append(
                        trend_row(kind, category.id, f"{unit.name} · {category.name}", category.id)
                    )
                if members:
                    trend_rows.append(
                        trend_row(kind, unit.id, f"{unit.name} total", unit.id,
                                  children=[c.id for c in members], emphasis=True)
                    )
                    trend_subtotals.append(unit.id)
                else:
                    trend_rows.append(trend_row(kind, unit.id, unit.name, unit.id))
                    trend_subtotals.append(unit.id)
            trend_rows.append(
                trend_row(kind, company.id, "Group", company.id,
                          children=trend_subtotals, emphasis=True)
            )
            # One chart, on revenue. Three line charts of the same rows would
            # be three ways of looking at the same shape, and the margin one
            # would share neither its axis nor its units.
            charts = [
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
            ] if table_key == "trend" else []
            sections.append(
                ArtifactSection(
                    heading=heading,
                    charts=charts,
                    table=Table(
                        key=table_key,
                        title=heading,
                        columns=trend_columns,
                        rows=trend_rows,
                        note=(
                            "Actual by month. Prior periods carry no budget: a trend needs "
                            "actuals, and generating budgets nobody reads would treble the "
                            "ledger."
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

    required: bool = True
    """Whether every document of this type must carry this section.

    ``True`` by default, and that default is what makes `structure.py`'s
    omission safe to enable globally: a type nobody has annotated has no
    optional sections, so a structural genome cannot strip the section that
    carried a fact the narration contract requires and turn a valid document
    into one that trips ``required_fact_omitted``. Marking a section optional is
    a deliberate statement that a reader would not find its absence strange —
    an appendix, a standing-exposure note, a "what we are doing about it" that
    a quiet month genuinely would not have.
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
            required=False,
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
            required=False,
        ),
    ),
    "incident_rca": (
        SectionPlan(
            "Summary", ("ops.feed_status", "ops.affected_records"), "any",
            "What failed, how much was affected, and what it stopped. Written for someone "
            "who will read this section and nothing else.",
        ),
        SectionPlan(
            # "Times matter here" was unsatisfiable as stated, and two writers
            # independently said so: no fact this section is scoped to renders
            # a clock time, and the digit rule forbids typing one. Every writer
            # who passed delivered sequence, so the purpose now asks for what
            # the facts actually fund — order, not clocks.
            "Timeline", ("ops.incident_opened", "ops.valuation_status", "close."), "any",
            "The sequence, in order, with the moment the close was put at risk made "
            "explicit. Order matters here; narrative flourish does not. No fact "
            "supplied renders a clock time — and the digits rule forbids writing one — "
            "so carry the timeline as sequence: what happened first, what followed, "
            "and what it forced.",
        ),
        SectionPlan(
            # This purpose demanded "the hypothesis triage recorded" while the
            # kinds scope it to the refutation alone — the hypothesis fact sits
            # in "Root cause". Widening the scope to `ops.cause` would fix the
            # wording but pull the confirmed cause in too, and — through the
            # intent's required-first-three rule in `_request_for` — demand
            # citations the accepted reference narration in
            # examples/grocery-close never made. So the purpose is brought to
            # the facts rather than the facts to the purpose: this section owns
            # the ruling-out, and says where the hypothesis itself lives.
            "Initial assessment and why it was wrong", ("ops.cause_ruled_out",), "any",
            "State how the initial attribution was closed: the evidence supplied is the "
            "refutation, and the belief it tested is implicit in it. Write it as a "
            "belief examined and ruled out at the time, not as an error — the point is "
            "what the evidence supported then, not blame now. The hypothesis itself is "
            "cited under Root cause; this section owns only the ruling-out.",
            # Optional because an incident that went straight to its cause has
            # no false trail to record, and a review without one reads as a
            # short investigation rather than a truncated document. The
            # hypothesis it tested is cited under Root cause — which is
            # required — so dropping this loses the ruling-out and never the
            # cause.
            required=False,
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
            required=False,
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
            required=False,
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
            # Optional on the article's own argument: the Procedure below says
            # a reader "should be able to follow this without understanding the
            # cause", so an article that is symptom then steps is the ordinary
            # runbook rather than a defective one. Procedure stays required —
            # it is what the article is for.
            required=False,
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
            required=False,
        ),
    ),
    "close_calendar": (
        SectionPlan(
            "Commitment", ("close.due_date",), "any",
            "State the committed date for the period. This is a standing published "
            "document; write it as policy, not as news.",
        ),
        # Fires only in a period the date actually moved in, which is what the
        # plan should always have said. It asked for the final status and the
        # delay as well, `generators/planning.py` gave the calendar neither, and
        # the section rendered zero times across thirty-one calendars — half of
        # every close calendar's declared outline, permanently unreachable. The
        # narrower ask is also the truer one: a timetable records the date it
        # moved to, not how the period turned out.
        SectionPlan(
            "Escalation", ("close.revised_date",), "any",
            "The date moved. State what it moved to and what the standing rule is when it "
            "does. Procedural register — this is read by people looking up a rule, not by "
            "people who want to know how the period went.",
            required=False,
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
            # Optional because an assessment issued before anybody has a
            # workaround has no holding position to state, and that is the
            # normal case for the first hour this document exists to serve.
            # "What it reaches" — its own purpose calls it the whole point of
            # the assessment — stays required.
            required=False,
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
            required=False,
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
            # The purpose already said this: "skip gracefully if the measures
            # given say nothing" is a section declaring its own conditionality,
            # the same tell `unit_close_commentary/Watch items` carries. A
            # forward look is the first thing a review of a month that has
            # already happened drops.
            required=False,
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

#: Alternative outlines for a type, rotated over its instances.
#:
#: The measurement: a six-period corpus produced **12 distinct shapes across 56
#: artifacts**, 95% of them sharing a shape with another, and every
#: near-duplicate group was exactly ×6 — the same document once per period, the
#: same headings in the same order. Six close calendars with different dates is
#: realistic. Six root-cause reviews with an identical five-section skeleton is
#: not: real reviews differ because the incidents differ, and a reader who sees
#: the same skeleton six times learns the skeleton rather than the content.
#:
#: **Rotated by ordinal, not drawn.** The variant is chosen by this document's
#: position among the instances of its own type, so N instances over M variants
#: land evenly by construction. A seeded draw would only *tend* to spread and
#: would happily give six documents the same shape on an unlucky seed — which is
#: the exact failure being fixed.
#:
#: **The first variant is the outline that shipped**, so a type's first instance
#: is byte-identical to what it was. Later instances move, which is the intended
#: generation change and the whole point.
#:
#: Each alternative is a different *argument*, never a shuffle of the same one.
#: A memo led by the exception is a different document from one led by the
#: position, and re-ordering headings without changing what each section is for
#: would be variety a reader can see and a retriever cannot.
_OUTLINE_VARIANTS: dict[str, tuple[tuple[SectionPlan, ...], ...]] = {}


def _variant_for(world: Any, intent: ArtifactIntent) -> tuple[SectionPlan, ...]:
    """Which outline this particular document gets.

    Two decisions, in order: which of a type's authored variants, then which of
    that variant's sections. Both live in `structure.py` — the choosing was
    here first and moved there so the two compose in one place, and its
    measurement is worth keeping in front of whoever reads this next.

    Chosen by hashing the intent's own id, not by cycling an ordinal. The
    ordinal read beautifully — "rotate the variants over the documents of a
    type, in minted order" — and it aliased to zero at the shipped shape:
    `unit_close_commentary` has three variants and the default retailer has
    three business units, so `ordinal % 3` pinned every unit to one variant in
    every period at every seed. Measured across five seeds and three periods:
    distinct variants seen per unit = 1, and the `"Why"` variant — locked to
    the one unit that mints no `metric.*` facts — rendered 0 times in 15
    documents. Any modulus cycle has this failure mode whenever the count of
    documents per period shares a factor with the variant count; a hash of the
    id has no period to alias with, because ids never repeat.

    Deterministic for the same reason everything here is: the id is minted by
    walk order, `crc32` is defined byte-for-byte, and neither knows the clock.
    A document's shape still never moves when a later period adds another of
    its type — its id is already minted.

    The genome comes off the *recipe*, not off a `World` field and not off a
    process global. The recipe is already the thing that survives to disk and
    drives replay, so a corpus whose documents were shaped by a genome resolves
    the same shapes when it is loaded back, and a rebuild reproduces them
    without anything being threaded through four domain builders.
    """
    genome = recipe_module.structure_of(getattr(world, "_recipe", None))
    key = f"{intent.artifact_type}:{intent.id}"
    variants = _OUTLINE_VARIANTS.get(intent.artifact_type)
    if variants:
        chosen: tuple[SectionPlan, ...] = tuple(structure.choose(variants, key=key, genome=genome))
    else:
        chosen = _OUTLINES.get(intent.artifact_type, _DEFAULT_OUTLINE)
    return structure.derive(chosen, key=key, genome=genome)


_MEASURES_ALL = ("financial.revenue.", "financial.gross_profit.",
                 "financial.gross_margin_pct.")

_OUTLINE_VARIANTS.update({
    # Three ways to argue a division's month, and the difference is which
    # question the writer is answering. The first states the position and then
    # what to watch; the second leads with the exception, which is what a
    # partner writes when the month went wrong; the third answers the question
    # the divisional MD will actually ask, which is what happens when the month
    # was unremarkable and the meeting is about next month.
    #
    # This is the corpus's most-repeated close document — forty-eight instances
    # on a six-period, eight-division build — and rotating it is most of what
    # the whole variant mechanism buys. It also invalidates two of the four
    # commentaries in `examples/grocery-close/narration.json`, which is real
    # model prose checked in against the shipped headings; those two are
    # rewritten against the new sections rather than the type being left alone,
    # because a reference narration is worth keeping current and a document type
    # nobody varies is worth less than the work of keeping it.
    "unit_close_commentary": (
        _OUTLINES["unit_close_commentary"],
        (
            SectionPlan(
                "What moved", _MEASURES_ALL, "unit",
                "Lead with the line that missed or beat, and say by how much"
                " before saying why. A commentary that opens with a summary of"
                " a month its reader already lived through has spent its first"
                " paragraph on nothing.",
            ),
            SectionPlan(
                "Why", ("metric.",), "any",
                "Attribute the movement to something a person did or something"
                " that happened to them. 'Volume was lower' is a restatement,"
                " not a reason.",
            ),
            SectionPlan(
                "Position", _MEASURES_ALL, "unit",
                "The rest of the month, briefly, for the record. Lines that"
                " behaved get a clause each.",
                # A for-the-record trailer, and this variant says so: it leads
                # with the exception, and "the rest of the month, briefly" is
                # what a partner cuts when there is nothing else to report.
                # "What moved" and "Why" carry the argument and stay required.
                required=False,
            ),
        ),
        (
            SectionPlan(
                "Where we landed", _MEASURES_ALL, "unit",
                "The month in the terms this division is held to. State it"
                " plainly and once.",
            ),
            SectionPlan(
                "What we are doing about it", ("metric.",), "any",
                "The actions in flight and who owns them. A commentary whose"
                " last word is a number leaves the reader to work out whether"
                " anybody has noticed.",
            ),
        ),
    ),
    # An RCA that opens with the timeline makes a reader work for the answer;
    # an RCA that opens with the cause makes them work for the evidence. Both
    # are written, and which one you get says something about who wrote it —
    # the first is what a reviewer asks for, the second is what an engineer
    # writes when they already know.
    "incident_rca": (
        _OUTLINES["incident_rca"],
        (
            SectionPlan(
                "Cause", ("ops.cause", "ops.root_cause_classification",
                          "ops.mapping_table_owner"), "any",
                "Open with the conclusion. A review that withholds the cause"
                " until section four is a review written to be defended rather"
                " than read.",
            ),
            SectionPlan(
                "What that cost", ("ops.feed_status", "ops.affected_records",
                                   "close."), "any",
                "The impact, in the units the business feels it in — records,"
                " days, the close. Not in units the platform feels it in.",
            ),
            SectionPlan(
                "How we got there", ("ops.incident_opened",
                                     "ops.valuation_status",
                                     "ops.cause_ruled_out"), "any",
                "The sequence, including the line of enquiry that was wrong."
                " A clean timeline is a rewritten one.",
            ),
            SectionPlan(
                "Standing exposure", ("ops.previous_similar_incident",
                                      "ops.workaround"), "any",
                "What is still true after the fix. This is the section a"
                " reader six months later is looking for.",
                # The variant's own "Contributing factors": same fact kinds,
                # same judgement. An incident with no precedent and no residual
                # workaround has no standing exposure, and a review that says
                # so by saying nothing is the one a reader expects. Marked here
                # as well as in variant 0 so the two arguments about one
                # incident vary alike rather than one of them being frozen.
                required=False,
            ),
            SectionPlan(
                "Actions", ("ops.remediation",), "any",
                "What changes, who owns it, and which of them addresses the"
                " control rather than the detection.",
            ),
        ),
    ),
    # A summary written for a committee that reads it before the meeting, and
    # one written for a committee that reads it in the meeting. The second is
    # shorter and leads with the ask.
    "executive_summary": (
        _OUTLINES["executive_summary"],
        (
            SectionPlan(
                "The ask", ("close.", "financial.incident_pl_impact"), "any",
                "What the committee is being asked to note or decide, in the"
                " first sentence. A summary that buries the ask is a summary"
                " that will be read after the decision.",
            ),
            SectionPlan(
                "The month", ("financial.revenue.",
                              "financial.gross_margin_pct."), "group",
                "The group position in two figures. The committee has the pack"
                " if they want the rest.",
            ),
        ),
    ),
})


_DEFAULT_OUTLINE: tuple[SectionPlan, ...] = (
    SectionPlan("Summary", ("",), "any", "Summarise what the facts below establish."),
)


#: Words that title-casing gets wrong. An artifact type is a snake_case key, and
#: `.title()` turns `cfo_variance_memo` into "Cfo Variance Memo" — which no
#: finance function has ever written on a document, and which is exactly the kind
#: of tell that marks a corpus as generated.
_ACRONYMS = {"Cfo": "CFO", "Ceo": "CEO", "Cio": "CIO", "Rca": "RCA", "Kb": "KB", "It": "IT"}

# A document's declared domain is an authorship constraint, not a decorative
# tag. Broad cross-functional domains name the functions that legitimately own
# them; ``people`` is deliberately open because a succession notice is signed
# by the successor, whose function is the subject of the change.
_DOMAIN_AUTHORS: dict[str, frozenset[str] | None] = {
    "finance": frozenset({"Finance", "Executive"}),
    "operations": frozenset({
        "Operations", "ServiceOperations", "Technology", "Procurement", "Executive",
    }),
    "engineering": frozenset({"Technology", "Engineering"}),
    "strategy": frozenset({
        "Executive", "Finance", "Risk", "Actuarial", "Procurement", "Merchandising",
        "Technology", "Operations", "ServiceOperations", "Audit",
    }),
    "risk": frozenset({"Risk", "Audit", "Finance", "Executive"}),
    "actuarial": frozenset({"Actuarial"}),
    "procurement": frozenset({"Procurement", "Finance", "Operations", "Executive"}),
    "people": None,
    # A standing document's domain (`worldloom.policies`). Open like `people`,
    # and for a related reason: a policy is owned by the function it governs,
    # so an information security policy is signed in Technology and a leave
    # policy in Executive or People, while the *same* library has to work on
    # four engines whose function vocabularies do not agree. A closed set here
    # would refuse a hospital its clinical governance policy on the strength of
    # a word retail happens not to use.
    "governance": None,
}


def _title(artifact_type: str) -> str:
    """A human title for an artifact type."""
    words = artifact_type.replace("_", " ").title().split()
    return " ".join(_ACRONYMS.get(word, word) for word in words)


def _contracted(world: World, intent: ArtifactIntent, ir: ArtifactIR) -> ArtifactIR:
    """Enforce and stamp the renderer-independent artifact cohesion contract."""
    if intent.artifact_type not in declared_types() | reserved_types():
        raise ValueError(
            f"{intent.id}: artifact type {intent.artifact_type!r} has no declared contract"
        )
    author = world.people.by_id(intent.author_id)
    permitted = _DOMAIN_AUTHORS.get(intent.domain)
    if intent.domain not in _DOMAIN_AUTHORS:
        raise ValueError(f"{intent.id}: artifact domain {intent.domain!r} is undeclared")
    if permitted is not None and author.function not in permitted:
        article = "an" if intent.domain[:1].casefold() in "aeiou" else "a"
        raise ValueError(
            f"{intent.id}: {author.function} author {author.name!r} cannot own"
            f" {article} {intent.domain} artifact"
        )
    if not intent.audience.strip():
        raise ValueError(f"{intent.id}: artifact audience is empty")
    if not ir.title.strip():
        raise ValueError(f"{intent.id}: compiled artifact has no title")

    # Dedicated statutory compilers legitimately use filing names rather than
    # the type's literal label. Requiring one meaningful type word keeps the
    # title tied to the document family without replacing those domain titles.
    signals = {
        word.casefold() for word in _title(intent.artifact_type).split()
        if len(word) > 2 and word.casefold() not in {"working", "internal"}
    }
    signals.update({
        "finance_workbook": {"month-end", "model"},
    }.get(intent.artifact_type, set()))
    title_words = {word.strip("·—-:(),").casefold() for word in ir.title.split()}
    if signals and not signals.intersection(title_words):
        raise ValueError(
            f"{intent.id}: title {ir.title!r} is not cohesive with"
            f" artifact type {intent.artifact_type!r}"
        )

    facts = [world.facts.by_id(fact_id) for fact_id in intent.required_fact_ids]
    allowed = set(intent.required_fact_ids)
    escaped = sorted(set(ir.fact_ids()) - allowed)
    if escaped:
        raise ValueError(
            f"{intent.id}: compiled content escapes its declared fact scope: {escaped}"
        )

    periods = sorted({fact.period for fact in facts if fact.period})
    subjects = sorted({fact.subject for fact in facts})
    metadata = {
        **ir.metadata,
        "artifact_type": intent.artifact_type,
        "artifact_domain": intent.domain,
        "artifact_audience": intent.audience,
        "author_id": author.id,
        "author_function": author.function,
        "scope_periods": ",".join(periods),
        "scope_subjects": ",".join(subjects),
        "cohesion_contract": "artifact-contract@1",
    }
    return ir.model_copy(update={
        "subtitle": ir.subtitle or f"{author.title} · {intent.audience.replace('_', ' ')}",
        "metadata": metadata,
    })


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
    plan = _variant_for(world, intent)
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
            from . import templating

            # Resolve {{var:...}} variables in heading and purpose from the world.
            # Variables-of-variables are refused (they contain {{var:...}} after
            # substitution), and unresolved variables are left as [missing var:NAME].
            resolved_heading, _ = templating.substitute(step.heading, world)
            resolved_purpose, _ = templating.substitute(step.purpose, world)

            sections.append(
                ArtifactSection(
                    heading=resolved_heading,
                    body=None,
                    fact_ids=assigned,
                    purpose=resolved_purpose,
                    semantic_role=infer_semantic_role(resolved_heading, step.kinds),
                )
            )

    # The causal chain rides the *first* explanation section rather than a
    # section of its own, because it is not extra content — it is the shape of
    # the argument that section is already making, and a diagram sitting beside
    # the paragraph that explains it is a second telling a reader has to
    # reconcile.
    flow = _causal_flow(world, intent)
    if flow is not None:
        # The section a reader goes to for a chain, when the outline has one:
        # an RCA has several explanation sections and the diagram belongs with
        # the conclusion rather than with the discarded first hypothesis, which
        # is where "first explanation section" put it.
        explanations = [
            index for index, section in enumerate(sections)
            if section.semantic_role == "explanation"
        ]
        named = [i for i in explanations if "root cause" in sections[i].heading.lower()]
        for index in (named or explanations)[:1]:
            sections[index] = sections[index].model_copy(update={"flow": flow})

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



#: Artifact types whose explanation sections describe a chain of events rather
#: than a set of figures. An RCA is the archetype: its "Root cause" section is a
#: walk from trigger to effect, and until there was a `FlowDiagram` to declare
#: it, the shape was flattened into a paragraph and a renderer had no way to
#: know a chain was what it was reading.
_CAUSAL_NARRATIVE = frozenset({"incident_rca"})

#: Event kinds that are the *spine* of an incident, in the order a reader walks
#: them. The world mints more events than an RCA should draw — a chain that
#: included every `caused_by` edge would put the close-finalised administrivia
#: beside the control failure and bury the point. Ordered and closed, because
#: which events constitute the story is an editorial claim about incidents, not
#: something derivable from the graph.
_CAUSAL_SPINE: tuple[str, ...] = (
    "pipeline_failed",
    "incident_opened",
    "hypothesis_recorded",
    "hypothesis_superseded",
    "root_cause_confirmed",
    "control_failure_identified",
    "workaround_applied",
)


def _causal_flow(world: World, intent: ArtifactIntent) -> FlowDiagram | None:
    """The incident's chain of events, as a declared shape.

    Read from ``EnterpriseEvent.caused_by`` — the edges the world already
    minted and that `benchmark.py`'s `causal_multi_hop` family already walks —
    rather than from a second description of the incident kept beside it. There
    is one account of what caused what, and this is a view of it.

    Edges are emitted only between events that are both on the spine, so the
    chain a reader sees is connected: a spine event whose direct cause was
    filtered out is linked to its nearest surviving ancestor instead of being
    left floating, because a node with no path to the trigger is exactly the
    thing a causal diagram must not show.

    Deterministic by construction — `world.events` is ordered, the spine is a
    literal tuple, and nothing here consults a set for iteration order.
    """
    if intent.artifact_type not in _CAUSAL_NARRATIVE:
        return None

    spine = {event.id: event for event in world.events if event.kind in _CAUSAL_SPINE}
    if len(spine) < 2:
        return None

    by_id = {event.id: event for event in world.events}

    def nearest_on_spine(event_id: str, seen: frozenset[str] = frozenset()) -> str | None:
        """The closest ancestor of *event_id* that the spine keeps.

        Walks `caused_by` upward. `seen` guards a cycle: the world does not
        mint one today, and a causal graph that ever did would hang this
        function rather than produce a wrong answer, which is the worse of the
        two failures.
        """
        event = by_id.get(event_id)
        if event is None or event_id in seen:
            return None
        for cause in event.caused_by:
            if cause in spine:
                return cause
            found = nearest_on_spine(cause, seen | {event_id})
            if found is not None:
                return found
        return None

    order = {kind: index for index, kind in enumerate(_CAUSAL_SPINE)}
    ordered = sorted(spine.values(), key=lambda e: (order[e.kind], e.id))
    nodes = [
        FlowNode(key=event.id, label=event.kind.replace("_", " ").capitalize())
        for event in ordered
    ]
    edges = []
    for event in ordered:
        source = nearest_on_spine(event.id)
        if source is not None:
            edges.append(FlowEdge(source=source, target=event.id, label="led to"))
    return FlowDiagram(nodes=nodes, edges=edges)


def approver_of(
    roles: dict[str, str], artifact_type: str, author: str,
    table: Mapping[str, str], *, role_key: str | None = None,
) -> str | None:
    """Who signs *artifact_type*, or ``None`` if nobody does.

    Four planners now name approvers — retail's close, banking's return,
    insurance's valuation, procurement's match — and each owns its own *table*
    because who signs a prudential return is an argument about banking. What
    they share is the two ways a signature legitimately comes back empty, and
    those live here so the four cannot drift apart on them.

    *role_key* overrides the table for a type whose approver depends on the
    document rather than on the type — a division's close commentary is signed
    by *that division's* managing director, and a table keyed by type has no way
    to say which one.

    A role this world does not have resolves to ``None`` rather than raising:
    several types are gated on facets that mint roles conditionally, and a build
    whose role table could not carry one must still produce the document. An
    approver who *is* the author resolves to ``None`` too — a document somebody
    signed off for themselves is not an approval, it is a byline printed twice,
    and ``validate.approvals`` fails any that gets past here.
    """
    key = role_key or table.get(artifact_type)
    person = roles.get(key) if key else None
    return None if person == author else person


def _signoff(
    world: World, facts: list[CanonicalFact], intent: ArtifactIntent
) -> ArtifactSection | None:
    """Prepared by, reviewed by — the block a signed document ends with.

    Fully structured, so it costs the narration loop nothing: no ``body``, no
    request, nothing for a writer to invent. That is the same argument
    ``meeting_minutes`` makes about its attendee list, and it is what lets a
    signature reach every rendered format without a renderer learning a new
    concept — it is a table, and every renderer already draws tables.

    Dated from the artifact's own facts through ``written_at`` rather than from
    a clock, for the reason the manifest date is: a document whose signature
    block disagreed with its own metadata would be a document that fails its
    corpus's reconciliation before a reader gets to the numbers.

    Returns ``None`` when nobody signed, which is most types
    (``planning._APPROVED_BY``) and every corpus built before this existed —
    a document with no approver renders exactly as it always did.
    """
    if not intent.approver_id:
        return None
    author = world.people.by_id(intent.author_id)
    approver = world.people.by_id(intent.approver_id)
    if author is None or approver is None:
        return None

    at = written_at(intent, {f.id: f for f in facts}).date().isoformat()
    columns = [
        Column(key="name", label="Name"),
        Column(key="role", label="Role"),
        Column(key="date", label="Date"),
    ]

    def row(key: str, label: str, person) -> Row:  # type: ignore[no-untyped-def]
        return Row(key=key, label=label, cells={
            "name": Cell(value=person.name),
            "role": Cell(value=person.title),
            "date": Cell(value=at),
        })

    return ArtifactSection(
        heading="Approval",
        table=Table(
            key="approval",
            title="Prepared and reviewed",
            columns=columns,
            rows=[row("prepared", "Prepared by", author),
                  row("approved", "Approved by", approver)],
            note="Approval is recorded against the period the document reports on.",
        ),
    )


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

    # The fourth copy of the same column decisions, now the same declaration
    # narrowed and relabelled. `columns.DIVISIONAL`'s own comment records what
    # `columns.lint` has to say about it: the margin ratio's numerator column is
    # not on this table, so XLSX emits no formula for it. Latent — the memo is a
    # Word document — and reported rather than fixed, because both fixes change
    # what a reader sees.
    columns = _columns(columns_module.DIVISIONAL)
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

def company_timeline(world: World, intent: ArtifactIntent, minter: Minter) -> ArtifactIR:
    """The company's own past, as the dated table the lore already witnesses.

    `organisation.generate` mints one ``MFACT-`` fact per dated lore commitment
    — the hierarchy remap, the replatform, the four-day close norm — and for a
    long time nothing planned a document that carried any of them: five facts
    per world, on every engine, readable nowhere, and the whole
    ``milestone_provenance`` evaluation family silently minting zero cases
    behind its reachability guard because the guard was doing its job. This is
    the missing consumer, and it is the document a real intranet always has —
    the "about us" page every onboarding pack links to.

    Compiled rather than outlined on purpose: a timeline is a table of dated
    assertions, prose would only restate the rows, and a table-only IR makes no
    narration request — so the reference ledger does not grow by one document's
    worth of prose to keep this page in existence.
    """
    facts = [world.facts.by_id(f) for f in intent.required_fact_ids]
    company = world.company
    rows = [
        Row(
            key=fact.id.lower(),
            label=fact.valid_from.strftime("%B %Y"),
            cells={"what": Cell(value=fact.text_value, fact_id=fact.id)},
        )
        # By date, oldest first — a timeline in mint order would interleave
        # 2022 between 2024 and 2025 wherever the lore file listed it that way.
        # The id is the tiebreak so two same-month milestones cannot swap.
        for fact in sorted(facts, key=lambda f: (f.valid_from, f.id))
    ]
    table = Table(
        key="timeline",
        title="Milestones",
        columns=[Column(key="what", label="What happened, and what it left behind")],
        rows=rows,
        note=(
            "Standing record. Each row is dated by when the milestone happened, "
            "not by when this page was written — the page is always younger than "
            "everything on it."
        ),
    )
    return ArtifactIR(
        id=intent.id,
        intent_id=intent.id,
        title=f"{company.name} — Company Timeline",
        subtitle="How this company came to run the way it runs",
        sections=[ArtifactSection(heading="Milestones", table=table)],
        metadata={
            "worldloom_synthetic": "true",
            "worldloom_seed": str(world.seed),
            "worldloom_period": world.period or "",
            "worldloom_created": max(f.valid_from for f in facts).isoformat(),
            "company": company.name,
            "note": "Synthetic corpus generated by Worldloom. Not a real company.",
        },
    )


def _cut_table(world: World, intent: ArtifactIntent) -> Table:
    """The one cited row a standing extract carries: when it was cut.

    Both extracts below are projections of entity collections rather than of
    the fact ledger, and an intent citing no fact has no date — `written_at`
    raises, correctly. So each cites exactly one fact, the close's committed
    date, and states it here: an extract is cut *for* a close, and the row is
    what `validate.carried_evidence` holds the citation to.
    """
    fact = next(world.facts.by_id(f) for f in intent.required_fact_ids)
    return Table(
        key="cut", title="Extract basis",
        columns=[Column(key="value", label="Value")],
        rows=[Row(key="cut_for", label="Cut for the close committed on",
                  cells={"value": Cell(value=fact.text_value, fact_id=fact.id)})],
        note="A point-in-time extract, not a live view. Re-cut each time only if re-planned.",
    )


def service_register(world: World, intent: ArtifactIntent, minter: Minter) -> ArtifactIR:
    """The estate, in a document — because a graph nobody rendered is not corpus.

    `--estate large` grew the world to dozens of services and, measured, the
    *document layer* was byte-identical to `medium`: every generated service
    reached `worldloom topology` and the ServiceNow CMDB sidecar (which has no
    manifest row, so the workspace drive never shelves it) and not one page a
    retriever could read. Eight evaluation cases asked about dependency depth
    and blast radius while their quantitative answers appeared in zero artifact
    bytes. This register is the missing page: the service inventory a real IT
    department keeps, plus the shape figures those questions grade against.
    """
    company = world.company
    people = {p.id: p.name for p in world.people}
    systems = {s.id: s.name for s in world.systems}
    services = sorted(world.services, key=lambda s: s.id)

    rows = [
        Row(key=svc.id, label=svc.name, cells={
            "purpose": Cell(value=svc.purpose),
            "tier": Cell(value=float(svc.criticality_tier)),
            "owner": Cell(value=people.get(svc.owner_id, "")),
            "system": Cell(value=systems.get(svc.system_id, svc.system_id)),
            "depends": Cell(value=float(len(svc.depends_on))),
        })
        for svc in services
    ]
    register = Table(
        key="register", title="Service register",
        columns=[
            Column(key="purpose", label="Purpose"),
            Column(key="tier", label="Criticality tier", number_format="0"),
            Column(key="owner", label="Owner"),
            Column(key="system", label="Runs on"),
            Column(key="depends", label="Direct dependencies", number_format="0"),
        ],
        rows=rows,
        note=(
            f"{company.name} · one row per running service. Dependencies count both "
            "services and the systems they run on; the chain, not this count, is what "
            "an outage travels along."
        ),
    )

    # The shape figures, computed from the same `depends_on` edges `graphs`
    # reads — iterative and id-ordered, so the walk is deterministic and safe
    # on a cycle (the validator forbids one, but a register must not hang on
    # the corpus it would be reporting a defect in).
    depth: dict[str, int] = {}

    def chain(service_id: str) -> int:
        if service_id in depth:
            return depth[service_id]
        depth[service_id] = 0  # cycle guard: a revisit reads 0 rather than recursing
        svc = next((s for s in services if s.id == service_id), None)
        below = [chain(d) for d in (svc.depends_on if svc else ()) if d.startswith("SVC-")]
        depth[service_id] = 1 + max(below, default=0)
        return depth[service_id]

    deepest = max(services, key=lambda s: (chain(s.id), s.id), default=None)
    shape = Table(
        key="shape", title="Shape of the estate",
        columns=[Column(key="value", label="Value")],
        rows=[
            Row(key="services", label="Running services",
                cells={"value": Cell(value=float(len(services)))}),
            Row(key="systems", label="Systems hosting them",
                cells={"value": Cell(value=float(len(systems)))}),
            Row(key="depth", label="Longest dependency chain (hops)",
                cells={"value": Cell(value=float(chain(deepest.id)) if deepest else None)}),
            Row(key="top", label="Service at the top of that chain",
                cells={"value": Cell(value=deepest.name if deepest else "")}),
        ],
        note="Depth counts service-to-service hops; an outage at the bottom reaches the top.",
    )

    return ArtifactIR(
        id=intent.id,
        intent_id=intent.id,
        title=f"{company.name} — Service Register",
        subtitle="The technology estate, one row per running service",
        sections=[
            ArtifactSection(heading="Service register", table=register),
            ArtifactSection(heading="Shape of the estate", table=shape),
            ArtifactSection(heading="Extract basis", table=_cut_table(world, intent)),
        ],
        metadata={
            "worldloom_synthetic": "true",
            "worldloom_seed": str(world.seed),
            "worldloom_period": world.period or "",
            "worldloom_created": max(
                (f.valid_from for f in (world.facts.by_id(i) for i in intent.required_fact_ids)),
            ).isoformat(),
            "company": company.name,
            "note": "Synthetic corpus generated by Worldloom. Not a real company.",
        },
    )


def reference_data_extract(world: World, intent: ArtifactIntent, minter: Minter) -> ArtifactIR:
    """The master data, in a document — the other 800 rows nothing read.

    `--master-data` minted vendors, customers and SKUs into `masterdata.json`,
    whose only readers in the entire tree were the two lines in `world.py` that
    wrote it and read it back: not in the manifest, not in the retrieval index,
    not in the workspace drive, no validator group. ~1.8 MB of corpus at the
    advertised size that no reader, retriever or eval case could reach. This
    extract is the join surface the masterdata docstring already claims to be —
    the vendor and item listing an ERP actually exports.
    """
    company = world.company
    md = world.masterdata

    def block(key: str, title: str, columns: list[Column], rows: list[Row], note: str) -> ArtifactSection:
        return ArtifactSection(
            heading=title,
            table=Table(key=key, title=title, columns=columns, rows=rows, note=note),
        )

    sections = []
    if md.vendors:
        sections.append(block(
            "vendors", "Vendor master",
            [Column(key="category", label="Category"),
             Column(key="terms", label="Payment terms"),
             Column(key="contact", label="Contact")],
            [Row(key=v.id, label=v.name, cells={
                "category": Cell(value=v.category),
                "terms": Cell(value=v.payment_terms),
                "contact": Cell(value=v.contact_name),
            }) for v in md.vendors],
            "As held in the ERP vendor master. Terms are the contracted default, not "
            "what any one invoice was settled at.",
        ))
    if md.customers:
        sections.append(block(
            "customers", "Customer master",
            [Column(key="segment", label="Segment"),
             Column(key="terms", label="Payment terms"),
             Column(key="contact", label="Contact")],
            [Row(key=c.id, label=c.name, cells={
                "segment": Cell(value=c.segment),
                "terms": Cell(value=c.payment_terms),
                "contact": Cell(value=c.contact_name),
            }) for c in md.customers],
            "Trade customers only; a till transaction has no master record.",
        ))
    if md.skus:
        vendors = {v.id: v.name for v in md.vendors}
        sections.append(block(
            "skus", "Item master",
            [Column(key="vendor", label="Vendor"),
             Column(key="category", label="Category"),
             Column(key="price", label="Unit list price", number_format="#,##0.00")],
            [Row(key=s.id, label=s.name, cells={
                "vendor": Cell(value=vendors.get(s.vendor_id, s.vendor_id)),
                "category": Cell(value=s.category),
                "price": Cell(value=s.unit_price),
            }) for s in md.skus],
            "List price per unit, before any negotiated rate — the number a margin "
            "conversation starts from, never the one it ends at.",
        ))
    sections.append(ArtifactSection(heading="Extract basis", table=_cut_table(world, intent)))

    return ArtifactIR(
        id=intent.id,
        intent_id=intent.id,
        title=f"{company.name} — Reference Data Extract",
        subtitle="Vendor, customer and item masters, as at the close",
        sections=sections,
        metadata={
            "worldloom_synthetic": "true",
            "worldloom_seed": str(world.seed),
            "worldloom_period": world.period or "",
            "worldloom_created": max(
                (f.valid_from for f in (world.facts.by_id(i) for i in intent.required_fact_ids)),
            ).isoformat(),
            "company": company.name,
            "note": "Synthetic corpus generated by Worldloom. Not a real company.",
        },
    )


_COMPILERS: dict[str, Any] = {
    "finance_workbook": finance_workbook,
    "meeting_minutes": minutes_ir,
    "email_thread": thread_ir,
    "company_timeline": company_timeline,
    "service_register": service_register,
    "reference_data_extract": reference_data_extract,
}
_STANDING.update({
    # Circulated minutes are the approved record of the meeting; a thread is a
    # record too, but an informal one — the authority gap between them is what
    # a who-was-told-when evaluation resolves against.
    "meeting_minutes": (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED),
    "email_thread": (Authority.UNOFFICIAL_NOTE, Lifecycle.PUBLISHED),
    # A standing intranet page, not a filing: authoritative about its dates
    # because the milestone facts are, published because everyone can see it.
    "company_timeline": (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED),
    # Extracts of systems of record are systems of record: the CMDB and the
    # ERP masters are where these rows *live*, and the page only projects them.
    "service_register": (Authority.SYSTEM_OF_RECORD, Lifecycle.PUBLISHED),
    "reference_data_extract": (Authority.SYSTEM_OF_RECORD, Lifecycle.PUBLISHED),
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
        ir = builder(world, intent, minter)
    else:
        ir = outline(world, intent, minter)
    return _contracted(world, intent, _signed(world, intent, ir))


def _signed(world: World, intent: ArtifactIntent, ir: ArtifactIR) -> ArtifactIR:
    """*ir* with its signature block, when the document carries one.

    Here rather than in ``outline`` because ``outline`` is one of a dozen
    builders: the workbook, the ServiceNow bundle, the Jira export, banking's
    return and insurance's triangle each build their own IR, and an approval
    that only reached the outline path would have put ``approver_id`` on a
    finance workbook's manifest entry and no signature on the workbook. Caught
    by the test that pins the two to each other rather than by reading the
    file, which is the only way that gap is visible — the manifest and the
    document disagreed and both looked fine alone.

    Inserted before the first *hidden* section rather than appended. A
    signature is the last thing on the readable surface and "Supporting facts"
    is not on it; appending would have put the sign-off underneath the
    fact-provenance appendix, which is nowhere a signature goes.
    """
    signoff = _signoff(world, list(world.facts), intent)
    if signoff is None:
        return ir
    sections = list(ir.sections)
    cut = next(
        (index for index, section in enumerate(sections) if section.hidden), len(sections)
    )
    sections.insert(cut, signoff)
    approver = world.people.by_id(intent.approver_id) if intent.approver_id else None
    return ir.model_copy(update={
        "sections": sections,
        "metadata": {
            **ir.metadata,
            "approver": approver.name if approver else "",
            "approver_title": approver.title if approver else "",
        },
    })
