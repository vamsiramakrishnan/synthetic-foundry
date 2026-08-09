"""Lines of Business as authored data — a schema and a cascade.

A LOB spec is built in stages, like a probe. A harness seeds a LOB with a
minimal premise — name, purpose, engine — and then asks for roles and
responsibility edges through a handshake, refusing incoherence at each stage.
The final accepted spec — roles, responsibilities, and derived accountability
structures — rides the pack/recipe and replays byte-for-byte.

**Responsibilities are the cohesion primitive.** One declared edge — "the
controller answers for financial facts and authors memos" — derives:
- role table rows
- authorship hints the planner reads
- accountability facts minting a person and a measure

Never five hand-written tables: declare responsibility once, derive all
consequences.

**The cascade.** Stage one: seed with name, purpose, engine. Stage two: propose
roles. Stage three: propose responsibility edges (refused if they name fact
kinds nothing generates). Final: the harness derives the role table,
authorship hints, and accountability mapping from accepted responsibilities.

**Determinism.** The final accepted spec is deterministic and replays from
the ledger. Entries are ordered by key; no draw, no clock, no set iteration.

**The cascade is an instance of the shared protocol** (``cascade.py``), which
states the invariants once: a refusal carries findings a reviser can act on
and commits nothing, stages are ordered, context rides every brief, and only
the resolved spec replays — never this conversation. Iteration and resumption
follow from the ``Session`` being a frozen value of accepted stages: a refused
answer leaves the session unchanged, so a stage may be revised and resubmitted
any number of times, and a session is resumed by replaying its accepted
answers through ``open``/``accept`` — the same way a probe's ledger rebuilds
its graph.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field as _field, replace
from pathlib import Path
from typing import Any

from pydantic import Field

from . import cascade
from .cascade import Brief, CascadeModel
from .models import ConstraintKind, LoreConstraint
from .roles import Role, to_rows

__all__ = [
    "LobSeed", "Lob", "RoleSpec", "Responsibility", "SlotBinding",
    "Participant", "load_seed", "open", "resolve", "publish", "installed",
    "describe", "lint_seed", "lint_roles", "lint_responsibilities",
    "lint_bindings", "participation", "accountability_constraints",
]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class LobModel(CascadeModel):
    """Base for all LOB schema objects — frozen and closed, per the protocol."""


class RoleSpec(LobModel):
    """One role a LOB declares."""

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    """The role's key, lowercase snake_case. Appears in ids and lookups."""
    title: str = Field(min_length=1)
    """The role's title — what documents print."""
    function: str = Field(min_length=1)
    """The function this role sits in (Finance, Technology, etc.)."""
    reports_to: str | None = None
    """The role this one reports to, or None for the root."""

    def as_row(self) -> tuple[str, str, str, str | None]:
        """Convert to the tuple shape generators consume."""
        return (self.key, self.title, self.function, self.reports_to)


class Responsibility(LobModel):
    """One role's accountability for facts and documents."""

    role_key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    """The role answerable for this responsibility."""
    fact_kinds: list[str] = Field(default_factory=list)
    """Fact kinds this role answers for (e.g., 'financial.revenue')."""
    artifact_types: list[str] = Field(default_factory=list)
    """Artifact types this role authors or approves."""


class SlotBinding(LobModel):
    """One of this LOB's roles, bound into a seat a process declares.

    The division of vocabulary is the settled design (docs/next-phase-plan.md,
    "Who authors a process"): a process declares *slots* — preparer,
    challenger, approver, in its own words and its own order — and the company
    says which of its roles sits in each. The slots are the process's
    vocabulary; this binding is the company's. A binding lives on the LOB and
    not on the process spec because the same process runs at every company
    that adopts it, each with different role keys in the seats.
    """

    process: str = Field(pattern=r"^[A-Z][a-zA-Z0-9]*$")
    """The process spec's name (``episodes.EpisodeSpec.name``)."""
    slot: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    """The declared slot being filled."""
    role_key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    """This LOB's role taking the seat."""


