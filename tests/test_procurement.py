"""The procure-to-pay vertical, held to its contract.

The episode's claims, each pinned: three documents state three quantities and
no document states two of them; the order, the receipt and the invoice are
immutable forever; the two variance halves account for the whole gap between
what was billed and what is owed; the settlement pays the contract and never
the invoice; the month-end accrual is built from the receipt and not from the
invoice; an above-tolerance exception is approved by somebody who did not
raise the order; the exception status walks one unbroken chain; a shortfall
recorded at one close is released at exactly the next one; and the whole thing
replays byte-for-byte from its seed and from its own recipe over a six-month
history.

Tamper tests follow the actor-, banking- and insurance-suite convention: every
procurement check is shown *firing*, not just passing, because a check that
has never failed proves only that it compiles.

The last two tests are the thin-waist tests this vertical owes. Core is
scanned for procurement vocabulary directly rather than by adding names to
``tests/test_thin_waist.py``'s ledger: that file is a ratchet over the three
verticals that already exist, and a fourth vertical proving its own
non-coupling in its own file is the arrangement a fifth should copy.
"""

from __future__ import annotations

import io
import tokenize
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from worldloom import (
    Authority,
    ProcureToPayWorld,
    PurchaseToPayCycle,
    World,
)
from worldloom.generators import procurement_match
from worldloom.models import EvaluationType
from worldloom.parameters import DEFAULT, Parameters, Span

SEED = 8128
PERIOD = "2026-03"
NEXT_PERIOD = "2026-04"


@pytest.fixture(scope="module")
def world() -> World:
    return ProcureToPayWorld(seed=SEED).build().run(PurchaseToPayCycle(period=PERIOD))


@pytest.fixture(scope="module")
def compiled(world: World) -> World:
    return world.compile()


@pytest.fixture(scope="module")
def history() -> World:
    built = ProcureToPayWorld(seed=SEED).build()
    for period in ("2026-03", "2026-04", "2026-05"):
        built = built.run(PurchaseToPayCycle(period=period))
    return built.compile()


def codes(world: World) -> set[str]:
    return {v.code for v in world.validate().violations}


def only(world: World, kind: str, **where: object):  # type: ignore[no-untyped-def]
    found = [
        f for f in world.facts
        if f.kind == kind and all(getattr(f, k) == v for k, v in where.items())
    ]
    assert len(found) == 1, f"expected exactly one {kind} {where}, got {len(found)}"
    return found[0]


def retyped(world: World, fact_id: str, **update: object) -> World:
    """*world* with one fact edited — the tamper the validator has to catch."""
    return replace(world, _facts=tuple(
        f.model_copy(update=update) if f.id == fact_id else f for f in world._facts
    ))


# ---------------------------------------------------------------------------
# The episode is coherent
# ---------------------------------------------------------------------------


def test_the_episode_is_coherent(compiled: World) -> None:
    report = compiled.validate()
    assert report.ok, "\n".join(str(v) for v in report.violations)


def test_a_history_is_coherent(history: World) -> None:
    """Three consecutive months, which is the thing the insurance vertical
    cannot do at all — its scenario refuses a second run."""
    report = history.validate()
    assert report.ok, "\n".join(str(v) for v in report.violations)


def test_the_shape_of_the_episode(world: World) -> None:
    assert len(world.artifact_intents) == 7
    assert {i.artifact_type for i in world.artifact_intents} == {
        "purchase_order", "goods_receipt_note", "supplier_invoice",
        "match_exception_report", "payment_approval_memo", "vendor_master_change",
        # The seventh reports the company rather than one cycle — see
        # `tests/test_procurement_spine.py`, which holds it to that.
        "spend_and_commitment_workbook",
    }
    assert len(world.intentional_errors) == 1
    kinds = {f.kind for f in world.facts}
    assert {"close.due_date", "close.status", "close.delay"} <= kinds
    assert {
        "p2p.contract_rate", "p2p.contract_counterparty",
        "p2p.ordered_quantity", "p2p.ordered_value",
        "p2p.received_quantity", "p2p.received_value",
        "p2p.invoiced_quantity", "p2p.invoiced_unit_price", "p2p.invoiced_value",
        "p2p.match_quantity_variance", "p2p.match_price_variance",
        "p2p.match_total_variance", "p2p.approval_tolerance",
        "p2p.approval_tolerance_pct", "p2p.exception_status",
        "p2p.exception_approved_by", "p2p.credit_note_value",
        "p2p.approved_payment_value", "p2p.open_shortfall_quantity",
        "p2p.open_shortfall_value", "p2p.shortfall_released_quantity",
        "p2p.shortfall_released_value", "p2p.vendor_change_status",
        "financial.accrual.grni",
    } <= kinds


