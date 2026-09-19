"""The enterprise eval loop, end to end, through the commands a user runs.

No test invoked any `enterprise-evals` command before this file, which is how
the loop came to be shipped unable to execute a single query it planned. The
unit tests passed throughout: every piece worked, and nothing checked that the
pieces reached each other.

So this asserts every row reaches completion or its exact designed failure point. `completed` is the count
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

import hashlib
import json
import time
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


def _build(tmp_path: Path, *, shapes: list[str]) -> Path:
    """Build the fixture corpus through the CLI, on a named shape selection."""
    # This positive demand uses evidence actually present in the golden world.
    # The historical broader demand remains unchanged and must fail validation
    # in the dedicated missing-evidence test below.
    workflow = dict(PROFILE["additional_workflows"][0])
    workflow["sources"] = [
        {"connector": "servicenow", "entities": ["incident"]},
        {"connector": "jira", "entities": ["issue"]},
    ]
    out = tmp_path / "corpus"
    shape_args = [arg for shape in shapes for arg in ("--dag-shape", shape)]
    result = RUNNER.invoke(
        app,
        [
            "enterprise-evals", "build", "examples/retail-close", str(out),
            "--profile", str(_profile(tmp_path, additional_workflows=[workflow])), "--limit", "12",
            *shape_args,
        ],
    )
    assert result.exit_code == 0, result.output
    return out


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """What a user gets: the default shape set, every groundable shape."""
    return _build(tmp_path_factory.mktemp("enterprise-evals"), shapes=[])


@pytest.fixture(scope="module")
def built_legacy(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The single-write trajectory, which `--dag-shape none` still plans."""
    return _build(tmp_path_factory.mktemp("enterprise-evals-legacy"), shapes=["none"])


def test_build_plans_and_materialises(built: Path) -> None:
    report = json.loads(built.parent.joinpath("corpus", "manifest.json").read_text())
    assert (built / "queries.jsonl").is_file()
    assert (built / "fixtures.jsonl").is_file()
    assert report


def test_the_corpus_validates(built: Path) -> None:
    result = RUNNER.invoke(app, ["enterprise-evals", "validate", str(built)])
    assert result.exit_code == 0, result.output
    assert "valid" in result.output


def _simulate(corpus: Path) -> dict:
    result = RUNNER.invoke(app, ["enterprise-evals", "simulate", str(corpus)])
    assert result.exit_code == 0, result.output
    return json.loads(result.output.strip().splitlines()[-1])


def _designed(corpus: Path) -> int:
    from worldloom.enterprise_io import load_exported_corpus

    queries = load_exported_corpus(corpus).queries
    designed = sum(query.dimensions.get("failure") == "permission_denied" for query in queries)
    assert designed, "this fixture must exercise an actual injected denial"
    return designed


def test_every_planned_query_executes(built: Path) -> None:
    """The number this file exists for, on the corpus a default build makes.

    Completion and the declared write denials partition the entire corpus.
    Neither a missing source nor harness breakage may enter the denial count.
    """
    report = _simulate(built)
    assert report["queries"] == 12
    designed = _designed(built)
    assert report["completed"] == 12 - designed
    assert report["blocked_at_designed_write"] == designed
    assert report["stopped_before_failure_point"] == 0
    assert report["raised"] == 0
    # A grammar row is graded on its assertions, never on the legacy weighted
    # score: the two have different denominators, so `simulate` leaves the
    # average unset rather than mixing them.
    assert report["average_dag_score"] is None
    assert report["assertion_passed"] == 12 and report["assertion_failed"] == 0
    blocked = [item for item in report["results"] if item["outcome"] == "blocked_at_designed_write"]
    # The write node's *name* varies with the shape now that every shape is
    # planned by default: `conditional` writes through `write-primary` and
    # `write-fallback`. What must hold is that the denial landed on a write and
    # was the designed one, not which branch of which shape carried it.
    assert blocked
    assert all(
        item["finding"].startswith("node write") and item["finding"].endswith("failed: denied")
        for item in blocked
    ), sorted({item["finding"] for item in blocked})


