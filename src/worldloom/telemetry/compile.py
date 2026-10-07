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
from typing import TYPE_CHECKING, Any, Literal, cast

from ..connector_definition import load_connector_definition
from ..enterprise_specs import (
    ContentAction,
    CoverageProfile,
    DestinationRole,
    Operation,
    ProcessSpec,
    ScenarioProfile,
    SourceRole,
    WorkflowSpec,
    builtin_registry,
)
from ..eval_design import (
    EvalShape,
    EvalSpec,
    EvalStepSpec,
    RecordShapeRequirement,
    RequirementKind,
    WorldRequirement,
)
from ..models import Model
from ..providers import Receipt, digest_bytes
from ..studio.construction import (
    ConstructionIssue,
    ConstructionPlan,
    compile_project,
)
from ..studio.models import ProjectSpec, UseCase
from .binding import (
    PHRASING_DEFAULT_USED,
    BindRule,
    bind_question,
    fallback_template,
    fold_map,
    prompt_template,
)
from .catalogue import (
    Catalogue,
    Cuj,
    FailureModeKind,
    Hardness,
    TemporalPattern,
    load_catalogue,
)
from .registry import match_catalogue
from .report import Finding, ImportReport, hard, info

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .binding import Binding
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

#: Argument names that hold what a person typed into a search. A value bound
#: to one of these, on a step that reads, names the record the search was
#: for — so it becomes that record's ``title`` in the world. ``title`` is not
#: a guess: it is the text field the world builder itself gives every
#: witness record it mints (``eval_witnesses``), and the field the design
#: document's worked example pins ("store ops").
_SEARCH_WORDS = frozenset({"query", "queries", "q", "search", "keyword",
                           "keywords", "term", "terms", "text"})

#: The hardness tiers the catalogue counts, as ``EvalSpec`` difficulties.
_DIFFICULTY = {Hardness.HEAD_EASY: "easy", Hardness.MEDIUM: "medium",
               Hardness.HARD_FAILURE: "hard", Hardness.ADVERSARIAL_EDGE: "hard"}
_HARDER = ("easy", "medium", "hard")

ARGUMENT_FIELD_UNKNOWN = "argument_field_unknown"
"""A read step used an argument the connector definition does not describe,
so no record shape can be asked for it. Info: nothing is wrong with the
journey, and with today's shipped connectors this is the common case."""


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


def _difficulty(cuj: Cuj) -> Literal["easy", "medium", "hard"]:
    """The most common hardness tier; a tie goes to the harder one (§5.4).

    Counted per difficulty, not per raw tier, because two tiers both mean
    hard: 10 ``HARD_FAILURE`` and 10 ``ADVERSARIAL_EDGE`` are 20 hard rows.
    """
    counts = dict.fromkeys(_HARDER, 0)
    for tier, count in cuj.hardness.items():
        counts[_DIFFICULTY[tier]] += count
    if not any(counts.values()):
        return "medium"
    chosen = max(_HARDER, key=lambda level: (counts[level], _HARDER.index(level)))
    return cast("Literal['easy', 'medium', 'hard']", chosen)


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


def _reads(cuj: Cuj, folds: Mapping[str, tuple[str, str]],
           ) -> dict[tuple[str, str], set[str]]:
    """Every pair the journey reads, with how, in first-use order.

    A folded lookup counts as a read of the pair it folded into. W2 deleted
    the step, but people did look the project up before creating the epics,
    and an agent that does the same must find something there. Leaving it
    out would let the world hold no issues in that project at all, so a
    careful agent checking first would find nothing and be marked down for
    the care. This is how the design document's worked example lists it.
    """
    reads: dict[tuple[str, str], set[str]] = {}
    for step in cuj.steps:
        if step.connector and step.entity and step.operation \
                and step.effect != "write":
            reads.setdefault((step.connector, step.entity), set()).add(
                str(step.operation))
    hosts = {step.id: step for step in cuj.steps}
    for host_id, _ in folds.values():
        host = hosts.get(host_id)
        if host is not None and host.connector and host.entity:
            reads.setdefault((host.connector, host.entity), set()).add("search")
    return reads


