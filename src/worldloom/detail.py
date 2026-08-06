"""Detail tables — transaction-level rows underneath the ledger's aggregates.

``p2p.ordered_value`` is one fact. A real purchasing system would hold ~1,100
order lines under it, and a workbook whose only sheet is fifteen load-bearing
rows announces itself as synthetic. This module is the layer between: a
recipe-shaped declaration (Snowfakery's best idea) generated *inside* the
determinism boundary, so the byte-replay promise holds and — the part no
recipe engine has — every figure the ledger also states is **derived from the
fact, never drawn beside it**.

Design informed by prior art the repository owner already proved out:
``@ge/synthkit`` (``packages/synthkit`` in ge-agent-factory) — its recipe of
per-field generator descriptors with FK edges resolved referent-first so
output is referentially closed by construction; its realism tier (log-normal
money spreads, zipf-weighted enums so frequent values dominate,
business-hours dates); and its seeded edge-case injection as a declared
fraction that never touches keys, so closure survives the mess. What synthkit
does not have, and this module will not give up, is the reconciliation rule:

**The non-negotiable rule.** A column that carries a quantity the ledger also
states is *allocated from the fact* by largest remainder (``finance.allocate``,
the ``rollup`` primitive's discipline, extended to N rows at declared
decimals) — so the lines sum to the declared total exactly, to the last cent,
by construction rather than by hope. Rows are never drawn independently and
then "checked close enough": a detail layer that merely approximated its own
ledger would be the copy-that-drifts this project exists to eliminate. The
``detail`` validator group recomputes every declared sum anyway, because a
guarantee nothing checks is a claim.

Three placement decisions, argued:

* **Declaration lives on the episode spec** (``episodes.EpisodeSpec.detail``),
  because a detail table is a claim about the facts one process mints, and the
  spec is where those facts are declared, linted, and carried by the pack. A
  recipe naming a fact kind the registry does not know is lint-refused —
  the same defence ``factkinds`` exists for (a plausible-looking invented kind
  once passed a spec's self-referential lint).
* **Generation runs as a runner hook, after the facts mint** — rows are
  *derived from* fact values and cite fact ids, so they cannot exist before
  ``episodes.run`` returns. A pre-mint pass would have to predict the draw it
  is supposed to reconcile against.
* **Rows are corpus data, one ``detail.jsonl``** — not embedded in the
  artifact IR (a 1,100-row table copied into ``artifact-ir.jsonl`` per format
  is the same number stored twice) and not one file per table (``load_models``
  reads one model per line, and a table is one generated thing with one
  provenance; its rows mean nothing individually). Written only when
  non-empty, so every corpus without a detail recipe is byte-identical to
  what it was.

Reference order is declaration order. synthkit topologically sorts its
collections so referents generate before referrers; here a ``ref`` column may
only point at an *earlier* table — the same "causality points backwards" rule
``EventSpec.caused_by`` enforces — which buys the identical guarantee
(referential closure by construction) without ever silently reordering what
an author wrote.

Determinism: every draw comes from a named ``Rng`` stream
``detail/<table>/<column>`` under the episode's own scenario stream; no clock,
no ``random``, no UUID, no set iteration, and no faker — vocabulary comes from
the vendored pools in ``data/detail_pools.json``.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import factkinds
from . import validate as validate_module

if TYPE_CHECKING:  # pragma: no cover
    from .models import CanonicalFact
    from .rng import Rng

#: A table larger than this is a database, not an export — and a count fact
#: misread as a row source (a money amount, a year) should fail loudly here
#: rather than as an out-of-memory in a renderer.
MAX_ROWS = 100_000

CellValue = str | int | float | None


class Model(BaseModel):
    """Base for every detail model — frozen and closed, like the episode grammar's."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# The recipe: what an author declares
# ---------------------------------------------------------------------------


