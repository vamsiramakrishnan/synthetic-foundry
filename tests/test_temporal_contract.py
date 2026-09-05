"""The ledger, narrator and predicate share one observer/time boundary."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from worldloom.collections import FactCollection
from worldloom.epistemics import AmbiguousFactView, ledger_from_facts
from worldloom.models import Authority, CanonicalFact, Quantity
from worldloom.narrative.claims import validate
from worldloom.narrative.requests import GeneratedClaim, GeneratedNarrative, NarrativeRequest
from worldloom.predicates import (
    AsOf, FieldPredicate, JoinPredicate, Predicate, PredicateOp, QueryContext,
    RelativeTime, evaluate, selectivity,
)

T = datetime(2026, 9, 1, tzinfo=UTC)
LATER = datetime(2026, 9, 3, tzinfo=UTC)


def fact(id_: str, amount: int, **kwargs: object) -> CanonicalFact:
    return CanonicalFact.model_validate(dict(
        id=id_, kind="inventory", subject="stock", value=Quantity(amount=amount, unit="units"),
        valid_from=T, authority=Authority.SYSTEM_OF_RECORD, **kwargs,
    ))


def test_new_fields_round_trip_without_changing_legacy_wire_shape() -> None:
    old = fact("old", 10)
    assert not {"observer", "source", "tx_from", "tx_to", "derived_from"} & old.model_dump().keys()
    new = fact("new", 11, observer="finance", tx_from=LATER, derived_from=("old",))
    assert CanonicalFact.model_validate_json(new.model_dump_json()) == new
    assert ledger_from_facts((new,)).to_tuple()[0] is new


def test_latent_truth_does_not_overwrite_an_employee_belief() -> None:
    actual = fact("actual", 11, observer="*", source="latent", tx_from=T)
    belief = fact("belief", 10, observer="finance", tx_from=T)
    visible = FactCollection((actual, belief)).view("finance", valid_at=T, tx_at=LATER)
    assert visible.ids() == ["belief"]


def test_restatement_changes_now_not_the_historical_record() -> None:
    early = fact("early", 10, observer="finance", tx_from=T)
    corrected = fact("corrected", 11, observer="finance", tx_from=LATER, supersedes="early")
    ledger = ledger_from_facts((early, corrected))
    assert ledger.view("finance", valid_at=T, tx_at=T).to_tuple() == (early,)
    assert ledger.view("finance", valid_at=T, tx_at=LATER).to_tuple() == (corrected,)


def test_transaction_interval_is_half_open() -> None:
    early = fact("early", 10, tx_from=T, tx_to=LATER)
    assert early.known_at(T)
    assert not early.known_at(LATER)
    with pytest.raises(ValueError, match="tx_to"):
        fact("invalid", 10, tx_from=LATER, tx_to=T)


def test_ambiguous_authority_is_not_resolved_by_identifier() -> None:
    ledger = ledger_from_facts((fact("a", 10), fact("z", 11)))
    with pytest.raises(AmbiguousFactView):
        ledger.view("*", valid_at=T, tx_at=T)
    corrected = fact("winner", 12, tx_from=LATER)
    assert ledger_from_facts((*ledger, corrected)).view("*", valid_at=T, tx_at=LATER).best() == corrected


def test_as_of_predicate_removes_inaccessible_current_value() -> None:
    late = fact("late", 11, observer="finance", tx_from=LATER)
    context = QueryContext(clock=T, facts=(late,))
    pred = Predicate(where=(FieldPredicate(field="inventory", value=11),), as_of=AsOf(observer="finance"))
    assert not evaluate(pred, {"id": "stock", "inventory": 11}, context=context)
    with pytest.raises(ValueError, match="QueryContext"):
        evaluate(pred, {"id": "stock", "inventory": 11})


def test_join_selectivity_uses_same_frozen_context() -> None:
    context = QueryContext(clock=LATER, records=(
        {"id": "inc1", "entity": "incident", "priority": "P1"},
        {"id": "inc2", "entity": "incident", "priority": "P3"},
    ))
    pred = Predicate(entity="bug", joins=(JoinPredicate(field="incident", predicate=Predicate.equalities({"priority": "P1"}, entity="incident")),))
    records = ({"id": "b1", "entity": "bug", "incident": "inc1"}, {"id": "b2", "entity": "bug", "incident": "inc2"})
    assert evaluate(pred, records[0], context=context)
    assert not evaluate(pred, records[1], context=context)
    assert selectivity(pred, records, context=context) == .5


def test_temporal_boundary_and_missing_fields_are_explicit() -> None:
    pred = Predicate(where=(FieldPredicate(field="opened", op=PredicateOp.LTE, value=RelativeTime(days=-2)),))
    assert evaluate(pred, {"opened": T.isoformat()}, context=QueryContext(clock=LATER))
    assert not evaluate(Predicate.equalities({"optional": None}), {})
    assert not evaluate(Predicate.equalities({"count": 1}), {"count": True})
    assert not evaluate(Predicate.equalities({}, entity="incident"), {"entity": "bug"})


def test_narrative_cannot_learn_a_backdated_fact_before_transaction_time() -> None:
    late = fact("late", 11, tx_from=LATER)
    request = NarrativeRequest(artifact_id="a", artifact_type="memo", section="summary", persona_id="p", voice="plain", audience="finance", author_title="controller", temporal_cutoff=T, allowed_fact_ids=["late"])
    narrative = GeneratedNarrative(text="Inventory is {{fact:late}}.", claims=[GeneratedClaim(text="Inventory is {{fact:late}}.", supporting_fact_ids=["late"])])
    verdict = validate(request, narrative, {"late": late})
    assert "not_yet_known" in {violation.code for violation in verdict.violations}