def test_the_role_handles_are_resolved(world: World) -> None:
    assert world.categories.by_id(world._roles["cat_contested_line"]).name == "Subcontract Labour"
    assert world.categories.by_id(world._roles["cat_clean_line"]).name == "Plant Hire"


def test_a_world_without_spend_categories_is_refused() -> None:
    built = ProcureToPayWorld(seed=SEED).build()
    stripped = replace(built, _roles={
        k: v for k, v in built._roles.items() if k != "cat_contested_line"
    })
    with pytest.raises(ValueError, match="no spend categories"):
        stripped.run(PurchaseToPayCycle(period=PERIOD))


def test_the_estate_flag_is_refused_with_its_reason() -> None:
    """Refused rather than served half-way — see ``ProcureToPayWorld.estate``."""
    with pytest.raises(ValueError, match="no registration seam"):
        ProcureToPayWorld(seed=SEED, estate="small").build()


# ---------------------------------------------------------------------------
# Three documents, three quantities, and no document holding two of them
# ---------------------------------------------------------------------------


def test_no_source_document_states_two_of_the_three_quantities(compiled: World) -> None:
    """The property the whole authority family rests on. If any one of the
    three ever carried a second quantity, the join would collapse into a
    single-document lookup and the corpus would stop asking anything."""
    quantities = {
        "purchase_order": "p2p.ordered_quantity",
        "goods_receipt_note": "p2p.received_quantity",
        "supplier_invoice": "p2p.invoiced_quantity",
    }
    by_id = {f.id: f for f in compiled.facts}
    for entry in compiled.artifacts:
        if entry.artifact_type not in quantities:
            continue
        carried = {
            by_id[f].kind for f in entry.supporting_fact_ids
            if f in by_id and by_id[f].kind in set(quantities.values())
        }
        assert carried == {quantities[entry.artifact_type]}, (
            f"{entry.artifact_type} carries {sorted(carried)}"
        )


def test_the_three_documents_sit_at_three_authorities(compiled: World) -> None:
    standing = {a.artifact_type: a.authority for a in compiled.artifacts}
    assert standing["purchase_order"] is Authority.APPROVED_REPORT
    assert standing["goods_receipt_note"] is Authority.SYSTEM_OF_RECORD
    assert standing["supplier_invoice"] is Authority.SYSTEM_OF_RECORD


def test_rank_alone_picks_the_wrong_rate(world: World) -> None:
    """The inversion, stated as arithmetic rather than as a claim in a
    docstring: the invoiced unit price outranks the contracted one, and the
    contracted one is the answer to what the group owes per unit."""
    from worldloom.models import AUTHORITY_RANK

    contested = world._roles["cat_contested_line"]
    contracted = only(world, "p2p.contract_rate", subject=contested)
    invoiced = only(world, "p2p.invoiced_unit_price", subject=contested, period=PERIOD)
    assert AUTHORITY_RANK[invoiced.authority] > AUTHORITY_RANK[contracted.authority]
    assert invoiced.value.amount > contracted.value.amount


def test_the_clean_line_is_agreed_by_all_three(world: World) -> None:
    """The control, and it has to be exactly clean — a "nearly clean" line
    would make the contrast case answerable by picking whichever document was
    closest."""
    clean = world._roles["cat_clean_line"]
    ordered = only(world, "p2p.ordered_quantity", subject=clean, period=PERIOD)
    received = only(world, "p2p.received_quantity", subject=clean, period=PERIOD)
    invoiced = only(world, "p2p.invoiced_quantity", subject=clean, period=PERIOD)
    assert ordered.value.amount == received.value.amount == invoiced.value.amount
    assert only(world, "p2p.match_total_variance", subject=clean, period=PERIOD).value.amount == 0