class LobSeed(LobModel):
    """The seed for a new LOB: minimal, just name and purpose."""

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    """The LOB's key name."""
    title: str = Field(min_length=1)
    """A short title (e.g., 'Finance')."""
    purpose: str = Field(min_length=1)
    """One sentence describing why this LOB exists."""
    engine: str = Field(min_length=1)
    """Which engine this LOB is for (retail, banking, insurance)."""


class Lob(LobModel):
    """A complete, accepted LOB specification.

    This is what rides the pack/recipe and replays. Derived from accepted
    roles and responsibilities; never authored directly.
    """

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    engine: str = Field(min_length=1)
    roles: list[RoleSpec]
    responsibilities: list[Responsibility]
    artifact_filings: list[str] = Field(default_factory=list)
    episode_contributions: list[str] = Field(default_factory=list)
    slot_bindings: list[SlotBinding] = Field(default_factory=list)
    """This company's roles in the seats its processes declare. Checked by
    ``lint_bindings`` against each process spec — an unbound required slot and
    a binding to a role this LOB lacks are both refused there."""


@dataclass(frozen=True)
class Session:
    """A LOB being authored, stored between calls.

    The graph and final spec are *derived*, never stored. This holds only
    the accepted stages: seed and the accepted answers to each stage.
    """

    name: str
    title: str
    purpose: str
    engine: str
    #: Accepted roles, keyed by role_key for lookup
    roles: Mapping[str, RoleSpec] = _field(default_factory=dict)
    #: Accepted responsibilities
    responsibilities: tuple[Responsibility, ...] = ()

    def to_lob(
        self,
        artifact_filings: list[str] | None = None,
        episode_contributions: list[str] | None = None,
    ) -> Lob:
        """Convert the session to a final Lob spec."""
        return Lob(
            name=self.name,
            title=self.title,
            purpose=self.purpose,
            engine=self.engine,
            roles=list(self.roles.values()),
            responsibilities=list(self.responsibilities),
            artifact_filings=artifact_filings or [],
            episode_contributions=episode_contributions or [],
        )

    def to_role_table(self) -> tuple[Role, ...]:
        """Derive the role table from accepted roles."""
        return tuple(Role(*spec.as_row()) for spec in self.roles.values())


# The next question in LOB authoring is the protocol's own `Brief` — stage
# ('roles' or 'responsibilities'), question, context. Imported, not redefined:
# an identical dataclass per cascade is how the shapes drift apart.


class Answer(LobModel):
    """One answer to a LOB brief."""

    stage: str = Field(min_length=1)
    roles: list[RoleSpec] = Field(default_factory=list)
    """If stage is 'roles', the proposed roles."""
    responsibilities: list[Responsibility] = Field(default_factory=list)
    """If stage is 'responsibilities', the proposed edges."""


# ---------------------------------------------------------------------------
# Cascade operations
# ---------------------------------------------------------------------------


def open(seed: LobSeed | dict[str, Any]) -> Session:
    """Start authoring a new LOB from a seed.

    Args:
        seed: A ``LobSeed`` or a dict matching its shape.

    Returns:
        A ``Session`` ready for the role-proposal stage.
    """
    if isinstance(seed, dict):
        seed = LobSeed.model_validate(seed)
    return Session(
        name=seed.name,
        title=seed.title,
        purpose=seed.purpose,
        engine=seed.engine,
    )


def next_stage(session: Session) -> Brief:
    """What to ask the harness next.

    Returns:
        A ``Brief`` with the stage, question, and context needed to answer.
    """
    if not session.roles:
        return Brief(
            stage="roles",
            asks="Propose the roles this LOB needs, each with a key, title, "
            "function, and who it reports to. One role should report to nobody "
            "(the root). These will be checked for tree structure and "
            "consistency.",
            context={
                "example_role": {
                    "key": "controller",
                    "title": "Financial Controller",
                    "function": "Finance",
                    "reports_to": "cfo",
                }
            },
        )
    if not session.responsibilities:
        return Brief(
            stage="responsibilities",
            asks="For each role, propose what facts and documents it answers for. "
            "A responsibility is a role_key, a list of fact_kinds, and a list of "
            "artifact_types. These will be refused if they name fact kinds or "
            "types that nothing in the corpus declares.",
            context={"roles": {k: v.title for k, v in session.roles.items()}},
        )
    return Brief(
        stage="resolve",
        asks="All stages are complete. Call resolve() to finalize the LOB.",
        context={},
    )


