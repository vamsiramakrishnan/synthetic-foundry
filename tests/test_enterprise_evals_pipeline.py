"""The enterprise eval loop, end to end, through the commands a user runs.

No test invoked any `enterprise-evals` command before this file, which is how
the loop came to be shipped unable to execute a single query it planned. The
unit tests passed throughout: every piece worked, and nothing checked that the
pieces reached each other.

So this asserts the number that says the loop works. `completed` is the count
of planned DAGs the simulator drove to their last node, and it was `0` out of
`12` on a corpus this same file builds. Three defects held it there, each in a
different module and each invisible to the others:

- `_target_id` handed a source read the *destination* record id, because it
  chose by fixture field rather than by the connector and entity the node
  addresses, so every `read-0` 404'd;
- the `simulate` command manufactured a `ToolBinding` per DAG triple, and since
  `RunnerConfig.resolve` consults bindings before the connector definition, the
  synthesised `sharepoint.readback` beat the definition lookup that normalises
  `readback` to `read`;
- `_op_get` resolved entity aliases in one direction only, so a record stored
  as `file` was invisible to the `docx` tool that should have read it.

A test that only asserted `completed > 0` would have passed with two of the
three still broken (they were worth 3 and 6 of 12 on the way up), so the
assertion here is the exact count.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom.cli import app

RUNNER = CliRunner()

#: A selection that exercises both a multi-member entity alias on the source
#: side (`jira/issue`) and one on the destination side (`sharepoint/file`),
#: because those were two of the three defects. Kept small on purpose: 5,120
#: candidates cover in well under a second.
PROFILE = {
    "name": "snow-to-sharepoint",
    "industry": "retail",
    "company_description": "Retail operations close.",
    "connectors": ["servicenow", "jira", "sharepoint"],
    "workflows": ["change_assurance"],
    "additional_workflows": [
        {
            "name": "change_assurance",
            "purpose": "change assurance pack",
            "process": "service_management",
            "sources": [
                {"connector": "servicenow", "entities": ["change_request", "incident"]},
                {"connector": "jira", "entities": ["issue"]},
            ],
            "destinations": [
                {
                    "connector": "sharepoint",
                    "entities": ["file"],
                    "operations": ["create", "update"],
                    "formats": ["xlsx", "docx"],
                }
            ],
            "content_actions": ["extract", "reconcile", "generate", "render"],
            "audiences": ["executive", "manager", "analyst", "operations"],
            "prompt_template": (
                "Prepare the {period} {purpose} for {company}'s {audience} audience."
                " Use {sources}. {action_instruction} {output_label} in {destination}."
                " Reconcile records by stable identifiers, preserve source links and"
                " manually entered content, then {verification_instruction}."
                "{failure_instruction}"
            ),
        }
    ],
    "coverage": {
        "name": "narrow",
        "strengths": 2,
        "connector_counts": [1, 2],
        "failures": ["none", "permission_denied"],
        "max_candidates": 10_000_000,
    },
}


def _profile(tmp_path: Path, **overrides: object) -> Path:
    payload = {**PROFILE, **overrides}
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(payload), encoding="utf-8", newline="\n")
    return path


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A corpus built through the CLI, shared by the assertions below."""
    tmp_path = tmp_path_factory.mktemp("enterprise-evals")
    out = tmp_path / "corpus"
    result = RUNNER.invoke(
        app,
        [
            "enterprise-evals", "build", "examples/retail-close", str(out),
            "--profile", str(_profile(tmp_path)), "--limit", "12",
        ],
    )
    assert result.exit_code == 0, result.output
    return out


def test_build_plans_and_materialises(built: Path) -> None:
    report = json.loads(built.parent.joinpath("corpus", "manifest.json").read_text())
    assert (built / "queries.jsonl").is_file()
    assert (built / "fixtures.jsonl").is_file()
    assert report


def test_the_corpus_validates(built: Path) -> None:
    result = RUNNER.invoke(app, ["enterprise-evals", "validate", str(built)])
    assert result.exit_code == 0, result.output
    assert "valid" in result.output


def test_every_planned_query_executes(built: Path) -> None:
    """The number this file exists for.

    `completed` was 0/12 as shipped, 3/12 with one fix, 6/12 with two. The exact
    count is asserted so a partial regression cannot pass.
    """
    result = RUNNER.invoke(app, ["enterprise-evals", "simulate", str(built)])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output.strip().splitlines()[-1])
    assert report["queries"] == 12
    assert report["completed"] == 12, f"only {report['completed']}/12 executed"
    assert report["blocked_by_injected_failure"] == 0
    assert report["average_dag_score"] > 0.7


def test_a_write_targets_the_destination_even_when_it_is_also_a_source() -> None:
    """A destination is sometimes also a source, and the write must not drift.

    `customer_health` reads and upserts the same `salesforce/account`, so the
    fixture holds the source record and the destination record under one key.
    Preferring the source unconditionally made the write mutate an input record
    instead of the destination materialised for the mutation, and `verify` then
    followed the same wrong id and reported a clean trajectory over a corrupted
    side effect: a green run that had broken the thing it was measuring.

    Only a node with nothing upstream reads a source. `verify` is a read too,
    but it depends on the write, so it resolves through `dependencies`.
    """
    from worldloom.connectors.enterprise import EnterpriseConnectorRuntime
    from worldloom.enterprise_corpus import QueryFixture

    source, destination = "REC-SOURCE", "REC-DESTINATION"
    fixture = QueryFixture(
        query_id="Q1",
        input_record_ids={"salesforce:account": (source, destination)},
        destination_record_id=destination,
        overrides=(),
        expected_side_effects=(),
    )
    target = EnterpriseConnectorRuntime._target_id
    common = {"connector": "salesforce", "entity": "account"}

    assert target(fixture, {}, **common, prefer_source=True) == source
    assert target(fixture, {}, **common, prefer_source=False) == destination
    assert (
        target(fixture, {"write": {"record_id": destination}}, **common, prefer_source=False)
        == destination
    )


def test_a_mistyped_connector_is_refused_rather_than_silently_empty(
    tmp_path: Path,
) -> None:
    """The failure this surface hides best.

    `connectors: ["sharepont"]` used to behave as a filter matching nothing:
    zero candidates, an empty corpus written, exit 0. A build that tests nothing
    and reports success is worse than one that fails.
    """
    profile = _profile(tmp_path, connectors=["servicenow", "jira", "sharepont"])
    result = RUNNER.invoke(
        app,
        [
            "enterprise-evals", "build", "examples/retail-close",
            str(tmp_path / "out"), "--profile", str(profile), "--limit", "12",
        ],
    )
    assert result.exit_code != 0
    assert "sharepont" in result.output


def test_a_selection_that_admits_no_workflow_is_refused(tmp_path: Path) -> None:
    """Every name resolves and the cross of them still admits nothing.

    The same silent-empty outcome reached a different way: a workflow whose
    destinations all sit outside the chosen connectors is dropped, leaving no
    workflow and, before this, a clean exit.
    """
    profile = _profile(tmp_path, connectors=["servicenow"])
    result = RUNNER.invoke(
        app,
        [
            "enterprise-evals", "build", "examples/retail-close",
            str(tmp_path / "out"), "--profile", str(profile), "--limit", "12",
        ],
    )
    assert result.exit_code != 0
    assert "no workflow survives" in result.output