# ---------------------------------------------------------------------------
# The check group, each check shown firing
# ---------------------------------------------------------------------------


def test_a_mispriced_order_line_trips_the_check(compiled: World) -> None:
    contested = compiled._roles["cat_contested_line"]
    value = only(compiled, "p2p.ordered_value", subject=contested, period=PERIOD)
    tampered = retyped(compiled, value.id,
                       value=value.value.model_copy(update={"amount": value.value.amount + 500}))
    assert "ordered_value_does_not_reconcile" in codes(tampered)


def test_an_over_receipt_trips_the_check(compiled: World) -> None:
    contested = compiled._roles["cat_contested_line"]
    received = only(compiled, "p2p.received_quantity", subject=contested, period=PERIOD)
    ordered = only(compiled, "p2p.ordered_quantity", subject=contested, period=PERIOD)
    tampered = retyped(compiled, received.id, value=received.value.model_copy(
        update={"amount": ordered.value.amount + 1}))
    assert "receipt_exceeds_order" in codes(tampered)


def test_a_wrong_quantity_variance_trips_the_check(compiled: World) -> None:
    contested = compiled._roles["cat_contested_line"]
    variance = only(compiled, "p2p.match_quantity_variance", subject=contested, period=PERIOD)
    tampered = retyped(compiled, variance.id, value=variance.value.model_copy(
        update={"amount": variance.value.amount * 2}))
    assert "quantity_variance_does_not_reconcile" in codes(tampered)


def test_a_wrong_price_variance_trips_the_check(compiled: World) -> None:
    contested = compiled._roles["cat_contested_line"]
    variance = only(compiled, "p2p.match_price_variance", subject=contested, period=PERIOD)
    tampered = retyped(compiled, variance.id, value=variance.value.model_copy(
        update={"amount": variance.value.amount + 40}))
    assert "price_variance_does_not_reconcile" in codes(tampered)


def test_a_match_that_leaves_the_gap_unaccounted_trips_the_check(compiled: World) -> None:
    """The identity the vertical rests on: invoiced less variance is what was
    received at the contracted rate. Tampered by moving the *total* alone, so
    the two halves still reconcile against their own inputs and only this
    check catches it — which is why it exists separately from them."""
    contested = compiled._roles["cat_contested_line"]
    total = only(compiled, "p2p.match_total_variance", subject=contested, period=PERIOD)
    tampered = retyped(compiled, total.id, value=total.value.model_copy(
        update={"amount": total.value.amount + 25}))
    found = codes(tampered)
    assert "match_does_not_account_for_the_gap" in found


def test_a_group_total_that_is_not_its_lines_trips_the_check(compiled: World) -> None:
    total = only(compiled, "p2p.invoiced_value", subject=compiled.company.id, period=PERIOD)
    tampered = retyped(compiled, total.id, value=total.value.model_copy(
        update={"amount": total.value.amount + 99}))
    assert "group_total_does_not_reconcile" in codes(tampered)


def test_variance_halves_that_do_not_sum_trip_the_check(compiled: World) -> None:
    company = compiled.company.id
    total = only(compiled, "p2p.match_total_variance", subject=company, period=PERIOD)
    tampered = retyped(compiled, total.id, value=total.value.model_copy(
        update={"amount": total.value.amount + 7}))
    assert "variance_halves_do_not_sum" in codes(tampered)


def test_a_credit_note_that_does_not_cover_the_variance_trips_the_check(compiled: World) -> None:
    credit = only(compiled, "p2p.credit_note_value", subject=compiled.company.id, period=PERIOD)
    tampered = retyped(compiled, credit.id, value=credit.value.model_copy(
        update={"amount": credit.value.amount / 2}))
    assert "credit_note_does_not_cover_the_variance" in codes(tampered)


