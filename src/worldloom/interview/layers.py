"""The interview's questions, in order, and the lint that refuses each answer.

One question at a time, each settled before the next exists, the order the
authoring stack already runs in (``/worldloom-author``): the company, its
lines of business, the people and their levels, each LOB's processes, the
documents those processes file, how the company changes over time, and what
its employees would ask an agent to do. A later question's context carries
what earlier answers settled, so every answer is written inside the box the
accepted work built.

Every lint delegates to the seam its answer feeds: ``company.resolve`` for
the company, ``lob.open``/``lob.accept`` and ``lob.lint_lob`` for a line of
business, ``episodes.lint`` for a process, ``doctypes.lint`` and
``packs.lint`` for the paperwork and the pack they assemble into,
``timeline.review`` for the history. The interview adds only the rules no
seam could state, because only the interview holds the pieces they relate:
a report sits at or below its manager's level, every process step names the
systems it touches, a document is approved above its author, and an eval
intent reads only systems a step declared.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from .. import packkit
from ..cascade import CascadeModel, Finding
from .model import (
    ANSWERS,
    LEVELS,
    CompanyAnswer,
    DocumentsAnswer,
    EmployeesAnswer,
    EvalsAnswer,
    LobsAnswer,
    ProcessesAnswer,
    TimelineAnswer,
    rank,
)
from .systems import DOCUMENT_ENTITIES, STEP_ENTITIES, SYSTEMS, writable

#: The layers, in the order they are asked.
LAYERS: tuple[str, ...] = ("company", "lobs", "employees", "processes", "documents", "timeline", "evals")


@dataclass(frozen=True)
class Question:
    """One question: which layer it settles, what it asks, and what earlier answers settled."""

    id: str
    layer: str
    asks: str
    context: dict[str, Any] = field(default_factory=dict)
    lob: str = ""


@dataclass(frozen=True)
class State:
    """The answers accepted so far, by question id, in the order they were accepted.

    A value, like a cascade ``Session``: accepting returns a new one and a
    refusal leaves the old one untouched, so a revision is judged against
    exactly the state that refused it.
    """

    answers: tuple[tuple[str, CascadeModel], ...] = ()

    def get(self, question_id: str) -> Any:
        for key, value in self.answers:
            if key == question_id:
                return value
        return None

    def accepted(self, question_id: str) -> bool:
        return self.get(question_id) is not None

    def with_answer(self, question_id: str, answer: CascadeModel) -> State:
        if self.accepted(question_id):
            raise ValueError(f"question {question_id!r} is already settled")
        return State(self.answers + ((question_id, answer),))

    # -- what earlier layers settled ------------------------------------

    @property
    def company(self) -> CompanyAnswer | None:
        value = self.get("company")
        return value if isinstance(value, CompanyAnswer) else None

    @property
    def lobs(self) -> LobsAnswer | None:
        value = self.get("lobs")
        return value if isinstance(value, LobsAnswer) else None

    @property
    def employees(self) -> EmployeesAnswer | None:
        value = self.get("employees")
        return value if isinstance(value, EmployeesAnswer) else None

    def processes(self) -> dict[str, ProcessesAnswer]:
        """Accepted processes answers by LOB name, in LOB order."""
        out: dict[str, ProcessesAnswer] = {}
        for key, value in self.answers:
            if key.startswith("processes:") and isinstance(value, ProcessesAnswer):
                out[key.split(":", 1)[1]] = value
        return out

    @property
    def documents(self) -> DocumentsAnswer | None:
        value = self.get("documents")
        return value if isinstance(value, DocumentsAnswer) else None

    @property
    def timeline(self) -> TimelineAnswer | None:
        value = self.get("timeline")
        return value if isinstance(value, TimelineAnswer) else None

    @property
    def evals(self) -> EvalsAnswer | None:
        value = self.get("evals")
        return value if isinstance(value, EvalsAnswer) else None


def questions(state: State) -> tuple[Question, ...]:
    """Every question this state can ask, in order. Per-LOB questions exist once the LOBs do."""
    listed = [_question("company", state), _question("lobs", state), _question("employees", state)]
    if state.lobs is not None:
        listed.extend(_question("processes", state, lob=draft.name) for draft in state.lobs.lobs)
    listed.extend(_question(layer, state) for layer in ("documents", "timeline", "evals"))
    return tuple(listed)


def next_question(state: State) -> Question | None:
    """The first question not yet settled, or ``None`` when the interview is complete."""
    for question in questions(state):
        if not state.accepted(question.id):
            return question
    return None


def _question(layer: str, state: State, *, lob: str = "") -> Question:
    identifier = f"{layer}:{lob}" if lob else layer
    asks = packkit.text(f"world.interview.ask.{layer}", lob=lob) if lob else packkit.text(f"world.interview.ask.{layer}")
    return Question(id=identifier, layer=layer, asks=asks, context=context(state, layer, lob=lob), lob=lob)


def context(state: State, layer: str, *, lob: str = "") -> dict[str, Any]:
    """What earlier answers settled, as a harness needs it to answer *layer*: data, never prose."""
    out: dict[str, Any] = {"layers": list(LAYERS), "levels": list(LEVELS), "systems": list(SYSTEMS)}
    resolution = company_resolution(state)
    if resolution is not None:
        out["company"] = {
            "name": resolution.pack.company_name if resolution.pack is not None else "",
            "engine": resolution.engine, "archetype": resolution.archetype_key,
            "units": [unit.key for unit in resolution.pack.units] if resolution.pack is not None else [],
            "role_table": [list(row) for row in (resolution.role_table or ())],
            "unmet": list(resolution.unmet),
        }
    if state.lobs is not None:
        out["lobs"] = [draft.model_dump(mode="json") for draft in state.lobs.lobs]
    if state.employees is not None:
        out["levels_by_role"] = dict(sorted(state.employees.levels.items()))
    processes = state.processes()
    if processes:
        out["processes"] = {
            name: {
                "episodes": [spec.name for spec in answer.episodes],
                "steps": {f"{spec.name}.{event.kind}": answer.systems.get(f"{spec.name}.{event.kind}", [])
                          for spec in answer.episodes for event in spec.events},
                "fact_kinds": sorted({fk.kind for spec in answer.episodes for fk in spec.fact_kinds}),
                "documents": sorted({artifact.artifact_type for spec in answer.episodes for artifact in spec.artifacts}),
            }
            for name, answer in processes.items()
        }
    if layer == "processes" and lob:
        out["lob"] = lob
    if state.documents is not None:
        out["documents"] = {chain.artifact_type: chain.model_dump(mode="json") for chain in state.documents.chains}
    if state.timeline is not None:
        from ..timeline import periods_from

        out["periods"] = list(periods_from(state.timeline.start, state.timeline.periods))
    return out


# ---------------------------------------------------------------------------
# Derived views the lints share
# ---------------------------------------------------------------------------


def company_resolution(state: State) -> Any:
    """The company specification, resolved, or ``None`` before the company is settled."""
    answer = state.company
    if answer is None:
        return None
    from .. import company

    return company.resolve(company.from_document(answer.spec))


def engine_of(state: State) -> str:
    resolution = company_resolution(state)
    return str(resolution.engine) if resolution is not None else ""


def lob_roles(state: State) -> dict[str, Any]:
    """Every role the LOBs declared, by key; the first declaration of a shared key wins."""
    roles: dict[str, Any] = {}
    for draft in state.lobs.lobs if state.lobs is not None else ():
        for role in draft.roles:
            roles.setdefault(role.key, role)
    return roles


def lob_of_role(state: State) -> dict[str, str]:
    """Which LOB each role belongs to: the first LOB that declares it outside the shared chain above it."""
    owners: dict[str, str] = {}
    for draft in state.lobs.lobs if state.lobs is not None else ():
        for role in draft.roles:
            owners.setdefault(role.key, draft.name)
    return owners


def all_episodes(state: State, *, extra: Sequence[Any] = ()) -> list[Any]:
    return [spec for answer in state.processes().values() for spec in answer.episodes] + list(extra)


def planned_documents(state: State) -> dict[str, tuple[str, str, str]]:
    """Every artifact type a process plans -> (process, author role, triggering event kind)."""
    planned: dict[str, tuple[str, str, str]] = {}
    for spec in all_episodes(state):
        for artifact in spec.artifacts:
            trigger = artifact.triggered_by_events[0] if artifact.triggered_by_events else ""
            planned.setdefault(artifact.artifact_type, (spec.name, artifact.author_role, trigger))
    return planned


def process_lob(state: State) -> dict[str, str]:
    """Process name -> the LOB that runs it."""
    return {spec.name: lob for lob, answer in state.processes().items() for spec in answer.episodes}


# ---------------------------------------------------------------------------
# The lint, per layer
# ---------------------------------------------------------------------------


def parse(layer: str, answer: Mapping[str, Any] | None) -> tuple[CascadeModel | None, list[Finding]]:
    """*answer* as *layer*'s model, or every field it gets wrong."""
    if not isinstance(answer, Mapping):
        return None, ["answer: the reply carries no `answer` object"]
    try:
        return ANSWERS[layer].model_validate(dict(answer)), []
    except ValidationError as error:
        return None, [
            f"{'.'.join(str(part) for part in problem.get('loc', ())) or 'answer'}: {problem.get('msg', 'invalid')}"
            for problem in error.errors()[:12]
        ]


