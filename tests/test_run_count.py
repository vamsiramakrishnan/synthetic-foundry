"""How many times an episode has run is not allowed to change the answer.

Every domain check group in this repository was written against a corpus that
held exactly *one* run of its episode, and several of them encoded that
assumption in the way they reach for a fact: the subject's globally latest
booked figure, the corpus's first-and-last central estimate, the whole
world's liquidity series sorted as one line. Under one run "the corpus's
latest" and "this period's" are the same fact, so the defect is invisible;
under two they diverge, and the check either reports a violation the corpus
does not have or — worse — passes because some carry-forward happened to
complete the pair it was looking for.

The blanket CLI refusal that used to make that safe (`--periods N` exited 2
for any single-episode domain) is gone, so nothing outside the check groups
stands between a user and a multi-run corpus. This file is the replacement
gate, and it is a property rather than a fixture per vertical:

    for every domain the registry knows, at N = 1, 2, 3, 4 runs of that
    domain's own period cadence, the compiled corpus validates with zero
    violations.

Three deliberate choices, each of which would rot if left implicit:

- **The domain list comes from the registry** (`domains.names()`), never from
  a literal here. A fifth vertical is covered the day it calls
  `register_domain`, which is the only way this property keeps its meaning —
  a hardcoded list would pass forever while the thing it claims to cover grew.
- **The cadence comes from the domain too** (`Domain.period_step_months`), so
  banking's four runs are four *quarters* and procurement's are four *months*.
  Stepping every domain monthly would build a banking corpus of four
  overlapping quarters, which is not what `--periods 4` builds and so not what
  this file is allowed to check.
- **A refusal is an outcome, not a skip.** `QuarterlyReserving` refuses its own
  second quarter (attribution supersession is increment 2 — the guard lives in
  the scenario, which is the only code that knows). That refusal is recorded in
  `EXPECTED_REFUSALS` and asserted: a domain that starts refusing, or stops,
  fails here rather than silently reducing this property's coverage to N = 1.
  `pytest.skip` would have made insurance's entry in this suite indistinguishable
  from a vertical nobody had got round to covering.

Because insurance's shipped scenario stops at one quarter, the registry path
alone would leave `insurance._checks` unmeasured beyond a single run — and that
group is where the defect class was first found. So the authored insurer
(`examples/packs/longtail-insurer.json`, the same cycle expressed on the cohort
axis, which *can* run repeatedly) carries the same property at N = 1…4. It is
named explicitly rather than derived, because it is a pack on disk rather than
something the registry could hand back.

What this property found when it was first run, seed 8128, so a later reader can
tell a regression from the original state of things: banking (four quarters),
procurement (four months) and retail (four closes) validated clean at every N;
`QuarterlyReserving` refused its second quarter as recorded; and the authored
insurer reported one spurious `unexplained_override` at three valuations and two
at four. Two more checks in the same shape were then found by reading rather than
by running — banking's `correction_before_confirmation` and `correction_exceeds_
error`, plus procurement's `segregation_of_duties_breached` — because a check
that reaches into a neighbouring run to *pass* leaves a corpus that validates
clean, which no property over clean corpora can see. Those are pinned by the
tamper block at the foot of this file, which is where the second half of every
fix lives.

The registry-restoring fixture is `tests/test_cohorts.py`'s, for its reason
verbatim: installing a spec also registers its derived check group, which
`validate` then runs against every world for the rest of the session, and a test
may add to a registry but may not leave anything in one.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from worldloom import (
    Authority,
    BankingWorld,
    InsuranceWorld,
    ProcureToPayWorld,
    PurchaseToPayCycle,
    QuarterlyCapitalReturn,
    QuarterlyReserving,
    World,
    archetypes,
    doctypes,
    domains,
    episodes,
    lob,
    packs,
)
from worldloom import validate as validate_module
from worldloom.scenarios import MonthEndClose

SEED = 8128

#: The first period every domain starts from. A quarter end, so it is a legal
#: valuation/return date for the quarterly verticals and an ordinary month for
#: the monthly ones — one constant rather than a table nobody would maintain.
START = "2026-03"

#: The run counts the property covers. 1 is the world every existing test
#: already builds; 2 is where "the corpus's latest" and "this period's" first
#: diverge; 3 and 4 are where a check that pairs positionally (the *n*-th of
#: this against the *n*-th of that) stops being able to hide behind a pair.
RUN_COUNTS = (1, 2, 3, 4)

#: Scenarios that legitimately refuse a further run, as
#: ``domain -> (run index that refuses, a phrase from the refusal)``. The index
#: is 0-based, so ``1`` means "the second run is refused".
#:
#: Recorded rather than skipped: this table is the difference between "this
#: vertical is capped at one run, on purpose, and here is the reason" and "this
#: vertical is not covered". `test_the_refusals_are_exactly_the_recorded_ones`
#: holds the table to the code both ways.
EXPECTED_REFUSALS: dict[str, tuple[int, str]] = {
    "insurance": (1, "a second QuarterlyReserving run would be phase 2"),
}

#: The authored insurer, and the quarters it observes. The pack is the only
#: multi-quarter insurance corpus that exists today (see the module docstring),
#: so it is what measures `insurance._checks` past its shipped scenario's cap.
INSURER_PACK = "examples/packs/longtail-insurer.json"
INSURER_EPISODE = "QuarterlyValuation"

#: The five process-global registries this file writes to. `tests/test_cohorts.py`
#: names three, which is all an episode spec touches; loading a *pack* installs
#: its doctypes and lines of business too, so the list here is
#: `tests/test_validate_packs.py`'s. Found rather than foreseen, and by exactly
#: the test that pins the consequence: with the two extra registries left dirty,
#: `test_validate_packs`'s packless check count moved from 1283 to 1284 — a
#: leftover doctype from this file's insurer being applied to `retail-close`,
#: reported there as a regression in a path this file is not even about.
_REGISTRIES = (
    lambda: doctypes._INSTALLED,
    lambda: episodes._LOADED,
    lambda: episodes._REGISTERED_CHECKS,
    lambda: lob._INSTALLED,
    lambda: validate_module._DOMAIN_CHECKS,
)


@pytest.fixture(autouse=True)
def _restore_the_registries():
    saved = [(registry(), dict(registry())) for registry in _REGISTRIES]
    try:
        yield
    finally:
        for registry, original in saved:
            registry.clear()
            registry.update(original)


# ---------------------------------------------------------------------------
# Building N runs of an arbitrary domain
# ---------------------------------------------------------------------------


def _step(period: str, index: int, step_months: int) -> str:
    """*period* advanced by *index* steps of *step_months* months.

    The same arithmetic `cli._step_period` performs, restated here rather than
    imported: this file's whole claim is about what `--periods N` produces, and
    a test that borrowed the CLI's own stepping could not tell a broken step
    from a matching one. Both are trivial and neither is allowed to know a
    domain's name.
    """
    year, month = (int(part) for part in period.split("-"))
    total = year * 12 + (month - 1) + index * step_months
    year, month = divmod(total, 12)
    return f"{year:04d}-{month + 1:02d}"


def _episode_for(domain: domains.Domain):
    """``period -> scenario`` for *domain*.

    A domain that registers `single_episode` says how it runs one period, and
    that is what the CLI calls. A domain that registers ``None`` is driven by
    the core close loop instead — `cli.build` runs `MonthEndClose` per period
    for exactly those domains — so mirroring that here keeps this property
    covering retail without naming it, and gives any future domain the same
    default the CLI would give it.
    """
    if domain.single_episode is not None:
        return domain.single_episode
    return lambda period: MonthEndClose(period=period)


#: Prefix worlds, memoised by ``(domain name, runs)``. A world is immutable and
#: every build here is a pure function of `SEED`, so the N = 4 corpus is the
#: N = 3 corpus with one more run on it — building each N from scratch would
#: quadruple this file's cost for identical worlds. Keyed by name (never by the
#: `Domain`, which is not hashable-by-identity across a registry restore) and
#: filled in ascending N, so nothing here depends on iteration order.
_WORLDS: dict[tuple[str, int], World] = {}

#: Where a domain's episode refused, as ``domain name -> (run index, message)``.
#: Filled by `_prefix` the first time it happens; read by the tests below.
_REFUSALS: dict[str, tuple[int, str]] = {}


def _prefix(domain: domains.Domain, runs: int) -> World | None:
    """*domain*'s world with *runs* consecutive periods on it, or ``None`` if
    its episode refused before reaching that many."""
    if runs == 0:
        return domain.world(
            seed=SEED, archetype=archetypes.get(domain.default_archetype)
        ).build()
    key = (domain.name, runs)
    if key in _WORLDS:
        return _WORLDS[key]
    if domain.name in _REFUSALS and _REFUSALS[domain.name][0] < runs:
        return None
    earlier = _prefix(domain, runs - 1)
    if earlier is None:
        return None
    stamp = _step(START, runs - 1, domain.period_step_months)
    try:
        world = earlier.run(_episode_for(domain)(stamp))
    except ValueError as refusal:
        # The scenario is the authority on whether it supports another run —
        # recorded here and asserted below, never swallowed.
        _REFUSALS.setdefault(domain.name, (runs - 1, str(refusal)))
        return None
    _WORLDS[key] = world
    return world


def _violations(world: World) -> list[str]:
    """Every violation the compiled corpus reports, as readable strings.

    Compiled rather than raw, because several domain checks are driven by the
    artifact manifest — insurance's override check reads the memos that explain
    a gap — and a world that has been run but not compiled would pass them for
    having no documents rather than for having coherent ones.
    """
    return [str(violation) for violation in world.compile().validate().violations]


# ---------------------------------------------------------------------------
# The property
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("runs", RUN_COUNTS)
@pytest.mark.parametrize("domain_name", domains.names())
def test_a_corpus_validates_at_any_run_count(domain_name: str, runs: int) -> None:
    """N runs of a domain's own cadence, and zero violations at every N.

    The failure this exists to catch is not a build that crashes — it is a
    corpus that is internally coherent and a check group that says otherwise
    because it reached past the period it was asked about.
    """
    domain = domains.by_name(domain_name)
    assert domain is not None
    world = _prefix(domain, runs)
    if world is None:
        expected = EXPECTED_REFUSALS.get(domain_name)
        assert expected is not None, (
            f"{domain_name} refused run {_REFUSALS[domain_name][0] + 1} and no"
            f" refusal is recorded for it: {_REFUSALS[domain_name][1]}"
        )
        index, phrase = expected
        assert _REFUSALS[domain_name][0] == index
        assert phrase in _REFUSALS[domain_name][1]
        return
    violations = _violations(world)
    assert violations == [], (
        f"{domain_name} at {runs} run(s) of {domain.period_step_months}-month"
        f" periods:\n" + "\n".join(violations)
    )


def test_the_refusals_are_exactly_the_recorded_ones() -> None:
    """The table is held to the code in both directions.

    A domain that gains a refusal fails here rather than quietly dropping out
    of the property above; a domain whose refusal is lifted fails here rather
    than leaving a stale note claiming a cap that no longer exists.
    """
    for domain_name in domains.names():
        domain = domains.by_name(domain_name)
        assert domain is not None
        for runs in RUN_COUNTS:
            _prefix(domain, runs)
    assert {name: index for name, (index, _) in _REFUSALS.items()} == {
        name: index for name, (index, _) in EXPECTED_REFUSALS.items()
    }


# ---------------------------------------------------------------------------
# The insurer past its shipped scenario's cap
# ---------------------------------------------------------------------------


def _authored_insurer(quarters: int) -> World:
    """The pack's insurer, *quarters* consecutive valuations deep."""
    pack = packs.load(INSURER_PACK)
    world = InsuranceWorld.from_pack(pack, seed=SEED).build()
    for index in range(quarters):
        world = world.run(episodes.AuthoredEpisode(
            episode=INSURER_EPISODE, period=_step(START, index, 3),
        ))
    return world.compile()