class ColumnSpec(Model):
    """One column of a detail table, and how its values are generated."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    """The column's key — the field name each row carries."""

    label: str = ""
    """Header text for renderers. Empty means the name."""

    kind: Literal["sequence", "choice", "date_in_period", "from_fact", "ref", "constant"]
    """How values are made.

    - **sequence**: deterministic line ids — ``prefix`` + 1-based index.
    - **choice**: a draw from a named vendored pool (``data/detail_pools.json``).
    - **date_in_period**: a business day inside the episode's own period, on the
      corpus's calendar.
    - **from_fact**: THE RULE — the named fact's value, allocated across the
      rows by largest remainder so the column sums to it exactly.
    - **ref**: a value copied from an earlier table's column, so the tables
      join (a receipt line names the order line it receipts).
    - **constant**: one authored value on every row.
    """

    # -- sequence ------------------------------------------------------------
    prefix: str = ""
    """Line-id prefix, e.g. ``"POL-"``. ``{period}`` interpolates the period."""

    width: int = Field(default=4, ge=1, le=9)
    """Zero-padding for the sequence number."""

    # -- choice --------------------------------------------------------------
    pool: str = ""
    """Name of a pool in ``data/detail_pools.json``. In-repo on purpose: a
    faker call would put a third-party wordlist inside the byte-replay
    boundary, where a vendored, versioned list is data a seed can mean."""

    weighting: Literal["uniform", "zipf"] = "uniform"
    """``zipf`` weights the pool head-heavy (synthkit's enum realism: frequent
    values dominate, the long tail appears occasionally), in pool order."""

    zipf_exponent: float = Field(default=1.0, gt=0.0, le=3.0)

    # -- date_in_period ------------------------------------------------------
    with_time: bool = False
    """When true, a business-hours-weighted timestamp (``YYYY-MM-DDTHH:MM``)
    rather than a bare date — 09:00–17:00 dominates, shoulders are light,
    exactly the bias real system exports show."""

    # -- from_fact -----------------------------------------------------------
    fact_kind: str = ""
    """The declared fact kind this column carries. Must be minted by the
    episode *and* known to the fact-kind registry — an invented kind is
    lint-refused, never generated around."""

    decimals: int = Field(default=2, ge=0, le=6)
    """Allocation precision: 0 for unit counts, 2 for money in the fact's own
    published unit. The column sums to the fact exactly at this precision."""

    spread: Literal["even", "lognormal"] = "even"
    """How the total is shared before the largest-remainder pass. ``even``
    reads as one rate applied N times; ``lognormal`` (synthkit's money shape)
    reads as a mixed basket — a few large lines, many small. Either way the
    weights only shape the split; the *sum* is the fact's, always."""

    sigma: float = Field(default=0.6, gt=0.0, le=2.5)
    """Log-space standard deviation for the ``lognormal`` spread."""

    # -- ref -----------------------------------------------------------------
    table: str = ""
    """The earlier detail table a ``ref`` column reads."""

    column: str = ""
    """The column of that table whose values are referenced."""

    align: bool = True
    """Row *i* references the referent's row *i* — how a receipt that is short
    receipts the order's first N lines and the missing tail *is* the
    shortfall. ``false`` draws a referent per row instead (a fan-out join)."""

    # -- constant ------------------------------------------------------------
    value: CellValue = None