def lint(question: Question, answer: Mapping[str, Any] | None, state: State) -> tuple[CascadeModel | None, list[Finding]]:
    """Judge one answer to *question* against *state*. Every finding at once; nothing is committed."""
    parsed, findings = parse(question.layer, answer)
    if parsed is None:
        return None, findings
    checks = {
        "company": _lint_company, "lobs": _lint_lobs, "employees": _lint_employees,
        "processes": _lint_processes, "documents": _lint_documents, "timeline": _lint_timeline,
        "evals": _lint_evals,
    }
    findings = checks[question.layer](parsed, state, question)
    return parsed, findings


def _lint_company(answer: Any, state: State, question: Question) -> list[Finding]:
    from .. import company, domains

    try:
        spec = company.from_document(answer.spec)
    except (ValueError, TypeError) as error:
        return [f"spec: {error}"]
    resolution = company.resolve(spec)
    findings = [f"spec: {conflict}" for conflict in resolution.conflicts]
    if spec.identity is None or not spec.identity.company_name.strip():
        findings.append("spec.identity.company_name: required, so the world is one particular company rather than "
                        "the engine's default; name it")
    elif spec.pack:
        findings.append("spec.pack: an interview composes the pack from its answers; drop `pack` and describe the company")
    if not findings:
        domain = domains.by_name(resolution.engine)
        if resolution.pack is None:
            findings.append("spec: the description composed no pack; give it an identity and an engine")
        elif domain is None or not hasattr(domain.world, "from_pack"):
            findings.append(f"spec.engine: {resolution.engine!r} cannot build from a pack; choose an engine that can")
    return findings