@pytest.mark.parametrize("quarters", RUN_COUNTS)
def test_the_authored_insurer_validates_at_any_quarter_count(quarters: int) -> None:
    """The same property, on the only multi-quarter insurance corpus there is.

    `QuarterlyReserving` refuses its second quarter, so the registry path above
    can say nothing about `insurance._checks` past one run — and that group is
    where this defect class was first measured: check (g) resolved the booked
    figure as the subject's globally latest rather than the one belonging to the
    gap's own valuation, which is invisible at one quarter and wrong at four.
    """
    violations = _violations(_authored_insurer(quarters))
    assert violations == [], f"{quarters} valuation(s):\n" + "\n".join(violations)

# ---------------------------------------------------------------------------
# The tampers: every check the property moved is shown still firing
# ---------------------------------------------------------------------------
#
# A check that stops firing is worse than one that fires spuriously, and every
# fix here narrowed *which* fact a check reaches for. So each one is pinned
# twice: it still reports the defect it exists to catch, in a corpus of several
# runs, and it no longer reaches into a neighbouring run to reach its verdict.
# The second half is the half the property above cannot state — a check that
# passes for the wrong reason validates clean, which is exactly why the class
# survived this long.
#
# The tamper idiom is `tests/test_banking.py`'s: `dataclasses.replace` on the
# world with a `model_copy`-ed fact or manifest entry, then read the violation
# codes back. Extra unrelated violations are expected and ignored — a tamper is
# allowed to be crude as long as the assertion is precise.