class TableSpec(Model):
    """One detail table a process step declares under the facts it mints."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")

    title: str = ""
    """Sheet/heading title. Empty means the name."""

    artifact_type: str = ""
    """The planned document these rows sit under (a spec ``artifacts`` entry).
    The generated table binds to that intent's id, which is how the workbook
    renderer knows which file gets the sheet. Empty means the rows are corpus
    data only — exported and validated, rendered nowhere."""

    rows: int = Field(default=0, ge=0, le=MAX_ROWS)
    """A literal row count. Exactly one of ``rows`` / ``count_from_fact``."""

    count_from_fact: str = ""
    """A fact kind whose (integer) value *is* the row count — one line per
    ordered unit. The generated count is checked against the fact by the
    ``detail`` validator group, like every other declared relationship."""

    columns: list[ColumnSpec] = Field(min_length=1)

    edge_case_rate: float = Field(default=0.0, ge=0.0, le=0.2)
    """Fraction of rows given a realistic imperfection (synthkit's seeded edge
    injection): a unicode variant or a near-duplicate in a ``choice`` column.
    Sequence, ref and from_fact columns are never touched, so line ids, joins
    and the sum-to-fact rule hold by construction whatever the rate — and
    every injected row is recorded on the table, because an imperfection a
    reader cannot establish mechanically is noise, not texture."""

    note: str = ""


# ---------------------------------------------------------------------------
# The corpus data: what generation produces
# ---------------------------------------------------------------------------


class DetailColumn(Model):
    """One generated column: its header, and the provenance a checker needs."""

    name: str
    label: str
    number_format: str | None = None
    fact_id: str = ""
    """The fact this column was allocated from — the reconciliation edge the
    validator recomputes. Empty for columns the ledger does not state."""
    decimals: int = 2
    ref_table: str = ""
    ref_column: str = ""


class DetailTable(Model):
    """Generated detail rows, as they land in ``detail.jsonl``."""

    id: str
    name: str
    title: str
    episode: str
    period: str
    artifact_id: str = ""
    count_fact_id: str = ""
    columns: list[DetailColumn]
    rows: list[dict[str, CellValue]]
    edge_rows: list[str] = Field(default_factory=list)
    """Injected imperfections, recorded as ``"<row index>:<column>:<kind>"`` —
    labelled, so a reader holding only the corpus can tell texture from
    defect (the messiness pass's own contract)."""
    note: str = ""


# ---------------------------------------------------------------------------
# Pools
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def pools() -> dict[str, tuple[str, ...]]:
    """The vendored vocabulary pools, by name. Cached; the file is data."""
    path = Path(__file__).parent / "data" / "detail_pools.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        name: tuple(values)
        for name, values in raw.items()
        if isinstance(values, list) and not name.startswith("//")
    }


# ---------------------------------------------------------------------------
# The lint
# ---------------------------------------------------------------------------


