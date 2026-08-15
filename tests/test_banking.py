"""The banking vertical: one challenged capital return, held to its contract.

The episode's claims, each pinned: the filing is immutable and the restatement
leaves it standing; the two lodgements tie on authority so only the ``restates``
edge and fact validity resolve them; the as-filed record is never touched; the
daily cadence runs gapless through the window; the contested treatment coexists
legally at different authority and illegally at equal; and the whole thing
replays byte-for-byte from its seed and from its own recipe.

Tamper tests follow the actor-suite convention: every banking check is shown
*firing*, not just passing, because a check that has never failed proves only
that it compiles.
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from datetime import timedelta

import pytest
from typer.testing import CliRunner

from worldloom import (
    Authority,
    BankingWorld,
    Lifecycle,
    QuarterlyCapitalReturn,
    World,
)
from worldloom.banking import FILING_TYPES
from worldloom.cli import app
from worldloom.evaluate import score
from worldloom.models import EvaluationType

runner = CliRunner()

PERIOD = "2026-03"
SECOND_PERIOD = "2026-06"
SEED = 8128


@pytest.fixture(scope="module")
def world() -> World:
    return BankingWorld(seed=SEED).build().run(QuarterlyCapitalReturn(period=PERIOD))


@pytest.fixture(scope="module")
def compiled(world: World) -> World:
    return world.compile()


@pytest.fixture(scope="module")
def two_quarters() -> World:
    """A second consecutive quarter on the same world — the coherence surface
    ``QuarterlyCapitalReturn.run`` and the banking check group were reworked
    for. Three months apart (``PERIOD`` to ``SECOND_PERIOD``), matching the
    domain's registered ``period_step_months`` rather than one month, so this
    fixture exercises the same stepping a `--periods 2` CLI build performs."""
    return (
        BankingWorld(seed=SEED).build()
        .run(QuarterlyCapitalReturn(period=PERIOD))
        .run(QuarterlyCapitalReturn(period=SECOND_PERIOD))
    )


def codes(world: World) -> set[str]:
    return {v.code for v in world.validate().violations}


# ---------------------------------------------------------------------------
# The episode is coherent
# ---------------------------------------------------------------------------


def test_the_episode_is_coherent(compiled: World) -> None:
    report = compiled.validate()
    assert report.ok, "\n".join(str(v) for v in report.violations)


def test_locale_holidays_cannot_move_a_cause_after_its_effect() -> None:
    world = BankingWorld(
        seed=81_281, locale="germany", estate="large"
    ).build().run(QuarterlyCapitalReturn(period=PERIOD))

    events = {event.id: event for event in world.events}
    assert all(
        events[cause].occurred_at <= event.occurred_at
        for event in world.events
        for cause in event.caused_by
    )
    report = world.validate()
    assert report.ok, "\n".join(str(v) for v in report.violations)


def test_the_shape_of_the_episode(world: World) -> None:
    """Twelve artifacts — the nine records, the approval minutes, the
    pre-lodgement thread and the divisional performance pack — two labelled
    omissions, and the three cadences' facts."""
    assert len(world.artifact_intents) == 12
    assert len(world.intentional_errors) == 2
    kinds = {f.kind for f in world.facts}
    # Retail's kinds reused verbatim — the cross-vertical sharing evidence.
    assert {"close.due_date", "close.status", "close.delay"} <= kinds
    assert {"ops.cause", "ops.cause_ruled_out", "ops.affected_records",
            "ops.root_cause_classification", "ops.remediation_addresses"} <= kinds
    # Banking's own vocabulary.
    assert {"capital.cet1_ratio", "capital.cet1_ratio_as_filed",
            "capital.rwa_by_book", "review.challenge", "liquidity.lcr",
            "regulatory.notification"} <= kinds