def _writes(cuj: Cuj) -> dict[tuple[str, str], set[str]]:
    writes: dict[tuple[str, str], set[str]] = {}
    for step in cuj.steps:
        if step.connector and step.entity and step.operation \
                and step.effect == "write":
            writes.setdefault((step.connector, step.entity), set()).add(
                str(step.operation))
    return writes


def _searched_for(field: str) -> bool:
    return any(word in _SEARCH_WORDS for word in field.casefold().split("_"))


def _selectors(reads: Mapping[tuple[str, str], set[str]],
               bindings: tuple[Binding, ...],
               ) -> dict[tuple[str, str], dict[str, str | int | bool]]:
    """What each read pair's record must look like, for the world to answer
    the question that was written.

    The question names values; the world has to hold them. Three kinds are
    pinned:

        an option          the connector's own declared value
        a container        the key-shaped name, "ACTIONITEM"
        a search phrase    the title of what was searched for, "store ops"

    A person is left out — the world chooses one after it is built — and so
    is free text written *into* a record, which is the agent's output, not
    the world's starting state. The world builder mints matching records
    plus one near miss per pinned field, so every pinned value exists and
    has look-alikes.
    """
    selectors: dict[tuple[str, str], dict[str, str | int | bool]] = {
        pair: {"connector": pair[0], "entity": pair[1]} for pair in reads}
    for binding in bindings:
        selector = selectors.get((binding.connector, binding.entity))
        if selector is None:
            continue
        if binding.rule in (BindRule.OPTION, BindRule.KEY):
            selector[binding.field] = binding.value
        elif binding.rule is BindRule.TEXT and _searched_for(binding.field):
            selector["title"] = binding.value
    return selectors


def _requirements(reads: Mapping[tuple[str, str], set[str]],
                  selectors: Mapping[tuple[str, str],
                                     dict[str, str | int | bool]],
                  ) -> tuple[WorldRequirement, ...]:
    """One hard requirement per pair that is *read* — not per step, and not
    per pair written (§5.4).

    Per pair because Studio rejects a case whose requirements for one
    ``(connector, entity)`` disagree about their selectors
    (``ambiguous_source_contract``). Read pairs only because a requirement
    says what must exist *before* the agent starts; a record the agent is
    about to create is its output.
    """
    return tuple(
        WorldRequirement(id=f"{connector}.{entity}",
                         kind=RequirementKind.CONNECTOR,
                         selector=selectors[(connector, entity)])
        for connector, entity in reads)


def _roles(reads: Mapping[tuple[str, str], set[str]],
           writes: Mapping[tuple[str, str], set[str]],
           selectors: Mapping[tuple[str, str], dict[str, str | int | bool]],
           ) -> tuple[tuple[SourceRole, ...], tuple[DestinationRole, ...]]:
    """Read pairs become sources, write pairs become destinations.

    A source's ``required_fields`` are its selector's pinned fields, as the
    design document asks: the fields a record must carry for the agent to
    find the one the question means. A pair read *and* written is both.
    """
    def operations(names: set[str]) -> tuple[Operation, ...]:
        return tuple(sorted(Operation(name) for name in names))

    sources = tuple(
        SourceRole(connector=connector, entities=(entity,),
                   operations=operations(names),
                   required_fields=tuple(sorted(
                       key for key in selectors[(connector, entity)]
                       if key not in ("connector", "entity"))))
        for (connector, entity), names in sorted(reads.items()))
    destinations = tuple(
        DestinationRole(connector=connector, entities=(entity,),
                        operations=operations(names))
        for (connector, entity), names in sorted(writes.items()))
    return sources, destinations


