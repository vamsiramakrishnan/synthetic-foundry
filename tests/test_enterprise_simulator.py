from __future__ import annotations

import asyncio

from worldloom.connector_data import ConnectorDataset
from worldloom.enterprise_corpus import EnterpriseCorpus, QueryFixture, StateOverride
from worldloom.enterprise_queries import (
    GenerationRequirement,
    MutationRequirement,
    PlannedEnterpriseQuery,
)
from worldloom.enterprise_runner import RunnerConfig, ToolBinding, execute_query
from worldloom.enterprise_simulator import ConnectorSimulator


def _corpus(failure: str = "none") -> tuple[EnterpriseCorpus, QueryFixture]:
    query = PlannedEnterpriseQuery(
        id=f"query-{failure}",
        workflow="render-test",
        query="Create the operating report in SharePoint and verify it.",
        dimensions={"failure": failure},
        generation=GenerationRequirement(
            process="delivery_work",
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
    overrides: tuple[StateOverride, ...] = ()
    if failure != "none":
        overrides = (
            StateOverride(kind=failure, connector="sharepoint", details={}),
        )
    fixture = QueryFixture(
        query_id=query.id,
        input_record_ids={},
        destination_record_id=None,
        overrides=overrides,
        expected_side_effects=(),
    )
    return (
        EnterpriseCorpus(
            queries=(query,),
            connector_data=ConnectorDataset(capabilities=[], records=[]),
            fixtures=(fixture,),
        ),
        fixture,
    )


def _config() -> RunnerConfig:
    return RunnerConfig(
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


def test_simulator_creates_and_reads_back() -> None:
    corpus, fixture = _corpus()
    simulator = ConnectorSimulator(corpus)
    result = asyncio.run(
        execute_query(
            corpus.queries[0], fixture, _config(), simulator.invoke
        )
    )
    assert result.completed
    assert len(simulator.records) == 1
    assert result.calls[-1].record_id == result.calls[0].record_id


def test_simulator_executes_version_conflict() -> None:
    corpus, fixture = _corpus("version_conflict")
    simulator = ConnectorSimulator(corpus)
    result = asyncio.run(
        execute_query(
            corpus.queries[0], fixture, _config(), simulator.invoke
        )
    )
    assert not result.completed
    assert result.finding == "node write failed"
    assert not result.calls[0].succeeded
