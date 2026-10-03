"""Paired legacy/grammar planning: one identity set, two arms, one key.

Planning with ``dag_shapes`` expands every candidate row into each compatible
shape and drops the rows no shape admits, *before* the limit. A legacy
population and a grammar population of the same size therefore hold different
underlying requests, and comparing their grade counts compares two samples,
not two treatments of one sample. That was the stated caveat on the 400-row
measurement in ``docs/enterprise-execution-status.md``.

Here the limit selects base identities first: the first ``limit`` rows of the
same fair exhaustive stream the legacy arm already walks, so the legacy arm is
exactly the default legacy population at that limit. Each identity then gets
one grammar variant, built the way the default grammar expansion builds the
same (row, shape) pair, so the grammar arm's queries are members of the
default grammar universe rather than a lookalike. An identity no requested
shape admits is kept as a planning refusal in the grammar arm, never dropped:
dropping it is how the unpaired populations came to differ.

Opt-in only. Nothing here runs unless called, and ``plan_queries`` output is
untouched; the pairing key is added to ``dimensions`` after each query's id is
minted, so it changes no query identity.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from .enterprise_dag_planning import apply_dag_shape, compatible_shapes
from .enterprise_grounding import groundable_inventory
from .enterprise_queries import PlannedEnterpriseQuery, _plan, plan_queries
from .enterprise_specs import CoverageProfile, SpecRegistry, builtin_registry
from .ids import content_key
from .models import Model

if TYPE_CHECKING:
    from .connector_data import ConnectorProjectionRegistry
    from .world import World

#: The dimension both arms carry. Its value is the legacy query id: the id
#: ``_plan`` mints from the base row and its contract, which is the identity
#: the two arms share and the one a reader can look up in a legacy export.
PAIR_DIMENSION = "pair_key"

Arm = Literal["legacy", "grammar"]
ARMS: tuple[Arm, ...] = ("legacy", "grammar")

#: Pair categories, in report order. A refusal in either arm is its own
#: category: folding it into ``neither_ok`` would hide which arm could not
#: even attempt the request, and dropping it would re-create the unpaired
#: denominators this module exists to remove.
PAIR_CATEGORIES = (
    "both_ok", "legacy_only_ok", "grammar_only_ok", "neither_ok",
    "refused_legacy", "refused_grammar", "refused_both",
)


class QueryPair(Model):
    """One base identity and its two arms.

    ``grammar`` is ``None`` exactly when ``grammar_refusal`` names why no
    requested shape could be planned for this identity.
    """

    key: str
    legacy: PlannedEnterpriseQuery
    grammar: PlannedEnterpriseQuery | None = None
    grammar_shape: str | None = None
    grammar_refusal: str | None = None


def _keyed(query: PlannedEnterpriseQuery, key: str) -> PlannedEnterpriseQuery:
    return query.model_copy(update={"dimensions": {**query.dimensions, PAIR_DIMENSION: key}})


def _choose(key: str, shapes: tuple[str, ...]) -> str:
    # One variant per identity keeps the arms the same size. The choice is
    # keyed on the pair, not on position, so a shorter limit selects the same
    # shape for every identity it keeps; taking the first compatible shape
    # instead would have put nearly every pair on ``conditional``.
    return shapes[int(content_key("enterprise-pair-shape", key)[:8], 16) % len(shapes)]


def plan_paired_queries(
    world: World,
    *,
    limit: int,
    dag_shapes: tuple[str, ...] = ("*",),
    registry: SpecRegistry | None = None,
    profile: CoverageProfile | None = None,
    projections: ConnectorProjectionRegistry | None = None,
) -> tuple[QueryPair, ...]:
    """Plan ``limit`` base identities and both arms of each.

    Exhaustive strategy only: a covering walk selects rows by the
    interactions they add, and the grammar's ``dag_shape`` dimension changes
    which rows those are, so there is no single covering identity set for both
    arms to share.
    """
    if limit < 1:
        raise ValueError("paired planning needs a positive limit")
    if not dag_shapes:
        raise ValueError("paired planning needs at least one DAG shape for the grammar arm")
    registry = registry or builtin_registry()
    profile = profile or CoverageProfile()
    legacy, _ = plan_queries(
        world, registry=registry, profile=profile, strategy="exhaustive",
        limit=limit, projections=projections,
    )
    inventory = groundable_inventory(world, registry, projections=projections)
    pairs: list[QueryPair] = []
    for query in legacy:
        key = query.id
        row = dict(query.dimensions)
        shapes = compatible_shapes(row, dag_shapes, inventory=inventory)
        if not shapes:
            if not compatible_shapes(row, dag_shapes):
                refusal = f"no requested DAG shape admits failure={row.get('failure', 'none')!r} on this row"
            else:
                refusal = "no admissible DAG shape grounds in this world's source inventory"
            pairs.append(QueryPair(key=key, legacy=_keyed(query, key), grammar_refusal=refusal))
            continue
        shape = _choose(key, shapes)
        # Built exactly as ``plan_queries(dag_shapes=...)`` builds this row
        # and shape, so the grammar arm is a subset of the default grammar
        # universe and its rows grade as that population's rows would.
        variant = apply_dag_shape(_plan(world, {**row, "dag_shape": shape}, registry), shape)
        pairs.append(QueryPair(
            key=key, legacy=_keyed(query, key), grammar=_keyed(variant, key), grammar_shape=shape,
        ))
    return tuple(pairs)


def arm_queries(pairs: Iterable[QueryPair], arm: Arm) -> tuple[PlannedEnterpriseQuery, ...]:
    """The planned queries of one arm, in pair order; refused pairs contribute none."""
    if arm == "legacy":
        return tuple(pair.legacy for pair in pairs)
    return tuple(pair.grammar for pair in pairs if pair.grammar is not None)


@dataclass(frozen=True)
class ArmOutcome:
    """What one arm did with one pair.

    ``status`` is the existing grade status (``ok``, ``behavior``, ``fail``)
    or ``refused``; a refusal names its ``stage`` (``plan``, ``compile`` or
    ``runtime``) and the reason the stage gave.
    """

    status: str
    stage: str | None = None
    reason: str | None = None

    @property
    def refused(self) -> bool:
        return self.status == "refused"


def _category(legacy: ArmOutcome, grammar: ArmOutcome) -> str:
    if legacy.refused and grammar.refused:
        return "refused_both"
    if legacy.refused:
        return "refused_legacy"
    if grammar.refused:
        return "refused_grammar"
    return {
        (True, True): "both_ok", (True, False): "legacy_only_ok",
        (False, True): "grammar_only_ok", (False, False): "neither_ok",
    }[(legacy.status == "ok", grammar.status == "ok")]


def pair_outcomes(
    pairs: Iterable[QueryPair],
    legacy: Mapping[str, ArmOutcome],
    grammar: Mapping[str, ArmOutcome],
) -> dict[str, Any]:
    """Cross the two arms' per-query outcomes into the paired table.

    ``legacy`` and ``grammar`` map each arm's *query id* to its outcome, as
    the grading of that arm reported it. A pair whose grammar arm was refused
    at planning has no grammar query and is read from the pair itself. A
    query with no reported outcome is an error, not a silent refusal: the
    caller lost a row, and the table would otherwise absorb it.
    """
    categories: Counter[str] = Counter({name: 0 for name in PAIR_CATEGORIES})
    by_shape: dict[str, Counter[str]] = {}
    refusals: Counter[str] = Counter()
    crosstab: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    for pair in pairs:
        left = legacy[pair.legacy.id]
        if pair.grammar is None:
            right = ArmOutcome("refused", "plan", pair.grammar_refusal)
        else:
            right = grammar[pair.grammar.id]
        category = _category(left, right)
        categories[category] += 1
        # The categories answer "which arm succeeded"; the cross-tab keeps
        # what each arm actually graded, because ``neither_ok`` lumps a
        # designed failure both arms reported (``behavior``) with a wrong
        # answer (``fail``), and a refusal hides the other arm's grade.
        crosstab[f"legacy={left.status} grammar={right.status}"] += 1
        by_shape.setdefault(pair.grammar_shape or "(none)", Counter())[category] += 1
        for arm, outcome in (("legacy", left), ("grammar", right)):
            if outcome.refused:
                refusals[f"{arm}/{outcome.stage}: {outcome.reason}"] += 1
        rows.append({
            PAIR_DIMENSION: pair.key, "category": category,
            "grammar_shape": pair.grammar_shape,
            "legacy": {"query_id": pair.legacy.id, "status": left.status, "stage": left.stage, "reason": left.reason},
            "grammar": {"query_id": pair.grammar.id if pair.grammar else None, "status": right.status,
                        "stage": right.stage, "reason": right.reason},
        })
    return {
        "pairs": len(rows),
        "categories": {name: categories[name] for name in PAIR_CATEGORIES},
        "status_crosstab": dict(sorted(crosstab.items())),
        "by_grammar_shape": {shape: {name: counts[name] for name in PAIR_CATEGORIES if counts[name]}
                             for shape, counts in sorted(by_shape.items())},
        "refusal_reasons": dict(sorted(refusals.items(), key=lambda item: (-item[1], item[0]))),
        "rows": rows,
    }


__all__ = [
    "ARMS", "PAIR_CATEGORIES", "PAIR_DIMENSION", "Arm", "ArmOutcome", "QueryPair",
    "arm_queries", "pair_outcomes", "plan_paired_queries",
]