def _knows(connector: str, entity: str, field: str) -> bool:
    """Whether the connector definition describes *field* on *entity*: a
    field manifest, a query field, or a field required on create."""
    try:
        definition = load_connector_definition(connector)
        if definition.resolve_field(entity, field) is not None:
            return True
        members = definition.entity_members(entity)
    except (KeyError, ValueError):
        return False
    if field in definition.query_fields:
        return True
    return any(field in definition.entities[member].required_on_create
               for member in members)


def record_shapes(cuj: Cuj) -> tuple[EvalShape, tuple[Finding, ...]]:
    """A record shape per read step whose arguments the definition knows.

    Each asks that the record the step reads carries at least as many
    populated fields as the step's known arguments — the design document
    names the rule but not its numbers, and that is the least it can mean.
    Every argument the definition does not describe is reported instead.
    With today's shipped connectors that is nearly all of them: they carry
    no field manifests, and a search argument like ``queries`` names how a
    record was asked for, not a field it has.
    """
    shapes: list[RecordShapeRequirement] = []
    findings: list[Finding] = []
    for step in cuj.steps:
        if not (step.connector and step.entity) or step.effect == "write":
            continue
        known = [field for field in step.argument_fields
                 if _knows(step.connector, step.entity, field)]
        for field in step.argument_fields:
            if field not in known:
                findings.append(info(
                    ARGUMENT_FIELD_UNKNOWN,
                    f"step {step.id!r} passed {field!r} to "
                    f"{step.connector}.{step.entity}, which the connector "
                    "definition does not describe; no record shape asked "
                    "for it",
                    cuj_id=cuj.id,
                    detail={"step_id": step.id, "field": field,
                            "connector": step.connector,
                            "entity": step.entity}))
        if known:
            shapes.append(RecordShapeRequirement(
                connector=step.connector, entity=step.entity,
                minimum_populated_fields=len(known)))
    return EvalShape(records=tuple(shapes)), tuple(findings)


#: Write operations that change a record already there, rather than make one.
_UPDATES = frozenset({"update", "patch", "upsert"})


def _renderable(failure: str) -> bool:
    """Whether Worldloom can put *failure* into a question.

    The design document asks for support to be checked by feature, not by
    version, so the importer works before and after core changes land. The
    feature that matters is the sentence ``_render`` appends for the failure:
    without one, every question carrying it would fail to render.
    """
    from ..packkit import template

    try:
        template(f"enterprise.failure.{failure}")
    except KeyError:
        return False
    return True


def coverage_failures(cuj: Cuj) -> tuple[str, ...]:
    """The designed failures the journey's questions rotate through.

    ``"none"`` plus only the failures this journey actually showed, mapped by
    the coverage rows of §5.7:

        permission_denied        → permission_denied
        stale_version, or the    → stale_source, plus version_conflict when
          time pattern "latest"     the journey updates records
        wrong_entity, across     → ambiguous_join
          two connectors
        connector_unavailable    → connector_unavailable, once Worldloom can
                                    render it (core change C2)

    The default list would rotate six failures through every question,
    whatever the customer's users actually hit. Worldloom rotates evenly, so
    even this list over-represents: a failure seen in 6% of rows reaches half
    of them. The design document accepts that, and W8's fidelity report
    measures the gap.

    The other rows of §5.7 — adversarial markers, trajectory rules, phrasing
    variants, difficulty adjustments, and the ``failure_mode_unconstructable``
    finding for anything that cannot be built — are W5.
    """
    kinds = {mode.mode for mode in cuj.failure_modes}
    connectors = {step.connector for step in cuj.steps if step.connector}
    updates = any(step.effect == "write" and str(step.operation) in _UPDATES
                  for step in cuj.steps)
    stale = (FailureModeKind.STALE_VERSION in kinds
             or cuj.volatility.temporal_patterns.get(TemporalPattern.LATEST, 0) > 0)

    wanted: list[str] = []
    if FailureModeKind.PERMISSION_DENIED in kinds:
        wanted.append("permission_denied")
    if stale:
        wanted.append("stale_source")
        if updates:
            wanted.append("version_conflict")
    if FailureModeKind.WRONG_ENTITY in kinds and len(connectors) >= 2:
        wanted.append("ambiguous_join")
    if FailureModeKind.CONNECTOR_UNAVAILABLE in kinds:
        wanted.append("connector_unavailable")
    return ("none", *(failure for failure in wanted if _renderable(failure)))


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


