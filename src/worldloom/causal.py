"""Causal models: how one thing in a company makes another thing happen, declared.

The gap this closes is a specific one. Every imperfection a Worldloom corpus
carries is *labelled* — ``intentional-errors.jsonl`` names the stale page and
the figure it should have carried — and ``messiness.py`` made how much of it
there is a named, graded dimension. What neither can say is **why**. A
``lived_in`` profile asks for two stale pages and three orphaned documents and
gets them wherever the world can support them; nothing connects the stale page
to the ERP migration that made the team too busy to reconcile it, because
nothing in the model *has* an ERP migration that makes teams busy.

That connection is most of what makes messy data hard for an agent. Sprinkled
nulls test a parser. A cascade — a migration raises manual handling, manual
handling raises coding errors, coding errors delay payments, delayed payments
draw a supplier escalation, the escalation becomes a memo, the memo becomes a
board question — tests whether the agent can trace an effect to its cause
through five documents that never mention each other. The idea is mirrorGen's
(generate from a correlation DAG, and let bias and dirt propagate along it);
the implementation is this project's.

The grammar, and why it is closed
---------------------------------

A model is a DAG of named **nodes**. An *exogenous* node draws its value each
period from a ``parameters.py`` span, or holds a constant. A *derived* node is
a **linear** function of its parents — an intercept plus one weight per parent,
clamped to a declared range and rounded to declared places. **Interventions**
set a node to a value from a period onward, with a reason: the ``do()``
operator, and the way an author says "the ERP migration happened in April".
**Drives** connect a node to an imperfection kind: the node's value, scaled,
is that kind's budget — so a corpus's staleness is a *consequence* the model
computed, not a number an author typed.

Linear only, and that is the ``episodes.FactKindSpec.derive`` argument
applied here: a derivation the validator cannot recompute is a figure nothing
checks. Every derived value in a trace is recomputed by the ``causal``
validator group from its recorded parents, and a trace that drifted from its
own model is refused. A free-form ``function: "0.18 - 0.12 * q"`` string would
buy an author expressiveness at the cost of that guarantee; ``weights`` buys
the same function without the parser, the ``eval``, or the hole.

What is recorded, and where
---------------------------

The whole trace — the model, every period's node values, which interventions
applied when, the budgets derived and what was delivered against them — is
carried on the corpus as ``causal.jsonl``, written only when a model ran.
Each intervention mints an ``EnterpriseEvent`` so the world's own timeline
says the migration happened, and the ``Causal`` recipe verb replays the model
under the recorded physics. The imperfections themselves ride the existing
machinery (``generators/distractors.apply_messiness``), so a causally-driven
stale page is establishable from the corpus by exactly the audit trail
``messiness.py`` promises — and additionally traceable to the node that sized
its budget.

**Byte-identity.** No world without a model is touched: no file, no event, no
recipe key. A world with one records exactly the model it was given, and the
exogenous draws come from streams named ``causal/<model>/<node>/<period>`` so
adding a node never moves another's values.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import Field

from . import messiness as messiness_module
from .models import Model as ThinWaistModel
from .parameters import DEFAULT as DEFAULT_PHYSICS
from .parameters import Parameters
from .rng import Rng

if TYPE_CHECKING:  # pragma: no cover
    from .world import World

_PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class Model(ThinWaistModel):
    """The thin waist's model — frozen and closed — so a trace is a corpus
    record like any other and ``World.causal`` is a ``Collection`` of them."""


# ---------------------------------------------------------------------------
# The grammar
# ---------------------------------------------------------------------------


class NodeSpec(Model):
    """One quantity in the model, and how it comes to have a value."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    about: str = ""

    # -- exogenous: exactly one of these ------------------------------------
    parameter: str = ""
    """A ``parameters.py`` span the node draws from each period. The lint
    refuses a name the physics registry does not carry."""

    level: float | None = None
    """A constant. For a quantity the author is asserting rather than drawing."""

    # -- derived: parents and the linear rule --------------------------------
    depends_on: list[str] = Field(default_factory=list)
    intercept: float = 0.0
    weights: dict[str, float] = Field(default_factory=dict)
    """One coefficient per parent, keyed by parent name. Must key exactly
    ``depends_on`` — a parent with no weight or a weight with no parent is a
    model that says two different things about its own structure."""

    low: float | None = None
    high: float | None = None
    """Clamp. A rate cannot go negative and a share cannot exceed one; the
    clamp is where that is said, and the validator recomputes through it."""

    places: int = Field(default=4, ge=0, le=8)

    @property
    def derived(self) -> bool:
        return bool(self.depends_on)


