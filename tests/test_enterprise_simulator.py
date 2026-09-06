from __future__ import annotations

import asyncio

import pytest

from worldloom.connector_data import ConnectorDataset
from worldloom.enterprise_artifacts import render_corpus_artifacts
from worldloom.enterprise_corpus import EnterpriseCorpus, QueryFixture, StateOverride
from worldloom.enterprise_queries import (
    ArtifactRequirement,
    GenerationRequirement,
    MutationRequirement,
    PlannedEnterpriseQuery,
)
from worldloom.enterprise_runner import RunnerConfig, execute_query
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
            artifact=ArtifactRequirement(
                format="docx", sections=("Summary", "Sources")
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


def test_simulator_compatibility_name_uses_product_shaped_runtime() -> None:
    corpus, fixture = _corpus()
    simulator = ConnectorSimulator(corpus)
    result = asyncio.run(
        execute_query(corpus.queries[0], fixture, RunnerConfig(), simulator.invoke)
    )

    assert result.completed
    assert len(simulator.records) == 1
    assert result.calls[-1].record_id == result.calls[0].record_id
    write_payload = result.outputs["write"]["payload"]
    assert write_payload["name"].endswith("query-none")
    assert "webUrl" in write_payload


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        ("permission_denied", 403),
        ("version_conflict", 409),
        ("partial_write", 207),
    ],
)
def test_simulator_compiles_failure_overlays_into_emulator_faults(
    failure: str, status: int
) -> None:
    corpus, fixture = _corpus(failure)
    simulator = ConnectorSimulator(corpus)
    result = asyncio.run(
        execute_query(corpus.queries[0], fixture, RunnerConfig(), simulator.invoke)
    )

    assert not result.completed
    assert result.finding == "node write failed"
    assert not result.calls[0].succeeded
    assert result.outputs["write"]["status"] == status


def test_renderer_writes_real_docx(tmp_path) -> None:  # type: ignore[no-untyped-def]
    corpus, _ = _corpus()
    rendered = render_corpus_artifacts(corpus, tmp_path, limit=1)
    assert len(rendered) == 1
    path = tmp_path / f"{corpus.queries[0].id}.docx"
    assert path.read_bytes().startswith(b"PK")