def lint(
    tables: list[TableSpec],
    *,
    declared_kinds: set[str] | None = None,
    declared_artifacts: set[str] | None = None,
    where: str = "detail",
) -> list[str]:
    """Findings an author should read before building. Same contract as
    ``episodes.lint``: strings naming divergences, nothing raises."""
    findings: list[str] = []
    known_pools = pools()
    seen_tables: list[str] = []

    def check_kind(kind: str, spot: str) -> None:
        # The registry test is the non-negotiable half: a detail recipe naming
        # a kind nothing generates would put rows under a figure that does not
        # exist — the exact invention `factkinds` was built to refuse.
        if factkinds.get(kind) is None:
            findings.append(
                f"{spot}: fact kind {kind!r} is not in the fact-kind registry —"
                " detail rows may only sit under a kind something generates"
                " and something validates."
            )
        elif declared_kinds is not None and kind not in declared_kinds:
            findings.append(
                f"{spot}: fact kind {kind!r} is registry-known but not minted by"
                " this episode — a step's detail may only expand the facts the"
                " step itself declares."
            )

    for t_index, table in enumerate(tables):
        t_where = f"{where}[{t_index}] ({table.name})"

        if table.name in seen_tables:
            findings.append(f"{t_where}: table {table.name!r} is declared twice.")

        has_literal = table.rows > 0
        has_fact = bool(table.count_from_fact)
        if has_literal == has_fact:
            findings.append(
                f"{t_where}: exactly one of `rows` and `count_from_fact` must"
                " decide the row count — both or neither leaves the count"
                " ambiguous."
            )
        if has_fact:
            check_kind(table.count_from_fact, f"{t_where}.count_from_fact")

        if table.artifact_type and declared_artifacts is not None:
            if table.artifact_type not in declared_artifacts:
                findings.append(
                    f"{t_where}: artifact_type {table.artifact_type!r} is not an"
                    " artifact this episode plans — the sheet would have no"
                    " document to land in."
                )

        seen_columns: set[str] = set()
        for c_index, column in enumerate(table.columns):
            c_where = f"{t_where}.columns[{c_index}] ({column.name})"
            if column.name in seen_columns:
                findings.append(f"{c_where}: column {column.name!r} is declared twice.")
            seen_columns.add(column.name)

            if column.kind == "choice":
                if not column.pool:
                    findings.append(f"{c_where}: a choice column needs a `pool`.")
                elif column.pool not in known_pools:
                    findings.append(
                        f"{c_where}: pool {column.pool!r} is not a vendored pool."
                        f" Pools: {', '.join(sorted(known_pools))}."
                    )
            elif column.kind == "from_fact":
                if not column.fact_kind:
                    findings.append(f"{c_where}: a from_fact column needs a `fact_kind`.")
                else:
                    check_kind(column.fact_kind, c_where)
            elif column.kind == "ref":
                if not column.table or not column.column:
                    findings.append(f"{c_where}: a ref column needs `table` and `column`.")
                elif column.table not in seen_tables:
                    # Backwards only — same rule as `EventSpec.caused_by`. This
                    # is what makes the output referentially closed by
                    # construction without a topological sort: the referent
                    # exists, whole, before the first referring row is made.
                    findings.append(
                        f"{c_where}: ref table {column.table!r} is not declared"
                        " *earlier* in this recipe — references may only point"
                        " backwards, so referents exist before referrers."
                    )
                else:
                    target = next(t for t in tables if t.name == column.table)
                    if column.column not in {c.name for c in target.columns}:
                        findings.append(
                            f"{c_where}: ref column {column.column!r} is not a"
                            f" column of table {column.table!r}."
                        )
            elif column.kind == "constant":
                if column.value is None:
                    findings.append(f"{c_where}: a constant column needs a `value`.")

        if table.edge_case_rate > 0 and not any(c.kind == "choice" for c in table.columns):
            findings.append(
                f"{t_where}: edge_case_rate is set but no column can carry an"
                " edge case — only choice columns take one (sequence, ref and"
                " from_fact columns are protected by construction)."
            )

        seen_tables.append(table.name)

    return findings


# ---------------------------------------------------------------------------
# Distribution shapes (synthkit's realism tier, inside the Rng discipline)
# ---------------------------------------------------------------------------


def _normal(rng: Rng) -> float:
    """Box–Muller from two uniform draws on the given stream."""
    u1 = 1.0 - rng.number(0.0, 1.0)  # (0, 1] so log() is finite
    u2 = rng.number(0.0, 1.0)
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def _lognormal_weights(rng: Rng, count: int, sigma: float) -> list[float]:
    """Head-and-tail weights for a mixed basket. Only ever *weights*: the
    largest-remainder pass spends them against the fact's total, so the shape
    is synthkit's and the sum is the ledger's."""
    return [math.exp(sigma * _normal(rng)) for _ in range(count)]


def _zipf_weights(count: int, exponent: float) -> list[float]:
    return [1.0 / (rank ** exponent) for rank in range(1, count + 1)]


#: Business-hours bias for `with_time` dates — 9–17 dominate, shoulders are
#: light, night is rare (synthkit's HOUR_WEIGHTS, trimmed to working hours).
_HOURS = list(range(7, 20))
_HOUR_WEIGHTS = [3.0, 3.0] + [10.0] * 9 + [3.0, 3.0]