def accept(
    session: Session,
    answer: Answer | dict[str, Any],
) -> Session:
    """Accept an answer to a brief.

    Args:
        session: The current ``Session``.
        answer: An ``Answer`` or dict matching its shape.

    Returns:
        A new ``Session`` with the answer incorporated.

    Raises:
        ValueError: If the answer is invalid for the current stage.
    """
    if isinstance(answer, dict):
        answer = Answer.model_validate(answer)

    if answer.stage == "roles":
        findings = lint_roles(answer.roles, engine=session.engine)
        if findings:
            cascade.refuse("roles", findings)
        roles = {r.key: r for r in answer.roles}
        return replace(session, roles=roles)

    if answer.stage == "responsibilities":
        findings = lint_responsibilities(
            answer.responsibilities,
            roles=[r.key for r in session.roles.values()],
        )
        if findings:
            cascade.refuse("responsibilities", findings)
        return replace(session, responsibilities=tuple(answer.responsibilities))

    raise ValueError(f"unknown stage: {answer.stage!r}")


def resolve(
    session: Session,
    artifact_filings: list[str] | None = None,
    episode_contributions: list[str] | None = None,
) -> Lob:
    """Finalize the LOB from an accepted session.

    At this point, all stages are complete and the spec is ready to ride the
    pack/recipe. The role table and accountability mapping are derived from
    the accepted responsibilities.

    Args:
        session: The completed ``Session``.
        artifact_filings: Optional list of doctype names this LOB files.
        episode_contributions: Optional list of episodes this LOB participates in.

    Returns:
        A final ``Lob`` spec ready to be installed.
    """
    if not session.roles or not session.responsibilities:
        raise ValueError("cannot resolve: not all stages have been accepted yet")

    return session.to_lob(
        artifact_filings=artifact_filings,
        episode_contributions=episode_contributions,
    )


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_seed(source: str | Path | dict[str, Any]) -> LobSeed:
    """Load a LOB seed from a path, JSON text, or parsed data."""
    return cascade.load(source, LobSeed)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


#: All installed LOBs, by name.
_INSTALLED: dict[str, Lob] = {}


def installed() -> dict[str, Lob]:
    """The LOBs this process holds. A copy: the registry is not a surface."""
    return dict(_INSTALLED)


def describe(lob_name: str) -> dict[str, Any] | None:
    """An installed LOB as a document, or None if not found.

    A dict rather than the ``Lob`` itself, matching every other ``describe`` in
    this project (``sdk.Blueprint``, ``mosaic``, ``company``), because the
    interesting half is *derived*: ``participation`` is who this LOB puts into
    each process this Python process holds, computed as the join — never stored
    on the spec, where it could disagree with the responsibilities it comes
    from. ``installed()[name]`` still returns the spec itself.
    """
    spec = _INSTALLED.get(lob_name)
    if spec is None:
        return None
    from . import episodes

    joined: dict[str, list[dict[str, Any]]] = {}
    for process_name in sorted(episodes.loaded()):
        participants = participation(spec, episodes.loaded()[process_name])
        if participants:
            joined[process_name] = [
                {
                    "role": p.role_key, "title": p.title,
                    "slots": list(p.slots), "kinds": list(p.kinds),
                    "via": list(p.via),
                }
                for p in participants
            ]
    return {
        "name": spec.name,
        "title": spec.title,
        "purpose": spec.purpose,
        "engine": spec.engine,
        "roles": {role.key: role.title for role in spec.roles},
        "responsibilities": [
            {"role": r.role_key, "fact_kinds": list(r.fact_kinds),
             "artifact_types": list(r.artifact_types)}
            for r in spec.responsibilities
        ],
        "artifact_filings": list(spec.artifact_filings),
        "episode_contributions": list(spec.episode_contributions),
        "slot_bindings": [
            {"process": b.process, "slot": b.slot, "role": b.role_key}
            for b in spec.slot_bindings
        ],
        "participation": joined,
    }