def test_the_books_decompose_the_total_exactly(world: World) -> None:
    """Largest-remainder discipline, banking's version of the retail roll-up."""
    filed_total = next(
        f for f in world.facts.where(kind="capital.rwa_total")
        if f.authority is Authority.SYSTEM_OF_RECORD and f.is_superseded
    )
    books = [
        f for f in world.facts.where(kind="capital.rwa_by_book")
        if f.holds_at(filed_total.valid_from)
    ]
    assert len(books) == 7
    assert sum(f.value.amount for f in books) == filed_total.value.amount


# ---------------------------------------------------------------------------
# The restatement contract
# ---------------------------------------------------------------------------


def test_the_filing_stays_on_the_record(compiled: World) -> None:
    """The defining property: correction without retirement."""
    filed, restatement = [
        a for a in compiled.artifacts if a.artifact_type in FILING_TYPES
    ]
    assert restatement.restates == filed.id
    assert filed.lifecycle is Lifecycle.PUBLISHED
    assert restatement.lifecycle is Lifecycle.PUBLISHED
    assert compiled.provenance(filed.id)["restated_by"] == [restatement.id]
    assert compiled.provenance(restatement.id)["restates"] == filed.id


def test_the_lodgements_tie_on_authority(compiled: World) -> None:
    """The A10 trap, structurally: rank cannot resolve the pair, so anything
    that answers 'which figure is current' has to walk the restates edge or
    the facts' validity windows."""
    filed, restatement = [
        a for a in compiled.artifacts if a.artifact_type in FILING_TYPES
    ]
    assert filed.authority is Authority.SYSTEM_OF_RECORD
    assert restatement.authority is Authority.SYSTEM_OF_RECORD

    # And fact validity does resolve it.
    ratio = compiled.authoritative("capital.cet1_ratio", compiled.company.id, period=PERIOD)
    corrected = compiled.facts.by_id(ratio.id)
    assert corrected.supersedes is not None
    filed_ratio = compiled.facts.by_id(corrected.supersedes)
    assert filed_ratio.value.amount > corrected.value.amount


def test_what_was_reported_between_filing_and_restatement(world: World) -> None:
    """The temporal inverse of the contested figure: at a cutoff between the
    lodgements, the filed — later proven wrong — figure is the answer."""
    filed_ratio = next(
        f for f in world.facts.where(kind="capital.cet1_ratio")
        if f.authority is Authority.SYSTEM_OF_RECORD and f.is_superseded
    )
    between = filed_ratio.valid_from + (filed_ratio.valid_to - filed_ratio.valid_from) / 2
    held = [
        f for f in world.as_of(between).where(kind="capital.cet1_ratio")
        if f.authority is Authority.SYSTEM_OF_RECORD
    ]
    assert [f.value.amount for f in held] == [filed_ratio.value.amount]
    as_filed = world.facts.where(kind="capital.cet1_ratio_as_filed")
    assert len(as_filed) == 1 and as_filed[0].valid_to is None


def test_the_working_paper_is_revised_beside_the_restatement(compiled: World) -> None:
    """The pairing that teaches the difference: `revises` retires v1 and keeps
    the document's identity; `restates` leaves the filing standing."""
    v1, v2 = [a for a in compiled.artifacts if a.artifact_type == "rwa_working_paper"]
    assert v2.revises == v1.id and v2.version == 2
    assert v1.lifecycle is Lifecycle.SUPERSEDED


def test_a_retired_filing_trips_the_core_check(compiled: World) -> None:
    filed = next(a for a in compiled.artifacts if a.artifact_type in FILING_TYPES)
    tampered = replace(compiled, _artifacts=tuple(
        a.model_copy(update={"lifecycle": Lifecycle.SUPERSEDED}) if a.id == filed.id else a
        for a in compiled._artifacts
    ))
    found = codes(tampered)
    assert "restated_original_retired" in found
    assert "filing_left_the_record" in found


def test_a_revised_filing_trips_the_banking_check(compiled: World) -> None:
    """`revises` aimed at a filing is the correction the domain forbids."""
    filed = next(a for a in compiled.artifacts if a.artifact_type in FILING_TYPES)
    memo = next(a for a in compiled.artifacts if a.artifact_type == "second_line_challenge_memo")
    tampered = replace(compiled, _artifacts=tuple(
        a.model_copy(update={"revises": filed.id, "artifact_type": filed.artifact_type})
        if a.id == memo.id else a
        for a in compiled._artifacts
    ))
    assert "filing_revised" in codes(tampered)


