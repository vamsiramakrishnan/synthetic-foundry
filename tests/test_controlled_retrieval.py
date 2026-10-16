from __future__ import annotations

import json

import pytest

from worldloom.connector_definition import load_connector_definition
from worldloom.connector_emulator import ConnectorEmulator, ConnectorError
from worldloom.evalrun.retrieval import (
    ControlledRetrieval,
    QueryAlias,
    QueryIntent,
    ResponsePolicy,
    RetrievalContract,
    RetrievalFault,
)
from worldloom.predicates import FieldPredicate, Predicate, PredicateOp
from worldloom.providers import digest


def _records() -> list[dict[str, object]]:
    return [
        {"fid": fid, "server": "sharepoint", "entity": "xlsx", "ident": fid,
         "name": f"{fid}.xlsx", "business_unit": unit, "period": "FY2026", "status": status,
         "version": 2 if status == "approved" else 1, "amount": amount, "flag": True}
        for fid, unit, status, amount in (
            ("sp:2", "retail", "approved", 200), ("sp:1", "retail", "approved", 100),
            ("sp:draft", "retail", "draft", 90), ("sp:other", "banking", "approved", 500),
            ("sp:secret", "retail", "approved", 800),
        )
    ]


def _contract(**updates: object) -> RetrievalContract:
    data: dict[str, object] = {
        "id": "close-source", "connector": "sharepoint", "tool": "search_files",
        "intent": QueryIntent(entity="xlsx", scope=(FieldPredicate(field="business_unit", value="retail"),),
                              period=(FieldPredicate(field="period", value="FY2026"),),
                              authority=(FieldPredicate(field="status", value="approved"),)),
        "on_insufficient": ResponsePolicy(hint="Check the business unit, reporting period and approval status."),
        "aliases": (QueryAlias(field="status", canonical="approved", alternatives=("final",)),),
    }
    data.update(updates)
    return RetrievalContract.model_validate(data)


def _surface(contract: RetrievalContract | None = None) -> ConnectorEmulator:
    return ConnectorEmulator(load_connector_definition("sharepoint"), _records(),
                             acl={"sp:secret": {"denied": True}},
                             retrieval=ControlledRetrieval(contract or _contract()))


def _query(**updates: object) -> dict[str, object]:
    return {"business_unit": "retail", "period": "FY2026", "status": "approved", **updates}


def test_sufficient_query_delivers_real_records_preserving_acl_versions_and_receipts() -> None:
    surface = _surface()
    result = surface.call("search_files", entity="xlsx", predicate=_query(), fields=["name", "version"])
    assert surface.retrieval is not None
    receipt = surface.retrieval.receipts[-1]
    assert receipt.intent_status == "sufficient"
    assert [item.record_id for item in receipt.returned] == ["sp:1", "sp:2"]
    assert receipt.returned[0].source_digest == digest(surface.records["sp:1"])
    assert receipt.returned[0].payload_digest == digest(result["items"][0])
    assert receipt.response_digest == digest(result)
    assert result["total"] == 2
    assert result["retrieval"] == {"mode": "controlled", "completeness": "complete"}
    with pytest.raises(ConnectorError) as caught:
        surface.call("get_file", id="sp:secret")
    assert caught.value.kind == "denied"
    assert len(surface.retrieval.receipts) == 1


def test_aliases_and_clause_order_are_equivalent_but_do_not_make_retry_progress() -> None:
    surface = _surface()
    first = surface.call("search_files", entity="xlsx", predicate=_query())
    second = surface.call("search_files", entity="xlsx", predicate={"status": "FINAL", "period": "FY2026", "business_unit": "retail"})
    assert first == second
    assert surface.retrieval is not None
    left, right = surface.retrieval.receipts
    assert left.query_digest == right.query_digest
    assert right.progress == "no_progress"