def test_paying_the_invoice_rather_than_the_contract_trips_the_check(compiled: World) -> None:
    """The norm, as arithmetic. Settling at the invoiced total is the single
    most plausible way this corpus could go wrong, and it is a check rather
    than a comment."""
    company = compiled.company.id
    approved = only(compiled, "p2p.approved_payment_value", subject=company, period=PERIOD)
    invoiced = only(compiled, "p2p.invoiced_value", subject=company, period=PERIOD)
    tampered = retyped(compiled, approved.id, value=approved.value.model_copy(
        update={"amount": invoiced.value.amount}))
    found = codes(tampered)
    assert "settlement_is_not_the_contracted_rate" in found
    assert "settlement_does_not_reconcile" in found


def test_an_unapproved_above_tolerance_settlement_trips_the_check(compiled: World) -> None:
    approver = only(compiled, "p2p.exception_approved_by", period=PERIOD)
    stripped = replace(compiled, _facts=tuple(
        f for f in compiled._facts if f.id != approver.id
    ))
    assert "unapproved_settlement" in codes(stripped)


def test_the_buyer_approving_their_own_order_trips_the_check(compiled: World) -> None:
    """Segregation of duties, and the reason the org chart has the buyer and
    the payer reporting to different executives at all."""
    approver = only(compiled, "p2p.exception_approved_by", period=PERIOD)
    order = next(a for a in compiled.artifacts if a.artifact_type == "purchase_order")
    tampered = retyped(compiled, approver.id, subject=order.author_id)
    assert "segregation_of_duties_breached" in codes(tampered)


def test_an_accrual_built_from_the_invoice_trips_the_check(compiled: World) -> None:
    """The composition, held to its own claim. Without this check the corpus
    would be posing a cross-domain question whose answer it does not itself
    guarantee."""
    company = compiled.company.id
    accrual = only(compiled, "financial.accrual.grni", subject=company, period=PERIOD)
    invoiced = only(compiled, "p2p.invoiced_value", subject=company, period=PERIOD)
    tampered = retyped(compiled, accrual.id, value=accrual.value.model_copy(
        update={"amount": invoiced.value.amount}))
    assert "accrual_is_not_the_receipt" in codes(tampered)


def test_a_shortfall_that_is_not_the_quantity_variance_trips_the_check(compiled: World) -> None:
    company = compiled.company.id
    shortfall = only(compiled, "p2p.open_shortfall_value", subject=company, period=PERIOD)
    tampered = retyped(compiled, shortfall.id, value=shortfall.value.model_copy(
        update={"amount": shortfall.value.amount + 12}))
    assert "shortfall_is_not_the_quantity_variance" in codes(tampered)


def test_releasing_in_the_first_period_trips_the_check(compiled: World) -> None:
    company = compiled.company.id
    released = only(compiled, "p2p.shortfall_released_value", subject=company, period=PERIOD)
    tampered = retyped(compiled, released.id, value=released.value.model_copy(
        update={"amount": 1_000.0}))
    assert "released_before_anything_was_owed" in codes(tampered)


def test_a_carry_forward_that_does_not_match_trips_the_check(history: World) -> None:
    company = history.company.id
    released = only(history, "p2p.shortfall_released_value",
                    subject=company, period=NEXT_PERIOD)
    tampered = retyped(history, released.id, value=released.value.model_copy(
        update={"amount": released.value.amount + 30}))
    assert "carry_forward_does_not_match" in codes(tampered)


@pytest.mark.parametrize("kind", [
    "p2p.ordered_quantity", "p2p.received_quantity",
    "p2p.invoiced_quantity", "p2p.invoiced_unit_price",
])
def test_touching_a_source_record_trips_the_check(compiled: World, kind: str) -> None:
    contested = compiled._roles["cat_contested_line"]
    fact = only(compiled, kind, subject=contested, period=PERIOD)
    tampered = retyped(compiled, fact.id,
                       valid_to=fact.valid_from + timedelta(days=1))
    assert "source_record_touched" in codes(tampered)


def test_a_torn_exception_chain_trips_the_check(compiled: World) -> None:
    escalated = next(
        f for f in compiled.facts
        if f.kind == "p2p.exception_status" and f.supersedes and f.valid_to is not None
    )
    tampered = retyped(compiled, escalated.id,
                       valid_to=escalated.valid_to + timedelta(hours=3))
    assert "exception_status_torn" in codes(tampered)