def test_a_restatement_must_state_the_move(compiled: World) -> None:
    """Stripping the superseded side from the restatement's citations leaves a
    correction that never says what it corrected."""
    restatement = next(a for a in compiled.artifacts if a.restates)
    superseding = {
        f.id: f.supersedes for f in compiled.facts if f.supersedes
    }
    kept = [
        fact_id for fact_id in restatement.supporting_fact_ids
        if fact_id not in set(superseding.values())
    ]
    tampered = replace(compiled, _artifacts=tuple(
        a.model_copy(update={"supporting_fact_ids": kept}) if a.id == restatement.id else a
        for a in compiled._artifacts
    ))
    assert "restatement_states_nothing" in codes(tampered)


def test_a_correction_scoped_beyond_the_error_is_refused(compiled: World) -> None:
    """A restatement citing a brand-new by-book figure — one that corrects
    nothing on the record — is asserting a second error nobody confirmed."""
    restatement = next(a for a in compiled.artifacts if a.restates)
    untouched = next(
        f for f in compiled.facts.where(kind="capital.rwa_by_book")
        if not f.supersedes and not f.is_superseded
    )
    stray = untouched.model_copy(update={
        "id": "FACT-9901",
        "valid_from": untouched.valid_from + timedelta(days=40),
        "value": untouched.value.model_copy(update={"amount": untouched.value.amount + 75}),
    })
    tampered = replace(
        compiled,
        _facts=(*compiled._facts, stray),
        _artifacts=tuple(
            a.model_copy(update={
                "supporting_fact_ids": [*a.supporting_fact_ids, stray.id]
            }) if a.id == restatement.id else a
            for a in compiled._artifacts
        ),
    )
    assert "correction_exceeds_error" in codes(tampered)


def test_the_as_filed_record_is_untouchable(world: World) -> None:
    as_filed = world.facts.where(kind="capital.cet1_ratio_as_filed")[0]
    tampered = replace(world, _facts=tuple(
        f.model_copy(update={"valid_to": f.valid_from + timedelta(days=30)})
        if f.id == as_filed.id else f
        for f in world._facts
    ))
    assert "as_filed_touched" in codes(tampered)


# ---------------------------------------------------------------------------
# The contested window and the cadences
# ---------------------------------------------------------------------------


def test_the_contest_is_live_and_legal(world: World) -> None:
    """Two unclosed treatment facts for one book at different authority: the
    disagreement window the vertical exists to generate, and legal."""
    treatments = [
        f for f in world.facts.where(kind="capital.collateral_treatment")
        if not f.is_superseded
    ]
    assert len(treatments) == 2
    assert {f.authority for f in treatments} == {
        Authority.APPROVED_REPORT, Authority.CONFIRMED
    }
    assert world.validate().ok


def test_an_equal_authority_contest_is_a_defect(world: World) -> None:
    challenged = next(
        f for f in world.facts.where(kind="capital.collateral_treatment")
        if f.authority is Authority.APPROVED_REPORT
    )
    rival = challenged.model_copy(update={
        "id": "FACT-9902", "text_value": "fully secured after all",
    })
    tampered = replace(world, _facts=(*world._facts, rival))
    assert "contested_at_equal_authority" in codes(tampered)


def test_the_daily_cadence_is_gapless(world: World) -> None:
    lcr = sorted(world.facts.where(kind="liquidity.lcr"), key=lambda f: f.valid_from)
    assert len(lcr) == 6
    for earlier, later in itertools.pairwise(lcr):
        assert earlier.valid_to == later.valid_from
        assert later.supersedes == earlier.id
    assert lcr[-1].valid_to is None