def install(lobs: Sequence[Lob]) -> None:
    """Register *lobs* into the process registry.

    Refuses a LOB already installed with a different spec.
    """
    fresh = [lob for lob in lobs if _INSTALLED.get(lob.name) != lob]
    if not fresh:
        return

    for spec in fresh:
        _INSTALLED[spec.name] = spec


# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------


def lint_seed(seed: LobSeed | dict[str, Any]) -> list[str]:
    """Findings for a LOB seed before opening."""
    from . import domains

    if isinstance(seed, dict):
        try:
            seed = LobSeed.model_validate(seed)
        except Exception as e:
            return [str(e)]

    findings: list[str] = []
    if not seed.name or not seed.name.replace("_", "").isalnum():
        findings.append("name must be lowercase alphanumerics and underscores")
    # The domain registry, not a literal: this check used to type out
    # retail/banking/insurance, and the day procurement registered as the
    # fourth domain it started refusing a real engine — the exact closed-list
    # drift `domains.py` exists to end. Same check `process.lint_seed` runs.
    if domains.by_name(seed.engine) is None:
        findings.append(
            f"engine {seed.engine!r} is not a registered domain; known:"
            f" {domains.names()}"
        )
    return findings


def lint_roles(
    roles: Sequence[RoleSpec],
    *,
    engine: str = "",
) -> list[str]:
    """Findings for proposed roles before accepting."""
    findings: list[str] = []

    if not roles:
        findings.append("must propose at least one role")
        return findings

    by_key: dict[str, RoleSpec] = {}
    for i, role in enumerate(roles):
        if role.key in by_key:
            findings.append(f"roles[{i}]: key '{role.key}' is duplicated")
            continue

        if not role.key or not role.key.replace("_", "").isalnum():
            findings.append(
                f"roles[{i}] ({role.key}): key must be lowercase"
                " alphanumerics and underscores"
            )

        if not role.title.strip():
            findings.append(f"roles[{i}] ({role.key}): title must be non-empty")

        if not role.function.strip():
            findings.append(
                f"roles[{i}] ({role.key}): function must be non-empty"
            )

        by_key[role.key] = role

    # Check tree structure
    roots = [r.key for r in roles if r.reports_to is None]
    if len(roots) != 1:
        findings.append(
            f"must have exactly one root role (reporting to nobody);"
            f" found {len(roots)}"
        )
    elif roots[0] != "ceo":
        findings.append(
            f"by convention, the root role should be 'ceo', not '{roots[0]}'"
        )

    # Check reporting chain
    for i, role in enumerate(roles):
        if role.reports_to is not None and role.reports_to not in by_key:
            findings.append(
                f"roles[{i}] ({role.key}): reports to '{role.reports_to}'"
                " which is not in the proposed roles"
            )

        # Check for cycles
        seen = set()
        cursor = role.key
        while cursor is not None and cursor in by_key:
            if cursor in seen:
                findings.append(
                    f"roles[{i}] ({role.key}): reporting chain has a cycle"
                )
                break
            seen.add(cursor)
            cursor = by_key[cursor].reports_to

    return findings