def _lint_lobs(answer: Any, state: State, question: Question) -> list[Finding]:
    from .. import lob

    engine = engine_of(state)
    findings: list[Finding] = []
    if len(answer.lobs) < 2:
        findings.append("lobs: name at least two lines of business; an executive's question spans more than one")
    seen: set[str] = set()
    for draft in answer.lobs:
        if draft.name in seen:
            findings.append(f"lobs[{draft.name}]: declared twice")
        seen.add(draft.name)
        seed = lob.LobSeed(name=draft.name, title=draft.title, purpose=draft.purpose, engine=engine)
        findings.extend(f"lobs[{draft.name}]: {finding}" for finding in lob.lint_seed(seed))
        try:
            lob.accept(lob.open(seed), lob.Answer(stage="roles", roles=list(draft.roles)))
        except ValueError as refusal:
            findings.append(f"lobs[{draft.name}]: {refusal}")
    # One key is one post: two LOBs may share the chain above them, never disagree about it.
    held: dict[str, Any] = {}
    for draft in answer.lobs:
        for role in draft.roles:
            first = held.setdefault(role.key, (draft.name, role))
            if first[1].reports_to != role.reports_to:
                findings.append(f"lobs[{draft.name}]: role {role.key!r} reports to {role.reports_to!r} here and to "
                                f"{first[1].reports_to!r} in {first[0]}; one post has one manager")
    return findings


def _a(level: str) -> str:
    """*level* with its article: an ic, a manager, a director, an executive."""
    label = "individual contributor" if level == "ic" else level
    return f"{'an' if label[:1] in 'aeiou' else 'a'} {label}"


