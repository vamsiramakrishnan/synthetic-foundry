"""The procure-to-pay port — the grammar's second proof obligation, measured.

The ProcureToPay spec in `examples/episodes/` is the port of the procurement
engine's monthly cycle into the episode grammar, owned by the procurement LOB
(`examples/episodes/procure-to-pay-lob.json` carries the slot bindings). These
tests pin what the port actually achieves: it lints clean against the
fact-kind registry, the process cascade authors the identical spec through its
refusable stages, it runs multi-period with the open-shortfall carry-forward
exact, the procurement engine's own check group polices its facts with zero
violations, it replays byte-identically from its own recipe, and — the point
of the migration — it runs inside a *retail* world with its GRNI accrual
landing in `financial.*` where retail's close reads. What it does *not*
achieve, deliberately pinned nowhere: byte-identity with the engine's corpus.
The measured diff and its reasons live in docs/episode-grammar.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worldloom import MonthEndClose, ProcureToPayWorld, RetailWorld, episodes, lob, process
from worldloom.procurement import _checks as procurement_checks
from worldloom.procurement_scenarios import PurchaseToPayCycle  # noqa: F401 — registers the engine verb

SPEC_PATH = Path(__file__).parent.parent / "examples" / "episodes" / "procure-to-pay.json"
LOB_PATH = Path(__file__).parent.parent / "examples" / "episodes" / "procure-to-pay-lob.json"

PERIODS = ("2026-03", "2026-04", "2026-05")


@pytest.fixture(scope="module")
def spec() -> episodes.EpisodeSpec:
    specs = episodes.load(SPEC_PATH)
    episodes.install(specs)
    return specs[0]


@pytest.fixture(scope="module")
def p2p_lob() -> lob.Lob:
    return lob.Lob.model_validate(json.loads(LOB_PATH.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def world(spec: episodes.EpisodeSpec):
    built = ProcureToPayWorld(seed=8128).build()
    for period in PERIODS:
        built = built.run(episodes.AuthoredEpisode(episode=spec.name, period=period))
    return built


def test_the_port_spec_lints_clean(spec: episodes.EpisodeSpec) -> None:
    """Zero findings against the registry, the procurement role table, and
    itself — measured, not claimed."""
    assert episodes.lint([spec], base="procurement") == []


def test_the_cascade_refuses_what_its_missing_stage_cannot_hold(
    spec: episodes.EpisodeSpec,
) -> None:
    """The cascade's refusals, measured — including the one that names its own
    gap. An invented kind is refused at the stage that proposed it. And the
    port's `prior(K)` derives are refused too, *correctly*: a prior-period
    read needs a declared carry-forward slot, the process cascade has no
    carry-forward stage (process.py — a named seam, another owner), and a lint
    that let the derive through would hand every first period a silent zero
    wearing a declaration's clothes. So the P2P process is authored as a
    grammar file, and cascade authorship is blocked on exactly that stage —
    a measured finding, not a workaround."""
    seed = process.ProcessSeed(
        name=spec.name, purpose=spec.detail, engine="procurement",
        lob="procurement", period="month",
    )
    assert process.lint_seed(seed) == []
    session = process.open(seed)

    # A step minting an invented kind is refused at the stage that proposed it.
    with pytest.raises(ValueError, match="rejected"):
        process.accept(session, process.Answer(
            stage="steps",
            steps=[episodes.EventSpec(kind="order_raised", when="start",
                                      summary="x", fact_keys=["p2p.imagined_kind"])],
            kinds=[],
        ))

    # The port's own steps: refused, naming the carry-forward slot the
    # cascade cannot yet declare — not some incidental finding.
    with pytest.raises(ValueError, match="no sum/derive carry-forward"):
        process.accept(session, process.Answer(
            stage="steps", steps=list(spec.events), kinds=list(spec.fact_kinds),
        ))

    # Without the two prior-period reads, the same steps and kinds are
    # accepted and the slots stage completes — the rest of the port is
    # cascade-expressible today.
    trimmed_kinds = [
        fk.model_copy(update={"derive": "", "amount": 0.0})
        if fk.derive.startswith("prior(") else fk
        for fk in spec.fact_kinds
    ]
    session = process.accept(session, process.Answer(
        stage="steps", steps=list(spec.events), kinds=trimmed_kinds,
    ))
    session = process.accept(session, process.Answer(
        stage="slots", slots=list(spec.role_slots),
    ))
    resolved = process.resolve(session, artifacts=list(spec.artifacts))
    assert resolved.name == spec.name
    assert resolved.events == spec.events
    assert resolved.role_slots == spec.role_slots
    assert resolved.artifacts == spec.artifacts


def test_the_port_validates_multi_period(world) -> None:
    """The full validator over three consecutive months — including the
    procurement engine's own check group, which polices p2p.* whoever minted
    it, and the checks derived from the spec's invariants."""
    report = world.validate()
    assert report.ok, report.violations[:5]


