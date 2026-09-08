from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from worldloom.enterprise_corpus import QueryFixture
from worldloom.enterprise_queries import (
    GenerationRequirement,
    MutationRequirement,
    PlannedEnterpriseQuery,
)
from worldloom.enterprise_runner import (
    RunnerConfig,
    ToolBinding,
    canonical_operation,
    execute_query,
    shard_queries,
)


def _query(identifier: str) -> PlannedEnterpriseQuery:
    return PlannedEnterpriseQuery(
        id=identifier,
        workflow="test",
        query="Prepare the incident review and save it.",
        dimensions={},
        generation=GenerationRequirement(
            process="service_management",
            source_requirements=(),
            mutation=MutationRequirement(
                connector="sharepoint",
                entity="file",
                operation="create",
                output_format="docx",
                preexisting_record=False,
            ),
        ),
        expected_dag=(
            {
                "id": "write",
                "kind": "create",
                "connector": "sharepoint",
                "entity": "file",
                "depends_on": [],
            },
            {
                "id": "verify",
                "kind": "readback",
                "connector": "sharepoint",
                "entity": "file",
                "depends_on": ["write"],
            },
        ),
    )


def test_shards_are_disjoint_and_complete() -> None:
    queries = tuple(_query(str(index)) for index in range(9))
    shards = [shard_queries(queries, index, 3) for index in range(3)]
    assert {query.id for shard in shards for query in shard} == {
        query.id for query in queries
    }
    assert sum(len(shard) for shard in shards) == len(queries)


def test_runner_resolves_default_tools_from_connector_definitions() -> None:
    config = RunnerConfig()

    assert config.resolve("sharepoint", "create", "file") == "sharepoint.create_file"
    assert config.resolve("sharepoint", "readback", "file") == "sharepoint.get_file"
    assert config.resolve("jira", "transition", "bug") == "jira.transition_issue"


def test_explicit_mcp_binding_overrides_definition_resolution() -> None:
    config = RunnerConfig(
        bindings=(
            ToolBinding(
                connector="sharepoint",
                operation="readback",
                entity="file",
                tool_name="customer.read_file",
            ),
        )
    )

    assert config.resolve("sharepoint", "readback", "file") == "customer.read_file"
    assert config.resolve("sharepoint", "create", "file") == "sharepoint.create_file"


def test_runner_respects_dag_dependencies() -> None:
    query = _query("Q-1")
    fixture = QueryFixture(
        query_id=query.id,
        input_record_ids={},
        destination_record_id=None,
        overrides=(),
        expected_side_effects=(),
    )
    config = RunnerConfig(
        bindings=(
            ToolBinding(
                connector="sharepoint",
                operation="create",
                entity="file",
                tool_name="sharepoint.create_file",
            ),
            ToolBinding(
                connector="sharepoint",
                operation="readback",
                entity="file",
                tool_name="sharepoint.read_file",
            ),
        )
    )
    invocations: list[str] = []

    async def invoke(
        tool_name: str, arguments: Mapping[str, Any]
    ) -> dict[str, object]:
        invocations.append(tool_name)
        return {"record_id": "SP-1", "succeeded": True}

    result = asyncio.run(execute_query(query, fixture, config, invoke))
    assert result.completed
    assert invocations == ["sharepoint.create_file", "sharepoint.read_file"]


def test_runner_stops_after_failed_write() -> None:
    query = _query("Q-2")
    fixture = QueryFixture(
        query_id=query.id,
        input_record_ids={},
        destination_record_id=None,
        overrides=(),
        expected_side_effects=(),
    )
    config = RunnerConfig(
        bindings=(
            ToolBinding(
                connector="sharepoint",
                operation="create",
                entity="file",
                tool_name="sharepoint.create_file",
            ),
            ToolBinding(
                connector="sharepoint",
                operation="readback",
                entity="file",
                tool_name="sharepoint.read_file",
            ),
        )
    )

    async def invoke(
        tool_name: str, arguments: Mapping[str, Any]
    ) -> dict[str, object]:
        return {"succeeded": False}

    result = asyncio.run(execute_query(query, fixture, config, invoke))
    assert not result.completed
    assert result.finding == "node write failed"
    assert len(result.calls) == 1


@pytest.mark.parametrize("preexisting,tool", [(True, "update_sheet"), (False, "create_sheet")])
def test_upsert_selects_the_declared_precondition_arm(preexisting, tool) -> None:
    assert RunnerConfig().resolve(
        "drive", "upsert", "file", concrete_hint="gsheet", preexisting_record=preexisting,
    ) == f"drive.{tool}"


def test_upsert_without_a_precondition_refuses() -> None:
    with pytest.raises(ValueError, match="explicit preexisting_record"):
        RunnerConfig().resolve("confluence", "upsert", "page")


def test_patch_and_draft_resolve_as_declared_writes() -> None:
    assert canonical_operation("patch") == "update"
    assert RunnerConfig().resolve("email", "draft", "message") == "email.create_draft"
    assert RunnerConfig().resolve("drive", "patch", "file", concrete_hint="gdoc") == "drive.update_doc"


def test_executor_passes_mutation_context_to_tool_resolution() -> None:
    query = _query("upsert-new")
    query = query.model_copy(update={
        "generation": query.generation.model_copy(update={
            "mutation": query.generation.mutation.model_copy(update={
                "connector": "drive", "operation": "upsert", "output_format": "gsheet",
            }),
        }),
        "expected_dag": ({"id": "write", "kind": "upsert", "connector": "drive", "entity": "file", "depends_on": []},),
    })
    fixture = QueryFixture(query_id=query.id, input_record_ids={}, destination_record_id=None, overrides=(), expected_side_effects=())
    seen: list[str] = []

    async def invoke(tool_name: str, arguments: Mapping[str, Any]) -> dict[str, object]:
        seen.append(tool_name)
        return {"succeeded": True}

    assert asyncio.run(execute_query(query, fixture, RunnerConfig(), invoke)).completed
    assert seen == ["drive.create_sheet"]