def test_insufficient_query_needs_semantic_refinement_not_repetition() -> None:
    surface = _surface()
    first = surface.call("search_files", entity="xlsx", predicate={"business_unit": "retail"})
    assert first["items"] == []
    assert first["retrieval"]["hint"].startswith("Check")
    surface.call("search_files", entity="xlsx", predicate={"business_unit": "retail"})
    surface.call("search_files", entity="xlsx", predicate={"business_unit": "retail", "period": "FY2026"})
    surface.call("search_files", entity="xlsx", predicate=_query())
    assert surface.retrieval is not None
    receipts = surface.retrieval.receipts
    assert receipts[0].missing_dimensions == ("authority", "period")
    assert [receipt.progress for receipt in receipts] == ["initial", "no_progress", "refinement", "refinement"]
    assert receipts[-1].intent_status == "sufficient"
    assert "missing_dimensions" not in json.dumps(first)
    assert "satisfied" not in json.dumps(first)


def test_wrong_scope_never_gets_the_oracle_source() -> None:
    surface = _surface()
    result = surface.call("search_files", entity="xlsx", predicate=_query(business_unit="banking"))
    assert result["items"] == []
    assert surface.retrieval is not None
    assert surface.retrieval.receipts[-1].missing_dimensions == ("scope",)
    assert not surface.retrieval.receipts[-1].returned


def test_stale_response_is_an_intersection_with_the_actual_query() -> None:
    surface = _surface(_contract(on_insufficient=ResponsePolicy(
        mode="stale", selector=Predicate.equalities({"status": "draft"}), hint="This source is a draft.")))
    draft = surface.call("search_files", entity="xlsx", predicate={"business_unit": "retail"})
    assert draft["total"] == 1
    assert surface.trace[-1].reads == ("sp:draft",)
    assert draft["retrieval"]["completeness"] == "stale"
    # The oracle cannot return that same draft for another business unit.
    other = surface.call("search_files", entity="xlsx", predicate={"business_unit": "banking"})
    assert other["items"] == []
    final = surface.call("search_files", entity="xlsx", predicate=_query())
    assert final["total"] == 2
    assert surface.trace[-1].reads == ("sp:1", "sp:2")


def test_partial_cap_is_applied_before_paging_and_replays() -> None:
    contract = _contract(on_insufficient=ResponsePolicy(mode="partial", limit=1))
    left, right = _surface(contract), _surface(contract)
    for surface in (left, right):
        page = surface.call("search_files", entity="xlsx", predicate={"business_unit": "retail"}, max_results=1)
        assert page["total"] == 1
        assert page["is_last"]
    assert left.retrieval is not None and right.retrieval is not None
    assert left.retrieval.receipts == right.retrieval.receipts


def test_pagination_counts_only_the_next_new_page() -> None:
    surface = _surface()
    surface.call("search_files", entity="xlsx", predicate=_query(), max_results=1)
    surface.call("search_files", entity="xlsx", predicate=_query(), max_results=1, start_at=0)
    surface.call("search_files", entity="xlsx", predicate=_query(), max_results=1, start_at=1)
    surface.call("search_files", entity="xlsx", predicate=_query(), max_results=1, start_at=1)
    assert surface.retrieval is not None
    assert [receipt.progress for receipt in surface.retrieval.receipts] == ["initial", "no_progress", "pagination", "no_progress"]
    assert surface.retrieval.receipts[0].next_at == 1
    assert surface.retrieval.receipts[2].is_last


def test_transient_fault_is_distinct_from_query_failure_and_allows_a_valid_retry() -> None:
    surface = _surface(_contract(faults=(RetrievalFault(attempt=1),)))
    with pytest.raises(ConnectorError) as caught:
        surface.call("search_files", entity="xlsx", predicate=_query())
    assert caught.value.kind == "timeout"
    result = surface.call("search_files", entity="xlsx", predicate=_query(status="final"))
    assert result["total"] == 2
    assert surface.retrieval is not None
    failure, recovered = surface.retrieval.receipts
    assert failure.intent_status == "transport_fault" and not failure.returned
    assert recovered.intent_status == "sufficient" and recovered.progress == "retry"


