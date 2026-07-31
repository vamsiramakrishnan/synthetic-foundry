"""A self-audit of the component registry and the artifact grammars.

This module checks no world, no corpus, no seed. It checks the *declarations*
in ``compiler/components.py`` and ``compiler/grammar.py`` for internal
coherence — the same kind of promise ``validate.py`` makes about a generated
world, made instead about the hand-authored data those worlds are compiled
through. The reason it exists: a component whose ``requires_predecessor_role``
names a role nothing provides fails, at composition time, with a message about
ordering. The real defect is upstream and static, and nothing was checking for
it before this module.

Severity
--------
Findings carry a ``severity`` of ``"error"`` or ``"warning"``. The line is
drawn on provability, not on how bad the outcome sounds:

``error``
    The declaration makes something *unsatisfiable* — a component that can
    never be placed, a grammar that can never be matched, a lookup that
    resolves to the wrong spec. These are provable from the data alone, with
    no assumption this module invented. A registry or grammar set with an
    error is broken and should not ship.

``warning``
    The declaration is probably a mistake, but calling it unsatisfiable would
    require an assumption this module is not in a position to make with
    certainty — either because the surrounding system (the compose layer, the
    plan layer) is freer than the static data suggests, or because this
    module had to invent a number the codebase does not itself define. Two
    checks land here and each says why at its call site:
    ``asymmetric_incompatibility`` (behaviour is unaffected — ``compatible()``
    already checks both directions — only the declaration is inconsistent) and
    ``unreachable_component`` / ``impossible_density`` (both described below).

A checker that reports a style nit as loudly as an unsatisfiable constraint
teaches people to stop reading either. Treat ``error`` as CI-blocking and
``warning`` as worth a look.

Two checks needed a judgment call beyond error-vs-warning, recorded here
because the reasoning does not fit next to the code without breaking it up:

``unreachable_component`` (soundness)
    As specified — "requested by no grammar's roles, AND unreachable by any
    artifact type" — this check is **unsound**. ``grammar.py`` says plainly
    that an artifact type with no ``GRAMMARS`` entry is "unconstrained beyond
    its components' own compatibility": the compose layer picks components for
    such a type by matching an ``ArtifactPlan`` beat's free-form
    ``semantic_role`` string against ``roles_for()``, entirely outside
    ``GRAMMARS``. A role no grammar requests can still be exactly the role a
    plan for an ungrammared artifact type asks for tomorrow, and nothing here
    can see that plan in advance — static analysis of the registry has no
    view of what a future plan will name. Proving unreachability would mean
    proving no artifact type, present or future, could ever request the role,
    which is not a claim this module can make. What *is* provable is the
    weaker fact: no *grammar* currently asks for it. That is reported as a
    warning, worded as "no grammar requests this" rather than "nothing can
    reach this", which is the honest version of the same observation.

``impossible_density``
    ``ComponentSpec.density`` is a numeric band; ``plan.py``'s
    ``DensityProfile`` is three names. This check asks whether any profile lands
    inside a component's band, which needs a number per profile.

    That number was originally invented here, because nothing in the codebase
    defined one, and the finding was a warning on those grounds. It is no longer
    invented: ``plan.DENSITY_POINTS`` is now the single definition, shared with
    the composer that actually selects components. The finding stays a **warning**
    anyway, for a different and better reason — a band no profile hits today is
    unreachable by the *current* three profiles, not unsatisfiable in principle,
    and a fourth profile or a retuned point would make it live again. That is a
    weaker claim than the errors below, which are unsatisfiable from the data
    alone no matter what any other layer does.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import get_args

from .components import REGISTRY, ComponentSpec
from .grammar import GRAMMARS, Grammar
from .plan import DENSITY_POINTS, DensityProfile

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class AuditFinding:
    """One way the registry or a grammar fails to be internally coherent."""

    code: str
    subject: str  # component_id or artifact_type
    detail: str
    severity: str = ERROR


#: The profile-to-density mapping, taken from ``compiler.plan`` rather than
#: defined here.
#:
#: This module originally carried its own copy, because at the time nothing in
#: the codebase said what "sparse" meant numerically. Two callers then needed it
#: — component selection in the composer, and this audit — and both invented the
#: same thirds independently. Convergence is luck, not a guarantee: two private
#: copies agree until one is tuned, and then this audit would call a component's
#: band reachable while selection never picks it, with nothing reporting the
#: contradiction. It now lives in `plan.py`, next to the profile names it
#: interprets.
_PROFILE_POINTS = DENSITY_POINTS

# A profile that exists but has no numeric point would make `impossible_density`
# silently under-report. Cheap to assert, and it is the kind of mismatch that
# only shows up as a component quietly never being selected.
assert set(get_args(DensityProfile)) == set(_PROFILE_POINTS), (
    "compiler.plan.DensityProfile has a profile with no entry in DENSITY_POINTS"
)


def _all_roles(registry: tuple[ComponentSpec, ...]) -> frozenset[str]:
    """Every semantic role provided by *some* component in *registry*."""
    roles: set[str] = set()
    for spec in registry:
        roles |= spec.semantic_roles
    return frozenset(roles)


# ---------------------------------------------------------------------------
# Registry checks
# ---------------------------------------------------------------------------


def _check_unsatisfiable_precondition(registry: tuple[ComponentSpec, ...]) -> list[AuditFinding]:
    """A `requires_predecessor_role` naming a role no component provides.

    What breaks: `Grammar.check` marks every artifact that reaches this
    component with `missing_precondition`, always, regardless of what else the
    document contains — there is no sequence of *any* length that satisfies a
    predecessor role that does not exist. The component is dead on arrival and
    the failure a caller sees names an ordering problem in *their* document,
    not the broken declaration that actually caused it.
    """
    provided = _all_roles(registry)
    findings = []
    for spec in registry:
        role = spec.requires_predecessor_role
        if role is not None and role not in provided:
            findings.append(
                AuditFinding(
                    code="unsatisfiable_precondition",
                    subject=spec.component_id,
                    detail=(
                        f"requires_predecessor_role={role!r}, but no component in the"
                        " registry provides that role — this component can never be used"
                    ),
                    severity=ERROR,
                )
            )
    return findings


def _check_unreachable_component(
    registry: tuple[ComponentSpec, ...], grammars: Mapping[str, Grammar]
) -> list[AuditFinding]:
    """A component whose roles no grammar asks for.

    Deliberately weaker than "unreachable" — see the module docstring for why
    the stronger claim is unsound. What this reports: no *grammar* currently
    requires, opens with, or orders this component's roles. That is still
    worth a look, because it is exactly the shape a vestigial component takes
    after the grammar that used to want it is edited — but it is not proof of
    dead weight, since an artifact type with no grammar entry reaches
    components purely through a plan's free-form `semantic_role`.
    """
    requested: set[str] = set()
    for grammar in grammars.values():
        requested |= grammar.requires_roles
        requested |= grammar.opens_with
        for earlier, later in grammar.ordered_roles:
            requested.add(earlier)
            requested.add(later)

    findings = []
    for spec in registry:
        if not (spec.semantic_roles & requested):
            findings.append(
                AuditFinding(
                    code="unreachable_component",
                    subject=spec.component_id,
                    detail=(
                        f"semantic_roles {sorted(spec.semantic_roles)} are requested by no"
                        " grammar's requires_roles/opens_with/ordered_roles — may still be"
                        " reachable by an artifact type with no grammar, so this is"
                        " informational rather than proof of dead weight"
                    ),
                    severity=WARNING,
                )
            )
    return findings


def _check_impossible_density(registry: tuple[ComponentSpec, ...]) -> list[AuditFinding]:
    """A density band no density-profile point falls inside.

    What breaks: `fits()` is the gate the composer uses to select a component
    for a beat, and it rejects on density before anything else about the
    component is considered. If no profile the plan layer offers ever produces
    a density inside the band, the component can never pass that gate — it is
    selectable in principle and dead in practice. See the module docstring for
    why this is a warning rather than an error: the profile-to-number mapping
    is this module's own invention, not the codebase's.
    """
    findings = []
    for spec in registry:
        low, high = spec.density
        if not any(low <= point <= high for point in _PROFILE_POINTS.values()):
            findings.append(
                AuditFinding(
                    code="impossible_density",
                    subject=spec.component_id,
                    detail=(
                        f"density band ({low}, {high}) contains none of the density-profile"
                        f" points {sorted(_PROFILE_POINTS.items())} — no profile could ever"
                        " select this component"
                    ),
                    severity=WARNING,
                )
            )
    return findings


def _check_contradictory_rows(registry: tuple[ComponentSpec, ...]) -> list[AuditFinding]:
    """min_rows > max_rows.

    What breaks: `fits(rows=...)` requires `rows >= min_rows` and, when
    `max_rows` is set, `rows <= max_rows`. If `min_rows` exceeds `max_rows`
    those two conditions cannot both hold for any `rows` at all — the
    component rejects every row count, including its own declared minimum.
    """
    findings = []
    for spec in registry:
        if spec.max_rows is not None and spec.min_rows > spec.max_rows:
            findings.append(
                AuditFinding(
                    code="contradictory_rows",
                    subject=spec.component_id,
                    detail=(
                        f"min_rows={spec.min_rows} > max_rows={spec.max_rows} — no row"
                        " count can satisfy both"
                    ),
                    severity=ERROR,
                )
            )
    return findings


def _check_asymmetric_incompatibility(registry: tuple[ComponentSpec, ...]) -> list[AuditFinding]:
    """A lists B in incompatible_with but B does not list A back.

    `compatible()` checks both directions, so nothing breaks *behaviourally* —
    an assembly containing both A and B is rejected either way. What the
    asymmetry does signal is an authoring mistake: exactly one of the two
    specs was updated when the incompatibility was decided, and there is no
    way to tell from the data alone which declaration is the stale one. Hence
    a warning, not an error — the rule is enforced correctly regardless.
    """
    by_id = {spec.component_id: spec for spec in registry}
    findings = []
    reported: set[tuple[str, str]] = set()
    for spec in registry:
        for other_id in sorted(spec.incompatible_with):
            other = by_id.get(other_id)
            if other is None:
                continue  # a dangling id is a different defect, not this check's
            if spec.component_id in other.incompatible_with:
                continue  # symmetric — no mistake to report
            pair = (spec.component_id, other_id)
            if pair in reported:
                continue
            reported.add(pair)
            findings.append(
                AuditFinding(
                    code="asymmetric_incompatibility",
                    subject=spec.component_id,
                    detail=(
                        f"lists {other_id!r} in incompatible_with, but {other_id} does not"
                        f" list {spec.component_id!r} back — one of the two declarations is"
                        " a mistake, and which one is not knowable from the data"
                    ),
                    severity=WARNING,
                )
            )
    return findings


def _check_duplicate_component_id(registry: tuple[ComponentSpec, ...]) -> list[AuditFinding]:
    """Two specs sharing an id.

    What breaks: `components._BY_ID` is built by `{spec.component_id: spec for
    spec in REGISTRY}` — a dict comprehension, so the later spec silently
    replaces the earlier one. Every reference to the earlier id, wherever it
    was declared for a reason, resolves to whichever spec happened to be
    listed last. That failure produces no error; it produces the wrong
    component, silently, everywhere the id is used.
    """
    counts = Counter(spec.component_id for spec in registry)
    findings = []
    for component_id in sorted(cid for cid, count in counts.items() if count > 1):
        findings.append(
            AuditFinding(
                code="duplicate_component_id",
                subject=component_id,
                detail=(
                    f"declared {counts[component_id]} times — component() and every"
                    " lookup built from the registry resolve to only the last one"
                ),
                severity=ERROR,
            )
        )
    return findings


def _check_no_format(registry: tuple[ComponentSpec, ...]) -> list[AuditFinding]:
    """A component supporting no formats at all.

    What breaks: `fits()` starts with `if fmt not in self.supported_formats:
    return False`, for every `fmt`. An empty `supported_formats` fails that
    test unconditionally, so the component cannot be selected for any
    artifact in any format — it is inert vocabulary, indistinguishable from a
    typo that dropped the format list.
    """
    findings = []
    for spec in registry:
        if not spec.supported_formats:
            findings.append(
                AuditFinding(
                    code="no_format",
                    subject=spec.component_id,
                    detail="supports no formats — cannot be selected for any artifact",
                    severity=ERROR,
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Grammar checks
# ---------------------------------------------------------------------------


def _check_grammar_requires_unknown_role(
    grammars: Mapping[str, Grammar], provided: frozenset[str]
) -> list[AuditFinding]:
    """A grammar requires a role no component provides.

    What breaks: `Grammar.check` reports `missing_role` for every role in
    `requires_roles - present`, and `present` can only ever contain roles some
    component actually supplies. A required role nothing provides is missing
    from *every* possible `present`, so this artifact type fails
    `Grammar.check` unconditionally — no component sequence, however
    constructed, can ever satisfy it.
    """
    findings = []
    for artifact_type, grammar in sorted(grammars.items()):
        for role in sorted(grammar.requires_roles - provided):
            findings.append(
                AuditFinding(
                    code="grammar_requires_unknown_role",
                    subject=artifact_type,
                    detail=(
                        f"requires_roles includes {role!r}, which no component in the"
                        f" registry provides — {artifact_type} can never be satisfied"
                    ),
                    severity=ERROR,
                )
            )
    return findings


def _check_grammar_self_contradictory(grammars: Mapping[str, Grammar]) -> list[AuditFinding]:
    """A role in both requires_roles and forbids_roles.

    What breaks: `Grammar.check` fails `missing_role` when the role is absent
    and `forbidden_role` when it is present. A role required and forbidden at
    once fails one check or the other for every possible sequence — there is
    no `present` set that omits a required role or includes a forbidden one,
    so both cannot be satisfied together, ever.
    """
    findings = []
    for artifact_type, grammar in sorted(grammars.items()):
        for role in sorted(grammar.requires_roles & grammar.forbids_roles):
            findings.append(
                AuditFinding(
                    code="grammar_self_contradictory",
                    subject=artifact_type,
                    detail=(
                        f"{role!r} appears in both requires_roles and forbids_roles —"
                        " no component sequence can satisfy both at once"
                    ),
                    severity=ERROR,
                )
            )
    return findings


def _find_cycle(edges: dict[str, list[str]]) -> tuple[str, ...] | None:
    """One cycle in *edges* (adjacency, already sorted per node), if any exists.

    Classic three-colour DFS. Traversal order is fixed — nodes and each node's
    neighbours are visited in sorted order — so the witness cycle returned is
    the same on every call, which the determinism guarantee (and its test)
    depend on.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {node: WHITE for node in edges}
    path: list[str] = []

    def visit(node: str) -> tuple[str, ...] | None:
        color[node] = GRAY
        path.append(node)
        for neighbor in edges.get(node, ()):
            if color.get(neighbor, WHITE) == WHITE:
                found = visit(neighbor)
                if found is not None:
                    return found
            elif color.get(neighbor) == GRAY:
                start = path.index(neighbor)
                return tuple(path[start:])
        path.pop()
        color[node] = BLACK
        return None

    for node in sorted(edges):
        if color[node] == WHITE:
            found = visit(node)
            if found is not None:
                return found
    return None


