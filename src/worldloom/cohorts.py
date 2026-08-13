"""The cohort axis, held to what it declares.

``episodes.CohortSpec`` gives a process a second key — origin cohort beside
observation date — and three things follow from it that nothing in core can
check, because core has no vocabulary for a grid:

rolls-up-to
    A cohort-keyed kind declaring ``Invariant(kind="rolls-up-to",
    operands=[parent])`` owes its parent an exact reconciliation: the cells in
    view at one valuation sum to the parent's amount, to the cent. The
    allocation makes that true by construction (largest remainder, never drawn
    and summed), which is precisely why it is worth recomputing — a check that
    only ever passes on correct arithmetic is what catches the arithmetic
    changing.
grid completeness
    Every declared cohort period has exactly one cell per valuation. A grid
    with a hole is not a smaller grid: every roll-up over it is short by an
    unknown amount, and no reader can tell a cohort that reported nothing from
    one nobody minted. The lint refuses ``period-scoped`` on a cohort kind for
    the same reason; this is that refusal enforced against the facts rather
    than against the declaration.
cohort-period sanity
    No cell's cohort is at or after the valuation observing it. A quarter that
    has not happened cannot have developed, and a grid stating a figure for one
    is stating a figure nobody could hold.

Why this is a module of its own rather than more of ``episodes.derived_checks``:
the grid is a property of the *episode*, not of a kind — completeness and
period sanity are claims about a whole column, and the roll-up crosses two
kinds and an axis declaration. ``derived_checks`` is a per-kind, per-invariant
loop and folding a cross-kind grid into it would put the axis arithmetic in the
middle of the invariant switch, where the next reader would have to know the
grammar to read the reconciliation. Registered under its own name, this group
also runs over *every* installed spec at once, which is what lets it check a
world built before the spec was authored.

Recovering the valuation, which is the one thing a cell does not carry
--------------------------------------------------------------------
A cell's ``period`` is its cohort, and the valuation lives in ``valid_from``
plus the supersession chain (``CohortSpec``'s docstring says why: a ``cohort``
field on ``CanonicalFact`` would serialise ``"cohort": null`` into every fact
line of every corpus ever built). So a check that needs to say *which
valuation* a cell belongs to has to recover it, and it recovers it from the run
the cell was minted in: the nearest-in-time fact of one of the episode's own
**non-cohort** kinds, whose ``period`` is the valuation by construction
(``episodes.run`` sets ``fact_period = period`` for every kind that is not
standing, a series, or a cohort).

Nearest in time, in both directions, rather than the latest one at or before —
because a run's parent total may be minted before or after its cells (the
reserving example freezes the booked total last) and a rule that looked only
backwards would attribute a whole column to the *previous* valuation and
silently check the wrong grid. What makes "nearest" safe is that runs are a
period apart while one run's events are hours apart: the anchor competing with
a cell's own run is three months away. A world with no such anchor at all —
an episode whose every kind is cohort-keyed — is skipped rather than guessed
at, and that is the one shape of world these checks cannot see.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

from . import validate as validate_module
from .validate import Violation

if TYPE_CHECKING:  # pragma: no cover
    from datetime import datetime

    from .models import CanonicalFact
    from .world import World

#: How far a grid may miss its parent before it is a defect, in the money
#: unit's own smallest denomination.
#:
#: Half a cent, not ``validate.RECONCILIATION_TOLERANCE`` (a whole currency
#: unit): that tolerance exists because financial facts are *authored* as
#: rounded whole units and sub-unit drift is expected there. A cohort grid is
#: not authored — it is allocated from its parent by largest remainder, which
#: is exact by construction — so the only drift it can legitimately show is
#: float noise on a handful of additions, ~1e-9. Anything at a cent is
#: arithmetic that changed, and the whole value of an exact allocation is that
#: the check over it can be exact too.
CENT = 0.005


def check(
    facts: Sequence[CanonicalFact], specs: Iterable[Any]
) -> tuple[list[Violation], int]:
    """Check every cohort axis *specs* declares against *facts*.

    Split out from the registered group so a grid can be checked without a
    world: the tamper tests build the cells directly, which is what lets each
    check be shown *firing* on a hand-made defect rather than only passing on
    a world some generator happened to produce.
    """
    # Late, and function-scoped: the arithmetic that says which cohorts a
    # valuation observes has exactly one implementation (`episodes`), because
    # a second one would drift and the two grids would disagree about which
    # quarters they are even about. Imported here rather than at module scope
    # so `episodes` stays free to import this module later without a cycle.
    from .episodes import cohort_periods

    violations: list[Violation] = []
    checks = 0

    def fail(code: str, subject: str, detail: str) -> None:
        violations.append(Violation("cohort", code, subject, detail))

    by_kind: dict[str, list[CanonicalFact]] = {}
    for fact in facts:
        by_kind.setdefault(fact.kind, []).append(fact)

    for spec in specs:
        axes = {axis.name: axis for axis in spec.cohorts}
        if not axes:
            continue
        declared = {fk.kind: fk for fk in spec.fact_kinds}
        cohort_kinds = {kind: fk for kind, fk in declared.items() if fk.cohort}
        # The domain-check contract's early return, and here it is load-bearing
        # rather than merely cheap: every installed spec is checked against
        # every world, so a world that never ran this episode must cost it
        # nothing *and* must not be measured against a grid it never had.
        if not any(by_kind.get(kind) for kind in cohort_kinds):
            continue

        # The valuation anchors: this episode's own non-cohort facts, which
        # carry the observing period in `period` because the runner puts it
        # there. Sorted by (moment, id) so "nearest" resolves identically in
        # any process — ties are broken by the earlier moment and then by id,
        # never by whatever order the facts arrived in.
        anchors = sorted(
            (fact.valid_from, fact.id, fact.period)
            for kind, fk in declared.items()
            if not fk.cohort
            for fact in by_kind.get(kind, ())
            if fact.period
        )
        if not anchors:
            continue

        # Memoised on the moment, because a run mints a whole column at one
        # instant: without it every cell and every parent rescans every anchor
        # in the world, which is the quadratic shape `_Validator.__init__`
        # describes at length and pays for once.
        resolved: dict[datetime, str] = {}

        def valuation_of(at: datetime, _anchors=anchors, _seen=resolved) -> str:
            """Which observation a fact minted at *at* belongs to."""
            if at not in _seen:
                _seen[at] = min(
                    _anchors,
                    key=lambda anchor: (abs(anchor[0] - at), anchor[0], anchor[1]),
                )[2]
            return _seen[at]

        for kind, fk in sorted(cohort_kinds.items()):
            axis = axes.get(fk.cohort)
            cells = by_kind.get(kind, ())
            # A kind naming an axis the episode does not declare is the lint's
            # finding, not this group's: guessing a grid for it would report a
            # hole in every cohort of a grid nobody ever declared.
            if axis is None or not cells:
                continue

            # A column is one valuation's view of the whole grid — the cells
            # sharing a subject and a minting moment, which is the reading
            # docs/episode-grammar.md gives ("facts sharing this run's
            # `valid_from`"). Subject is part of the key because a kind minted
            # on two subjects is two grids, and merging them would let one
            # subject's cell fill another's hole.
            columns: dict[tuple[str, datetime], list[CanonicalFact]] = {}
            for cell in cells:
                columns.setdefault((cell.subject, cell.valid_from), []).append(cell)

            grids: dict[str, tuple[str, ...]] = {}
            for (subject, at), column in sorted(columns.items()):
                valuation = valuation_of(at)
                if valuation not in grids:
                    grids[valuation] = cohort_periods(valuation, axis)
                grid = grids[valuation]
                where = f"{kind}/{subject}@{valuation}"

                observed: dict[str | None, list[CanonicalFact]] = {}
                for cell in column:
                    observed.setdefault(cell.period, []).append(cell)

                # -- completeness: one cell per declared cohort, no more -----
                for cohort in grid:
                    checks += 1
                    present = observed.get(cohort, ())
                    if not present:
                        fail("cohort_grid_hole", where,
                             f"no cell for cohort {cohort} — the grid this valuation"
                             f" observes is {', '.join(grid)}, and a missing cell makes"
                             " every roll-up over it short by an unknown amount")
                    elif len(present) > 1:
                        fail("cohort_cell_duplicated", where,
                             f"{len(present)} cells for cohort {cohort}"
                             f" ({', '.join(sorted(f.id for f in present))}) — a"
                             " valuation states one figure per cohort, and two make"
                             " the sum a choice rather than a reading")
                for cohort in sorted(observed, key=lambda p: (p is None, p or "")):
                    if cohort in grid:
                        continue
                    checks += 1
                    stated = f"cohort {cohort}" if cohort else "no cohort at all"
                    fail("cohort_off_grid", where,
                         f"{', '.join(sorted(f.id for f in observed[cohort]))} carries"
                         f" {stated}, which is not one of the cohorts this valuation"
                         f" observes ({', '.join(grid)})")

                # -- sanity: a cohort the valuation could not have seen ------
                # Compared as strings, which is chronological because a period
                # is zero-padded ``YYYY-MM`` everywhere in this repository —
                # the same property `previous_periods` relies on to produce a
                # window it can index.
                #
                # `>=` rather than `>`: the observing period itself is not yet
                # developed either. That is what `lag_months` is for, and it is
                # why the shipped insurer's newest accident quarter is a
                # quarter behind its valuation rather than level with it.
                for cell in sorted(column, key=lambda f: f.id):
                    if cell.period is None:
                        continue  # already reported off-grid; nothing to compare
                    checks += 1
                    if cell.period >= valuation:
                        fail("cohort_after_valuation", cell.id,
                             f"is about cohort {cell.period} at the {valuation}"
                             " valuation — a cohort at or after the observation has"
                             " not developed, so there is nothing to have observed")

        # -- roll-up: the cells in view sum to their parent ------------------
        for kind, fk in sorted(cohort_kinds.items()):
            cells = by_kind.get(kind, ())
            if not cells:
                continue
            for invariant in fk.invariants:
                if invariant.kind != "rolls-up-to" or not invariant.operands:
                    continue
                parent_kind = invariant.operands[0]
                parents = by_kind.get(parent_kind, ())
                if not parents:
                    continue

                # Cells bucketed by the valuation they were minted at, then by
                # the cell they are a version of. Two buckets rather than one
                # because a valuation can mint a kind twice (the reserving
                # episode records the prior diagonal beside the current one),
                # and summing both columns against one parent would double the
                # grid.
                in_view: dict[str, dict[tuple[str, str | None], list[CanonicalFact]]] = {}
                for cell in cells:
                    at_valuation = in_view.setdefault(valuation_of(cell.valid_from), {})
                    at_valuation.setdefault((cell.subject, cell.period), []).append(cell)

                for parent in sorted(parents, key=lambda f: f.id):
                    if parent.value is None:
                        continue
                    valuation = valuation_of(parent.valid_from)
                    buckets = in_view.get(valuation)
                    if not buckets:
                        checks += 1
                        # Only reachable because this kind has cells somewhere
                        # in this world — so the grid exists and this valuation
                        # is missing it, which is the whole-grid case the
                        # per-cohort hole check cannot see (it has no column to
                        # look in).
                        fail("cohort_grid_absent", parent.id,
                             f"states a {parent_kind} for the {valuation} valuation"
                             f" and no {kind} cell was minted at it — a parent with"
                             " no grid under it reconciles against nothing")
                        continue

                    # A grid keyed on the parent's own subject when there is
                    # one, every subject otherwise: a kind may sit at the same
                    # scope as its parent (one book's triangle under that
                    # book's total) or below it, and summing every subject's
                    # triangle against one subject's total would fail a correct
                    # world.
                    scoped = {
                        key: versions for key, versions in buckets.items()
                        if key[0] == parent.subject
                    } or buckets

                    summed = 0.0
                    counted = 0
                    for _, versions in sorted(scoped.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
                        cell = _stated_at(parent, versions)
                        if cell.value is None:
                            continue
                        summed += cell.value.amount
                        counted += 1
                    if not counted:
                        continue
                    checks += 1
                    shortfall = parent.value.amount - summed
                    if abs(shortfall) > CENT:
                        fail("cohort_rollup_short", parent.id,
                             f"{counted} {kind} cells in view at {valuation} sum to"
                             f" {summed:,.2f} against a stated {parent.value.amount:,.2f}"
                             f" — short by {shortfall:,.2f}")

    return violations, checks


def _stated_at(
    parent: CanonicalFact, versions: list[CanonicalFact]
) -> CanonicalFact:
    """Which version of one cell the *parent* is stating.

    The one current at the parent's moment — and, when the run mints its cells
    *after* the total it allocates from, the first version the grid holds.
    ``holds_at`` is not the test: a valuation supersedes its predecessor cell by
    cell and leaves the predecessor's window open (``episodes.run`` mints no
    ``valid_to`` on a cell), so at a later valuation both versions "hold" and
    summing what holds would count the grid twice.
    """
    ordered = sorted(versions, key=lambda f: (f.valid_from, f.id))
    current = [f for f in ordered if f.valid_from <= parent.valid_from]
    return current[-1] if current else ordered[0]


def _specs() -> tuple[Any, ...]:
    """Every installed process spec, in a fixed order.

    Sorted by name so a violation list does not depend on install order — the
    registry is a dict, and two processes installed in either order have to
    produce the same report.
    """
    from . import episodes

    return tuple(spec for _, spec in sorted(episodes.loaded().items()))


def _checks(world: World) -> tuple[list[Violation], int]:
    return check(list(world.facts), _specs())


validate_module.register_domain_checks("cohorts", _checks)