class InterventionSpec(Model):
    """``do(node := value)`` from *at* onward, and why."""

    at: str = Field(pattern=_PERIOD.pattern)
    node: str
    value: float
    reason: str = Field(min_length=1)
    """Becomes the event summary. Required, because an intervention without a
    stated cause is exactly the unexplained mess this module exists to replace."""


class DriveSpec(Model):
    """A node's value, scaled, is an imperfection kind's budget."""

    node: str
    imperfection: str
    """One of ``messiness.KINDS``."""

    scale: float = Field(gt=0.0)
    """Budget per period = ``round(value × scale)``. A rate of 0.12 at scale 25
    is three stale pages a period; the same rate after an intervention that
    doubles it is six."""


class CausalModel(Model):
    """The declaration an author writes."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    about: str = ""
    source: str = ""
    """Where the structure came from, when it came from somewhere. Same
    boundary as ``parameters.Span.source``: a sector study of what drives
    invoice errors is a prior; a named company's audit findings are not."""

    nodes: list[NodeSpec] = Field(min_length=1)
    interventions: list[InterventionSpec] = Field(default_factory=list)
    drives: list[DriveSpec] = Field(default_factory=list)

    def node(self, name: str) -> NodeSpec:
        for spec in self.nodes:
            if spec.name == name:
                return spec
        raise KeyError(name)


def from_document(payload: Mapping[str, Any] | CausalModel) -> CausalModel:
    if isinstance(payload, CausalModel):
        return payload
    return CausalModel.model_validate(payload)


# ---------------------------------------------------------------------------
# Lint: what an author reads before building
# ---------------------------------------------------------------------------


def order(model: CausalModel) -> list[str]:
    """Node names in an evaluation order, or a ``ValueError`` naming the cycle.

    Kahn's algorithm with a *sorted* frontier, so the order is a function of
    the model and not of dict iteration — a trace's node order is part of its
    bytes.
    """
    parents = {spec.name: set(spec.depends_on) for spec in model.nodes}
    remaining = dict(parents)
    out: list[str] = []
    while remaining:
        ready = sorted(name for name, deps in remaining.items() if not deps - set(out))
        if not ready:
            raise ValueError(f"cycle among {sorted(remaining)}")
        for name in ready:
            out.append(name)
            del remaining[name]
    return out