def _check_grammar_unsatisfiable_ordering(grammars: Mapping[str, Grammar]) -> list[AuditFinding]:
    """A cycle in ordered_roles: A before B and (transitively) B before A.

    What breaks: `Grammar.check` orders on first appearance — if both roles on
    a cycle occur in a sequence, the check demands each precede the other,
    which no arrangement of two occurring roles can satisfy. This is checked
    unconditionally (not only when the cyclic roles are also required)
    because the contradiction is in the declaration itself: the moment any
    document happens to use every role on the cycle, `Grammar.check` fails it
    no matter how the components are ordered.
    """
    findings = []
    for artifact_type, grammar in sorted(grammars.items()):
        nodes = sorted({role for pair in grammar.ordered_roles for role in pair})
        edges: dict[str, list[str]] = {node: [] for node in nodes}
        for earlier, later in grammar.ordered_roles:
            edges[earlier].append(later)
        for node in edges:
            edges[node].sort()

        cycle = _find_cycle(edges)
        if cycle is not None:
            path = " -> ".join((*cycle, cycle[0]))
            findings.append(
                AuditFinding(
                    code="grammar_unsatisfiable_ordering",
                    subject=artifact_type,
                    detail=(
                        f"ordered_roles contains a cycle ({path}) — no sequence can place"
                        " every role on the cycle before every other role on it"
                    ),
                    severity=ERROR,
                )
            )
    return findings