def test_the_legacy_trajectory_still_executes_and_scores(built_legacy: Path) -> None:
    """`--dag-shape none` is the trajectory every build planned before shapes."""
    report = _simulate(built_legacy)
    assert report["queries"] == 12
    designed = _designed(built_legacy)
    assert report["completed"] == 12 - designed
    assert report["blocked_at_designed_write"] == designed
    assert report["stopped_before_failure_point"] == 0
    assert report["raised"] == 0
    assert all(item["finding"] == "node write failed"
               for item in report["results"] if item["outcome"] == "blocked_at_designed_write")
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


def test_build_refuses_original_profile_whose_change_evidence_is_only_a_placeholder(tmp_path: Path) -> None:
    result = RUNNER.invoke(app, [
        "enterprise-evals", "build", "examples/retail-close", str(tmp_path / "out"),
        "--profile", str(_profile(tmp_path)), "--limit", "12",
    ])
    assert result.exit_code == 1, result.output
    assert "carries no fact (servicenow:change_request)" in result.output
    assert not (tmp_path / "out" / "manifest.json").exists()


SHIPPED_RETAIL_PROFILE = Path("examples/enterprise-evals/omnichannel-retailer.json")

#: SHA-256 of the 312 rows the narrowed retail profile below plans for
#: `examples/hospital`, captured from the code at 8884546, before the cover
#: could stop at saturation. The walk is the same walk stopped early, so the
#: bytes must not move.
NARROWED_PLAN_DIGEST = "d32f9fe1eed6ffd8b5528baa8c642c2632a5f6d988017605414879345d735194"


def _narrowed_retail_profile(path: Path) -> Path:
    """The hand-narrowed profile that completed before anything shipped did:
    one workflow, three connectors, two failures, 73,600 candidates."""
    data = json.loads(SHIPPED_RETAIL_PROFILE.read_text(encoding="utf-8"))
    data.update(
        workflows=["executive_digest"], additional_workflows=[],
        connectors=["jira", "confluence", "email"],
        coverage={
            "name": "narrow", "strengths": 2, "connector_counts": [1, 2],
            "failures": ["none", "permission_denied"], "max_candidates": 10_000_000,
        },
    )
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_plan_with_a_shipped_profile_and_a_limit_returns_in_seconds(tmp_path: Path) -> None:
    """Killed at fifteen minutes with nothing written while the limit only
    cut the cover's output; under seven seconds once it capped the walk."""
    out = tmp_path / "plan.jsonl"
    started = time.perf_counter()
    result = RUNNER.invoke(app, [
        "enterprise-evals", "plan", "examples/hospital", str(out),
        "--profile", str(SHIPPED_RETAIL_PROFILE), "--limit", "40",
    ])
    elapsed = time.perf_counter() - started
    assert result.exit_code == 0, result.output
    assert elapsed < 60, elapsed
    assert len(out.read_text(encoding="utf-8").splitlines()) == 40
    summary = json.loads(result.output)
    assert summary["selected"] == 40
    assert summary["truncated"] is True and summary["exact"] is True
    assert summary["hole_count"] == summary["required_interactions"] - summary["covered_interactions"] > 0
    assert "holes" not in summary and len(summary["hole_examples"]) == 8


def test_a_narrowed_profile_plans_the_same_bytes_as_before(tmp_path: Path) -> None:
    out = tmp_path / "plan.jsonl"
    result = RUNNER.invoke(app, [
        "enterprise-evals", "plan", "examples/hospital", str(out),
        "--profile", str(_narrowed_retail_profile(tmp_path / "narrow.json")),
    ])
    assert result.exit_code == 0, result.output
    assert hashlib.sha256(out.read_bytes()).hexdigest() == NARROWED_PLAN_DIGEST
    summary = json.loads(result.output)
    assert summary["selected"] == 312
    assert summary["truncated"] is False and summary["exact"] is True
    assert summary["required_interactions"] == summary["covered_interactions"] == 1307
    assert summary["hole_count"] == 0