def _lint_employees(answer: Any, state: State, question: Question) -> list[Finding]:
    roles = lob_roles(state)
    levels = dict(answer.levels)
    findings: list[Finding] = []
    for key in sorted(set(roles) - set(levels)):
        findings.append(f"levels: role {key!r} has no level; give it one of {', '.join(LEVELS)}")
    for key in sorted(set(levels) - set(roles)):
        findings.append(f"levels: {key!r} is no role the lines of business declared; drop it or declare it")
    for key, role in sorted(roles.items()):
        if key not in levels:
            continue
        if role.reports_to is None and levels[key] != "executive":
            findings.append(f"levels[{key}]: the root of the organisation is an executive, not {levels[key]}")
        manager = role.reports_to
        if manager in levels and rank(levels[key]) > rank(levels[manager]):
            findings.append(f"levels[{key}]: {_a(levels[key])} cannot report to {manager!r}, {_a(levels[manager])}; "
                            "lower this role or raise its manager")
    missing = [level for level in LEVELS if level not in set(levels.values())]
    if missing:
        findings.append(f"levels: nobody sits at {', '.join(missing)}; the evals ask one question per level, so "
                        "every level needs somebody to ask it")
    return findings


def _lint_processes(answer: Any, state: State, question: Question) -> list[Finding]:
    from .. import episodes, lob

    engine = engine_of(state)
    findings: list[Finding] = []
    draft = next((item for item in state.lobs.lobs if item.name == question.lob), None) if state.lobs else None
    if draft is None:
        return [f"lob {question.lob!r} is not one the lines of business declared"]
    others = {spec.name for name, other in state.processes().items() if name != question.lob for spec in other.episodes}
    for spec in answer.episodes:
        if spec.name in others:
            findings.append(f"episodes[{spec.name}]: another line of business already runs a process of this name")
        if spec.domain != engine:
            findings.append(f"episodes[{spec.name}]: domain {spec.domain!r} is not the company's engine {engine!r}")
        functions = {role.key: role.function for role in draft.roles}
        for artifact in spec.artifacts:
            if artifact.author_role not in functions:
                findings.append(f"episodes[{spec.name}]: document {artifact.artifact_type!r} is authored by "
                                f"{artifact.author_role!r}, which {question.lob} does not declare")
                continue
            # The compiler's cohesion contract (`documents._contracted`), read
            # here so it refuses the answer rather than the build: a document's
            # domain names the functions that may own it.
            from ..documents import _DOMAIN_AUTHORS

            if artifact.domain not in _DOMAIN_AUTHORS:
                findings.append(f"episodes[{spec.name}]: document {artifact.artifact_type!r} has domain "
                                f"{artifact.domain!r}, which no contract declares; use one of {', '.join(sorted(_DOMAIN_AUTHORS))}")
                continue
            permitted = _DOMAIN_AUTHORS[artifact.domain]
            if permitted is not None and functions[artifact.author_role] not in permitted:
                findings.append(f"episodes[{spec.name}]: a {functions[artifact.author_role]} author "
                                f"({artifact.author_role}) cannot own {'an' if artifact.domain[:1] in 'aeiou' else 'a'} {artifact.domain} document "
                                f"({artifact.artifact_type}); its owners are {', '.join(sorted(permitted))}")
    role_keys = sorted({*(row[0] for row in (company_resolution(state).role_table or ())), *lob_roles(state)})
    findings.extend(episodes.lint(answer.episodes, base=engine, role_keys=role_keys))
    # Every step names where it leaves a record; nothing else may be named.
    steps = {f"{spec.name}.{event.kind}" for spec in answer.episodes for event in spec.events}
    for step in sorted(steps - set(answer.systems)):
        findings.append(f"systems[{step}]: this step names no system; list where it leaves a record ({', '.join(sorted(STEP_ENTITIES))})")
    for step, systems in sorted(answer.systems.items()):
        if step not in steps:
            findings.append(f"systems[{step}]: no process of this answer declares that event; key by `Process.event_kind`")
        if not systems and step in steps:
            findings.append(f"systems[{step}]: name at least one system")
        for system in systems:
            if system not in STEP_ENTITIES:
                findings.append(f"systems[{step}]: {system!r} keeps no process steps; use one of {', '.join(sorted(STEP_ENTITIES))}")
    touched = {system for systems in answer.systems.values() for system in systems}
    if len(touched) < 2:
        findings.append("systems: the processes touch fewer than two systems; a manager's question reads two")
    # The LOB, completed: its accountability edges and seats, linted by the LOB seam itself.
    completed = lob.Lob(
        name=draft.name, title=draft.title, purpose=draft.purpose, engine=engine, roles=list(draft.roles),
        responsibilities=list(answer.responsibilities), episode_contributions=[spec.name for spec in answer.episodes],
        slot_bindings=list(answer.slot_bindings),
    )
    planned = {artifact.artifact_type for spec in answer.episodes for artifact in spec.artifacts}
    findings.extend(lob.lint_lob(completed, base=engine, episodes=all_episodes(state, extra=answer.episodes),
                                 known_artifact_types=planned | set(planned_documents(state))))
    for spec in answer.episodes:
        bound = {binding.slot for binding in answer.slot_bindings if binding.process == spec.name}
        for slot in spec.role_slots:
            if slot.required and slot.slot not in bound:
                findings.append(f"episodes[{spec.name}]: required slot {slot.slot!r} is bound by no role of {question.lob}")
    return findings


