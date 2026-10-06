"""Turning matched journeys into things Worldloom can build.

W2 answered *can we emulate this?* — connector, record type, operation. That
is not the same as *can we build a test case from it?*, and this module asks
the second question.

Every journey lands in exactly one of four groups::

    write      a matched tool step writes        ──▶  built
    lookup     matched tool steps, none write    ──▶  answer_only_unsupported
    no_world   domain_cluster, or no tool step   ──▶  no_world_needed
    blocked    W2 found something hard           ──▶  already refused, upstream

Only ``write`` is built, and only in this wave. The other three are reported
rather than dropped, which is the same bargain W1 and W2 strike: anything the
importer cannot build says so by name.

The two it cannot build are not the same kind of problem, so they do not carry
the same severity.

``lookup`` is **hard**
    A journey of pure reads ending in an answer is a perfectly real journey.
    Worldloom simply has no way to express "no world changed, judge the
    answer" yet — that is core change C3, scheduled as W7. So the journey is
    refused, and the finding names what is missing rather than blaming the
    catalogue.

``no_world`` is **info**
    A journey with no tool calls at all — rewrite this email, summarise these
    notes — needs no fake world to run against. Nothing is missing and nothing
    is broken. It is counted as uncovered in the fidelity report, and the
    import is still accepted.

Sorting changes nothing. It reads a :class:`~.registry.MatchedCatalogue` and
returns the same journeys in labelled piles.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from ..enterprise_specs import (
    ContentAction,
    DestinationRole,
    Operation,
    ProcessSpec,
    ScenarioProfile,
    SourceRole,
    WorkflowSpec,
    builtin_registry,
)
from ..eval_design import EvalSpec, EvalStepSpec, RequirementKind, WorldRequirement
from ..models import Model
from ..studio.models import UseCase
from .binding import BindRule
from .catalogue import Cuj
from .report import Finding, ImportReport, hard, info

if TYPE_CHECKING:
    from .binding import Binding, BoundQuestion
    from .registry import MatchedCatalogue


ANSWER_ONLY_UNSUPPORTED = "answer_only_unsupported"
"""Reads only, then answers. Needs core change C3 (W7)."""

NO_WORLD_NEEDED = "no_world_needed"
"""Model-only work. There is no world to build, and that is fine."""


class Group(StrEnum):
    """Which pile a journey lands in."""

    WRITE = "write"
    LOOKUP = "lookup"
    NO_WORLD = "no_world"
    BLOCKED = "blocked"


class SortedCatalogue(Model):
    """Every journey, in exactly one pile. The four sum to the input."""

    write: tuple[Cuj, ...] = ()
    """The only pile this wave builds from, so these stay whole journeys."""

    lookup: tuple[str, ...] = ()
    no_world: tuple[str, ...] = ()
    blocked: tuple[str, ...] = ()
    """Ids only. Nothing downstream needs their steps."""

    report: ImportReport = ImportReport()
    """W2's findings, plus one per lookup and one per no_world journey."""

    @property
    def total(self) -> int:
        """Journeys sorted. Equals the catalogue's, or a pile was lost."""
        return (len(self.write) + len(self.lookup)
                + len(self.no_world) + len(self.blocked))


def group_for(cuj: Cuj) -> Group:
    """Which pile *cuj* belongs in, for a journey W2 did not refuse.

    ``blocked`` never comes back from here: it is a property of W2's verdict,
    not of the journey, so the caller assigns it.

    The ``domain_cluster`` test comes first because the anchor is a statement
    about how the journey was *identified* — answer-only traffic with no tool
    signature to name it by. A stray tool step does not change that.
    """
    if cuj.anchor == "domain_cluster":
        return Group.NO_WORLD
    tool_steps = [step for step in cuj.steps if step.is_tool_step]
    if not tool_steps:
        return Group.NO_WORLD
    # "A matched tool step writes" — a capability step is model-only work and
    # changes nothing, whatever its declared effect.
    if any(step.effect == "write" for step in tool_steps):
        return Group.WRITE
    return Group.LOOKUP


