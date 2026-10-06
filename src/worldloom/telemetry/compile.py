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
from typing import TYPE_CHECKING, Any

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
from ..providers import Receipt, digest_bytes
from ..studio.construction import (
    ConstructionIssue,
    ConstructionPlan,
    compile_project,
)
from ..studio.models import ProjectSpec, UseCase
from .binding import PHRASING_DEFAULT_USED, BindRule, bind_question, fold_map
from .catalogue import Catalogue, Cuj, load_catalogue
from .registry import match_catalogue
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

PHRASING_DEFAULT_UNAVAILABLE = "phrasing_default_unavailable"
"""A write journey with no usable phrasing. The design document falls back
to a built-in workflow's template, but those are ``str.format`` strings and
need the same treatment as the rest of the question text, which is not done
yet. Refused by name rather than built with a question nobody wrote."""


class ImportResult(Model):
    """Everything one import produced: the project, the split, the receipt,
    and every finding along the way."""

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

    built: list[UseCase] = []
    for cuj in piles.write:
        question, bind_findings = bind_question(cuj, catalogue_digest,
                                                folds=folds)
        if question is None:
            # ``bind_question`` reports that a default template will be used.
            # It will not be, yet, so that finding would be untrue here.
            findings.extend(finding for finding in bind_findings
                            if finding.code != PHRASING_DEFAULT_USED)
            findings.append(hard(
                PHRASING_DEFAULT_UNAVAILABLE,
                f"{cuj.id} has no usable phrasing, and the built-in fallback "
                "the design document describes is not implemented yet",
                cuj_id=cuj.id))
            continue
        findings.extend(bind_findings)
        built.append(build_use_case(cuj, question, question.bindings,
                                    industry=industry, persona=persona,
                                    audience=audience))

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
    return ImportResult(project=project, counts=counts, receipt=receipt,
                        report=ImportReport(findings=tuple(findings)))