def test_two_live_exception_statuses_trip_the_check(compiled: World) -> None:
    raised = next(
        f for f in compiled.facts
        if f.kind == "p2p.exception_status" and f.supersedes is None
    )
    # `valid_to=None` alone would leave the successor's `supersedes` pointer
    # intact, which the singularity check reads through — so this asserts the
    # *pair* of consequences the tamper actually has.
    tampered = retyped(compiled, raised.id, valid_to=None)
    found = codes(tampered)
    assert "exception_status_torn" in found


def test_the_check_group_costs_a_non_procurement_world_nothing() -> None:
    """The early-return contract every domain check group signs."""
    from worldloom.procurement import _checks
    from worldloom.retail import RetailWorld

    violations, checks = _checks(RetailWorld(seed=SEED).build())
    assert (violations, checks) == ([], 0)


def test_the_check_group_is_linear_in_the_history(compiled: World, history: World) -> None:
    """Bucketed once, not scanned per period. Three months must cost about
    three times one month — the shape `validate.financial()` uses and the shape
    `banking._checks` does not, which is why that group is 94% of validate's
    runtime at scale."""
    from worldloom.procurement import _checks

    one = _checks(compiled)[1]
    three = _checks(history)[1]
    assert three < one * 4, f"{one} checks for one month became {three} for three"


# ---------------------------------------------------------------------------
# The physics gate
# ---------------------------------------------------------------------------


def test_a_breach_multiple_at_one_is_refused() -> None:
    """A pack may tune how bad the exception is; it may not tune it away."""
    spans = dict(procurement_match.SPANS)
    spans["procurement.tolerance.breach_multiple"] = Span(
        1.0, 1.4, "number", None, "tuned away")
    with pytest.raises(ValueError, match=r"strictly above 1\.0"):
        procurement_match.generate(
            __import__("worldloom.rng", fromlist=["Rng"]).Rng(SEED),
            contested_category_id="CAT-0001", clean_category_id="CAT-0002",
            supplier="Test", physics=Parameters({**DEFAULT.spans, **spans}),
        )


def test_the_variance_always_breaches_the_tolerance() -> None:
    """Guaranteed by construction, not by luck on the seed — the property the
    backing-out and the outward rounding in ``procurement_match`` exist for.
    Checked across seeds because "it worked on 8128" is what that whole design
    is written to avoid."""
    from worldloom.rng import Rng

    for seed in range(40):
        position = procurement_match.generate(
            Rng(seed), contested_category_id="CAT-0001",
            clean_category_id="CAT-0002", supplier="Test",
        )
        assert position.breaches_tolerance, seed
        assert position.open_shortfall_quantity >= 1
        contested = next(line for line in position.lines if not line.is_clean)
        assert 0 < contested.received_quantity < contested.ordered_quantity


def test_procurement_physics_layer_under_a_callers_own() -> None:
    """The workaround for the missing ``parameters`` seam has to actually
    work: a caller who states one of these names must keep it."""
    tightened = Parameters({
        **DEFAULT.spans, **procurement_match.SPANS,
        "procurement.order.clean_quantity": Span(300, 300, "integer", None, "pinned"),
    })
    position = procurement_match.generate(
        __import__("worldloom.rng", fromlist=["Rng"]).Rng(SEED),
        contested_category_id="CAT-0001", clean_category_id="CAT-0002",
        supplier="Test", physics=tightened,
    )
    clean = next(line for line in position.lines if line.is_clean)
    assert clean.ordered_quantity == 300


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def test_the_authority_family_is_three_documents_wide(world: World) -> None:
    """Three questions, three right answers, three different documents. A
    family that resolved to one document would be a lookup wearing an
    authority question's name."""
    intents = {i.id: i.artifact_type for i in world.artifact_intents}
    families = [
        c for c in world.evaluations
        if c.evaluation_type is EvaluationType.AUTHORITY_RESOLUTION
    ]
    assert len(families) == 3
    sources = {intents[c.required_artifact_ids[0]] for c in families}
    assert sources == {"purchase_order", "goods_receipt_note", "supplier_invoice"}
    # And each one's distractors are the other two documents, never itself.
    for case in families:
        assert not set(case.required_artifact_ids) & set(case.distractor_artifact_ids)