def _report(world: World):
    return world.validate().violations


def _of(world: World, code: str) -> list:
    return [violation for violation in _report(world) if violation.code == code]


def _facts_of(world: World, kind: str) -> list:
    return [fact for fact in world.facts if fact.kind == kind]


# -- insurance (g): the override memo explains this valuation's gap ----------


def test_the_override_check_fires_for_each_valuations_own_memo() -> None:
    """Strip the booked totals from one quarter's memo and exactly that
    quarter's gap goes unexplained.

    Four quarters, tampered one at a time, because the two halves of the defect
    live in different quarters: before the fix, quarters 1 and 2 were reported
    as unexplained while their own memos explained them perfectly, and quarter 3
    *passed* on quarter 4's memo — which cites the prior central estimate as a
    comparative beside its own booked total, and so completed the pair this
    check looks for out of two different valuations. Asserting the violation's
    subject, not just its code, is what pins that: a check that fires for the
    right quarter cannot be borrowing another quarter's evidence.
    """
    world = _authored_insurer(4)
    booked = {fact.id for fact in _facts_of(world, "reserves.booked_total")}
    gaps = sorted(_facts_of(world, "reserves.held_vs_central_gap"),
                  key=lambda fact: fact.valid_from)
    memos = sorted((a for a in world.artifacts if a.artifact_type == "margin_decision_memo"),
                   key=lambda entry: entry.created_at)
    assert len(memos) == len(gaps) == 4

    for gap, memo in zip(gaps, memos):
        tampered = replace(world, _artifacts=tuple(
            entry.model_copy(update={"supporting_fact_ids": [
                fact_id for fact_id in entry.supporting_fact_ids if fact_id not in booked
            ]}) if entry.id == memo.id else entry
            for entry in world._artifacts
        ))
        reported = _of(tampered, "unexplained_override")
        assert [violation.subject for violation in reported] == [gap.id], (
            f"stripping {memo.id} should leave {gap.id} unexplained and nothing else"
        )