def test_a_dropped_liquidity_day_is_caught(world: World) -> None:
    lcr = sorted(world.facts.where(kind="liquidity.lcr"), key=lambda f: f.valid_from)
    victim = lcr[2]
    # Splice the chain around the removed day so referential checks stay
    # clean and only the cadence gap remains to notice.
    kept = []
    for f in world._facts:
        if f.id == victim.id:
            continue
        if f.id == lcr[1].id:
            f = f.model_copy(update={"valid_to": lcr[3].valid_from})
        if f.id == lcr[3].id:
            f = f.model_copy(update={"supersedes": lcr[1].id})
        kept.append(f)
    assert "liquidity_cadence_gap" in codes(replace(world, _facts=tuple(kept)))


def test_the_detection_is_structural(world: World) -> None:
    """Both calculation paths consume the shared upstream; only the daily one
    reconciles. The graph states it, no document needs to."""
    roles = world._roles
    sync = roles["svc_collateral_sync"]
    rwa = world.services.by_id(roles["svc_rwa_engine"])
    lcr = world.services.by_id(roles["svc_lcr_daily"])
    assert sync in rwa.depends_on and sync in lcr.depends_on
    breach = world.events.where(kind="reconciliation_break_detected")[0]
    assert roles["svc_lcr_daily"] in breach.services


def test_the_second_line_reports_outside_the_cfo(world: World) -> None:
    """The reporting line retail's role table could not express."""
    cro = world.people.by_id(world._roles["cro"])
    ceo = world.people.by_id(world._roles["ceo"])
    cfo = world.people.by_id(world._roles["cfo"])
    assert cro.manager_id == ceo.id
    assert cro.manager_id != cfo.id
    challenger = world.people.by_id(world._roles["prudential_risk_head"])
    assert challenger.manager_id == cro.id


def test_audit_reads_the_filing_without_preparing_it(compiled: World) -> None:
    """The third line's charter, mechanically: every auditor passes the
    filing's access policy, and no auditor authored a filing."""
    policies = {p.id: p for p in compiled.access_policies}
    auditors = [p for p in compiled.people if p.function == "Audit"]
    assert auditors
    for entry in compiled.artifacts:
        if entry.artifact_type not in FILING_TYPES:
            continue
        policy = policies[entry.access_policy_id]
        assert all(policy.permits(a) for a in auditors)
        assert compiled.people.by_id(entry.author_id).function != "Audit"


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------


def test_the_same_seed_rebuilds_the_same_world(world: World) -> None:
    again = BankingWorld(seed=SEED).build().run(QuarterlyCapitalReturn(period=PERIOD))
    assert [f.model_dump() for f in again.facts] == [f.model_dump() for f in world.facts]
    assert [e.model_dump() for e in again.events] == [e.model_dump() for e in world.events]


def test_the_recipe_rebuilds_the_world(world: World, tmp_path) -> None:
    """Resume-by-rebuild, banking's turn: the corpus says how it was made, and
    saying so is sufficient."""
    from worldloom.recipe import rebuild

    exported = world.compile().export(tmp_path / "bank")
    loaded = World.load(exported)
    again = rebuild(loaded.recipe)
    assert [f.model_dump() for f in again.facts] == [f.model_dump() for f in world.facts]


def test_export_then_replay_is_byte_identical(world: World, tmp_path) -> None:
    """Including the vertical's native formats: the return renders as a real
    workbook and the rulings as Word documents, through the renderer
    registration seam — and the whole set must still replay exactly."""
    from worldloom.narrative import DeterministicProvider, UnreachableProvider

    formats = ("xlsx", "docx", "markdown", "servicenow")
    first = world.narrate(DeterministicProvider()).render(*formats)
    first.export(tmp_path / "one")
    rendered = {p.name for p in (tmp_path / "one" / "artifacts").iterdir()}
    assert "art-0001-capital-return.xlsx" in rendered
    assert "art-0006-capital-return.xlsx" in rendered
    assert "art-0008-internal-audit-review.docx" in rendered
    assert not any(n.startswith("art-0001") and n.endswith(".md") for n in rendered), (
        "the return is a workbook; markdown must not shadow it with a flat projection"
    )

    again = BankingWorld(seed=SEED).build().run(QuarterlyCapitalReturn(period=PERIOD))
    again = again.narrate(UnreachableProvider(), ledger=first._ledger)
    again = again.render(*formats)
    again.export(tmp_path / "two")

    one = sorted((tmp_path / "one").rglob("*"))
    two = sorted((tmp_path / "two").rglob("*"))
    assert [p.relative_to(tmp_path / "one") for p in one] == [
        p.relative_to(tmp_path / "two") for p in two
    ]
    for left, right in zip(one, two):
        if left.is_file():
            assert left.read_bytes() == right.read_bytes(), left.name