def lint(model: CausalModel, *, physics: Parameters = DEFAULT_PHYSICS) -> list[str]:
    """Findings, as strings. Nothing raises; an empty list is a clean model.

    Same contract as ``episodes.lint`` and ``doctypes.lint``: every divergence
    between what was authored and what the engine would do, named.
    """
    findings: list[str] = []
    names = [spec.name for spec in model.nodes]
    seen: set[str] = set()
    for name in names:
        if name in seen:
            findings.append(f"node {name!r} is declared twice")
        seen.add(name)

    for spec in model.nodes:
        sources = [bool(spec.parameter), spec.level is not None, spec.derived]
        if sum(sources) != 1:
            findings.append(
                f"node {spec.name!r} must have exactly one of parameter, level,"
                f" or depends_on; it has {sum(sources)}"
            )
        if spec.parameter and spec.parameter not in physics.spans:
            findings.append(
                f"node {spec.name!r} draws from {spec.parameter!r}, which the"
                " physics registry does not carry (`worldloom pack params`)"
            )
        if spec.parameter and spec.parameter in physics.spans and physics.spans[spec.parameter].kind == "chance":
            findings.append(
                f"node {spec.name!r} draws from {spec.parameter!r}, a chance —"
                " a probability is not a level; give it a `level` instead"
            )
        for parent in spec.depends_on:
            if parent not in seen:
                findings.append(f"node {spec.name!r} depends on {parent!r}, which is not declared")
            if parent == spec.name:
                findings.append(f"node {spec.name!r} depends on itself")
        if spec.derived and set(spec.weights) != set(spec.depends_on):
            findings.append(
                f"node {spec.name!r}: weights key {sorted(spec.weights)} but"
                f" depends_on is {sorted(spec.depends_on)}"
            )
        if not spec.derived and (spec.weights or spec.intercept):
            findings.append(f"node {spec.name!r} has weights or an intercept but no parents")
        if spec.low is not None and spec.high is not None and spec.low > spec.high:
            findings.append(f"node {spec.name!r}: clamp [{spec.low}, {spec.high}] is inverted")

    try:
        order(model)
    except ValueError as exc:
        findings.append(f"the model is not a DAG: {exc}")

    for index, intervention in enumerate(model.interventions):
        if intervention.node not in seen:
            findings.append(f"intervention {index} sets {intervention.node!r}, which is not declared")

    by_name = {spec.name: spec for spec in model.nodes}
    for index, drive in enumerate(model.drives):
        if drive.node not in seen:
            findings.append(f"drive {index} reads {drive.node!r}, which is not declared")
        elif by_name[drive.node].low is None or by_name[drive.node].low < 0:  # type: ignore[operator]
            # A budget is a count, and `Messiness` refuses a negative one — at
            # build time, after `causal check` had passed the model. The floor
            # is what makes the budget's sign a property of the declaration
            # rather than of the draw (Codex review, PR #40).
            findings.append(
                f"drive {index} budgets from {drive.node!r}, which declares no"
                " non-negative `low`; a budget is a count, so the node must say it"
                " cannot go below zero"
            )
        if drive.imperfection not in messiness_module.KINDS:
            findings.append(
                f"drive {index} budgets {drive.imperfection!r}; imperfection kinds are"
                f" {list(messiness_module.KINDS)}"
            )
    counted: dict[str, int] = {}
    for drive in model.drives:
        counted[drive.imperfection] = counted.get(drive.imperfection, 0) + 1
    for kind, count in sorted(counted.items()):
        if count > 1:
            findings.append(
                f"{count} drives budget {kind!r}; one node decides one kind, or the"
                " budget is the sum of two claims nobody stated"
            )
    return findings


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


class PeriodValues(Model):
    """Every node's value in one period, and the interventions in force."""

    period: str
    values: dict[str, float]
    interventions: list[int] = Field(default_factory=list)
    """Indexes into the model's ``interventions`` that were in force — applied
    this period or persisting from an earlier one."""

    budgets: dict[str, int] = Field(default_factory=dict)
    """This period's contribution to each driven imperfection kind."""


class CausalTrace(Model):
    """What one model did to one world. Carried on the corpus as ``causal.jsonl``."""

    id: str
    model: CausalModel
    periods: list[PeriodValues]
    budgets: dict[str, int]
    """Total budget per imperfection kind — the sum over periods."""

    delivered: dict[str, int]
    """What the imperfection pass actually delivered against each budget.
    "Budget, not quota" is that pass's contract, so this may be less; it may
    never be more, and the validator holds it to that."""

    event_ids: list[str]
    """One event per intervention, in the model's order."""


def _clamp(value: float, low: float | None, high: float | None) -> float:
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return value