def allocate_scaled(total: float, weights: list[float], *, decimals: int) -> list[float]:
    """*total* split across *weights*, summing back exactly at *decimals*.

    ``finance.allocate``'s largest-remainder split (the ``rollup`` primitive)
    lifted from whole units to fixed-point: scale to integer 10^-decimals
    units, allocate, scale back. Exactness is integer arithmetic's, not
    floating point's — which is why the validator recompares in scaled ints.
    """
    from .generators.finance import allocate

    scale = 10 ** decimals
    units = int(round(total * scale))
    if units < 0:
        raise ValueError(f"cannot allocate a negative total ({total})")
    parts = allocate(units, weights)
    if decimals == 0:
        return [float(part) for part in parts]
    return [part / scale for part in parts]


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _current_fact(facts: tuple, kind: str) -> CanonicalFact:
    """The episode's current fact of *kind* — the last mint nothing in the
    same episode supersedes. Detail sits under the record as it stands, never
    under a belief the episode itself has already ruled out."""
    superseded = {f.supersedes for f in facts if f.supersedes}
    candidates = [f for f in facts if f.kind == kind and f.id not in superseded]
    if not candidates:
        raise ValueError(
            f"detail table needs a {kind!r} fact and this episode minted none —"
            " the lint names the kinds a step actually declares"
        )
    return candidates[-1]


def _numeric(fact: CanonicalFact, *, what: str) -> float:
    if fact.value is None:
        raise ValueError(f"{what}: fact {fact.id} ({fact.kind}) carries no amount")
    return fact.value.amount


def _row_count(table: TableSpec, facts: tuple) -> tuple[int, str]:
    if table.count_from_fact:
        fact = _current_fact(facts, table.count_from_fact)
        amount = _numeric(fact, what=f"{table.name}.count_from_fact")
        if amount != int(amount) or amount < 0:
            raise ValueError(
                f"{table.name}: count_from_fact {table.count_from_fact!r} is"
                f" {amount}, not a row count — a money figure cannot number lines"
            )
        count = int(amount)
        if count > MAX_ROWS:
            raise ValueError(f"{table.name}: {count} rows exceeds MAX_ROWS ({MAX_ROWS})")
        return count, fact.id
    return table.rows, ""


def _business_days(period: str, cadence: str, calendar) -> list:
    """Every business day inside the episode's own period, on the corpus's
    calendar — the same window `anchor="prior_period_end"` events land in."""
    from datetime import timedelta

    from .generators.finance import previous_periods
    from .generators.operations import period_end

    step = {"month": 1, "quarter": 3, "year": 12}[cadence]
    start = period_end(previous_periods(period, step)[0]) + timedelta(days=1)
    end = period_end(period)
    days = []
    day = start
    while day <= end:
        if calendar.is_business_day(day):
            days.append(day)
        day += timedelta(days=1)
    return days


_FORMATS = {0: "#,##0", 2: "#,##0.00"}