def _workflow(cuj: Cuj, prompt: str, sources: tuple[SourceRole, ...],
              destinations: tuple[DestinationRole, ...], *, audience: str,
              ) -> tuple[WorkflowSpec, ProcessSpec | None]:
    process, invented = _process(cuj)
    return WorkflowSpec(
        name=cuj.id, purpose=cuj.label, process=process,
        sources=sources, destinations=destinations,
        content_actions=_content_actions(cuj), audiences=(audience,),
        prompt_template=prompt), invented


def _scenario(cuj: Cuj, prompt: str, sources: tuple[SourceRole, ...],
              destinations: tuple[DestinationRole, ...], *, industry: str,
              audience: str) -> ScenarioProfile:
    workflow, invented = _workflow(cuj, prompt, sources, destinations,
                                   audience=audience)
    return ScenarioProfile(
        name=cuj.id, industry=industry, company_description="",
        connectors=tuple(sorted({connector for connector, _ in _pairs(cuj)})),
        additional_workflows=(workflow,),
        additional_processes=(invented,) if invented is not None else (),
        coverage=CoverageProfile(failures=coverage_failures(cuj)))


def build_use_case(cuj: Cuj, prompt: str,
                   bindings: tuple[Binding, ...], *, industry: str = "",
                   persona: str = DEFAULT_PERSONA,
                   audience: str = DEFAULT_AUDIENCE,
                   folds: Mapping[str, tuple[str, str]] | None = None,
                   shape: EvalShape | None = None,
                   count: int = 12) -> UseCase:
    """One write journey, as something ``worldloom studio init`` accepts.

    *prompt* is a template Worldloom fills once per generated question — see
    :func:`~.binding.prompt_template`. It goes into both the workflow and the
    construction contract, because the design document asks for the same
    text in each. *count* is how many questions this journey is worth.
    *folds* is W2's record of which lookups it folded and where, from
    :func:`~.binding.fold_map`; *shape* comes from :func:`record_shapes`.

    ``candidate_count`` is 1 and ``difficulty`` comes from the journey's
    hardness tally, both as §5.4 asks.

    ``activities`` is left empty, against the design document's "step ids in
    order". It is not a list of steps. ``ProjectSpec`` checks every activity
    against the activity ids of the company's own process structure, and
    refuses the whole project if one is missing — so step ids, which no
    company structure contains, make every imported case unbuildable. The
    steps already live in ``construction.steps``; an activity is a different
    thing, a slot in the company's process catalogue, and the catalogue
    cannot say which one a journey belongs to.
    """
    writes = _writes(cuj)
    # A journey that only writes reads nothing, and both ``WorkflowSpec`` (no
    # source) and ``EvalSpec`` (no requirement) refuse that outright — so a
    # single "create an issue" would crash the import rather than report
    # anything. Its written pairs stand in as what must exist beforehand,
    # which is true anyway: Worldloom mints a pre-existing record for every
    # write step, so updates and duplicates can be graded.
    reads = _reads(cuj, folds or {}) or {pair: {"read"} for pair in writes}
    selectors = _selectors(reads, bindings)
    sources, destinations = _roles(reads, writes, selectors)
    return UseCase(
        id=cuj.id, title=cuj.label, objective=_objective(cuj), count=count,
        scenario=_scenario(cuj, prompt, sources, destinations,
                           industry=industry, audience=audience),
        construction=EvalSpec(
            id=cuj.id, capability=_capability(cuj.label), persona=persona,
            request_template=prompt, steps=_eval_steps(cuj),
            requirements=_requirements(reads, selectors),
            shape=shape or EvalShape(), difficulty=_difficulty(cuj),
            candidate_count=1))