def _lint_documents(answer: Any, state: State, question: Question) -> list[Finding]:
    from .. import documents

    findings: list[Finding] = []
    planned = planned_documents(state)
    declared = {doctype.key for doctype in answer.doctypes}
    # What an engine declares, not what a pack built earlier in this process
    # installed (`doctypes.installed`): the answer is judged the same in a
    # fresh process as in one that has built other companies.
    from ..doctypes import installed

    shipped = set(documents.declared_types()) - set(installed())
    for artifact_type in sorted(set(planned) - declared - shipped):
        findings.append(f"doctypes: {artifact_type!r} is planned by {planned[artifact_type][0]} and declared by no "
                        "engine; declare it here")
    chains = {chain.artifact_type: chain for chain in answer.chains}
    levels = state.employees.levels if state.employees is not None else {}
    for artifact_type in sorted(set(planned) - set(chains)):
        findings.append(f"chains: {artifact_type!r} has no review chain; name its reviewer and approver")
    for artifact_type, chain in sorted(chains.items()):
        if artifact_type not in planned:
            findings.append(f"chains[{artifact_type}]: no process plans this document")
            continue
        author = planned[artifact_type][1]
        author_rank = rank(levels[author]) if author in levels else 0
        for seat, holder in (("reviewer", chain.reviewer), ("approver", chain.approver)):
            if holder is None:
                continue
            if holder not in levels:
                findings.append(f"chains[{artifact_type}].{seat}: {holder!r} is no role with a level")
                continue
            if rank(levels[holder]) < author_rank:
                findings.append(f"chains[{artifact_type}].{seat}: {holder!r} ({levels[holder]}) sits below the author "
                                f"{author!r} ({levels.get(author, '?')})")
        if chain.approver is not None and chain.approver in levels and rank(levels[chain.approver]) == author_rank \
                and levels.get(author) != "executive":
            findings.append(f"chains[{artifact_type}].approver: approval goes up; {chain.approver!r} is not above the author")
        if chain.approver is not None and chain.approver == author:
            findings.append(f"chains[{artifact_type}].approver: nobody approves their own document")
        for system in chain.published_on:
            if system not in DOCUMENT_ENTITIES:
                findings.append(f"chains[{artifact_type}].published_on: {system!r} holds no documents; use "
                                f"{', '.join(sorted(DOCUMENT_ENTITIES))}")
    authored_levels = {levels.get(author) for _, author, _ in planned.values()}
    for level in ("manager", "director", "executive"):
        if level not in authored_levels:
            findings.append(f"documents: no {level} authors a document; each of manager, director and executive files one")
    if not findings:
        from .assemble import pack_of

        findings.extend(f"pack: {finding}" for finding in _pack_findings(pack_of(state, documents=answer),
                                                                          lore_pending=True))
    return findings