def lint_responsibilities(
    responsibilities: Sequence[Responsibility],
    *,
    roles: Sequence[str],
    known_artifact_types: frozenset[str] | set[str] | None = None,
    known_fact_kinds: frozenset[str] | set[str] | None = None,
) -> list[str]:
    """Findings for proposed responsibilities before accepting.

    Fact kinds are checked against the process-global registry
    (``worldloom.factkinds``) — the arm this module deferred until that
    registry existed. A responsibility naming a kind nothing generates is an
    accountability edge that can never fire: no fact of that kind will ever be
    minted, so the person it makes answerable is answerable for nothing, and
    the corpus reports the edge as if it were load-bearing. Prefix semantics
    are the registry's (``financial.revenue`` covers ``financial.revenue.actual``
    at a dot boundary), because one edge honestly covers a fact family.
    """
    from . import factkinds

    findings: list[str] = []

    if not responsibilities:
        findings.append("must propose at least one responsibility")
        return findings

    roles_set = set(roles)
    seen_resp: dict[str, int] = {}

    for i, resp in enumerate(responsibilities):
        key = f"{resp.role_key}/{':'.join(sorted(resp.fact_kinds))}"
        if key in seen_resp:
            findings.append(
                f"responsibilities[{i}]: duplicate of"
                f" responsibilities[{seen_resp[key]}]"
            )
        seen_resp[key] = i

        if resp.role_key not in roles_set:
            findings.append(
                f"responsibilities[{i}]: role_key '{resp.role_key}' is not"
                " in the proposed roles"
            )

        if not resp.fact_kinds and not resp.artifact_types:
            findings.append(
                f"responsibilities[{i}] ({resp.role_key}): must name at least"
                " one fact kind or artifact type"
            )

        for kind in resp.fact_kinds:
            # A pack's own episodes mint kinds the process registry has never
            # heard of — that is what authoring a process *is* — so the lint
            # accepts them under the registry's own prefix semantics.
            authored_here = any(
                extra == kind or extra.startswith(kind + ".")
                for extra in (known_fact_kinds or ())
            )
            if not authored_here and not factkinds.resolvable(kind):
                findings.append(
                    f"responsibilities[{i}] ({resp.role_key}): fact kind"
                    f" '{kind}' is not in the fact-kind registry — nothing in"
                    " any registered vertical generates it, so this edge would"
                    " make someone answerable for facts that never exist."
                    " See worldloom.factkinds.names() for what is real."
                )

        # The other half of the same rule, unchecked for as long as the field
        # existed: a responsibility naming an artifact type nothing declares is
        # an edge to a document that will never be planned. The shipped `hr`
        # LOB declared two such types and nothing said so — the lint compared
        # fact kinds against their registry and took artifact types on faith.
        # `known_artifact_types` lets a pack pass the types it is authoring in
        # the same document; `None` means the process registry as it stands.
        for artifact_type in resp.artifact_types:
            if not _artifact_type_known(artifact_type, known_artifact_types):
                findings.append(
                    f"responsibilities[{i}] ({resp.role_key}): artifact type"
                    f" '{artifact_type}' is declared by no engine and authored"
                    " by no pack on hand — the edge points at a document that"
                    " will never be planned. See documents.declared_types()."
                )

    return findings


def _artifact_type_known(
    artifact_type: str, extra: frozenset[str] | set[str] | None
) -> bool:
    from . import documents

    if extra and artifact_type in extra:
        return True
    return artifact_type in documents.declared_types()