# --------------------------------------------------------------------------
# Sharing out the question count.
# --------------------------------------------------------------------------
#
# ``--cases N`` says how many questions the whole corpus gets. Each built
# journey's share of real traffic says how to split them.
#
# Two rules in the design document (§5.6) cannot both hold, and nothing says
# which wins:
#
#     A   the counts add up to exactly N
#     B   every built journey gets at least 1
#
# Largest-remainder rounding satisfies A by construction. ``max(1, …)`` is
# then applied on top, and raising a number never leaves a total alone — so
# whenever a journey rounds down to zero, B breaks A. It is latent rather
# than theoretical: a journey reaches zero exactly when its rescaled weight
# is under ``1/N``, which at the default 200 means half a percent. The
# sample's three journeys are nowhere near it; a customer with forty
# journeys and a long tail hits it on the first run.
#
# This resolves it by satisfying B and then repaying A out of the largest
# counts, one question at a time. Largest because it costs least
# proportionally: 5 → 4 moves that journey by a fifth, while taking the same
# question from a count of 2 moves that one by half.


DEFAULT_CASES = 200
"""``--cases`` default, from the design document."""

CASES_BELOW_JOURNEYS = "cases_below_journeys"
"""Fewer questions were asked for than there are journeys to ask them about.
No arrangement gives every journey one, so this refuses rather than capping:
capping would drop journeys silently, which is the one thing this importer
is built not to do."""


class Allocation(Model):
    """One journey's share of the question budget."""

    cuj_id: str
    original_share: float
    """``support.share`` as the catalogue reported it — of *all* traffic."""

    rescaled_share: float
    """Of the traffic we could actually build. Always larger."""

    count: int
    """Questions. May disagree with ``rescaled_share`` after the repayment
    above, which is correct rather than a rounding fault."""


class CaseCounts(Model):
    """How ``--cases N`` was divided, and what it could not cover."""

    allocations: tuple[Allocation, ...] = ()
    total: int = 0
    share_lost: float = 0.0
    """Real traffic represented by no question at all, because its journey
    was not built. Rescaling hides this by construction — the shares always
    sum to 1 afterwards, whatever was dropped — so it is reported explicitly
    or nobody would know to ask."""


def _apportion(weights: dict[str, float], total: int) -> dict[str, int]:
    """Largest remainder, then a floor of 1, then repay the difference.

    Ties are broken by journey id throughout, so the same catalogue always
    divides the same way.
    """
    exact = {key: total * weight for key, weight in weights.items()}
    counts = {key: int(value) for key, value in exact.items()}

    leftover = max(0, total - sum(counts.values()))
    by_remainder = sorted(weights, key=lambda key: (-(exact[key] - counts[key]), key))
    for key in by_remainder[:leftover]:
        counts[key] += 1

    deficit = sum(1 for value in counts.values() if value == 0)
    for key, value in counts.items():
        if value == 0:
            counts[key] = 1
    for _ in range(deficit):
        # Some count exceeds 1: the total is now N + deficit, which is more
        # than N, which is at least the number of journeys. Ties go to the
        # lowest id because ``max`` keeps the first of equal keys.
        donor = max(sorted(counts), key=lambda key: counts[key])
        counts[donor] -= 1
    return counts