def generate(
    tables: list[TableSpec],
    *,
    episode: str,
    period: str,
    cadence: str,
    facts: tuple,
    intents: tuple,
    rng: Rng,
    minter,
    calendar,
) -> tuple[DetailTable, ...]:
    """Materialise every declared table into rows, in declaration order.

    *rng* is the episode's own ``detail`` stream; each column draws on
    ``<table>/<column>`` under it, so adding a column can never reshuffle a
    neighbour's values — the stream-per-name rule every generator here keeps.
    """
    made: list[DetailTable] = []
    by_name: dict[str, DetailTable] = {}
    intent_of = {}
    for intent in intents:
        intent_of.setdefault(intent.artifact_type, intent.id)

    for table in tables:
        count, count_fact_id = _row_count(table, facts)
        artifact_id = ""
        if table.artifact_type:
            artifact_id = intent_of.get(table.artifact_type, "")
            if not artifact_id:
                raise ValueError(
                    f"{table.name}: artifact_type {table.artifact_type!r} matches"
                    " no planned intent of this episode"
                )

        columns: list[DetailColumn] = []
        values_by_column: dict[str, list[CellValue]] = {}
        for column in table.columns:
            stream = rng.derive(f"{table.name}/{column.name}")
            fact_id = ""
            number_format: str | None = None
            ref_table = ref_column = ""

            if column.kind == "sequence":
                prefix = column.prefix.replace("{period}", period)
                values: list[CellValue] = [
                    f"{prefix}{index + 1:0{column.width}d}" for index in range(count)
                ]
            elif column.kind == "choice":
                options = pools()[column.pool]
                if column.weighting == "zipf":
                    weights = _zipf_weights(len(options), column.zipf_exponent)
                    values = [stream.weighted(options, weights) for _ in range(count)]
                else:
                    values = [stream.choice(options) for _ in range(count)]
            elif column.kind == "date_in_period":
                days = _business_days(period, cadence, calendar)
                values = []
                for _ in range(count):
                    day = stream.choice(days)
                    if column.with_time:
                        hour = stream.weighted(_HOURS, _HOUR_WEIGHTS)
                        minute = stream.integer(0, 59)
                        values.append(f"{day.isoformat()}T{hour:02d}:{minute:02d}")
                    else:
                        values.append(day.isoformat())
            elif column.kind == "from_fact":
                fact = _current_fact(facts, column.fact_kind)
                total = _numeric(fact, what=f"{table.name}.{column.name}")
                if column.spread == "lognormal":
                    weights = _lognormal_weights(stream, count, column.sigma)
                else:
                    weights = [1.0] * count
                allocated = allocate_scaled(total, weights, decimals=column.decimals)
                values = (
                    [int(v) for v in allocated] if column.decimals == 0
                    else list(allocated)
                )
                fact_id = fact.id
                number_format = _FORMATS.get(column.decimals, "#,##0.00")
            elif column.kind == "ref":
                referent = by_name[column.table]
                pool = [row[column.column] for row in referent.rows]
                if column.align:
                    if count > len(pool):
                        raise ValueError(
                            f"{table.name}.{column.name}: {count} rows cannot align"
                            f" to {len(pool)} rows of {column.table!r} — an aligned"
                            " ref may be short (that shortfall is the point), never long"
                        )
                    values = list(pool[:count])
                else:
                    values = [stream.choice(pool) for _ in range(count)]
                ref_table, ref_column = column.table, column.column
            elif column.kind == "constant":
                values = [column.value] * count
            else:  # pragma: no cover — the Literal closes this
                raise ValueError(f"unknown column kind {column.kind!r}")

            values_by_column[column.name] = values
            columns.append(DetailColumn(
                name=column.name,
                label=column.label or column.name,
                number_format=number_format,
                fact_id=fact_id,
                decimals=column.decimals,
                ref_table=ref_table,
                ref_column=ref_column,
            ))

        rows = [
            {column.name: values_by_column[column.name][index] for column in table.columns}
            for index in range(count)
        ]

        # -- edge injection, last, on choice columns only ------------------
        # synthkit's own rule kept exactly: keys and FKs are never touched, so
        # closure and the sum-to-fact rule hold whatever the rate; and every
        # injected row is recorded, because the corpus's contract is that a
        # reader can establish mechanically which mess is deliberate.
        edge_rows: list[str] = []
        if table.edge_case_rate > 0:
            eligible = [c.name for c in table.columns if c.kind == "choice"]
            unicode_pool = pools().get("edge_unicode", ())
            edge = rng.derive(f"{table.name}/edge")
            for index, row in enumerate(rows):
                if not edge.chance(table.edge_case_rate):
                    continue
                target = edge.choice(eligible)
                if index > 0 and edge.chance(0.5):
                    row[target] = str(rows[0][target]).replace(" ", "  ", 1)
                    edge_rows.append(f"{index}:{target}:near_duplicate")
                elif unicode_pool:
                    row[target] = edge.choice(unicode_pool)
                    edge_rows.append(f"{index}:{target}:unicode_variant")

        built = DetailTable(
            id=minter.next("DET"),
            name=table.name,
            title=table.title or table.name,
            episode=episode,
            period=period,
            artifact_id=artifact_id,
            count_fact_id=count_fact_id,
            columns=columns,
            rows=rows,
            edge_rows=edge_rows,
            note=table.note,
        )
        made.append(built)
        by_name[table.name] = built

    return tuple(made)