def lint_lob(
    lob: Lob,
    *,
    base: str = "",
    episodes: Sequence[Any] = (),
    known_artifact_types: frozenset[str] | set[str] | None = None,
) -> list[str]:
    """Every finding for one complete LOB, composed from the stage lints.

    The pack seam's entry point: a ``Pack`` carries whole accepted ``Lob``s,
    not authoring sessions, so it needs the stage lints run together against
    the engine, the artifact registry *plus whatever the same pack authors*,
    and the episodes shipping beside it. ``artifact_filings`` gets the same
    known-type check a responsibility does — it is the field the shipped `hr`
    LOB used to name a type that does not exist, read by nothing but
    ``describe`` and wrong in the one place an author would look.
    """
    findings: list[str] = []
    if base and lob.engine != base:
        findings.append(
            f"lob[{lob.name}]: engine {lob.engine!r} is not the pack's base"
            f" {base!r} — a LOB ships with the company whose engine runs it"
        )
    findings.extend(
        f"lob[{lob.name}]: {finding}"
        for finding in lint_roles(lob.roles, engine=lob.engine)
    )
    findings.extend(
        f"lob[{lob.name}]: {finding}"
        for finding in lint_responsibilities(
            lob.responsibilities,
            roles=[role.key for role in lob.roles],
            known_artifact_types=known_artifact_types,
            known_fact_kinds=frozenset(
                fk.kind for spec in episodes for fk in getattr(spec, "fact_kinds", ())
            ),
        )
    )
    for filing in lob.artifact_filings:
        if not _artifact_type_known(filing, known_artifact_types):
            findings.append(
                f"lob[{lob.name}]: artifact_filings names '{filing}', which no"
                " engine declares and no pack on hand authors"
            )
    # Only the processes this LOB actually binds into: `lint_bindings`'s
    # unbound-required-slot refusal is a claim about a process this LOB claims
    # to staff, and holding the commercial LOB to the delivery process's seats
    # would refuse every pack that ships two of either. Whether *some* LOB in
    # the pack fills every seat is the pack's question, answered in
    # `packs.lint` across the union.
    for spec in episodes:
        if any(b.process == getattr(spec, "name", "") for b in lob.slot_bindings):
            findings.extend(
                f"lob[{lob.name}]: {finding}"
                for finding in lint_bindings(lob, spec)
            )
    # A binding into a process that is neither shipping beside this LOB nor
    # already installed is a seat in a room that does not exist.
    known_processes = {getattr(spec, "name", "") for spec in episodes} | set(_INSTALLED_PROCESSES())
    for binding in lob.slot_bindings:
        if binding.process not in known_processes:
            findings.append(
                f"lob[{lob.name}]: slot_bindings names process"
                f" '{binding.process}', which is neither in this pack's"
                " episodes nor installed"
            )
    return findings


def _INSTALLED_PROCESSES() -> tuple[str, ...]:
    from . import episodes

    return tuple(episodes.loaded())


def lint_bindings(lob: Lob, spec: Any) -> list[str]:
    """Findings for *lob*'s slot bindings against one process *spec*.

    The two refusals the settled design names, plus the bookkeeping ones:
    a **required slot left unbound** (the process cannot run — nobody sits in
    the seat), a **binding to a role the LOB lacks** (a seat filled by nobody),
    a binding to a slot the process never declared, and one slot bound twice.
    Bindings for other processes are ignored rather than flagged — a LOB binds
    into every process it joins, and this lint is per-process on purpose so a
    finding names the spec it is about.
    """
    findings: list[str] = []
    declared = {slot.slot: slot for slot in getattr(spec, "role_slots", ())}
    role_keys = {role.key for role in lob.roles}
    relevant = [b for b in lob.slot_bindings if b.process == spec.name]

    seen_slots: dict[str, int] = {}
    for i, binding in enumerate(relevant):
        where = f"slot_bindings[{spec.name}/{binding.slot}]"
        if binding.slot not in declared:
            findings.append(
                f"{where}: process {spec.name!r} declares no slot"
                f" '{binding.slot}' — its vocabulary is"
                f" {sorted(declared) or '(none)'}, and a binding into a seat"
                " that does not exist orders nothing."
            )
        if binding.role_key not in role_keys:
            findings.append(
                f"{where}: binds role '{binding.role_key}', which this LOB"
                " does not declare — a seat filled by nobody. Roles:"
                f" {sorted(role_keys)}."
            )
        if binding.slot in seen_slots:
            findings.append(
                f"{where}: slot bound twice (also bindings[{seen_slots[binding.slot]}])"
                " — one seat, one occupant; a second challenger is a second"
                " declared slot, not a second binding."
            )
        seen_slots[binding.slot] = i

    bound = {b.slot for b in relevant}
    for slot in getattr(spec, "role_slots", ()):
        if slot.required and slot.slot not in bound:
            findings.append(
                f"process {spec.name!r}: required slot '{slot.slot}' is unbound"
                " — the process declares the seat and nobody in this LOB sits"
                " in it, so the run has no one to"
                f" {slot.purpose or 'fill it'}."
            )
    return findings


@dataclass(frozen=True)
class Participant:
    """One role's derived membership in one process."""

    role_key: str
    title: str
    slots: tuple[str, ...]
    """Seats this LOB binds the role into, in the process's declared order."""
    kinds: tuple[str, ...]
    """The kinds the process's steps mint that this role answers for, in mint
    order."""
    via: tuple[str, ...]
    """The responsibility fact-kind families that made the join, in declaration
    order — the evidence, so a reader can trace a participant back to the one
    edge that put them in the room."""