def evaluate(
    model: CausalModel,
    periods: Sequence[str],
    *,
    physics: Parameters = DEFAULT_PHYSICS,
    rng: Rng,
) -> list[PeriodValues]:
    """Node values for each period, in the model's evaluation order.

    Interventions persist: a value set in April holds in May unless another
    intervention resets it. That is what ``do()`` means for a standing
    condition — a migration does not un-happen when the month ends — and the
    alternative (a one-period spike) is expressible by a second intervention
    restoring the level.
    """
    findings = lint(model, physics=physics)
    if findings:
        raise ValueError("causal model has lint findings: " + "; ".join(findings))
    sequence = order(model)
    forced: dict[str, tuple[int, float]] = {}
    out: list[PeriodValues] = []
    for period in periods:
        for index, intervention in enumerate(model.interventions):
            if intervention.at == period:
                forced[intervention.node] = (index, intervention.value)
        values: dict[str, float] = {}
        for name in sequence:
            spec = model.node(name)
            if name in forced:
                value = forced[name][1]
            elif spec.derived:
                value = spec.intercept + sum(
                    spec.weights[parent] * values[parent] for parent in spec.depends_on
                )
            elif spec.parameter:
                stream = rng.derive(f"{model.name}/{name}/{period}")
                value = float(physics.number(spec.parameter, stream))
            else:
                value = float(spec.level)  # type: ignore[arg-type]
            values[name] = round(_clamp(value, spec.low, spec.high), spec.places)
        budgets = {
            drive.imperfection: round(values[drive.node] * drive.scale)
            for drive in model.drives
        }
        out.append(PeriodValues(
            period=period, values=values,
            interventions=sorted(index for index, _ in forced.values()),
            budgets=budgets,
        ))
    return out


def recompute(spec: NodeSpec, values: Mapping[str, float]) -> float:
    """A derived node from its recorded parents — the validator's half of the
    arithmetic, shared with ``evaluate`` so the two cannot disagree."""
    value = spec.intercept + sum(spec.weights[parent] * values[parent] for parent in spec.depends_on)
    return round(_clamp(value, spec.low, spec.high), spec.places)


# ---------------------------------------------------------------------------
# The recipe verb
# ---------------------------------------------------------------------------


def _period_start(period: str) -> datetime:
    year, month = (int(part) for part in period.split("-"))
    return datetime(year, month, 1, 9, 0, tzinfo=UTC)


def periods_of(world: World) -> list[str]:
    """The periods a world has facts in, oldest first — the model's time axis."""
    found = sorted({fact.period for fact in world.facts if fact.period})
    if found:
        return found
    if world.period:
        return [world.period]
    raise ValueError("this world has no periods for a causal model to run over")


@dataclass(frozen=True)
class Causal:
    """Run a causal model over a built world. The recipe verb.

    Must run after the episodes that mint the corrections its drives will
    spend, for the same reason ``Imperfections`` must: a budget for staleness
    is spent against corrections the world already recorded.
    """

    model: Mapping[str, Any]
    physics: Any = None
    """Bound by ``recipe._under`` when a corpus was built under non-default
    physics — and *used*: exogenous nodes draw from it."""

    def run(self, world: World) -> World:
        from .generators.distractors import apply_messiness
        from .models import EnterpriseEvent
        from .recipe import with_step

        if world._minter is None or world.seed is None:
            raise ValueError("a causal model needs a generator-backed world; build one from a seed")
        model = from_document(self.model)
        physics = self.physics if self.physics is not None else DEFAULT_PHYSICS
        periods = periods_of(world)
        rng = Rng(world.seed).derive("causal")
        trace_periods = evaluate(model, periods, physics=physics, rng=rng)

        minter = world._minter
        events: list[EnterpriseEvent] = []
        for intervention in model.interventions:
            events.append(EnterpriseEvent(
                id=minter.next("EV"),
                kind="causal.intervention",
                occurred_at=_period_start(intervention.at),
                summary=(
                    f"{intervention.reason}: {intervention.node} set to"
                    f" {intervention.value:g} from {intervention.at}"
                ),
            ))

        budgets: dict[str, int] = {}
        for values in trace_periods:
            for kind, count in values.budgets.items():
                budgets[kind] = budgets.get(kind, 0) + count

        before = {kind: 0 for kind in messiness_module.KINDS}
        for error in world.intentional_errors:
            kind = _kind_of(error.error_type.value)
            if kind:
                before[kind] += 1

        # The imperfections ride the existing pass, unrecorded — this step is
        # the recipe entry, and a second `Imperfections` step beside it would
        # replay the decay twice.
        if any(budgets.values()):
            world = apply_messiness(
                world, messiness=messiness_module.Messiness(
                    budgets, about=f"derived by causal model {model.name!r}",
                ),
                record=False,
            )

        after = {kind: 0 for kind in messiness_module.KINDS}
        for error in world.intentional_errors:
            kind = _kind_of(error.error_type.value)
            if kind:
                after[kind] += 1
        delivered = {kind: after[kind] - before[kind] for kind in sorted(budgets)}

        trace = CausalTrace(
            id=minter.next("CAUSE"),
            model=model,
            periods=trace_periods,
            budgets=dict(sorted(budgets.items())),
            delivered=delivered,
            event_ids=[event.id for event in events],
        )
        return world.extend(
            events=tuple(events),
            causal=(trace,),
            recipe=with_step(world._recipe, "Causal", model=model.model_dump(mode="json")),
        )