def sort_catalogue(matched: MatchedCatalogue) -> SortedCatalogue:
    """Sort every journey in *matched* into one of the four groups.

    Journeys W2 refused are already explained by its hard findings, so they
    are counted as ``blocked`` without a second finding saying the same thing
    in different words.
    """
    write: list[Cuj] = []
    lookup: list[str] = []
    no_world: list[str] = []
    findings: list[Finding] = []

    for cuj in matched.cujs:
        group = group_for(cuj)
        if group is Group.WRITE:
            write.append(cuj)
        elif group is Group.LOOKUP:
            lookup.append(cuj.id)
            findings.append(hard(
                ANSWER_ONLY_UNSUPPORTED,
                f"{cuj.id} reads and answers without changing anything. "
                "Worldloom cannot yet express a journey that leaves no trace "
                "in the world, so there is nothing to build a case against. "
                "Needs core change C3 (answer-only workflows)",
                cuj_id=cuj.id,
                detail={"label": cuj.label, "steps": str(len(cuj.steps))}))
        else:
            no_world.append(cuj.id)
            findings.append(info(
                NO_WORLD_NEEDED,
                f"{cuj.id} calls no business tool, so it needs no world to "
                "run against. Not built, and counted as uncovered",
                cuj_id=cuj.id,
                detail={"label": cuj.label, "anchor": cuj.anchor}))

    return SortedCatalogue(
        write=tuple(write), lookup=tuple(lookup), no_world=tuple(no_world),
        blocked=matched.refused,
        report=ImportReport(findings=matched.report.findings + tuple(findings)))


# --------------------------------------------------------------------------
# Turning one write journey into something Worldloom can build.
# --------------------------------------------------------------------------
#
# A journey says what people did. A ``UseCase`` says what to build so an agent
# can be asked to do it again, and graded. Three things have to agree:
#
#     the question      "Create epics in ACTIONITEM ..."
#     the task skeleton find_notes -> read_notes -> draft_epics -> create_epics
#     the world         a Jira project called ACTIONITEM must exist
#
# The third is the one that is easy to get wrong, because nothing fails loudly
# when it is missing — the agent is simply asked for something that is not
# there. So every value written into the question is also written into a
# construction requirement, which is why ``Binding`` carries its connector and
# entity.


DEFAULT_PERSONA = "employee"
"""Who is asking. The catalogue cannot say: who asked is exactly what the
miner strips at the boundary. The design document calls this open question
D5. Overridable with ``--persona``, and recorded as an assumption."""

DEFAULT_AUDIENCE = "team"
"""Who the output is for. Also absent from the catalogue, also an option."""

#: ``capability`` on a step maps onto Worldloom's content actions. ``answer``
#: is deliberately absent: it is the ending C3 adds, and a journey that ends
#: in one is a lookup, which this wave does not build.
_CONTENT_ACTIONS = {
    "generate": ContentAction.GENERATE,
    "summarize": ContentAction.SUMMARIZE,
    "extract": ContentAction.EXTRACT,
    "classify": ContentAction.CLASSIFY,
    "compare": ContentAction.COMPARE,
    "reconcile": ContentAction.RECONCILE,
    "transform": ContentAction.TRANSFORM,
}

#: Values worth pinning in the world. An option or a derived container name
#: identifies something that must exist. Free text is a search phrase, and a
#: person is chosen by the world after it is built, so neither belongs here.
_SELECTOR_RULES = (BindRule.OPTION, BindRule.KEY)


def _capability(label: str) -> str:
    """``slug(label)``, cut to 64 — the doc's rule for ``EvalSpec.capability``."""
    slug = "".join(character if character.isalnum() else "-"
                   for character in label.casefold())
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:64] or "telemetry-journey"


def _objective(cuj: Cuj) -> str:
    """Why this case exists, in terms a reader can check against the file.

    No customer text: the label is the miner's own, and the two numbers are
    counts. Anyone can open the catalogue and verify both.
    """
    return (f"Reproduce telemetry CUJ {cuj.id} ({cuj.label}): "
            f"{cuj.support.sessions} sessions, share {cuj.support.share}.")