def participation(lob: Lob, spec: Any) -> tuple[Participant, ...]:
    """Who from *lob* is in the process *spec* — a join, never a table.

    Derived fresh from two declarations that already exist: the process's
    steps declare the fact kinds they mint (``EventSpec.fact_keys``), and a
    responsibility edge declares the kinds a role answers for. The join —
    under ``factkinds.covers``'s dot-prefix semantics, so "answers for
    ``financial.revenue``" meets "mints ``financial.revenue.actual``" — is who
    participates, plus whoever the slot bindings seat. Stored nowhere,
    deliberately: a participation *table* would be the second account that can
    disagree with the responsibilities it came from, which is the exact defect
    the responsibility primitive exists to prevent.

    Order is declaration order throughout (roles, then kinds in mint order,
    slots in the spec's slot order), so the same LOB and spec derive the same
    participants in every process.
    """
    from . import factkinds

    minted: list[str] = []
    for event in spec.events:
        for kind in event.fact_keys:
            if kind not in minted:
                minted.append(kind)

    slot_order = [slot.slot for slot in getattr(spec, "role_slots", ())]
    seated: dict[str, list[str]] = {}
    for binding in lob.slot_bindings:
        if binding.process != spec.name or binding.slot not in slot_order:
            continue
        seats = seated.setdefault(binding.role_key, [])
        if binding.slot not in seats:
            seats.append(binding.slot)

    participants: list[Participant] = []
    for role in lob.roles:
        via: list[str] = []
        kinds: list[str] = []
        for resp in lob.responsibilities:
            if resp.role_key != role.key:
                continue
            for family in resp.fact_kinds:
                hits = [kind for kind in minted if factkinds.covers(family, kind)]
                if hits and family not in via:
                    via.append(family)
                for kind in hits:
                    if kind not in kinds:
                        kinds.append(kind)
        slots = tuple(sorted(seated.get(role.key, []), key=slot_order.index))
        if via or slots:
            participants.append(Participant(
                role_key=role.key, title=role.title, slots=slots,
                kinds=tuple(kinds), via=tuple(via),
            ))
    return tuple(participants)


def accountability_constraints(
    lob: Lob, *, tolerance_pct: float = 5.0
) -> tuple[LoreConstraint, ...]:
    """The accountability mapping, derived from responsibility edges.

    The second arm this module deferred: a ``Responsibility`` already says who
    answers for which fact kinds, and ``ConstraintKind.ACCOUNTABILITY`` lore is
    the engine's one way of saying the same thing (target ``role_key/fact_kind``,
    magnitude the tolerance band — consumed by
    ``generators.org_builder.accountability_facts``, which mints the
    person-subject fact). Deriving one from the other, rather than authoring
    both, is the whole cohesion argument in this module's docstring: five
    hand-written tables can disagree; one declared edge cannot.

    ``tolerance_pct`` mirrors ``org_builder.DEFAULT_TOLERANCE_PCT`` — the band
    a variance memo in this corpus treats as worth explaining. Order is the
    declaration order of the responsibilities and their kinds, so a LOB
    resolves to the same constraints in every process.

    The result is constraints, not commitments: a ``LoreCommitment`` needs a
    minted id and an ``effective_from``, and a LOB knows what the organisation
    *is*, not when it started being that — the same boundary
    ``probe.Finding.constraint`` states.
    """
    constraints: list[LoreConstraint] = []
    titles = {role.key: role.title for role in lob.roles}
    for resp in lob.responsibilities:
        title = titles.get(resp.role_key, resp.role_key)
        for kind in resp.fact_kinds:
            constraints.append(LoreConstraint(
                kind=ConstraintKind.ACCOUNTABILITY,
                target=f"{resp.role_key}/{kind}",
                effect=f"The {title} answers for {kind}",
                magnitude=tolerance_pct,
            ))
    return tuple(constraints)


