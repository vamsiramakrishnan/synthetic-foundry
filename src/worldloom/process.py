"""Process specs authored through a cascade — seed → stages → resolved spec.

The ontology this module implements is settled (docs/next-phase-plan.md): a
**process** is the recurring type, declared once — P2P, the month-end close, a
recruitment drive; an **episode** is one bounded run of it over a period. The
spec a process resolves to is ``episodes.EpisodeSpec``, and this module is how
one gets *authored*: through the same seed→Session→Brief→accept→resolve
handshake ``lob.py`` uses, because the arguments are the same —

- **a minimal seed**, not a finished document: name, one purpose sentence, the
  engine, and the LOB the process belongs to. Everything else is proposed in
  stages and refused when incoherent, rather than arriving whole and wrong.
- **company context rides the brief**: the engine, the facets, and the owning
  LOB's roles and responsibilities travel in every ``Brief.context``, so a
  harness proposes steps for *this* company rather than a generic one.
- **every stage is refusable by the grammar's lint.** A proposed step minting
  a kind that is neither registry-known nor declared with invariants is
  refused at the stage that proposed it — the exact invention the fact-kind
  registry exists to catch, refused before it can reach a spec.
- **only the resolved spec replays.** The session, its briefs and its refused
  answers are working state; what rides a pack or a recipe is the resolved
  ``EpisodeSpec``, installed with ``episodes.install`` and run as an
  ``AuthoredEpisode``. Recording the conversation would be a second account
  of how the spec came to be, and the spec is the account.

Registry-known kinds may leave ``invariants`` empty in a proposal: the
registry already documents what the validator enforces for them, and
``accept`` fills the declaration from it — restating the rules by hand is how
a spec and the registry drift apart, which is the drift ``episodes.lint``'s
registry check exists to name.

The handshake is an instance of the shared protocol (``cascade.py``), whose
docstring states the invariants once. Iteration and resumption work as they do
for a LOB: a refused answer leaves the frozen ``Session`` unchanged, so a
stage may be revised and resubmitted any number of times, and a session is
resumed by replaying its accepted answers through ``open``/``accept``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError

from . import cascade, episodes
from .cascade import Brief, CascadeModel
from .episodes import (
    ArtifactIntentSpec,
    EpisodeSpec,
    EventSpec,
    FactKindSpec,
    Invariant,
    RoleSlotSpec,
)

__all__ = [
    "ProcessSeed", "Session", "Brief", "Answer", "load_seed", "open",
    "next_stage", "accept", "resolve", "lint_seed", "lint_steps", "lint_slots",
]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class ProcessModel(CascadeModel):
    """Base for all process-cascade schema objects — frozen and closed, per
    the protocol."""


class ProcessSeed(ProcessModel):
    """The seed for a new process: minimal on purpose.

    Four commitments and a cadence — everything structural (steps, kinds,
    slots) is proposed in stages where the lint can refuse it, not asserted
    here where nothing checks it.
    """

    name: str = Field(pattern=r"^[A-Z][a-zA-Z0-9]*$")
    """The process's name — ``EpisodeSpec.name``'s shape (``MonthEndClose``)."""
    purpose: str = Field(min_length=1)
    """One sentence: why the company runs this process."""
    engine: str = Field(min_length=1)
    """The industry frame this process runs inside (a registered domain)."""
    lob: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    """The LOB this process belongs to — the function whose responsibility
    edges will derive who participates (``lob.participation``)."""
    period: Literal["month", "quarter", "year"] = "month"
    """The cadence one episode of this process runs over."""


@dataclass(frozen=True)
class Session:
    """A process being authored, stored between calls.

    Holds only accepted stages, like ``lob.Session``: the seed, the accepted
    steps and kinds, and the accepted slots. The resolved spec is derived at
    ``resolve``, never stored — a session is working state and does not ride
    anything.

    ``None`` versus empty is load-bearing on ``slots``: a process may honestly
    declare no slots (nothing to order), and ``None`` is how the cascade tells
    "not yet asked" from "asked, and the answer was none".
    """

    name: str
    purpose: str
    engine: str
    lob: str
    period: str
    #: Company context (facets) carried into every brief. Data, not consulted
    #: by any lint here — the proposals it shapes are checked on their merits.
    facets: tuple[tuple[str, str], ...] = ()
    kinds: tuple[FactKindSpec, ...] | None = None
    steps: tuple[EventSpec, ...] | None = None
    slots: tuple[RoleSlotSpec, ...] | None = None


# The next question in process authoring is the protocol's own `Brief` —
# stage ('steps', 'slots', or 'resolve'), question, and the company context:
# engine, facets, the owning LOB's roles and responsibilities when installed.


class Answer(ProcessModel):
    """One answer to a process brief."""

    stage: str = Field(min_length=1)
    steps: list[EventSpec] = Field(default_factory=list)
    """If stage is 'steps', the proposed steps (events), in order."""
    kinds: list[FactKindSpec] = Field(default_factory=list)
    """If stage is 'steps', the kinds those steps mint. A registry-known kind
    may leave ``invariants`` empty (filled from the registry on accept); an
    unknown kind must declare its own or be refused."""
    slots: list[RoleSlotSpec] = Field(default_factory=list)
    """If stage is 'slots', the ordered role slots. May be empty — a process
    with nothing to order declares no seats."""


# ---------------------------------------------------------------------------
# Cascade operations
# ---------------------------------------------------------------------------


def open(
    seed: ProcessSeed | dict[str, Any],
    *,
    facets: dict[str, str] | None = None,
) -> Session:
    """Start authoring a new process from a seed.

    ``facets`` is the company's self-description (``listing=listed``, ...) —
    carried into every brief so proposals are contextual, exactly as the
    settled design asks. Sorted here so two callers passing equal dicts get
    equal sessions.
    """
    if isinstance(seed, dict):
        seed = ProcessSeed.model_validate(seed)
    return Session(
        name=seed.name,
        purpose=seed.purpose,
        engine=seed.engine,
        lob=seed.lob,
        period=seed.period,
        facets=tuple(sorted((facets or {}).items())),
    )


def _context(session: Session) -> dict[str, Any]:
    """The company, in every brief — so an answer is written for *this* world."""
    from . import lob as lob_module

    context: dict[str, Any] = {
        "engine": session.engine,
        "facets": dict(session.facets),
        "lob": session.lob,
        "purpose": session.purpose,
        "period": session.period,
    }
    owning = lob_module.installed().get(session.lob) or lob_module.publish().get(session.lob)
    if owning is not None:
        context["lob_roles"] = {role.key: role.title for role in owning.roles}
        context["lob_responsibilities"] = [
            {"role": r.role_key, "fact_kinds": list(r.fact_kinds)}
            for r in owning.responsibilities
        ]
    return context


def next_stage(session: Session) -> Brief:
    """What to ask the harness next."""
    if session.steps is None:
        return Brief(
            stage="steps",
            asks="Propose the steps of this process, in order, and the fact "
            "kinds they mint. A step is an EventSpec (kind, when, summary, "
            "fact_keys, causality); a kind is a FactKindSpec. Every minted "
            "kind must be declared in `kinds`: registry-known kinds may leave "
            "invariants empty (they are filled from the fact-kind registry), "
            "an unknown kind must declare its own invariants or be refused. "
            "See worldloom.factkinds.names() for what already exists.",
            context=_context(session),
        )
    if session.slots is None:
        return Brief(
            stage="slots",
            asks="Propose the ordered role slots this process needs filled — "
            "its own vocabulary (e.g. preparer, challenger, approver), in the "
            "order the work moves. Mark a slot required if the process cannot "
            "run without someone in it. Propose none if there is nothing to "
            "order. The LOB binds its roles to these afterwards; do not name "
            "company role keys here.",
            context={
                **_context(session),
                "steps": [step.kind for step in session.steps],
                "minted_kinds": _minted(session.steps),
            },
        )
    return Brief(
        stage="resolve",
        asks="All stages are complete. Call resolve() to derive the "
        "EpisodeSpec, then episodes.install() it — only the resolved spec "
        "replays.",
        context=_context(session),
    )


def accept(session: Session, answer: Answer | dict[str, Any]) -> Session:
    """Accept an answer to a brief, refusing what the grammar's lint refuses.

    Raises ``ValueError`` naming the findings; a refused answer changes
    nothing, exactly as in the LOB cascade and narration's handshake.
    """
    if isinstance(answer, dict):
        answer = Answer.model_validate(answer)

    if answer.stage == "steps":
        findings = lint_steps(session, answer.steps, answer.kinds)
        if findings:
            cascade.refuse("steps", findings)
        return replace(
            session,
            steps=tuple(answer.steps),
            kinds=_filled(answer.kinds),
        )

    if answer.stage == "slots":
        findings = lint_slots(answer.slots)
        if findings:
            cascade.refuse("slots", findings)
        return replace(session, slots=tuple(answer.slots))

    raise ValueError(f"unknown stage: {answer.stage!r}")


def resolve(
    session: Session,
    *,
    artifacts: list[ArtifactIntentSpec] | None = None,
) -> EpisodeSpec:
    """Derive the process spec from an accepted session.

    The result is an ordinary ``episodes.EpisodeSpec`` — install it with
    ``episodes.install`` and run it as an ``AuthoredEpisode``; the recipe
    records the spec's name and period, never this session. Linted once more
    whole, because the stages were linted separately and the one thing a
    stage cannot see is the others.
    """
    if session.steps is None or session.kinds is None:
        raise ValueError("cannot resolve: the steps stage has not been accepted")
    if session.slots is None:
        raise ValueError("cannot resolve: the slots stage has not been accepted")

    spec = EpisodeSpec(
        name=session.name,
        domain=session.engine,
        period=session.period,  # type: ignore[arg-type]
        fact_kinds=list(session.kinds),
        events=list(session.steps),
        role_slots=list(session.slots),
        artifacts=list(artifacts or []),
        detail=session.purpose,
    )
    findings = episodes.lint([spec])
    if findings:
        cascade.refuse("resolved spec", findings)
    return spec


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_seed(source: str | Path | dict[str, Any]) -> ProcessSeed:
    """Load a process seed from a path, JSON text, or parsed data."""
    return cascade.load(source, ProcessSeed)


# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------


def lint_seed(seed: ProcessSeed | dict[str, Any]) -> list[str]:
    """Findings for a process seed before opening."""
    from . import domains
    from . import lob as lob_module

    if isinstance(seed, dict):
        try:
            seed = ProcessSeed.model_validate(seed)
        except ValidationError as error:
            return [str(error)]

    findings: list[str] = []
    if domains.by_name(seed.engine) is None:
        findings.append(
            f"engine {seed.engine!r} is not a registered domain; known:"
            f" {domains.names()}"
        )
    if (seed.lob not in lob_module.installed()
            and seed.lob not in lob_module.publish()):
        findings.append(
            f"no LOB named {seed.lob!r} is installed or in the standard"
            " library — the cascade still runs, but its briefs carry no roles"
            " or responsibilities, and participation will have nothing to"
            " join. Author the LOB first (worldloom.lob) or name one of:"
            f" {sorted(lob_module.publish())}"
        )
    return findings


def _minted(steps: tuple[EventSpec, ...] | list[EventSpec]) -> list[str]:
    """The kinds the steps mint, in mint order, once each."""
    minted: list[str] = []
    for step in steps:
        for kind in step.fact_keys:
            if kind not in minted:
                minted.append(kind)
    return minted


def _filled(kinds: list[FactKindSpec]) -> tuple[FactKindSpec, ...]:
    """Invariants for registry-known kinds, taken from the registry.

    A proposal restating a known kind's rules by hand is how a spec and the
    registry drift apart — `episodes.lint` refuses a spec claiming invariants
    the registry does not hold, and this is the constructive counterpart:
    leave them empty and the declaration is *derived* from the one source
    that documents what the validators actually enforce.
    """
    from . import factkinds

    out: list[FactKindSpec] = []
    for fk in kinds:
        if fk.invariants:
            out.append(fk)
            continue
        registered = factkinds.get(fk.kind)
        if registered is None:
            out.append(fk)  # lint_steps has already refused this shape
            continue
        derived = []
        for invariant in registered.invariants:
            head, operands = factkinds.parse_invariant(invariant)
            derived.append(Invariant(
                kind=head,  # type: ignore[arg-type]
                operands=list(operands),
                detail=f"from the fact-kind registry ({registered.generated_by})",
            ))
        out.append(fk.model_copy(update={"invariants": derived}))
    return tuple(out)


def lint_steps(
    session: Session,
    steps: list[EventSpec],
    kinds: list[FactKindSpec],
) -> list[str]:
    """Findings for proposed steps and kinds before accepting.

    The stage's own rule first — a minted kind must be registry-known or
    declared with invariants — then the whole proposal is assembled into a
    provisional spec and handed to ``episodes.lint``, so the cascade refuses
    with the grammar's own findings rather than a parallel set that could
    drift from it.
    """
    from . import factkinds

    findings: list[str] = []
    if not steps:
        return ["must propose at least one step"]

    declared = {fk.kind for fk in kinds}
    for i, step in enumerate(steps):
        for kind in step.fact_keys:
            if kind not in declared:
                findings.append(
                    f"steps[{i}] ({step.kind}): mints {kind!r} with no"
                    " declaration in this answer's kinds. Declare it —"
                    " registry-known kinds may leave invariants empty, an"
                    " unknown kind must state its own."
                )
    for i, fk in enumerate(kinds):
        if not fk.invariants and factkinds.get(fk.kind) is None:
            findings.append(
                f"kinds[{i}] ({fk.kind}): neither registry-known nor declared"
                " with invariants — a kind nothing validates may not enter a"
                " process spec. See worldloom.factkinds.names() for what is"
                " real, or declare the rules this kind must satisfy."
            )
    if findings:
        return findings

    try:
        provisional = EpisodeSpec(
            name=session.name,
            domain=session.engine,
            period=session.period,  # type: ignore[arg-type]
            fact_kinds=list(_filled(kinds)),
            events=list(steps),
            detail=session.purpose,
        )
    except ValidationError as error:
        return [str(error)]
    return episodes.lint([provisional])


def lint_slots(slots: list[RoleSlotSpec]) -> list[str]:
    """Findings for proposed slots before accepting.

    An empty proposal is fine — a process with nothing to order declares no
    seats. The vocabulary is the proposal's own (spec-defined, deliberately
    not a fixed list), so the only structural rule is uniqueness: declaration
    order is the ordering, and a duplicate seat sits nowhere in it.
    """
    findings: list[str] = []
    seen: dict[str, int] = {}
    for i, slot in enumerate(slots):
        if slot.slot in seen:
            findings.append(
                f"slots[{i}] ({slot.slot}): duplicates slots[{seen[slot.slot]}]"
                " — declaration order is the ordering, and one seat cannot"
                " hold two places in it."
            )
        seen[slot.slot] = i
    return findings