def share_counts(piles: SortedCatalogue, catalogue: Catalogue, *,
                 cases: int = DEFAULT_CASES,
                 ) -> tuple[CaseCounts, tuple[Finding, ...]]:
    """Divide *cases* questions across the journeys that were built.

    Weighted by each journey's share of real traffic, rescaled over only the
    journeys that survived — the rest of the mix cannot be rebuilt, so it is
    reported as lost rather than handed to whoever is left.
    """
    built = {cuj.id: cuj.support.share for cuj in piles.write}
    lost = sum(cuj.support.share for cuj in catalogue.cujs
               if cuj.id not in built)

    if not built:
        return CaseCounts(share_lost=lost), ()

    if cases < len(built):
        return CaseCounts(share_lost=lost), (hard(
            CASES_BELOW_JOURNEYS,
            f"--cases {cases} cannot cover {len(built)} journeys; every "
            "journey must get at least one question, so ask for at least "
            f"{len(built)}",
            detail={"cases": str(cases), "journeys": str(len(built))}),)

    weight = sum(built.values())
    rescaled = {cuj_id: share / weight for cuj_id, share in built.items()}
    counts = _apportion(rescaled, cases)

    return CaseCounts(
        allocations=tuple(
            Allocation(cuj_id=cuj_id, original_share=built[cuj_id],
                       rescaled_share=rescaled[cuj_id], count=counts[cuj_id])
            for cuj_id in sorted(built)),
        total=sum(counts.values()), share_lost=lost), ()


# --------------------------------------------------------------------------
# Studio's checks, run during import.
# --------------------------------------------------------------------------
#
# ``worldloom studio run`` checks a project before building it. If the
# importer did not run the same checks, a catalogue could import cleanly and
# then fail later, in a different command, far from the file that caused it.
# So the importer calls ``compile_project`` itself and copies every issue into
# its own report.
#
# Two of Studio's checks matter here:
#
#     within one case    ambiguous_source_contract    same pair, different
#                                                     selectors
#     across all cases   conflicting_company_demands  one object demanded in
#                                                     two exclusive states
#
# The first cannot fire on importer output: ``_requirements`` merges every
# step touching a pair into one requirement. The second, today, cannot either.
# Studio's conflict rule only compares demands that share an identity key —
# ``id``, ``record_id`` and the like — and the importer never writes one,
# because an id in a selector is an id in the question. The resolution below
# exists because the design document requires it and because that will stop
# being true the moment any binding rule pins a record.
#
# When it does fire, the clash has to be traced to two cases. That needs no
# new bookkeeping: Studio prefixes every requirement and step id with its
# case id before merging, and every demand carries those ids, so a demand
# already says which case asked for it.


CONFLICTING_COMPANY_DEMANDS = "conflicting_company_demands"
"""Studio's own code for a cross-case clash."""

DROPPED_FOR_CONFLICT = "dropped_for_conflict"
"""A journey removed so the rest could share one world. Hard: real
behaviour was lost, and a strict run should notice."""

class JourneyOutcome(Model):
    """What became of one journey. One per journey in the catalogue, built or
    not, so a report can account for every one of them."""

    cuj_id: str
    label: str
    group: Group
    share: float
    """``support.share`` as the catalogue reported it."""
    count: int = 0
    """Questions it was given. Zero when it was not built."""


class ImportResult(Model):
    """Everything one import produced: the project, the split, the receipt,
    and every finding along the way."""

    catalogue_id: str
    journeys: tuple[JourneyOutcome, ...] = ()

    project: ProjectSpec | None = None
    """``None`` when nothing could be built. Whether that stops the run is
    the command line's decision."""

    counts: CaseCounts = CaseCounts()
    receipt: Receipt
    report: ImportReport = ImportReport()


def _case_of(source_id: str) -> str:
    """``cuj_9636dd61a048:jira.issue`` → ``cuj_9636dd61a048``."""
    return source_id.split(":", 1)[0]


def _studio_finding(issue: ConstructionIssue) -> Finding:
    """One Studio issue, in the importer's vocabulary.

    The code is kept exactly, so anyone who later sees the same code from
    ``studio run`` recognises it.
    """
    where = issue.use_case_id or "the combined project"
    make = hard if issue.hard else info
    return make(issue.code, f"Studio, checking {where}: {issue.detail}",
                cuj_id=issue.use_case_id,
                detail={"requirement_id": issue.requirement_id,
                        "detail": issue.detail})


