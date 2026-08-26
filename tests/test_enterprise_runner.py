from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from worldloom.enterprise_corpus import QueryFixture
from worldloom.enterprise_queries import (
    GenerationRequirement,
    MutationRequirement,
    PlannedEnterpriseQuery,
)
from worldloom.enterprise_runner import (
    RunnerConfig,
    ToolBinding,
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