# -- insurance (e): the attribution decomposes its own valuation's movement --


def test_the_attribution_check_still_fires_on_a_split_that_does_not_sum() -> None:
    """The shipped insurer, with the pattern-change half overstated."""
    world = InsuranceWorld(seed=SEED).build().run(QuarterlyReserving(period=START)).compile()
    assert _of(world, "attribution_does_not_sum") == []

    pattern = _facts_of(world, "reserves.attribution_pattern_change")[0]
    tampered = replace(world, _facts=tuple(
        fact.model_copy(update={
            "value": fact.value.model_copy(update={"amount": fact.value.amount + 10})
        }) if fact.id == pattern.id else fact
        for fact in world._facts
    ))
    assert [v.subject for v in _of(tampered, "attribution_does_not_sum")] == [pattern.id]


def test_a_later_valuation_does_not_change_what_an_attribution_decomposes() -> None:
    """A second quarter's central estimate arriving must not fail the first
    quarter's split.

    `QuarterlyReserving` refuses its own second quarter, so the second estimate
    is planted rather than run — which is the only way to state this claim
    today, and stating it is the point: the check compared the split against
    `central[-1] - central[0]`, first against last across the whole corpus, so
    the day a second valuation lands (increment 2, or an authored episode that
    mints attribution) a correct split would have been reported as arithmetic
    that does not add up. The movement a split decomposes is its own quarter's
    step, and a later quarter is not part of it.
    """
    world = InsuranceWorld(seed=SEED).build().run(QuarterlyReserving(period=START)).compile()
    estimates = sorted(_facts_of(world, "reserves.central_estimate_total"),
                       key=lambda fact: fact.valid_from)
    next_quarter = estimates[-1].model_copy(update={
        "id": "FACT-9801",
        "valid_from": estimates[-1].valid_from + timedelta(days=90),
        "value": estimates[-1].value.model_copy(
            update={"amount": estimates[-1].value.amount + 50}
        ),
    })
    later = replace(world, _facts=(*world._facts, next_quarter))
    assert _of(later, "attribution_does_not_sum") == []