def _eval_steps(cuj: Cuj) -> tuple[EvalStepSpec, ...]:
    """One step each, in order. ``inv2`` already guarantees the order is
    topological, and W2's rewiring preserves it, so ``EvalSpec``'s own
    "depends_on names an earlier step" check cannot fire here."""
    steps: list[EvalStepSpec] = []
    for step in cuj.steps:
        if step.is_tool_step:
            steps.append(EvalStepSpec(
                id=step.id, capability=str(step.operation),
                connector=step.connector, entity=step.entity,
                operation=str(step.operation), effect=step.effect,
                depends_on=step.depends_on))
        else:
            steps.append(EvalStepSpec(
                id=step.id, capability=str(step.capability),
                effect="transform", depends_on=step.depends_on))
    return tuple(steps)


def _pairs(cuj: Cuj) -> tuple[tuple[str, str], ...]:
    """Every ``(connector, entity)`` the journey touches, first use first."""
    seen: list[tuple[str, str]] = []
    for step in cuj.steps:
        if step.connector and step.entity:
            pair = (step.connector, step.entity)
            if pair not in seen:
                seen.append(pair)
    return tuple(seen)


def _requirements(cuj: Cuj,
                  bindings: tuple[Binding, ...]) -> tuple[WorldRequirement, ...]:
    """What the world must contain: one requirement per pair, not per step.

    Per *pair* because Studio rejects a case whose requirements for one
    ``(connector, entity)`` disagree about their selectors
    (``ambiguous_source_contract``). Three steps touching Jira issues are one
    demand on the world, with their fields merged, not three demands that
    happen to agree.
    """
    selectors: dict[tuple[str, str], dict[str, str | int | bool]] = {
        pair: {"connector": pair[0], "entity": pair[1]} for pair in _pairs(cuj)}
    for binding in bindings:
        pair = (binding.connector, binding.entity)
        if binding.rule in _SELECTOR_RULES and pair in selectors:
            selectors[pair][binding.field] = binding.value
    return tuple(
        WorldRequirement(id=f"{connector}.{entity}",
                         kind=RequirementKind.CONNECTOR,
                         selector=selectors[(connector, entity)])
        for connector, entity in _pairs(cuj))


def _roles(cuj: Cuj, bindings: tuple[Binding, ...],
           ) -> tuple[tuple[SourceRole, ...], tuple[DestinationRole, ...]]:
    """Read pairs become sources, write pairs become destinations.

    A pair read *and* written is both. The workflow describes what the agent
    has to touch, and a step that reads an issue before updating it needs the
    issue findable as well as writable.
    """
    reads: dict[tuple[str, str], set[str]] = {}
    writes: dict[tuple[str, str], set[str]] = {}
    for step in cuj.steps:
        if not (step.connector and step.entity and step.operation):
            continue
        side = writes if step.effect == "write" else reads
        side.setdefault((step.connector, step.entity), set()).add(
            str(step.operation))

    selector_fields: dict[tuple[str, str], list[str]] = {}
    for binding in bindings:
        if binding.rule in _SELECTOR_RULES and binding.field:
            selector_fields.setdefault(
                (binding.connector, binding.entity), []).append(binding.field)

    sources = tuple(
        SourceRole(connector=connector, entities=(entity,),
                   operations=tuple(sorted(Operation(name)
                                           for name in sorted(operations))),
                   required_fields=tuple(
                       sorted(selector_fields.get((connector, entity), []))))
        for (connector, entity), operations in sorted(reads.items()))
    destinations = tuple(
        DestinationRole(connector=connector, entities=(entity,),
                        operations=tuple(sorted(Operation(name)
                                                for name in sorted(operations))))
        for (connector, entity), operations in sorted(writes.items()))
    return sources, destinations