# ---------------------------------------------------------------------------
# Standard library
# ---------------------------------------------------------------------------


def publish() -> dict[str, Lob]:
    """The standard library: minimal LOB seeds/expansions.

    Shipped as resolved LOBs demonstrating the cascade.
    """
    return {
        "finance": _FINANCE,
        "procurement": _PROCUREMENT,
        "hr": _HR,
    }


#: Finance LOB: controllers, analysts, CFOs
_FINANCE = Lob(
    name="finance",
    title="Finance",
    purpose="Financial management, reporting, and close-out.",
    engine="retail",
    roles=[
        RoleSpec(key="cfo", title="Chief Financial Officer", function="Finance"),
        RoleSpec(
            key="controller",
            title="Financial Controller",
            function="Finance",
            reports_to="cfo",
        ),
        RoleSpec(
            key="reporting_manager",
            title="Reporting Manager",
            function="Finance",
            reports_to="controller",
        ),
    ],
    responsibilities=[
        # `financial.revenue` and `financial.gross_profit` are registry
        # prefixes covering the actual/budget/variance family. The library
        # used to say `financial.cost`, which nothing in any vertical
        # generates — exactly the never-fires edge `lint_responsibilities`
        # now refuses, found the day the registry existed to ask.
        Responsibility(
            role_key="cfo",
            fact_kinds=["financial.revenue", "financial.gross_profit"],
            artifact_types=["executive_summary"],
        ),
        Responsibility(
            role_key="controller",
            fact_kinds=["financial.revenue", "financial.gross_profit"],
            artifact_types=["cfo_variance_memo"],
        ),
    ],
    artifact_filings=["cfo_variance_memo"],
    episode_contributions=["MonthEndClose"],
)


#: Procurement LOB: CPO, category managers, accounts payable
_PROCUREMENT = Lob(
    name="procurement",
    title="Procurement",
    purpose="Procurement, purchasing, and accounts payable.",
    engine="retail",
    roles=[
        RoleSpec(
            key="chief_procurement",
            title="Chief Procurement Officer",
            function="Procurement",
        ),
        RoleSpec(
            key="category_manager",
            title="Category Manager",
            function="Procurement",
            reports_to="chief_procurement",
        ),
    ],
    responsibilities=[
        # `p2p` covers the whole procure-to-pay family the vertical mints.
        # The library used to say `procurement.order`, a kind that does not
        # exist — the registry's vocabulary is `p2p.*`.
        Responsibility(
            role_key="chief_procurement",
            fact_kinds=["p2p"],
            artifact_types=["purchase_order"],
        ),
    ],
    artifact_filings=["purchase_order"],
    episode_contributions=["ProcurementCycle"],
)


#: HR LOB: heads of people, recruiters, payroll
_HR = Lob(
    name="hr",
    title="Human Resources",
    purpose="Employee management, recruitment, and payroll.",
    engine="retail",
    roles=[
        RoleSpec(
            key="head_of_people",
            title="Head of People",
            function="HR",
        ),
        RoleSpec(
            key="recruiter",
            title="Recruiter",
            function="HR",
            reports_to="head_of_people",
        ),
    ],
    responsibilities=[
        # The org-change scenarios mint `org.joined` / `org.departed`; the
        # library used to say `employee.headcount` and `employee.hire`, a
        # vocabulary nothing generates. The artifact types had the same
        # disease one field over: `org_announcement` and `hire_announcement`
        # existed nowhere, and the lint took artifact types on faith while it
        # checked fact kinds against their registry — so the library's own
        # exemplar carried edges to documents that could never be planned.
        # These are `worldloom.workforce`'s real types, which is what HR
        # actually authors in this engine.
        Responsibility(
            role_key="head_of_people",
            fact_kinds=["org.joined", "org.departed"],
            artifact_types=["job_requisition", "performance_review"],
        ),
        Responsibility(
            role_key="recruiter",
            fact_kinds=["org.joined"],
            artifact_types=["offer_letter", "onboarding_checklist"],
        ),
    ],
    artifact_filings=["job_requisition"],
    episode_contributions=["Hire"],
)