def _kind_of(error_type: str) -> str:
    """Which imperfection kind an intentional-error type belongs to.

    Read from the labels ``apply_messiness`` writes rather than restated:
    ``stale_status`` is staleness, ``duplicate_issue`` is disagreement,
    ``outdated_owner`` is orphaning — the same three mappings that pass uses.
    """
    return {
        "stale_status": "staleness",
        "duplicate_issue": "disagreement",
        "outdated_owner": "orphaning",
    }.get(error_type, "")


def apply(world: World, model: Mapping[str, Any] | CausalModel) -> World:
    """Run *model* on *world*. The library entry point."""
    document = from_document(model).model_dump(mode="json")
    return world.run(Causal(model=document))


# ---------------------------------------------------------------------------
# The validator group
# ---------------------------------------------------------------------------


def _checks(world: Any) -> tuple[list, int]:
    """The ``causal`` group: a trace must agree with its own model.

    Recomputes every derived node from its recorded parents; checks every
    intervention in force is reflected in the node it set; re-sums the budgets;
    holds delivery to the budget; and requires each intervention's event to
    exist on the timeline at the period it names.
    """
    from .validate import Violation

    violations: list[Violation] = []
    checks = 0
    traces = getattr(world, "_causal", ())
    if not traces:
        return violations, checks

    def fail(code: str, subject: str, detail: str) -> None:
        violations.append(Violation(group="causal", code=code, subject=subject, detail=detail))

    events = {event.id: event for event in world.events}
    for trace in traces:
        model = trace.model
        findings = lint(model)
        checks += 1
        if findings:
            fail("model_lint", trace.id, "; ".join(findings))
            continue
        summed: dict[str, int] = {}
        for values in trace.periods:
            for spec in model.nodes:
                if spec.name not in values.values:
                    checks += 1
                    fail("node_missing", f"{trace.id}/{values.period}", f"no value for {spec.name!r}")
                    continue
                forced = {
                    model.interventions[i].node: model.interventions[i].value
                    for i in values.interventions
                }
                if spec.name in forced:
                    checks += 1
                    expected = round(_clamp(forced[spec.name], spec.low, spec.high), spec.places)
                    if values.values[spec.name] != expected:
                        fail("intervention_not_applied", f"{trace.id}/{values.period}/{spec.name}",
                             f"in force at {expected:g}, recorded {values.values[spec.name]:g}")
                elif spec.derived:
                    checks += 1
                    expected = recompute(spec, values.values)
                    if values.values[spec.name] != expected:
                        fail("derived_drift", f"{trace.id}/{values.period}/{spec.name}",
                             f"recomputes to {expected:g} from its parents, recorded"
                             f" {values.values[spec.name]:g}")
            for drive in model.drives:
                checks += 1
                expected_budget = round(values.values.get(drive.node, 0.0) * drive.scale)
                if values.budgets.get(drive.imperfection) != expected_budget:
                    fail("budget_drift", f"{trace.id}/{values.period}/{drive.imperfection}",
                         f"{drive.node} × {drive.scale:g} budgets {expected_budget}, recorded"
                         f" {values.budgets.get(drive.imperfection)}")
            for kind, count in values.budgets.items():
                summed[kind] = summed.get(kind, 0) + count
        checks += 1
        if dict(sorted(summed.items())) != dict(sorted(trace.budgets.items())):
            fail("budget_sum", trace.id, f"periods sum to {summed}, recorded {trace.budgets}")
        for kind, count in trace.delivered.items():
            checks += 1
            if count > trace.budgets.get(kind, 0):
                fail("over_delivered", f"{trace.id}/{kind}",
                     f"{count} delivered against a budget of {trace.budgets.get(kind, 0)}")
        checks += 1
        if len(trace.event_ids) != len(model.interventions):
            fail("events_miscounted", trace.id,
                 f"{len(model.interventions)} interventions, {len(trace.event_ids)} events")
        for intervention, event_id in zip(model.interventions, trace.event_ids):
            checks += 1
            event = events.get(event_id)
            if event is None:
                fail("event_missing", f"{trace.id}/{event_id}", "intervention event is not on the timeline")
            elif event.kind != "causal.intervention" or event.occurred_at != _period_start(intervention.at):
                fail("event_disagrees", f"{trace.id}/{event_id}",
                     f"expected a causal.intervention at {intervention.at}, found"
                     f" {event.kind} at {event.occurred_at.isoformat()}")
    return violations, checks