def _content_actions(cuj: Cuj) -> tuple[ContentAction, ...]:
    """The model-only work the journey does, in step order.

    ``(EXTRACT,)`` when there is none: ``WorkflowSpec`` requires at least one
    action, and a journey that only moves records between systems is still
    pulling something out of what it read.
    """
    actions: list[ContentAction] = []
    for step in cuj.steps:
        action = _CONTENT_ACTIONS.get(str(step.capability or ""))
        if action is not None and action not in actions:
            actions.append(action)
    return tuple(actions) or (ContentAction.EXTRACT,)


def _process(cuj: Cuj) -> tuple[str, ProcessSpec | None]:
    """A built-in process that covers every pair, or a new one named for the
    journey.

    "Covers" has to mean every pair, not some: a process is what tells
    Worldloom which events a world of this kind generates, and one that knows
    about Jira but not Confluence would quietly build half a world.
    """
    pairs = _pairs(cuj)
    registry = builtin_registry()
    wanted = {connector: entity for connector, entity in pairs}
    best: ProcessSpec | None = None
    overlap = 0
    for process in registry.processes.values():
        if all(process.connector_entities.get(connector) == entity
               for connector, entity in wanted.items()):
            return process.name, None
        shared = sum(1 for connector, entity in wanted.items()
                     if process.connector_entities.get(connector) == entity)
        if shared > overlap or best is None:
            best, overlap = process, shared
    # Nothing covers it, so invent one and borrow the event kinds from
    # whichever built-in came closest. Event kinds are what a world's
    # timeline is made of; guessing them from nothing would be worse.
    return cuj.id, ProcessSpec(
        name=cuj.id, connector_entities=dict(wanted),
        event_kinds=best.event_kinds if best is not None else ("work",))


def _workflow(cuj: Cuj, question: BoundQuestion,
              bindings: tuple[Binding, ...], *, audience: str,
              ) -> tuple[WorkflowSpec, ProcessSpec | None]:
    sources, destinations = _roles(cuj, bindings)
    process, invented = _process(cuj)
    return WorkflowSpec(
        name=cuj.id, purpose=cuj.label, process=process,
        sources=sources, destinations=destinations,
        content_actions=_content_actions(cuj), audiences=(audience,),
        prompt_template=question.text), invented


def _scenario(cuj: Cuj, question: BoundQuestion, bindings: tuple[Binding, ...],
              *, industry: str, audience: str) -> ScenarioProfile:
    workflow, invented = _workflow(cuj, question, bindings, audience=audience)
    return ScenarioProfile(
        name=cuj.id, industry=industry, company_description="",
        connectors=tuple(sorted({connector for connector, _ in _pairs(cuj)})),
        additional_workflows=(workflow,),
        additional_processes=(invented,) if invented is not None else ())


def build_use_case(cuj: Cuj, question: BoundQuestion,
                   bindings: tuple[Binding, ...], *, industry: str = "",
                   persona: str = DEFAULT_PERSONA,
                   audience: str = DEFAULT_AUDIENCE,
                   count: int = 12) -> UseCase:
    """One write journey, as something ``worldloom studio init`` accepts.

    *count* is how many questions this journey is worth.

    ``activities`` is left empty, against the design document's "step ids in
    order". It is not a list of steps. ``ProjectSpec`` checks every activity
    against the activity ids of the company's own process structure, and
    refuses the whole project if one is missing — so step ids, which no
    company structure contains, make every imported case unbuildable. The
    steps already live in ``construction.steps``; an activity is a different
    thing, a slot in the company's process catalogue, and the catalogue
    cannot say which one a journey belongs to.
    """
    return UseCase(
        id=cuj.id, title=cuj.label, objective=_objective(cuj), count=count,
        scenario=_scenario(cuj, question, bindings,
                           industry=industry, audience=audience),
        construction=EvalSpec(
            id=cuj.id, capability=_capability(cuj.label), persona=persona,
            request_template=question.text, steps=_eval_steps(cuj),
            requirements=_requirements(cuj, bindings)))