# -- insurance (d): booked = central + margin, within one valuation ----------


def test_the_booking_check_fires_on_the_valuation_that_does_not_reconcile() -> None:
    """One quarter's booked total moved, and only that quarter is reported."""
    world = _authored_insurer(4)
    booked = sorted(_facts_of(world, "reserves.booked_total"), key=lambda fact: fact.valid_from)
    target = booked[1]
    tampered = replace(world, _facts=tuple(
        fact.model_copy(update={
            "value": fact.value.model_copy(update={"amount": fact.value.amount + 7})
        }) if fact.id == target.id else fact
        for fact in world._facts
    ))
    assert [v.subject for v in _of(tampered, "booked_does_not_reconcile")] == [target.id]


def test_a_valuation_missing_a_margin_does_not_shift_the_later_ones() -> None:
    """Drop the first quarter's margin and the later quarters still reconcile.

    This is the positional `zip` the check used to pair with, stated as a
    corpus: with one figure missing from the first round, the *n*-th booked
    total lined up with the (*n*+1)-th central estimate for every round after
    it, and three coherent valuations were reported as arithmetic errors.
    Nothing here is a defect in the corpus — a valuation that states no margin
    simply cannot be checked — so the right answer is silence about it and the
    truth about its neighbours.
    """
    world = _authored_insurer(4)
    margins = sorted(_facts_of(world, "reserves.risk_margin_remaining"),
                     key=lambda fact: fact.valid_from)
    without = replace(world, _facts=tuple(
        fact for fact in world._facts if fact.id != margins[0].id
    ))
    assert _of(without, "booked_does_not_reconcile") == []


# -- banking (c): a correction follows its own quarter's confirmed cause -----


def _banking(quarters: int) -> World:
    world = BankingWorld(seed=SEED).build()
    for index in range(quarters):
        world = world.run(QuarterlyCapitalReturn(period=_step(START, index, 3)))
    return world.compile()


def _restatement_periods(world: World, entry) -> set[str]:
    by_id = {fact.id: fact for fact in world.facts}
    return {
        by_id[fact_id].period for fact_id in entry.supporting_fact_ids
        if fact_id in by_id and by_id[fact_id].kind.startswith("capital.")
        and by_id[fact_id].period
    }


def test_a_correction_still_cannot_precede_its_own_quarters_confirmed_cause() -> None:
    """Backdate the second quarter's restatement to the first quarter's cause.

    Which is precisely the corpus the unscoped check could not see: a June
    correction lodged months before June's own root cause was confirmed, but
    after March's was, passed a check whose whole claim is that a correction
    is not a guess. The document is the one that moved, so the tamper moves the
    document rather than the facts.
    """
    world = _banking(2)
    assert _of(world, "correction_before_confirmation") == []

    restatements = sorted(
        (entry for entry in world.artifacts if entry.restates),
        key=lambda entry: entry.created_at,
    )
    assert len(restatements) == 2
    second = restatements[-1]
    assert _restatement_periods(world, second) == {_step(START, 1, 3)}

    causes = sorted(
        fact.valid_from for fact in world.facts
        if fact.kind == "ops.cause" and fact.authority is Authority.CONFIRMED
    )
    # Between the two quarters' confirmations: after the first, before the
    # second. Under the corpus-wide reading this instant cleared the check.
    between = causes[0] + timedelta(days=1)
    assert between < causes[-1]
    tampered = replace(world, _artifacts=tuple(
        entry.model_copy(update={"created_at": between}) if entry.id == second.id else entry
        for entry in world._artifacts
    ))
    assert [v.subject for v in _of(tampered, "correction_before_confirmation")] == [second.id]