def _pack_findings(pack: Any, *, lore_pending: bool = False) -> list[Finding]:
    """``packs.lint`` on the assembled pack.

    *lore_pending* drops the one finding about lore being absent: the policies
    are the timeline question's to answer, so asking the documents question
    to supply them would be asking two questions at once.
    """
    from .. import packs

    findings = list(packs.lint(pack))
    if lore_pending and not pack.lore:
        findings = [finding for finding in findings if "carries no lore" not in finding]
    return findings


def _lint_timeline(answer: Any, state: State, question: Question) -> list[Finding]:
    from .. import timeline as timeline_module
    from .assemble import history, pack_of, world_of

    findings: list[Finding] = []
    periods = timeline_module.periods_from(answer.start, answer.periods)
    for period in answer.incidents:
        if period not in periods:
            findings.append(f"incidents: {period} is outside the history {periods[0]} to {periods[-1]}")
    for index, change in enumerate(answer.changes):
        if change.period not in periods:
            findings.append(f"changes[{index}]: {change.period} is outside the history")
    later = [policy for policy in answer.policies if policy.effective_from > periods[0]]
    if not later:
        findings.append("policies: none takes effect after the first period, so nothing changes what later documents "
                        "say; date at least one policy inside the history")
    for index, policy in enumerate(answer.policies):
        if policy.effective_from > periods[-1]:
            findings.append(f"policies[{index}]: effective {policy.effective_from}, after the history ends")
    if findings:
        return findings
    pack = pack_of(state, timeline=answer)
    findings.extend(f"pack: {finding}" for finding in _pack_findings(pack))
    if findings:
        return findings
    from .. import registries

    # Built to be reviewed against, then forgotten: a build installs the
    # pack's types, processes and LOBs for the life of the process, and a
    # later lint that read them would judge the next answer by this one.
    with registries.scoped():
        try:
            world = world_of(state, pack=pack)
            history_value = history(answer)
        except (ValueError, KeyError) as error:
            return [f"changes: {error}"]
        roster = timeline_module.Roster.of(world)
    findings.extend(f"history: {violation}" for violation in timeline_module.review(history_value, roster))
    return findings


