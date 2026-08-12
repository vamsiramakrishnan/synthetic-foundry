"""The fact-kind registry: which generator answers for each kind, under what rules.

Every check the validator runs names a fact kind, every responsibility a LOB
declares names one, and every episode spec mints some — but until this registry
existed the only way to learn whether ``capital.rwa_total`` was a real kind or a
plausible-looking invention was to grep the generators. That gap had a measured
cost: an episode spec was authored citing ``capital.challenge_reason`` and
``capital.break_identified`` — kinds nothing generates — and its own lint could
only compare the spec against *itself*, so the invention passed as declared.

The registry is the process-global answer to "does anything generate this kind,
and what must facts of it satisfy". Same posture as ``domains.register_domain``:
populated at package import by the modules that own the kinds (each vertical
registers its own vocabulary from its own file), identical re-registration is a
harmless module reload, and a *different* declaration under a known kind is
refused — two modules disagreeing about what a kind means would make a lint's
verdict depend on import order.

Invariants are recorded as strings in a closed vocabulary (``head`` or
``head(operand, ...)``) rather than as structured models, deliberately: the
registry documents what the validators already enforce, it does not enforce
anything itself. ``episodes.py`` is where an invariant declaration becomes a
derived check; here it is the honest index of who checks what.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

#: The invariant vocabulary. Closed for lore's reason (``ConstraintKind``):
#: an invariant the engine cannot check is a claim wearing a rule's clothes.
#:
#: - **holds-at**: current over ``[valid_from, valid_to)``; the core temporal
#:   validator checks every fact's window. The floor every kind stands on.
#: - **sums-to(child_kind)**: SYSTEM_OF_RECORD facts of this kind equal the sum
#:   of the named child kind's facts holding at the same moment, same period.
#: - **supersedes-prior**: a later fact of this kind replaces an earlier one by
#:   ``supersedes``, and the replaced fact's window closes exactly where the
#:   successor's opens.
#: - **never-superseded**: the permanent record — no fact of this kind is ever
#:   closed or superseded (banking's ``as_filed_touched``, insurance's
#:   ``booked_total_touched``).
#: - **standing**: carries no period; minted once per subject and reused by
#:   later periods rather than re-minted.
#: - **carries-forward-as(rule)**: next period's fact is resolved from this
#:   period's by ``reuse``, ``sum``, or ``derive``.
#: - **reconciles-against(a, b)**: this kind's value is derived from the two
#:   named kinds (a ratio from its amounts, a variance from actual and budget)
#:   and a checker recomputing the derivation must agree.
#: - **precedes-event**: valid before the event that cites it — the core
#:   temporal check on ``event_id``.
INVARIANT_HEADS = frozenset({
    "holds-at",
    "sums-to",
    "supersedes-prior",
    "never-superseded",
    "standing",
    "carries-forward-as",
    "reconciles-against",
    "precedes-event",
    # **rolls-up-to**: the cells of a cohort grid, at one observation, sum to
    # the named parent kind. Distinct from `sums-to`, which decomposes across
    # *subjects* at one period; a grid decomposes one subject across *cohort
    # periods*, and a check that conflated them would look for the breakdown
    # on the wrong axis and pass vacuously.
    "rolls-up-to",
})

_INVARIANT = re.compile(r"^(?P<head>[a-z-]+)(?:\((?P<operands>[^()]*)\))?$")

_KIND = re.compile(r"^[a-z][a-z0-9_.]*$")


@dataclass(frozen=True)
class FactKind:
    """One kind: its name, who generates it, and the rules its facts obey."""

    kind: str
    domain: str
    """The domain whose generators mint this kind — ``retail``, ``banking``,
    ``insurance``, ``procurement``, or ``core`` for the kinds the shared
    generators mint before any scenario runs."""
    generated_by: str
    """The module that mints it, as a path a reader can open. Documentation,
    not dispatch — nothing resolves this to a callable."""
    invariants: tuple[str, ...]
    """The rules, in the ``INVARIANT_HEADS`` vocabulary. Never empty: a kind
    with no invariant is a kind nothing validates, which is the defect the
    episode grammar's lint exists to refuse."""
    about: str = ""
    """What a fact of this kind states, in a sentence."""