# -- banking (e): the correction is scoped to this quarter's error -----------


def test_a_correction_citing_a_book_that_moved_in_another_quarter_is_refused() -> None:
    """A June restatement citing a new figure for a book that only moved in March.

    Two tampers, because the corpus does not contain this shape on its own: the
    stale collateral mapping hits the same book every quarter, so "moved
    somewhere" and "moved here" never diverge in a shipped bank. A March
    movement is planted for an untouched book, and June's restatement is made to
    cite a new June figure for it. The scoped check calls that what it is — a
    second, unconfirmed correction — while the corpus-wide one waved it through
    on the strength of March.
    """
    world = _banking(2)
    quarters = [_step(START, index, 3) for index in range(2)]
    untouched = next(
        fact for fact in world.facts
        if fact.kind == "capital.rwa_by_book" and fact.period == quarters[0]
        and not fact.supersedes and not fact.is_superseded
    )
    moved_in_march = untouched.model_copy(update={
        "id": "FACT-9701",
        "supersedes": untouched.id,
        "valid_from": untouched.valid_from + timedelta(days=40),
    })
    june = next(
        fact for fact in world.facts
        if fact.kind == "capital.rwa_by_book" and fact.period == quarters[1]
        and fact.subject == untouched.subject and not fact.supersedes
    )
    stray = june.model_copy(update={
        "id": "FACT-9702",
        "valid_from": june.valid_from + timedelta(days=40),
        "value": june.value.model_copy(update={"amount": june.value.amount + 75}),
    })
    restatement = max(
        (entry for entry in world.artifacts if entry.restates),
        key=lambda entry: entry.created_at,
    )
    tampered = replace(
        world,
        _facts=(*world._facts, moved_in_march, stray),
        _artifacts=tuple(
            entry.model_copy(update={
                "supporting_fact_ids": [*entry.supporting_fact_ids, stray.id]
            }) if entry.id == restatement.id else entry
            for entry in world._artifacts
        ),
    )
    reported = _of(tampered, "correction_exceeds_error")
    assert [violation.subject for violation in reported] == [restatement.id]
    assert untouched.subject in reported[0].detail
    assert quarters[1] in reported[0].detail


# -- procurement (h): the order they raised is this month's order ------------


def _procurement(months: int) -> World:
    world = ProcureToPayWorld(seed=SEED).build()
    for index in range(months):
        world = world.run(PurchaseToPayCycle(period=_step(START, index, 1)))
    return world.compile()


def _orders(world: World) -> list:
    return sorted(
        (entry for entry in world.artifacts if entry.artifact_type == "purchase_order"),
        key=lambda entry: entry.created_at,
    )


@pytest.mark.parametrize("month", (0, 2))
def test_segregation_of_duties_fires_for_the_month_whose_own_order_it_was(month: int) -> None:
    """The approver raised one month's order, and that month is what is reported.

    Both directions of the same defect in one assertion. Before the scoping, a
    buyer who raised *any* order in the corpus was reported in *every* month
    they approved an exception in — three accusations for one breach — and each
    of them cited whichever purchase order sorted first in the manifest, so a
    genuine August breach was evidenced with January's document. The subject and
    the named order are both asserted, because the code alone cannot tell those
    two failures apart.
    """
    world = _procurement(3)
    assert _of(world, "segregation_of_duties_breached") == []

    approver = next(
        fact for fact in world.facts if fact.kind == "p2p.exception_approved_by"
    )
    order = _orders(world)[month]
    tampered = replace(world, _artifacts=tuple(
        entry.model_copy(update={"author_id": approver.subject})
        if entry.id == order.id else entry
        for entry in world._artifacts
    ))
    reported = _of(tampered, "segregation_of_duties_breached")
    assert len(reported) == 1, [violation.detail for violation in reported]
    assert order.id in reported[0].detail