# ---------------------------------------------------------------------------
# Registration — the same seams every vertical uses
# ---------------------------------------------------------------------------

from . import recipe as _recipe
from . import validate as _validate

_recipe.register_step("Causal", ("model",), Causal)
_validate.register_domain_checks("causal", _checks)


#: A worked model an author can start from — the procure-to-pay cascade the
#: module docstring describes, with the migration as its intervention.
TEMPLATE: dict[str, Any] = {
    "name": "erp_migration_cascade",
    "about": "An ERP migration raises manual handling; manual handling and weak"
             " supplier quality raise the invoice error rate; errors and approver"
             " load delay payments. The error rate sizes how many stale pages the"
             " archive carries; the delay sizes how many secondary documents"
             " disagree with their source.",
    "nodes": [
        {"name": "supplier_quality", "level": 0.8, "low": 0.0, "high": 1.0,
         "about": "Share of suppliers whose invoices arrive clean."},
        {"name": "manual_touch_rate", "level": 0.15,
         "about": "Share of invoices somebody keys by hand."},
        {"name": "approver_load", "level": 0.5,
         "about": "How saturated the approval queue is, 0 to 1."},
        {"name": "invoice_error_rate", "depends_on": ["supplier_quality", "manual_touch_rate"],
         "intercept": 0.18, "weights": {"supplier_quality": -0.12, "manual_touch_rate": 0.06},
         "low": 0.0, "high": 1.0,
         "about": "Share of invoices with a coding error."},
        {"name": "payment_delay_days", "depends_on": ["invoice_error_rate", "approver_load"],
         "intercept": 2.0, "weights": {"invoice_error_rate": 40.0, "approver_load": 6.0},
         "low": 0.0, "places": 1,
         "about": "Days late the average supplier is paid."},
    ],
    "interventions": [
        {"at": "2026-04", "node": "manual_touch_rate", "value": 0.35,
         "reason": "ERP migration cut-over"},
    ],
    "drives": [
        {"node": "invoice_error_rate", "imperfection": "staleness", "scale": 20},
        {"node": "payment_delay_days", "imperfection": "disagreement", "scale": 0.25},
    ],
}


__all__ = [
    "Causal", "CausalModel", "CausalTrace", "DriveSpec", "InterventionSpec",
    "NodeSpec", "PeriodValues", "TEMPLATE", "apply", "evaluate", "from_document",
    "lint", "order", "periods_of", "recompute",
]