def _parse(invariant: str) -> tuple[str, tuple[str, ...]]:
    match = _INVARIANT.match(invariant)
    if match is None:
        raise ValueError(f"malformed invariant {invariant!r}; expected 'head' or 'head(a, b)'")
    head = match.group("head")
    if head not in INVARIANT_HEADS:
        raise ValueError(
            f"unknown invariant head {head!r}; the vocabulary is closed:"
            f" {', '.join(sorted(INVARIANT_HEADS))}"
        )
    raw = match.group("operands")
    operands = tuple(part.strip() for part in raw.split(",")) if raw else ()
    return head, operands


def parse_invariant(invariant: str) -> tuple[str, tuple[str, ...]]:
    """``"sums-to(capital.rwa_by_book)"`` → ``("sums-to", ("capital.rwa_by_book",))``.

    The one parser, shared with ``episodes.py``'s check derivation so the
    registry and the runner cannot drift on what an invariant string means.
    """
    return _parse(invariant)


#: Every declared kind this process holds. Module state on purpose — the same
#: argument as ``validate._DOMAIN_CHECKS``: a registry consulted lazily would
#: give different answers in processes that imported different modules.
_KINDS: dict[str, FactKind] = {}


def register(kinds: Sequence[FactKind]) -> None:
    """Register *kinds*. Identical re-registration is a harmless reload; a
    different declaration under a known kind is refused, because a lint that
    consults the registry must not change its verdict with import order.
    """
    for spec in kinds:
        if not _KIND.match(spec.kind):
            raise ValueError(f"malformed fact kind {spec.kind!r}")
        if not spec.invariants:
            raise ValueError(
                f"fact kind {spec.kind!r} declares no invariants — a kind nothing"
                " validates may not be registered; 'holds-at' is the floor"
            )
        for invariant in spec.invariants:
            _parse(invariant)  # refuse malformed or unknown heads at registration
        existing = _KINDS.get(spec.kind)
        if existing is not None:
            if existing == spec:
                continue
            raise ValueError(
                f"fact kind {spec.kind!r} is already registered by domain"
                f" {existing.domain!r} ({existing.generated_by}) — a kind has one"
                " generator answering for it, and a second, different declaration"
                " would make the registry's answer depend on import order"
            )
        _KINDS[spec.kind] = spec


def get(kind: str) -> FactKind | None:
    """The declaration for *kind*, or ``None`` for an unregistered one."""
    return _KINDS.get(kind)


def known() -> dict[str, FactKind]:
    """Every registered kind, by name. A copy; the registry is not a surface."""
    return dict(_KINDS)


def names() -> list[str]:
    """Every registered kind name, sorted."""
    return sorted(_KINDS)


def resolvable(name: str) -> bool:
    """Whether *name* names a registered kind, exactly or as a dot-prefix.

    Prefix semantics exist for responsibilities: "the controller answers for
    ``financial.revenue``" is a claim about ``financial.revenue.actual``,
    ``.budget`` and ``.variance`` together, and demanding the edge be declared
    three times would invite the three to disagree. The boundary is a dot, so
    ``financial.rev`` does not resolve — a truncation is a typo, not a family.
    """
    if name in _KINDS:
        return True
    prefix = name + "."
    return any(kind.startswith(prefix) for kind in _KINDS)


def covers(name: str, kind: str) -> bool:
    """Whether *name* claims *kind*: exact, or a dot-boundary prefix.

    The same boundary rule ``resolvable`` applies against the registry, made
    pairwise so a join can use it — ``lob.participation`` matches a
    responsibility's declared family (``financial.revenue``) against the kinds
    a process's steps actually mint (``financial.revenue.actual``). One
    predicate, shared, so the lint that admits an edge and the join that
    derives who participates cannot disagree about what a prefix means.
    """
    return kind == name or kind.startswith(name + ".")


# ---------------------------------------------------------------------------
# The core kinds: minted by the shared generators before any scenario runs.
# Registered here rather than from a vertical because no vertical owns them —
# `org_builder` mints them for every world builder alike.
# ---------------------------------------------------------------------------

