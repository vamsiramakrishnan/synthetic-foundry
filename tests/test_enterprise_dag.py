"""Executable grammar proofs: control flow is determined by actual results."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from worldloom.connector_eval_runtime import run_eval_row
from worldloom.connector_trace import grade_trace
from worldloom.enterprise_corpus import QueryFixture
from worldloom.enterprise_dag import (
    EnterpriseDag,
    EnterpriseDagNode,
    ResultReference,
    dag_metrics,
    resolve_reference,
    shape_catalogue,
)
from worldloom.enterprise_dag_planning import apply_dag_shape
from worldloom.enterprise_queries import (
    GenerationRequirement,
    MutationRequirement,
    PlannedEnterpriseQuery,
    SourceRequirement,
)
from worldloom.enterprise_rows import compile_row


def query_and_fixture(shape: str, count: int = 3):
    sources = (SourceRequirement(connector="jira", entity="issue"),
               SourceRequirement(connector="servicenow", entity="incident"))
    query = PlannedEnterpriseQuery(
        id="grammar-query", workflow="test", query="Create an evidence report.", dimensions={},
        generation=GenerationRequirement(
            process="test", source_requirements=sources,
            mutation=MutationRequirement(connector="sharepoint", entity="file", operation="create",
                                         output_format="docx", preexisting_record=False),
        ), expected_dag=(),
    )
    records = tuple(
        {"fid": f"{source.connector}:{index}", "id": f"{source.connector}:{index}",
         "server": source.connector, "entity": source.entity,
         "ident": f"{source.connector}-{index}", "name": f"Evidence {index}",
         "title": f"Evidence {index}", "priority": 1}
        for source in sources for index in range(count)
    )
    fixture = QueryFixture(
        query_id=query.id, input_record_ids={
            f"{source.connector}:{source.entity}": tuple(f"{source.connector}:{index}" for index in range(count))
            for source in sources
        }, destination_record_id=None, overrides=(), expected_side_effects=(),
    )
    shaped = apply_dag_shape(query, shape)
    shaped = shaped.model_copy(update={"generation": shaped.generation.model_copy(update={
        "source_requirements": tuple(source.model_copy(update={"minimum": 1}) for source in shaped.generation.source_requirements),
    })})
    return shaped, fixture.model_copy(update={"query_id": shaped.id}), records


def compiled(shape: str, count: int = 3):
    query, fixture, records = query_and_fixture(shape, count)
    return compile_row(query, fixture, records), records


@pytest.mark.parametrize("shape", tuple(shape_catalogue()))
def test_every_authored_shape_compiles_executes_and_grades(shape):
    row, records = compiled(shape)
    result = run_eval_row(row, records)
    assert result.grade["fails"] == [], (shape, result.grade)
    assert result.spans
    assert any(span.writes for span in result.spans)
    assert row == compiled(shape)[0]
    # The only error a shipped shape expects is the readback after a delete.
    errors = [(span.node, span.error["kind"]) for span in result.spans if span.error]
    assert errors == ([("verify-deleted", "not_found")] if shape == "delete_chain" else [])


def test_the_delete_chain_grades_the_record_gone_and_the_readback_failing():
    row, records = compiled("delete_chain")
    assertions = {assertion["type"]: assertion for assertion in row["assertions"]}
    assert assertions["deleted"] == {"type": "deleted", "node": "delete", "created_by": "write"}
    assert assertions["failure_at"]["node"] == "verify-deleted" and assertions["failure_at"]["kind"] == "not_found"
    result = run_eval_row(row, records)
    created = next(span for span in result.spans if span.node == "write").writes
    assert created and not any(fid in result.post_state for fid in created)
    # Without the delete the record persists and the last readback succeeds: both are fails.
    kept = tuple(span for span in result.spans if span.node not in {"delete", "verify-deleted"})
    post_state = {**result.post_state, created[0]: {"entity": "docx", "name": "kept"}}
    fails = grade_trace(kept, row, post_state=post_state)["fails"]
    assert "not_deleted:delete" in fails and "failure_not_observed:verify-deleted:not_found" in fails
    # A readback that succeeds after the delete is an unexpected success, not a pass.
    readback = next(span for span in result.spans if span.node == "verify-deleted")
    forged = tuple(replace(span, error=None, reads=tuple(created)) if span is readback else span for span in result.spans)
    assert "failure_not_observed:verify-deleted:not_found" in grade_trace(forged, row, post_state=result.post_state)["fails"]


def test_shapes_change_structure_and_measured_depth():
    rows = [compiled(shape)[0] for shape in shape_catalogue()]
    signatures = {
        str([(node["node_kind"], node["op"], node.get("condition"), node.get("for_each"))
             for node in row["expected_dag"]["nodes"]]) + str(row["expected_dag"]["edges"])
        for row in rows
    }
    assert len(signatures) == len(rows)
    depths = {row["metrics"]["depth"] for row in rows}
    assert max(depths) >= 6 and len(depths) >= 3


@pytest.mark.parametrize("count,selected,skipped", [(1, "write-fallback", "write-primary"), (3, "write-primary", "write-fallback")])
def test_condition_evaluates_prior_search_result_count(count, selected, skipped):
    row, records = compiled("conditional", count)
    result = run_eval_row(row, records)
    assert result.grade["fails"] == []
    assert selected in {span.node for span in result.spans}
    assert skipped not in {span.node for span in result.spans}
    # A trace cannot pick the other branch by relabeling its call.
    forged = tuple(replace(span, node=skipped) if span.node == selected else span for span in result.spans)
    failures = grade_trace(forged, row, post_state=result.post_state)["fails"]
    assert f"branch_not_selected:{skipped}" in failures


@pytest.mark.parametrize("count", [1, 3])
def test_map_fetches_each_returned_record_and_joins_actual_results(count):
    row, records = compiled("map_read", count)
    result = run_eval_row(row, records)
    assert result.grade["fails"] == []
    assert len([span for span in result.spans if span.node == "fetch-0"]) == count
    write = next(span for span in result.spans if span.node == "write")
    assert write.args["fields"]["evidence_count"] == count * 2
    assert len(write.args["fields"]["evidence"]) == count * 2
    incomplete = tuple(span for span in result.spans if not (span.node == "fetch-0" and span.reads == ("jira:0",)))
    assert any("per_item" in failure for failure in grade_trace(incomplete, row, post_state=result.post_state)["fails"])


def test_empty_map_performs_zero_fetches_and_keeps_join_defined():
    row, records = compiled("map_read")
    row = deepcopy(row)
    for node in row["expected_dag"]["nodes"]:
        if node["node_kind"] == "search":
            node["payload"]["predicate"] = {"id": ["in", []]}
            node["expected_reads"] = []
    result = run_eval_row(row, records)
    assert result.grade["fails"] == []
    assert not any(span.node.startswith("fetch-") for span in result.spans)
    assert next(span for span in result.spans if span.node == "write").args["fields"]["evidence_count"] == 0


def test_map_bound_is_effective_and_gradeable():
    row, records = compiled("map_read", 3)
    row = deepcopy(row)
    for node in row["expected_dag"]["nodes"]:
        if node.get("for_each"):
            node["for_each"]["limit"] = 2
    result = run_eval_row(row, records)
    assert result.grade["fails"] == []
    assert len([span for span in result.spans if span.node == "fetch-0"]) == 2
    assert next(span for span in result.spans if span.node == "write").args["fields"]["evidence_count"] == 4


def test_readback_binds_to_actual_created_record_and_writes_are_verified():
    row, records = compiled("write_chain")
    result = run_eval_row(row, records)
    write = next(span for span in result.spans if span.node == "write")
    verify = next(span for span in result.spans if span.node == "verify-write")
    marker = next(span for span in result.spans if span.node == "write-marker")
    assert write.writes == verify.reads == marker.writes
    damaged = deepcopy(result.post_state)
    damaged[write.writes[0]]["verified"] = False
    assert any("field_mismatch" in failure for failure in grade_trace(result.spans, row, post_state=damaged)["fails"])


def test_reference_and_graph_validation_refuse_missing_values_cycles_and_duplicate_ids():
    node = EnterpriseDagNode(id="r", kind="read", connector="jira", entity="issue", operation="read")
    assert dag_metrics(EnterpriseDag(nodes=(node,)))["depth"] == 1
    assert resolve_reference(ResultReference(node="r", select="count", encoding="json"), {"r": [{"id": "one"}]}) == "1"
    with pytest.raises(ValueError, match="duplicate"):
        EnterpriseDag(nodes=(node, node))
    with pytest.raises(ValueError, match="cyclic"):
        EnterpriseDag(nodes=(node.model_copy(update={"depends_on": ("r",)}),))
    bad = EnterpriseDagNode(id="w", kind="write", connector="jira", entity="issue", operation="update",
                            bindings={"id": ResultReference(node="r", path=("id",))})
    with pytest.raises(ValueError, match="not ancestors"):
        EnterpriseDag(nodes=(node, bad))
    with pytest.raises(ValueError, match="empty_result"):
        resolve_reference(ResultReference(node="r"), {"r": []})
    with pytest.raises(ValueError, match="missing_result_field"):
        resolve_reference(ResultReference(node="r", path=("absent",)), {"r": [{"id": "one"}]})


def test_execution_budget_refuses_before_unbounded_calls():
    row, records = compiled("map_read")
    row["max_calls"] = 1
    with pytest.raises(ValueError, match="execution_budget_exceeded"):
        run_eval_row(row, records)


def test_bound_write_argument_tampering_fails_without_executor_metadata():
    row, records = compiled("fan_in")
    result = run_eval_row(row, records)
    changed = tuple(replace(span, args={**span.args, "fields": {"evidence_count": 99}})
                    if span.node == "write" else span for span in result.spans)
    failures = grade_trace(changed, row, post_state=result.post_state)["fails"]
    assert "argument_mismatch:write:fields" in failures


def test_planning_grammar_is_opt_in_and_shards_preserve_global_sequence():
    from worldloom.enterprise_queries import plan_queries
    from worldloom.enterprise_sdk import EnterpriseEvalHarness
    from worldloom.world import World

    world = World.load("examples/retail-close")
    legacy, _ = plan_queries(world, strategy="exhaustive", limit=3)
    assert all("dag_grammar" not in query.dimensions for query in legacy)
    harness = EnterpriseEvalHarness.from_world(world).exhaustive().with_dag_grammar().take(400)
    planned, _ = harness.plan()
    assert {query.dimensions["dag_shape"] for query in planned} == set(shape_catalogue())
    shards = [harness.take(200).shard(index, 2)[0] for index in range(2)]
    assert tuple(query.id for pair in zip(*shards, strict=True) for query in pair) == tuple(query.id for query in planned)
    assert any(source.minimum >= 2 for query in planned if query.dimensions["dag_shape"] == "map_read"
               for source in query.generation.source_requirements)


def test_mutating_call_cannot_hide_under_a_local_transform():
    row, records = compiled("fan_in")
    result = run_eval_row(row, records)
    write = next(span for span in result.spans if span.node == "write")
    extra = replace(write, id="hidden-write", node="collect")
    assert "unexpected_transform_call:collect" in grade_trace((*result.spans, extra), row, post_state=result.post_state)["fails"]


def test_kind_operation_and_count_path_mismatches_are_refused():
    with pytest.raises(ValueError, match="read cannot execute"):
        EnterpriseDagNode(id="r", kind="read", connector="jira", entity="issue", operation="delete")
    with pytest.raises(ValueError, match="count references"):
        ResultReference(node="r", select="count", path=("id",))


def test_local_result_budget_is_enforced_before_fan_in_allocation():
    row, records = compiled("map_read")
    row["max_result_items"] = 2
    with pytest.raises(ValueError, match="result_budget_exceeded"):
        run_eval_row(row, records)


def test_native_readback_payload_can_bind_a_later_write_from_recorded_result():
    query, fixture, records = query_and_fixture("write_chain")
    nodes = deepcopy(list(query.expected_dag))
    marker = next(node for node in nodes if node["id"] == "write-marker")
    marker["bindings"]["fields.original_mime"] = {
        "node": "verify-write", "path": ["payload", "file", "mimeType"], "select": "first",
    }
    query = query.model_copy(update={"expected_dag": tuple(nodes)})
    row = compile_row(query, fixture, records)
    result = run_eval_row(row, records)
    assert result.grade["fails"] == []
    write = next(span for span in result.spans if span.node == "write-marker")
    assert write.args["fields"]["original_mime"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_native_source_field_drives_a_condition_and_receipts_are_checked():
    query, fixture, records = query_and_fixture("conditional")
    nodes = deepcopy(list(query.expected_dag))
    for node in nodes:
        if node.get("condition"):
            primary = "primary" in node["id"]
            node["condition"] = {
                "reference": {"node": "read-0", "path": ["payload", "fields", "summary"], "select": "first"},
                "operator": "eq" if primary else "ne", "value": "Evidence 0",
            }
    query = query.model_copy(update={"expected_dag": tuple(nodes)})
    row = compile_row(query, fixture, records)
    result = run_eval_row(row, records)
    assert result.grade["fails"] == []
    assert "write-primary" in {span.node for span in result.spans}
    source = next(span for span in result.spans if span.node == "read-0")
    tampered = deepcopy(source.result)
    tampered["items"][0]["fields"]["summary"] = "Unrelated source"
    forged = tuple(replace(span, result=tampered) if span.id == source.id else span for span in result.spans)
    assert any(failure.startswith("result_mismatch:read-0") for failure in grade_trace(forged, row, post_state=result.post_state)["fails"])


def test_wrong_bound_identity_and_created_entity_are_rejected():
    row, records = compiled("fan_in")
    result = run_eval_row(row, records)
    wrong_id = tuple(replace(span, args={**span.args, "id": "unrelated"}) if span.node == "verify-write" else span for span in result.spans)
    assert "argument_mismatch:verify-write:id" in grade_trace(wrong_id, row, post_state=result.post_state)["fails"]
    wrong_entity = tuple(replace(span, args={**span.args, "entity": "xlsx"}) if span.node == "write" else span for span in result.spans)
    assert "entity_mismatch:write" in grade_trace(wrong_entity, row, post_state=result.post_state)["fails"]


@pytest.mark.parametrize("shape", ["fan_in", "fan_out", "conditional", "map_read", "delete_chain"])
@pytest.mark.parametrize("kind", ["permission_denied", "version_conflict", "partial_write", "missing_stable_id"])
def test_designed_failures_keep_control_flow_and_independent_branches(shape, kind):
    from worldloom.enterprise_corpus import StateOverride

    query, fixture, records = query_and_fixture(shape)
    source_failure = kind == "missing_stable_id"
    override = StateOverride(kind=kind, connector="jira" if source_failure else "sharepoint",
                             record_id="jira:0" if source_failure else None,
                             details={"fail_after": 1} if kind == "partial_write" else {})
    fixture = fixture.model_copy(update={"overrides": (override,)})
    row = compile_row(query, fixture, records)
    result = run_eval_row(row, records)
    assert result.grade["fails"] == [], (shape, kind, result.grade)
    failures = [span for span in result.spans if span.error]
    assert failures
    assert not any(span.node.startswith("verify-") for span in result.spans)
    if source_failure:
        assert any(span.node == "read-1" and not span.error for span in result.spans)
    # A different infrastructure failure must not satisfy the injected condition.
    wrong = tuple(replace(span, error={**span.error, "kind": "timeout"}) if span.error else span for span in result.spans)
    assert grade_trace(wrong, row, post_state=result.post_state)["fails"]


@pytest.mark.parametrize("operation,shape", [("send", "fan_out"), ("reply", "fan_in")])
def test_email_effects_use_native_body_and_distinct_create_identity(operation, shape):
    query, fixture, records = query_and_fixture(shape)
    mutation = MutationRequirement(connector="email", entity="message", operation=operation,
                                    output_format="record", preexisting_record=operation == "reply")
    query = query.model_copy(update={"generation": query.generation.model_copy(update={"mutation": mutation}), "expected_dag": ()})
    query = apply_dag_shape(query, shape)
    if operation == "reply":
        records = (*records, {"fid": "email:parent", "id": "email:parent", "server": "email", "entity": "message", "name": "Existing request"})
    fixture = fixture.model_copy(update={"query_id": query.id, "destination_record_id": "email:parent" if operation == "reply" else None})
    row = compile_row(query, fixture, records)
    result = run_eval_row(row, records)
    assert result.grade["fails"] == []
    written = [fid for span in result.spans for fid in span.writes]
    if operation == "send":
        assert len(set(written)) == 2
    else:
        assert result.post_state[written[0]]["reply_to"] == "email:parent"
        assert "jira:0" in result.post_state[written[0]]["body"]


def test_known_missing_source_payload_path_refuses_at_compile_time():
    query, fixture, records = query_and_fixture("fan_in")
    nodes = deepcopy(list(query.expected_dag))
    write = next(node for node in nodes if node["id"] == "write")
    write["bindings"]["fields.impossible"] = {"node": "read-0", "path": ["payload", "nonexistent"]}
    with pytest.raises(ValueError, match="missing_result_field"):
        compile_row(query.model_copy(update={"expected_dag": tuple(nodes)}), fixture, records)


def test_external_attribution_reconstructs_only_delivered_result_values():
    from worldloom.enterprise_dag import condition_matches
    from worldloom.enterprise_dag_rows import program_for
    from worldloom.enterprise_dag_runtime import observed_outputs

    row, records = compiled("conditional", 1)
    result = run_eval_row(row, records)
    assert observed_outputs(row, ()) == {}
    before_write = tuple(span for span in result.spans if span.node.startswith("read-"))
    outputs = observed_outputs(row, before_write)
    nodes = {node.id: node for node in program_for(row).nodes}
    assert not condition_matches(nodes["write-primary"].condition, outputs)
    assert condition_matches(nodes["write-fallback"].condition, outputs)
    assert outputs["collect"]


def test_compiled_arguments_match_advertised_connector_tool_schemas():
    from worldloom.connector_definition import builtin_connector_definitions

    definitions = builtin_connector_definitions()
    for shape in shape_catalogue():
        row, _ = compiled(shape)
        for node in row["expected_dag"]["nodes"]:
            if node["node_kind"] == "transform":
                continue
            assert set(node["payload"]) <= set(definitions[node["server"]].tool(node["tool"]).params)
    query, fixture, records = query_and_fixture("write_chain")
    nodes = deepcopy(list(query.expected_dag))
    next(node for node in nodes if node["id"] == "write-marker")["arguments"]["name"] = "Unadvertised update argument"
    with pytest.raises(ValueError, match="does not accept arguments"):
        compile_row(query.model_copy(update={"expected_dag": tuple(nodes)}), fixture, records)