def test_the_cross_domain_case_names_the_receipt_and_never_the_invoice(world: World) -> None:
    """The question nothing in this project could pose before: a general
    ledger figure whose authority is a site receipting note."""
    intents = {i.id: i.artifact_type for i in world.artifact_intents}
    case = next(
        c for c in world.evaluations
        if c.evaluation_type is EvaluationType.CROSS_ARTIFACT
    )
    assert {intents[a] for a in case.required_artifact_ids} == {
        "goods_receipt_note", "payment_approval_memo"
    }
    assert {intents[a] for a in case.distractor_artifact_ids} == {"supplier_invoice"}
    kinds = {world.facts.by_id(f).kind for f in case.expected_fact_ids}
    assert "financial.accrual.grni" in kinds
    assert not any(k.startswith("p2p.invoiced") for k in kinds)


def test_the_cross_month_case_appears_only_once_there_is_a_month_before(
    world: World, history: World
) -> None:
    def cross_month(w: World) -> list[object]:
        return [c for c in w.evaluations
                if c.evaluation_type is EvaluationType.TEMPORAL_STATE
                and "still undelivered" in c.question]

    assert cross_month(world) == []
    assert len(cross_month(history)) == 2


def test_the_abstention_is_structural(world: World) -> None:
    """An abstention is only worth minting if the answer is absent by
    construction rather than by this month's luck. The vendor master change
    says a change was requested and held; nothing anywhere says what to, and
    no fact in the corpus carries an account identifier of any shape.

    Checked on identifier vocabulary rather than on the word "account", which
    the payables tension lore legitimately contains — a test that failed on
    "Accounts payable regards the invoice as the number" would be measuring
    the wrong thing and would be turned off within a week."""
    case = next(c for c in world.evaluations if c.expects_abstention)
    assert "bank account" in case.question
    identifiers = ("iban", "bsb", "sort code", "account number", "swift")
    for fact in world.facts:
        text = (fact.text_value or "").lower()
        assert not any(token in text for token in identifiers), fact.id
    change = only(world, "p2p.vendor_change_status")
    assert not any(character.isdigit() for character in change.text_value)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_the_world_is_the_same_world_every_time() -> None:
    def build() -> list[str]:
        w = ProcureToPayWorld(seed=SEED).build()
        for period in ("2026-03", "2026-04"):
            w = w.run(PurchaseToPayCycle(period=period))
        return [f.model_dump_json() for f in w.compile().facts]

    assert build() == build()


def test_a_history_replays_from_its_own_recipe() -> None:
    from worldloom.recipe import rebuild

    built = ProcureToPayWorld(seed=SEED).build()
    for period in ("2026-03", "2026-04", "2026-05"):
        built = built.run(PurchaseToPayCycle(period=period))

    again = rebuild(built.recipe)
    assert [f.model_dump_json() for f in again.facts] == \
           [f.model_dump_json() for f in built.facts]
    assert [i.model_dump_json() for i in again.artifact_intents] == \
           [i.model_dump_json() for i in built.artifact_intents]
    assert [e.model_dump_json() for e in again.evaluations] == \
           [e.model_dump_json() for e in built.evaluations]


def test_consecutive_months_are_not_one_month_photocopied(history: World) -> None:
    """A history has to actually have a history in it. The accrual moves
    because the receipt moves, and the second month's accrual carries the
    first month's shortfall — which is the whole difference between
    ``--periods 3`` and three copies of one month."""
    company = history.company.id
    accruals = [
        f.value.amount for f in sorted(
            (f for f in history.facts
             if f.kind == "financial.accrual.grni" and f.subject == company),
            key=lambda f: f.period or "",
        )
    ]
    assert len(accruals) == 3
    assert len(set(accruals)) == 3
    released = only(history, "p2p.shortfall_released_value",
                    subject=company, period=NEXT_PERIOD)
    assert released.value.amount > 0