register([
    FactKind(
        kind="lore.milestone", domain="core",
        generated_by="generators/org_builder.py",
        invariants=("holds-at", "precedes-event"),
        about="A dated lore commitment witnessed on the corpus's own timeline.",
    ),
    FactKind(
        kind="org.accountability", domain="core",
        generated_by="generators/org_builder.py",
        invariants=("holds-at",),
        about="A person and the measure they answer for, with the tolerance band.",
    ),
    FactKind(
        kind="org.joined", domain="core",
        generated_by="scenarios.py (Hire)",
        invariants=("holds-at", "precedes-event"),
        about="A person's recorded start.",
    ),
    FactKind(
        kind="org.departed", domain="core",
        generated_by="scenarios.py (Departure)",
        invariants=("holds-at", "precedes-event"),
        about="A person's recorded last working day.",
    ),
    FactKind(
        kind="org.role_changed", domain="core",
        generated_by="scenarios.py (Reorganisation)",
        invariants=("holds-at", "precedes-event"),
        about="A reporting line moved, witnessed by the reorganisation event.",
    ),
    FactKind(
        kind="org.unit_leader_changed", domain="core",
        generated_by="scenarios.py (Reorganisation)",
        invariants=("holds-at", "precedes-event"),
        about="A business unit's leadership handover.",
    ),
    FactKind(
        kind="org.headcount", domain="core",
        generated_by="scenarios.py (WorkforceChange)",
        invariants=("holds-at", "precedes-event"),
        about="The company's stated total workforce after an aggregate change.",
    ),
    FactKind(
        kind="org.headcount.delta", domain="core",
        generated_by="scenarios.py (WorkforceChange)",
        invariants=("holds-at", "precedes-event"),
        about="The signed change from the preceding stated workforce total.",
    ),
    *(
        FactKind(
            kind=f"estate.{entity}.{measure}", domain="core",
            generated_by="scenarios.py (StructuralChange)",
            invariants=("holds-at", "precedes-event"),
            about=(
                f"Active {entity.replace('_', '-')} {measure} recorded by a"
                " structural-estate movement."
            ),
        )
        for entity in ("business_units", "sites", "systems", "services")
        for measure in ("count", "delta")
    ),
])

# ---------------------------------------------------------------------------
# The actor-tool kinds: minted when employees, not generators, write the facts.
#
# Registered here rather than from `actors/tools/` because that package is
# imported only when `--actors` runs — and a registration that happens at tool
# import is the exact lazy-registration defect the policies module had, where
# `known()` answered differently depending on what had been imported first. A
# corpus built with actors and linted without them would call these fourteen
# kinds inventions. They went unregistered for as long as the actor layer has
# existed, which is precisely the failure this registry's own docstring says it
# was built to catch: `build --actors scripted --incident` writes nine of them
# into facts.jsonl, and none was in `known()`.
#
# `holds-at` only, honestly: the deeper rules for these facts — ledger
# integrity, authority ceilings, rejection residue — live in the `actors`
# validator group, which checks the *ledger*, not the fact stream. Declaring
# richer invariants here would document checks nothing runs.
# ---------------------------------------------------------------------------

register([
    FactKind(
        kind=kind, domain="core", generated_by=module, invariants=("holds-at",),
        about=about,
    )
    for kind, module, about in (
        ("close.assessment", "actors/tools/finance.py",
         "An actor's recorded reading of where the close stands."),
        ("close.journal_request", "actors/tools/finance.py",
         "A journal an actor asked to have posted, before anyone approved it."),
        ("close.journal_posted", "actors/tools/finance.py",
         "The journal as posted, once the request cleared its approver."),
        ("close.dependency", "actors/tools/finance.py",
         "One close task waiting on another, raised by the person waiting."),
        ("close.decision", "actors/tools/finance.py",
         "A decision taken in the close, on the record with its taker."),
        ("ops.incident_state", "actors/tools/incidents.py",
         "The ticket's state as an actor moved it."),
        ("ops.incident_assignee", "actors/tools/incidents.py",
         "Who the ticket was handed to."),
        ("ops.work_note", "actors/tools/incidents.py",
         "A working note on the ticket, in its author's own words."),
        ("ops.incident_priority", "actors/tools/incidents.py",
         "The priority as set, and reset, while the incident ran."),
        ("ops.cause_assessment", "actors/tools/engineering.py",
         "An engineer's assessment of cause, before it is anyone's finding."),
        ("ops.change_proposal", "actors/tools/engineering.py",
         "A change an engineer proposed to make."),
        ("ops.change_approval", "actors/tools/engineering.py",
         "The proposal's approval, by someone with the authority to give it."),
        ("ops.remediation_owner", "actors/tools/engineering.py",
         "Who took ownership of the remediation."),
        ("decision.artifact_approved", "actors/tools/artifacts.py",
         "An artifact signed off through the tool rather than by the planner."),
    )
])


__all__ = [
    "FactKind",
    "INVARIANT_HEADS",
    "covers",
    "get",
    "known",
    "names",
    "parse_invariant",
    "register",
    "resolvable",
]