# ---------------------------------------------------------------------------
# The checks: the rule, enforced as well as constructed
# ---------------------------------------------------------------------------


def _checks(world) -> tuple[list, int]:
    """The ``detail`` validator group.

    Generation *constructs* the sums; this recomputes them from the corpus on
    disk, because the corpus outlives the process that built it and a loaded
    ``detail.jsonl`` that no longer agrees with ``facts.jsonl`` is exactly the
    drifted copy the rule forbids. Integer comparison in scaled units — the
    same arithmetic ``allocate_scaled`` used — so float accumulation over a
    thousand rows cannot manufacture a spurious cent either way.
    """
    from .validate import Violation

    violations: list[Violation] = []
    checks = 0
    tables = getattr(world, "_detail_tables", ())
    if not tables:
        return violations, checks

    def fail(code: str, subject: str, detail: str) -> None:
        violations.append(Violation(group="detail", code=code, subject=subject, detail=detail))

    facts_by_id = {f.id: f for f in world.facts}
    by_name_period = {(t.name, t.period): t for t in tables}

    for table in tables:
        if table.count_fact_id:
            checks += 1
            fact = facts_by_id.get(table.count_fact_id)
            if fact is None or fact.value is None:
                fail("count_fact_missing", table.id,
                     f"count fact {table.count_fact_id} does not resolve to an amount")
            elif int(fact.value.amount) != len(table.rows):
                fail("count_disagrees", table.id,
                     f"{len(table.rows)} rows against a declared count of"
                     f" {fact.value.amount:,.0f} ({fact.kind})")

        for column in table.columns:
            if column.fact_id:
                checks += 1
                fact = facts_by_id.get(column.fact_id)
                if fact is None or fact.value is None:
                    fail("fact_missing", f"{table.id}/{column.name}",
                         f"allocated from {column.fact_id}, which does not resolve")
                    continue
                scale = 10 ** column.decimals
                summed = sum(
                    int(round(float(row[column.name]) * scale)) for row in table.rows
                )
                declared = int(round(fact.value.amount * scale))
                if summed != declared:
                    fail("rows_do_not_sum", f"{table.id}/{column.name}",
                         f"rows sum to {summed / scale:,.{column.decimals}f} against"
                         f" {fact.value.amount:,.2f} declared by {fact.id}"
                         f" ({fact.kind})")

            if column.ref_table:
                checks += 1
                referent = by_name_period.get((column.ref_table, table.period))
                if referent is None:
                    fail("ref_table_missing", f"{table.id}/{column.name}",
                         f"references table {column.ref_table!r}, absent for"
                         f" period {table.period}")
                    continue
                known = {row[column.ref_column] for row in referent.rows}
                dangling = [
                    row[column.name] for row in table.rows
                    if row[column.name] not in known
                ]
                if dangling:
                    fail("ref_dangles", f"{table.id}/{column.name}",
                         f"{len(dangling)} values resolve to no {column.ref_column!r}"
                         f" in {column.ref_table!r} (first: {dangling[0]!r})")

        for entry in table.edge_rows:
            checks += 1
            index_text, _, rest = entry.partition(":")
            column_name = rest.partition(":")[0]
            if not index_text.isdigit() or int(index_text) >= len(table.rows):
                fail("edge_row_unlabelled", table.id,
                     f"edge record {entry!r} names no row of this table")
            elif column_name not in {c.name for c in table.columns}:
                fail("edge_row_unlabelled", table.id,
                     f"edge record {entry!r} names no column of this table")

    return violations, checks


validate_module.register_domain_checks("detail", _checks)


__all__ = [
    "MAX_ROWS",
    "ColumnSpec",
    "TableSpec",
    "DetailColumn",
    "DetailTable",
    "allocate_scaled",
    "generate",
    "lint",
    "pools",
]