def test_changing_scope_after_fault_does_not_get_retry_credit() -> None:
    surface = _surface(_contract(faults=(RetrievalFault(attempt=1, kind="rate_limit"),)))
    with pytest.raises(ConnectorError):
        surface.call("search_files", entity="xlsx", predicate=_query())
    surface.call("search_files", entity="xlsx", predicate=_query(business_unit="banking"))
    assert surface.retrieval is not None
    assert surface.retrieval.receipts[-1].progress == "no_progress"


def test_broad_in_is_not_specific_even_when_fixture_has_only_one_period() -> None:
    surface = _surface()
    query = Predicate(entity="xlsx", where=(
        FieldPredicate(field="business_unit", value="retail"),
        FieldPredicate(field="period", op=PredicateOp.IN, value=("FY2026", "FY2025")),
        FieldPredicate(field="status", value="approved"),
    ))
    assert surface.call("search_files", predicate=query)["items"] == []
    assert surface.retrieval is not None
    assert surface.retrieval.receipts[-1].missing_dimensions == ("period",)


def test_boolean_integer_in_normalization_is_type_sensitive_and_order_independent() -> None:
    contract = _contract(intent=QueryIntent(entity="xlsx", scope=(FieldPredicate(field="flag", value=True),)))
    digests = []
    for values in ((True, 1), (1, True)):
        surface = _surface(contract)
        query = Predicate(entity="xlsx", where=(FieldPredicate(field="flag", op=PredicateOp.IN, value=values),))
        assert surface.call("search_files", predicate=query)["items"] == []
        assert surface.retrieval is not None
        receipt = surface.retrieval.receipts[-1]
        assert receipt.intent_status == "insufficient"
        digests.append(receipt.query_digest)
    assert digests[0] == digests[1]


def test_controller_state_is_transactional_and_fresh_runs_reset_it() -> None:
    original = _surface(_contract(faults=(RetrievalFault(attempt=1),)))
    discarded = original.transaction()
    with pytest.raises(ConnectorError):
        discarded.call("search_files", entity="xlsx", predicate=_query())
    assert original.retrieval is not None and not original.retrieval.receipts
    # The dropped transaction cannot consume the original run's first fault.
    with pytest.raises(ConnectorError):
        original.call("search_files", entity="xlsx", predicate=_query())
    trial = original.transaction()
    trial.call("search_files", entity="xlsx", predicate=_query())
    assert trial.retrieval is not None
    assert trial.retrieval.receipts[-1].progress == "retry"
    assert len(original.retrieval.receipts) == 1
    fresh = trial.fork()
    assert fresh.retrieval is not None and not fresh.retrieval.receipts
    with pytest.raises(ConnectorError):
        fresh.call("search_files", entity="xlsx", predicate=_query())


def test_preflight_requires_a_sufficient_source_of_the_requested_entity() -> None:
    surface = _surface()
    assert surface.retrieval is not None
    visible = tuple(record for fid, record in surface.records.items() if surface._visible(fid))
    assert surface.retrieval.qualify(visible) == ("sp:1", "sp:2")
    with pytest.raises(ValueError, match="no visible source"):
        surface.retrieval.qualify(tuple({**record, "entity": "list_item"} for record in visible))
    assert not surface.retrieval.receipts


def test_native_query_is_an_explicit_unsupported_capability_not_a_wrong_query() -> None:
    surface = _surface()
    with pytest.raises(ConnectorError) as caught:
        surface.call("search_files", entity="xlsx", query='filename="sp:1.xlsx"')
    assert caught.value.kind == "unsupported_query"
    assert "predicate=" in caught.value.message
    assert surface.retrieval is not None
    assert surface.retrieval.receipts[-1].intent_status == "unsupported_query"
    surface.call("search_files", entity="xlsx", predicate=_query())
    assert surface.retrieval.receipts[-1].progress == "refinement"