def _compile(company: dict[str, Any],
             cases: tuple[UseCase, ...]) -> ConstructionPlan:
    return compile_project(ProjectSpec(company=company, use_cases=cases))


def _clashing_pair(company: dict[str, Any], cases: tuple[UseCase, ...],
                   plan: ConstructionPlan) -> tuple[str, str] | None:
    """The first pair of cases that cannot share a world, or ``None``.

    Candidates come from the demands themselves. A clash is one object in two
    states, so both cases must demand the same kind of record in the same
    system; any pair that does not is skipped without asking Studio. Each
    candidate is then confirmed by Studio itself, on just those two cases, so
    the conflict rule is never reimplemented here.
    """
    touches: dict[tuple[str, str, str], set[str]] = {}
    for construction in plan.use_cases:
        for demand in construction.demands.demands:
            connector = demand.selector.get("connector")
            entity = demand.selector.get("entity")
            if not demand.hard or not isinstance(connector, str) \
                    or not isinstance(entity, str):
                continue
            for source in (*demand.source_requirement_ids,
                           *demand.source_step_ids):
                touches.setdefault((demand.kind.value, connector, entity),
                                   set()).add(_case_of(source))

    by_id = {case.id: case for case in cases}
    candidates = sorted({tuple(sorted((left, right)))
                         for owners in touches.values()
                         for left in owners for right in owners
                         if left < right})
    for left, right in candidates:
        pair = _compile(company, (by_id[left], by_id[right]))
        if any(issue.code == CONFLICTING_COMPANY_DEMANDS
               for issue in pair.findings):
            return left, right
    return None


def check_with_studio(company: dict[str, Any], cases: tuple[UseCase, ...],
                      shares: dict[str, float],
                      ) -> tuple[tuple[UseCase, ...], tuple[Finding, ...]]:
    """Run Studio's checks, and keep only the cases that can share one world.

    A case Studio refuses on its own is removed, its issue explaining why.
    When the cases clash with each other, the clashing pair is found and the
    one with the smaller share of real traffic is dropped — the survivor
    should be the behaviour more people actually did — then everything is
    checked again. Ties drop the higher id, so the same catalogue always
    loses the same case.

    ``ProjectSpec`` raising here is not caught. The company has already been
    validated by then, so a refusal means the importer built something
    invalid, and that should be loud.
    """
    survivors = tuple(sorted(cases, key=lambda case: case.id))
    findings: list[Finding] = []

    while survivors:
        plan = _compile(company, survivors)

        refused = {issue.use_case_id for issue in plan.findings
                   if issue.hard and issue.use_case_id}
        if refused:
            findings.extend(_studio_finding(issue) for issue in plan.findings
                            if issue.use_case_id in refused)
            survivors = tuple(case for case in survivors
                              if case.id not in refused)
            continue

        clash = next((issue for issue in plan.findings
                      if issue.code == CONFLICTING_COMPANY_DEMANDS), None)
        if clash is None:
            findings.extend(_studio_finding(issue) for issue in plan.findings)
            break

        pair = _clashing_pair(company, survivors, plan)
        if pair is None:
            # Studio says the set clashes, but no two cases clash alone. Its
            # current rule is strictly pairwise, so this should not happen;
            # if it ever does, stopping loudly beats guessing which to drop.
            findings.append(_studio_finding(clash))
            break

        kept, dropped = sorted(pair, key=lambda case_id: (-shares[case_id],
                                                          case_id))
        findings.append(hard(
            DROPPED_FOR_CONFLICT,
            f"{dropped} cannot share a world with {kept}: {clash.detail}. "
            f"{dropped} was dropped because fewer real sessions performed it "
            f"(share {shares[dropped]} against {shares[kept]})",
            cuj_id=dropped,
            detail={"kept": kept, "dropped": dropped, "reason": clash.detail}))
        survivors = tuple(case for case in survivors if case.id != dropped)

    return survivors, tuple(findings)