def test_the_rate_card_is_agreed_once_and_holds(history: World) -> None:
    """A standing agreement that silently re-negotiated itself every month
    would make every cross-month comparison meaningless, and nothing in the
    corpus would say so."""
    for handle in ("cat_contested_line", "cat_clean_line"):
        rates = [f for f in history.facts
                 if f.kind == "p2p.contract_rate" and f.subject == history._roles[handle]]
        assert len(rates) == 1


def test_the_vendor_master_change_is_raised_once_per_corpus(history: World) -> None:
    assert len([f for f in history.facts if f.kind == "p2p.vendor_change_status"]) == 1
    assert len([a for a in history.artifacts
                if a.artifact_type == "vendor_master_change"]) == 1


# ---------------------------------------------------------------------------
# The thin waist
# ---------------------------------------------------------------------------
#
# This vertical's own non-coupling proof. `tests/test_thin_waist.py` is a
# ratchet over the three verticals that already existed and carries an exact
# exceptions ledger; adding a fourth vertical's vocabulary to it would mean
# editing a file whose whole value is that it is not edited casually. So the
# same scan runs here, over the same core modules, for this vertical's own
# words — and a fifth vertical should copy this rather than grow that ledger.

_CORE = (
    "models.py", "world.py", "validate.py", "domains.py", "packs.py",
    "recipe.py", "cli.py", "documents.py", "parameters.py", "landscape.py",
    "locales.py", "scenarios.py", "archetypes.py",
    "generators/org_builder.py", "generators/cases.py",
    "render/__init__.py", "render/markdown.py", "render/xlsx.py",
    "render/docx.py",
)

_PROCUREMENT_VOCABULARY = (
    "p2p.", "purchase_order", "goods_receipt_note", "supplier_invoice",
    "match_exception_report", "payment_approval_memo", "vendor_master_change",
    "PurchaseToPayCycle", "category_manager", "accounts_payable_lead",
    "site_receiving_lead", "chief_procurement", "procurement.",
)

#: The two occurrences that are legitimately in core, with the reason. Both are
#: *data*, not machinery: an archetype is a shape in a registry (which is what
#: `archetypes.py` is for and where the other four verticals' shapes also sit),
#: and it names no fact kind, no artifact type and no scenario.
_ALLOWED = {
    ("archetypes.py", "midsize_infrastructure_services"),
}


def _code_only(source: str) -> str:
    """The file with comments and docstrings removed — coupling is measured in
    code, not in prose that explains it. Same technique as
    ``tests/test_thin_waist.py``; kept as a local copy rather than imported so
    that this file passes or fails on its own."""
    import ast

    docstrings: set[tuple[int, int]] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add((body[0].value.lineno, body[0].value.col_offset))
    out: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            continue
        if token.type == tokenize.STRING and token.start in docstrings:
            continue
        if token.type not in (tokenize.NL, tokenize.NEWLINE):
            out.append(token.string)
    return " ".join(out)


def test_core_code_never_learned_this_vertical_exists() -> None:
    src = Path("src/worldloom")
    found = [
        (module, token)
        for module in _CORE
        for token in _PROCUREMENT_VOCABULARY
        if token in _code_only((src / module).read_text(encoding="utf-8"))
        and (module, token) not in _ALLOWED
    ]
    assert not found, (
        "procurement vocabulary reached core — the fix is a registration seam or a"
        " domain module, not a new exception:\n"
        + "\n".join(f"  {module}: {token!r}" for module, token in found)
    )


def test_the_only_hand_edit_outside_this_vertical_is_the_package_import() -> None:
    """The fifth seam, and the one that is not a registry: a domain module
    registers by being imported, and the only thing that imports it
    unconditionally is ``worldloom/__init__``. Pinned so that a later change
    which quietly moved registration elsewhere — a lazy import, an entry
    point — has to say so here."""
    text = Path("src/worldloom/__init__.py").read_text(encoding="utf-8")
    assert "from .procurement import ProcureToPayWorld" in text
    assert "from .procurement_scenarios import PurchaseToPayCycle" in text