# ---------------------------------------------------------------------------
# Consecutive quarters
# ---------------------------------------------------------------------------
#
# A second ``QuarterlyCapitalReturn`` on the same world, and the three
# blockers fixing it surfaced: the standing CET1 minimum minted twice, the
# daily cadence check sorting both quarters' liquidity series into one global
# timeline, and the reconciliation checks summing a second quarter's books
# against a first quarter's total because neither was ever period-scoped
# when only one quarter could ever exist. Each test below pins one of those,
# or the two-quarter `validate()` run that found the rest.


def _lcr_chains(world: World) -> tuple[list, list]:
    """The two quarters' LCR observations, split chronologically.

    ``liquidity.lcr`` carries no ``period`` (see the comment where it is
    minted, in ``generators/regulatory.py``) — a chain's own ``supersedes``
    links are what relate its facts, not a period label — so tests split
    quarters the same way the corpus does: the windows sit months apart by
    design, so a plain chronological sort never interleaves them."""
    lcr = sorted(world.facts.where(kind="liquidity.lcr"), key=lambda f: f.valid_from)
    midpoint = len(lcr) // 2
    return lcr[:midpoint], lcr[midpoint:]


def test_two_consecutive_quarters_are_coherent(two_quarters: World) -> None:
    report = two_quarters.compile().validate()
    assert report.ok, "\n".join(str(v) for v in report.violations)


def test_the_standing_minimum_is_not_re_minted(two_quarters: World) -> None:
    """1a: a second quarter reuses the world's standing CET1 floor rather
    than minting a duplicate — two would tie at SYSTEM_OF_RECORD for the same
    (kind, subject), which `contested_at_equal_authority` exists to catch."""
    minimums = two_quarters.facts.where(kind="capital.minimum_cet1_requirement")
    assert len(minimums) == 1
    # Both quarters' filings cite the one standing fact, not one each.
    returns = [i for i in two_quarters.artifact_intents if i.artifact_type == "capital_return"]
    filed = [i for i in returns if not i.restates]
    assert len(filed) == 2
    for intent in filed:
        assert minimums[0].id in intent.required_fact_ids


def test_each_quarter_files_and_restates_independently(two_quarters: World) -> None:
    """Two periods, two independent filed+restated pairs: the restatement
    contract repeats per quarter rather than a second quarter's correction
    reaching into the first's."""
    returns = [i for i in two_quarters.artifact_intents if i.artifact_type == "capital_return"]
    filed = [i for i in returns if not i.restates]
    restated = [i for i in returns if i.restates]
    assert len(filed) == 2
    assert len(restated) == 2
    assert {i.restates for i in restated} == {i.id for i in filed}

    def period_of(intent: object) -> str:
        for fact_id in intent.required_fact_ids:  # type: ignore[attr-defined]
            fact = two_quarters.facts.by_id(fact_id)
            if fact.period:
                return fact.period
        raise AssertionError(f"{intent.id} carries no period-bearing fact")  # type: ignore[attr-defined]

    filed_periods = {i.id: period_of(i) for i in filed}
    assert set(filed_periods.values()) == {PERIOD, SECOND_PERIOD}
    for restatement in restated:
        assert period_of(restatement) == filed_periods[restatement.restates]