def test_the_shortfall_carries_forward_exactly(world) -> None:
    """Each month releases exactly what the month before left outstanding,
    and the first month releases zero — stated as a fact, not omitted."""
    company = world.company.id
    prior = None
    for period in PERIODS:
        released = world.authoritative("p2p.shortfall_released_value", company, period=period)
        shortfall = world.authoritative("p2p.open_shortfall_value", company, period=period)
        accrual = world.authoritative("financial.accrual.grni", company, period=period)
        received = world.authoritative("p2p.received_value", company, period=period)
        assert released is not None and shortfall is not None
        expected = 0.0 if prior is None else prior.value.amount
        assert released.value.amount == expected
        # The composition's own claim: the accrual is the receipt plus the
        # released balance, and nothing from the invoice.
        assert accrual.value.amount == round(
            received.value.amount + released.value.amount, 2
        )
        prior = shortfall


def test_standing_facts_are_minted_once_and_reused(world) -> None:
    """The rate card, counterparty, delegation and held vendor change are one
    fact each across three months — the reuse carry-forward, measured."""
    counts: dict[str, int] = {}
    for fact in world.facts:
        counts[fact.kind] = counts.get(fact.kind, 0) + 1
    for kind in ("p2p.contract_rate", "p2p.contract_counterparty",
                 "p2p.approval_tolerance_pct", "p2p.vendor_change_status"):
        assert counts[kind] == 1, (kind, counts[kind])


def test_the_exception_chain_hands_over_exactly(world) -> None:
    """Raised → escalated → resolved, each superseded link closing exactly
    where its successor opens, one live status per month — the three-link
    chain the pair primitive was generalised for."""
    for period in PERIODS:
        chain = sorted(
            (f for f in world.facts
             if f.kind == "p2p.exception_status" and f.period == period),
            key=lambda f: f.valid_from,
        )
        assert len(chain) == 3
        assert [f.valid_to is None for f in chain] == [False, False, True]
        for earlier, later in zip(chain, chain[1:]):
            assert earlier.valid_to == later.valid_from
            assert later.supersedes == earlier.id


def test_the_engine_checks_police_the_port(world) -> None:
    """The engine's own check group runs against the ported facts and finds
    nothing — the port is held to the vertical's rules, not to its own."""
    violations, checks = procurement_checks(world)
    assert checks > 0
    assert violations == []


def test_the_port_replays_from_its_recipe(world) -> None:
    from worldloom import recipe

    again = recipe.rebuild(recipe=world.recipe)
    assert tuple(again._facts) == tuple(world._facts)
    assert tuple(again._events) == tuple(world._events)
    assert tuple(again._artifact_intents) == tuple(world._artifact_intents)


def test_the_lob_binds_the_cycle_seats(spec: episodes.EpisodeSpec, p2p_lob: lob.Lob) -> None:
    """preparer/matcher/approver, bound by the LOB against the spec's declared
    slots, lint clean; participation derives the seats and the p2p family."""
    assert lob.lint_bindings(p2p_lob, spec) == []
    participants = {p.role_key: p for p in lob.participation(p2p_lob, spec)}
    assert participants["category_manager"].slots == ("preparer",)
    assert participants["accounts_payable_lead"].slots == ("matcher",)
    assert participants["financial_controller"].slots == ("approver",)
    # The CPO is in the room through the responsibility join alone — the p2p
    # family covers every p2p.* kind the steps mint — with no seat.
    assert participants["chief_procurement"].slots == ()
    assert "p2p" in participants["chief_procurement"].via


def test_cross_engine_attachment_lands_the_accrual(
    spec: episodes.EpisodeSpec, p2p_lob: lob.Lob
) -> None:
    """The whole point of the migration: the LOB's people enter a RETAIL world
    through the roles seam, the authored process runs inside it, the GRNI
    accrual lands in `financial.*` where retail's close reads, the procurement
    check group polices it there, and retail's own MonthEndClose still runs on
    the same world."""
    from worldloom.generators.organisation import _ROLES as RETAIL_ROLES

    table = tuple(RETAIL_ROLES) + tuple(role.as_row() for role in p2p_lob.roles)
    world = RetailWorld(seed=8128, role_table=table).build()
    world = world.run(episodes.AuthoredEpisode(episode=spec.name, period="2026-03"))

    accrual = world.authoritative("financial.accrual.grni", world.company.id, period="2026-03")
    assert accrual is not None and accrual.value is not None
    assert accrual.value.unit == "AUD_thousands"

    # Same seed, same process, same figures whichever engine hosts it: the
    # stream is named for the spec and the period, not for the world builder.
    procurement_world = ProcureToPayWorld(seed=8128).build().run(
        episodes.AuthoredEpisode(episode=spec.name, period="2026-03"))
    twin = procurement_world.authoritative(
        "financial.accrual.grni", procurement_world.company.id, period="2026-03")
    assert accrual.value.amount == twin.value.amount

    violations, checks = procurement_checks(world)
    assert checks > 0 and violations == []
    assert world.validate().ok

    closed = world.run(MonthEndClose(period="2026-04"))
    assert closed.validate().ok