def _lint_evals(answer: Any, state: State, question: Question) -> list[Finding]:
    from ..timeline import periods_from

    findings: list[Finding] = []
    levels = state.employees.levels if state.employees is not None else {}
    processes = state.processes()
    steps: dict[str, list[str]] = {step: systems for answer_ in processes.values() for step, systems in answer_.systems.items()}
    owner = process_lob(state)
    planned = planned_documents(state)
    chains = {chain.artifact_type: chain for chain in state.documents.chains} if state.documents else {}
    periods = periods_from(state.timeline.start, state.timeline.periods) if state.timeline else ()
    cap = int(packkit.policy("world.interview.max_reads"))
    seen: set[str] = set()
    for intent in answer.intents:
        where = f"intents[{intent.id}]"
        if intent.id in seen:
            findings.append(f"{where}: id used twice")
        seen.add(intent.id)
        if intent.asker not in levels:
            findings.append(f"{where}: asker {intent.asker!r} is no role with a level")
        elif levels[intent.asker] != intent.level:
            findings.append(f"{where}: {intent.asker!r} is {_a(levels[intent.asker])}, not {_a(intent.level)}; an "
                            "employee asks at their own level")
        if len(intent.reads) > cap:
            findings.append(f"{where}: {len(intent.reads)} reads; at most {cap}")
        lobs_read: set[str] = set()
        systems_read: set[str] = set()
        for index, read in enumerate(intent.reads):
            at = f"{where}.reads[{index}]"
            if read.is_document:
                if read.document not in planned:
                    findings.append(f"{at}: no process files {read.document!r}")
                    continue
                process, _, _ = planned[read.document]
                lobs_read.add(owner.get(process, ""))
                system = read.system or (chains[read.document].published_on[0] if read.document in chains and chains[read.document].published_on else "sharepoint")
                if read.document in chains and system not in chains[read.document].published_on:
                    findings.append(f"{at}: {read.document!r} is published on {chains[read.document].published_on}, not {system!r}")
                systems_read.add(system)
                if read.period not in {"latest", "first", "previous", "all"} and read.period not in periods:
                    findings.append(f"{at}: period {read.period!r} is neither latest, first, previous, all nor a period of the history")
                continue
            step = f"{read.process}.{read.step}"
            if step not in steps:
                findings.append(f"{at}: {step!r} is no process step the interview declared")
                continue
            if read.system not in steps[step]:
                findings.append(f"{at}: step {step!r} leaves records on {steps[step]}, not {read.system!r}")
            if read.period not in {"latest", "first", "previous", "all"} and read.period not in periods:
                findings.append(f"{at}: period {read.period!r} is neither latest, first, previous, all nor a period of the history")
            lobs_read.add(owner.get(read.process, ""))
            systems_read.add(read.system)
        # A case binds its fixture records per connector entity
        # (`QueryFixture.input_record_ids`), so two reads of one entity on one
        # system would share one fixture and the second would silently replace
        # the first. Refused here, where the interviewee can move one read.
        sources: dict[tuple[str, str], int] = {}
        for index, read in enumerate(intent.reads):
            if read.is_document:
                system = read.system or (chains[read.document].published_on[0] if read.document in chains else "sharepoint")
                pair = (system, DOCUMENT_ENTITIES.get(system, ""))
            else:
                pair = STEP_ENTITIES.get(read.system, (read.system, ""))
            if pair in sources:
                findings.append(f"{where}.reads[{index}]: reads {pair[0]} {pair[1]} records, as reads[{sources[pair]}] "
                                "already does; one case reads each system entity once, so read this on another "
                                "system it is recorded or published on")
            sources.setdefault(pair, index)
        if intent.branch is not None and intent.branch.read >= len(intent.reads):
            findings.append(f"{where}.branch: read {intent.branch.read} does not exist")
        deliver = intent.deliver
        problem = writable(deliver.system, deliver.entity, deliver.operation, deliver.format)
        if problem:
            findings.append(f"{where}.deliver: {problem}")
        findings.extend(f"{where}: {finding}" for finding in _level_contract(intent, systems_read, lobs_read))
    present = {intent.level for intent in answer.intents}
    for level in LEVELS:
        if level not in present:
            findings.append(f"intents: nobody at {level} asks anything; give every level at least one intent")
    # A level's cases are served together, and one served case set admits a
    # bounded tool catalogue: a level whose systems exceed it could be
    # planned and never run.
    from .cases import tool_budget

    for level in LEVELS:
        systems = {read.system or "sharepoint" for intent in answer.intents if intent.level == level for read in intent.reads}
        systems |= {intent.deliver.system for intent in answer.intents if intent.level == level}
        if not systems:
            continue
        try:
            tools, admitted = tool_budget(sorted(systems))
        except (KeyError, ValueError):
            continue
        if tools > admitted:
            findings.append(f"intents: the {level} intents touch {', '.join(sorted(systems))}, {tools} connector tools; "
                            f"one served case set admits {admitted}, so read or deliver on fewer systems at this level")
    return findings


def _level_contract(intent: Any, systems: set[str], lobs: set[str]) -> list[Finding]:
    """What each level's question must be shaped like: the difficulty ladder, stated as rules."""
    documents = [read for read in intent.reads if read.is_document]
    out: list[Finding] = []
    if intent.level == "ic":
        if len(intent.reads) != 1 or documents:
            out.append("an individual contributor reads one system once; give exactly one step read")
        if intent.branch is not None or intent.per_entity:
            out.append("an individual contributor's task has no branch and no per-entity map")
    elif intent.level == "manager":
        if len(systems) < 2:
            out.append("a manager's question fans in across at least two systems")
        if intent.branch is not None:
            out.append("a manager's question fans in; branching on data is a director's")
    elif intent.level == "director":
        if not documents:
            out.append("a director reads a document at a stated period")
        if intent.branch is None:
            out.append("a director's write depends on the data; give a `branch`")
        if len(intent.reads) < 2:
            out.append("a director reads a document and at least one system")
    else:
        if len(lobs - {""}) < 2:
            out.append("an executive's question synthesises across at least two lines of business")
        if not intent.per_entity:
            out.append("an executive's question maps over each entity; set `per_entity`")
        if len(intent.reads) < 3:
            out.append("an executive reads at least three sources")
    return out


__all__ = ["LAYERS", "Question", "State", "company_resolution", "context", "engine_of", "lint", "lob_of_role",
           "lob_roles", "next_question", "parse", "planned_documents", "process_lob", "questions"]