def import_catalogue(data: bytes, company: dict[str, Any], *,
                     cases: int = DEFAULT_CASES,
                     persona: str = DEFAULT_PERSONA,
                     audience: str = DEFAULT_AUDIENCE) -> ImportResult:
    """A catalogue's bytes in, a project ``worldloom studio init`` accepts out.

    Every stage, in order::

        load → match → sort → bind → build → Studio checks → share counts

    Counts are shared *after* the Studio checks, not before. A journey
    dropped for a conflict should not keep questions it can no longer
    answer; sharing last means the survivors divide the whole budget and the
    dropped journey's traffic shows up in ``share_lost``, where it belongs.

    Raises ``CatalogueRefused`` exactly as ``load_catalogue`` does. Everything
    after loading is reported as findings rather than raised.
    """
    catalogue, receipt = load_catalogue(data)
    piles = sort_catalogue(match_catalogue(catalogue))
    folds = fold_map(piles.report)
    catalogue_digest = digest_bytes(data)
    industry = catalogue.industry_hint.industry if catalogue.industry_hint else ""
    findings: list[Finding] = list(piles.report.findings)

    company_name = str((company.get("identity") or {}).get("company_name") or "")
    built: list[UseCase] = []
    for cuj in piles.write:
        question, bind_findings = bind_question(cuj, catalogue_digest,
                                                folds=folds)
        if question is not None:
            findings.extend(bind_findings)
            prompt = prompt_template(question, company_name=company_name)
            bindings = question.bindings
        else:
            # No real wording survived, so a built-in workflow's template
            # stands in. The finding names which one, so a reader can see
            # the question was not written by anyone at the customer.
            prompt, workflow = fallback_template(cuj)
            bindings = ()
            findings.extend(finding for finding in bind_findings
                            if finding.code != PHRASING_DEFAULT_USED)
            findings.append(info(
                PHRASING_DEFAULT_USED,
                f"{cuj.id} has no usable phrasing, so its question comes from "
                f"the built-in workflow {workflow!r} rather than from real "
                "wording",
                cuj_id=cuj.id,
                detail={"workflow": workflow,
                        "phrasings": str(len(cuj.phrasings))}))
        shape, shape_findings = record_shapes(cuj)
        findings.extend(shape_findings)
        built.append(build_use_case(cuj, prompt, bindings,
                                    industry=industry, persona=persona,
                                    audience=audience, folds=folds,
                                    shape=shape))

    shares = {cuj.id: cuj.support.share for cuj in piles.write}
    survivors, studio_findings = check_with_studio(company, tuple(built), shares)
    findings.extend(studio_findings)

    kept = {case.id for case in survivors}
    counts, count_findings = share_counts(
        piles.model_copy(update={"write": tuple(
            cuj for cuj in piles.write if cuj.id in kept)}),
        catalogue, cases=cases)
    findings.extend(count_findings)

    allotted = {allocation.cuj_id: allocation.count
                for allocation in counts.allocations}
    final = tuple(case.model_copy(update={"count": allotted[case.id]})
                  for case in survivors if case.id in allotted)
    project = (ProjectSpec(company=company, use_cases=final)
               if final else None)
    groups = {
        **{cuj.id: Group.WRITE for cuj in piles.write},
        **dict.fromkeys(piles.lookup, Group.LOOKUP),
        **dict.fromkeys(piles.no_world, Group.NO_WORLD),
        **dict.fromkeys(piles.blocked, Group.BLOCKED),
    }
    journeys = tuple(
        JourneyOutcome(cuj_id=cuj.id, label=cuj.label, group=groups[cuj.id],
                       share=cuj.support.share, count=allotted.get(cuj.id, 0)
                       if cuj.id in kept else 0)
        for cuj in sorted(catalogue.cujs, key=lambda cuj: cuj.id))
    return ImportResult(catalogue_id=catalogue.catalogue_id, journeys=journeys,
                        project=project, counts=counts, receipt=receipt,
                        report=ImportReport(findings=tuple(findings)))