def test_supersession_completes_across_the_quarter_boundary(two_quarters: World) -> None:
    """1c: the first quarter's last LCR observation stays open — never
    superseded — rather than being closed by the second quarter's first
    observation. Closing it would need a cross-quarter `supersedes` edge
    asserting the reading held continuously across the months between
    windows, which nothing in this corpus observed; left open,
    `supersession_incomplete` (a fact with no ``valid_to`` needs no
    superseder) must not fire for it, and the second quarter's own chain
    still starts fresh (`supersedes=None`)."""
    assert "supersession_incomplete" not in codes(two_quarters)
    first_quarter_lcr, second_quarter_lcr = _lcr_chains(two_quarters)
    assert first_quarter_lcr[-1].valid_to is None
    assert not first_quarter_lcr[-1].is_superseded
    assert second_quarter_lcr[0].supersedes is None


def test_no_spurious_gap_between_quarters(two_quarters: World) -> None:
    """1b: the cadence check walks supersession chains, not a global sort —
    the months between the two quarters' windows must never read as a
    dropped day."""
    assert "liquidity_cadence_gap" not in codes(two_quarters)
    assert "liquidity_window_torn" not in codes(two_quarters)


def test_a_dropped_day_in_the_second_quarter_is_still_caught(two_quarters: World) -> None:
    """The chain-walk rewrite must still have teeth inside a quarter's own
    chain once a second quarter's chain sits beside it in the same world —
    the point of walking chains is to tell the two apart, not to stop
    checking either one. Mirrors ``test_a_dropped_liquidity_day_is_caught``,
    scoped to the second quarter."""
    _, second_quarter_lcr = _lcr_chains(two_quarters)
    assert len(second_quarter_lcr) == 6
    victim = second_quarter_lcr[2]
    kept = []
    for f in two_quarters._facts:
        if f.id == victim.id:
            continue
        if f.id == second_quarter_lcr[1].id:
            f = f.model_copy(update={"valid_to": second_quarter_lcr[3].valid_from})
        if f.id == second_quarter_lcr[3].id:
            f = f.model_copy(update={"supersedes": second_quarter_lcr[1].id})
        kept.append(f)
    assert "liquidity_cadence_gap" in codes(replace(two_quarters, _facts=tuple(kept)))


def test_the_recipe_rebuilds_two_quarters(two_quarters: World, tmp_path) -> None:
    """1.3: each quarter appends its own step (``with_step``, already generic
    over scenario name), so a two-quarter corpus rebuilds byte-for-byte from
    its recipe with no ledger on hand — the same discipline
    ``test_the_recipe_rebuilds_the_world`` pins for one."""
    from worldloom.recipe import rebuild

    exported = two_quarters.compile().export(tmp_path / "bank2")
    loaded = World.load(exported)
    assert len(loaded.recipe["steps"]) == 2
    again = rebuild(loaded.recipe)
    assert [f.model_dump() for f in again.facts] == [f.model_dump() for f in two_quarters.facts]


def test_two_quarter_export_then_replay_is_byte_identical(two_quarters: World, tmp_path) -> None:
    """The two-quarter counterpart of ``test_export_then_replay_is_byte_identical``:
    narration, rendering, and replay must all still be exact once a second
    episode is in the mix."""
    from worldloom.narrative import DeterministicProvider, UnreachableProvider

    formats = ("xlsx", "docx", "markdown", "servicenow")
    first = two_quarters.narrate(DeterministicProvider()).render(*formats)
    first.export(tmp_path / "one")

    again = (
        BankingWorld(seed=SEED).build()
        .run(QuarterlyCapitalReturn(period=PERIOD))
        .run(QuarterlyCapitalReturn(period=SECOND_PERIOD))
    )
    again = again.narrate(UnreachableProvider(), ledger=first._ledger)
    again = again.render(*formats)
    again.export(tmp_path / "two")

    one = sorted((tmp_path / "one").rglob("*"))
    two = sorted((tmp_path / "two").rglob("*"))
    assert [p.relative_to(tmp_path / "one") for p in one] == [
        p.relative_to(tmp_path / "two") for p in two
    ]
    for left, right in zip(one, two):
        if left.is_file():
            assert left.read_bytes() == right.read_bytes(), left.name