def _check_grammar_cap_below_requirement(grammars: Mapping[str, Grammar]) -> list[AuditFinding]:
    """max_components smaller than the number of distinct required roles.

    What breaks: `Grammar.check` fails `too_many_components` above the cap and
    `missing_role` for any required role absent from the sequence. This is
    reported as a warning rather than an error because the bound is
    pessimistic, not proven: one component can carry more than one semantic
    role at once (see `finance.variance_bridge`, which fills both
    `explain_change` and `evidence`), so a cap below the *role* count does not
    strictly rule out a sequence that satisfies every role with fewer
    components than roles. It is still a strong signal something is
    miscounted, which is why it is reported at all.
    """
    findings = []
    for artifact_type, grammar in sorted(grammars.items()):
        if grammar.max_components is None:
            continue
        required = len(grammar.requires_roles)
        if grammar.max_components < required:
            findings.append(
                AuditFinding(
                    code="grammar_cap_below_requirement",
                    subject=artifact_type,
                    detail=(
                        f"max_components={grammar.max_components} but requires_roles has"
                        f" {required} distinct roles {sorted(grammar.requires_roles)} —"
                        " likely cannot be satisfied within its own cap"
                    ),
                    severity=WARNING,
                )
            )
    return findings


def _check_grammar_opening_impossible(
    grammars: Mapping[str, Grammar], registry: tuple[ComponentSpec, ...], provided: frozenset[str]
) -> list[AuditFinding]:
    """opens_with names a role nothing provides, or no component filling one is
    supported in any format.

    What breaks: `Grammar.check` requires the *first* component's roles to
    intersect `opens_with` whenever it is non-empty. If no component can ever
    fill one of those roles — because the role does not exist in the registry,
    or every component that fills it supports zero formats — no artifact of
    this type can ever open legally, regardless of what follows.
    """
    findings = []
    for artifact_type, grammar in sorted(grammars.items()):
        if not grammar.opens_with:
            continue  # empty means unconstrained, per Grammar's own docstring

        unknown = sorted(grammar.opens_with - provided)
        if unknown:
            findings.append(
                AuditFinding(
                    code="grammar_opening_impossible",
                    subject=artifact_type,
                    detail=(
                        f"opens_with role(s) {unknown} are provided by no component in the"
                        f" registry — {artifact_type} can never open legally"
                    ),
                    severity=ERROR,
                )
            )
            continue

        matching = [spec for spec in registry if spec.semantic_roles & grammar.opens_with]
        if not any(spec.supported_formats for spec in matching):
            findings.append(
                AuditFinding(
                    code="grammar_opening_impossible",
                    subject=artifact_type,
                    detail=(
                        f"every component filling one of opens_with {sorted(grammar.opens_with)}"
                        f" supports no format — {artifact_type} can never open legally"
                    ),
                    severity=ERROR,
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def audit(
    registry: tuple[ComponentSpec, ...] | None = None,
    grammars: Mapping[str, Grammar] | None = None,
) -> list[AuditFinding]:
    """Every way *registry* and *grammars* fail to be internally coherent.

    Defaults to the shipped `REGISTRY`/`GRAMMARS`, but accepts either
    explicitly — required so a test can hand it a deliberately broken
    registry or grammar without touching the shipped data.

    Never raises: a broken registry is exactly the situation this function
    exists to report, not to fail on. Returns findings sorted by
    ``(code, subject, detail)`` — not insertion order, and not any structure
    that depends on dict or set iteration — so two calls against the same
    input always agree byte-for-byte, matching the determinism the rest of
    the corpus is held to.
    """
    active_registry = REGISTRY if registry is None else registry
    active_grammars = GRAMMARS if grammars is None else grammars
    provided = _all_roles(active_registry)

    findings: list[AuditFinding] = [
        *_check_unsatisfiable_precondition(active_registry),
        *_check_unreachable_component(active_registry, active_grammars),
        *_check_impossible_density(active_registry),
        *_check_contradictory_rows(active_registry),
        *_check_asymmetric_incompatibility(active_registry),
        *_check_duplicate_component_id(active_registry),
        *_check_no_format(active_registry),
        *_check_grammar_requires_unknown_role(active_grammars, provided),
        *_check_grammar_self_contradictory(active_grammars),
        *_check_grammar_unsatisfiable_ordering(active_grammars),
        *_check_grammar_cap_below_requirement(active_grammars),
        *_check_grammar_opening_impossible(active_grammars, active_registry, provided),
    ]
    return sorted(findings, key=lambda finding: (finding.code, finding.subject, finding.detail))


__all__ = ["AuditFinding", "ERROR", "WARNING", "audit"]