def test_malformed_predicate_is_recorded_as_invalid_query() -> None:
    surface = _surface()
    with pytest.raises(ConnectorError) as caught:
        surface.call("search_files", entity="xlsx", predicate={"period": ["unknown", "FY2026"]})
    assert caught.value.kind == "validation"
    assert surface.retrieval is not None
    assert surface.retrieval.receipts[-1].intent_status == "invalid_query"
    surface.call("search_files", entity="xlsx", predicate=_query())
    assert surface.retrieval.receipts[-1].progress == "refinement"


def test_contract_rejects_ambiguous_aliases_and_unsupported_operations() -> None:
    with pytest.raises(ValueError, match="conflicting query alias"):
        _contract(aliases=(QueryAlias(field="status", canonical="approved", alternatives=("final",)),
                           QueryAlias(field="status", canonical="draft", alternatives=("FINAL",))))
    with pytest.raises(ValueError, match="required operation"):
        _surface(_contract(tool="get_file"))


def test_narrow_numeric_bound_satisfies_requirement_without_exact_query_matching() -> None:
    contract = _contract(intent=QueryIntent(entity="xlsx", scope=(
        FieldPredicate(field="amount", op=PredicateOp.GTE, value=100),)))
    surface = _surface(contract)
    query = Predicate(entity="xlsx", where=(FieldPredicate(field="amount", op=PredicateOp.GT, value=150),))
    result = surface.call("search_files", predicate=query)
    assert result["total"] == 2
    assert surface.retrieval is not None
    assert surface.retrieval.receipts[-1].intent_status == "sufficient"


def test_contains_on_lists_cannot_claim_substring_implication() -> None:
    contract = _contract(intent=QueryIntent(entity="xlsx", scope=(
        FieldPredicate(field="tags", op=PredicateOp.CONTAINS, value="APAC"),)))
    records = [{**record, "tags": ["APAC-approved"]} for record in _records()]
    surface = ConnectorEmulator(load_connector_definition("sharepoint"), records,
                                retrieval=ControlledRetrieval(contract))
    query = Predicate(entity="xlsx", where=(
        FieldPredicate(field="tags", op=PredicateOp.CONTAINS, value="APAC-approved"),))
    assert surface.call("search_files", predicate=query)["items"] == []
    assert surface.retrieval is not None
    assert surface.retrieval.receipts[-1].intent_status == "insufficient"


def test_rejected_delivery_retains_attempt_number_but_never_claims_access() -> None:
    surface = _surface(_contract(faults=(RetrievalFault(attempt=2),)))
    surface.call("search_files", entity="xlsx", predicate=_query())
    assert surface.retrieval is not None
    corrected = surface.retrieval.reject_delivery(surface.trace[-1].id)
    assert corrected.intent_status == "transport_fault"
    assert corrected.error_kind == "response_limit"
    assert not corrected.returned and corrected.response_digest is None
    # The next call is still attempt two even though the transport discarded
    # the first payload. Rewinding the controller would skip this fixed fault.
    with pytest.raises(ConnectorError, match="Gateway timeout"):
        surface.call("search_files", entity="xlsx", predicate=_query())
    surface.call("search_files", entity="xlsx", predicate=_query())
    assert surface.retrieval.receipts[-1].progress == "retry"
    with pytest.raises(ValueError, match="latest"):
        surface.retrieval.reject_delivery(surface.trace[0].id)


def test_bounded_consecutive_transport_faults_are_valid_retry_attempts() -> None:
    surface = _surface(_contract(faults=(RetrievalFault(attempt=1), RetrievalFault(attempt=2))))
    for _ in range(2):
        with pytest.raises(ConnectorError):
            surface.call("search_files", entity="xlsx", predicate=_query())
    surface.call("search_files", entity="xlsx", predicate=_query())
    assert surface.retrieval is not None
    assert [item.progress for item in surface.retrieval.receipts] == ["initial", "retry", "retry"]