def test_cli_periods_steps_by_the_domains_own_cadence(two_quarters: World, tmp_path) -> None:
    """This test used to assert the opposite — that `--periods 2` was *refused*
    for a single-episode domain, pending "the episode grammar (Phase 2)". The
    grammar arrived, carry-forward became declared slots, and the refusal
    outlived its justification while the mosaic path stepped these domains
    multi-period all along. Now the claim is the one the test's name always
    made: `--periods` steps by the domain's own cadence — two banking periods
    are two consecutive *quarters*, and the built world validates.

    The per-scenario limit that is real stays where the code that knows it
    lives: `QuarterlyReserving` refuses its own second quarter with the
    increment-2 reason, and the CLI surfaces that message instead of guessing.
    """
    out = tmp_path / "two-quarter-cli"
    result = runner.invoke(app, [
        "build", "--seed", str(SEED), "--period", PERIOD, "--archetype", "midsize_adi",
        "--periods", "2", "--out", str(out),
    ])
    assert result.exit_code == 0, result.output
    world = World.load(str(out))
    quarters = sorted({f.period for f in world.facts if f.period})
    assert quarters == ["2026-03", "2026-06"], quarters
    assert world.validate().ok


def test_cli_still_refuses_the_retail_only_flags_for_banking(tmp_path) -> None:
    """The refusal narrows, it does not disappear: `--incident`, `--actors`,
    and `--comparatives` still belong to the retail close alone."""
    result = runner.invoke(app, [
        "build", "--archetype", "midsize_adi", "--incident", "--out", str(tmp_path / "x"),
    ])
    assert result.exit_code == 2
    assert "belong(s) to the retail close" in result.output
    assert "--incident" in result.output
    assert "--periods" not in result.output


# ---------------------------------------------------------------------------
# The A10 exit test, measured not asserted
# ---------------------------------------------------------------------------


def test_the_baseline_finds_the_hard_families_hard(world: World) -> None:
    """The gate: authority_resolution and temporal_state must score below
    direct_lookup at k=5. This is what the retail episode could not produce —
    its authority cases were resolvable by rank — and what the rank tie plus
    the filing's labelled omission exist to force."""
    from worldloom.narrative import DeterministicProvider

    scored = world.narrate(DeterministicProvider()).render("markdown", "servicenow")
    card = score(scored, k=5)
    by_type = card.by_type()

    direct_passed, direct_total = by_type[EvaluationType.DIRECT_LOOKUP]
    assert direct_passed == direct_total, "the floor must hold or hardness means nothing"

    for family in (EvaluationType.AUTHORITY_RESOLUTION, EvaluationType.TEMPORAL_STATE):
        passed, total = by_type[family]
        assert total >= 3
        assert passed / total < direct_passed / direct_total, (
            f"{family.value} scored {passed}/{total} — not measurably harder than lookup"
        )


def test_the_contested_figure_defeats_the_wrong_document(world: World) -> None:
    """The specific failure the pair was designed for: on the contested-figure
    question the baseline surfaces a SYSTEM_OF_RECORD document that carries no
    part of the answer."""
    from worldloom.narrative import DeterministicProvider

    scored = world.narrate(DeterministicProvider()).render("markdown", "servicenow")
    card = score(scored, k=5)
    contested = next(
        c for c in scored.evaluations
        if c.evaluation_type is EvaluationType.AUTHORITY_RESOLUTION
        and "CET1 ratio for the quarter" in c.question
    )
    outcome = next(o for o in card.outcomes if o.case_id == contested.id)
    assert not outcome.passed
    assert "carries none of the expected facts" in outcome.detail


def test_every_answer_is_reachable(world: World) -> None:
    reachable: set[str] = set()
    for intent in world.artifact_intents:
        reachable.update(intent.required_fact_ids)
    for case in world.evaluations:
        if not case.expects_abstention:
            assert set(case.expected_fact_ids) <= reachable, case.id
