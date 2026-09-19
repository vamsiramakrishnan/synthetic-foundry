"""The planner plans only what the world can ground, and the builder selects evidence.

Every shipped world and profile aborted at the last step of
`enterprise-evals build` with `evidence <rid> carries no fact`. Two causes
shared one missing predicate. The builder selected source records by
position, so a pool of thirty-eight issues with one fact-less record put
that record into twenty queries. The planner admitted rows over sources the
world had no records for, the builder minted fact-less fillers to meet the
count, and the validator refused them. `carries_evidence` is the predicate,
the builder selects by it, and the planner reads the world's inventory of
records that satisfy it before it plans a row.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom.cli import app
from worldloom.connector_data import ConnectorRecord
from worldloom.enterprise_corpus import _select_sources, materialize_corpus
from worldloom.enterprise_dag import default_shapes
from worldloom.enterprise_dag_planning import compatible_shapes
from worldloom.enterprise_evidence import _digest, carries_evidence
from worldloom.enterprise_grounding import groundable_inventory
from worldloom.enterprise_queries import (
    _subsets,
    plan_queries,
    required_interactions,
    ungroundable_sources,
    valid_rows,
)
from worldloom.enterprise_specs import (
    ContentAction,
    CoverageProfile,
    DestinationRole,
    Operation,
    SourceRole,
    SpecRegistry,
    WorkflowSpec,
    builtin_registry,
)
from worldloom.world import World

RUNNER = CliRunner()
SCOPE = "operational_simulation_not_macro_reconciliation"


def _record(identifier: str, *, fact_ids: tuple[str, ...] = (), **fields: object) -> ConnectorRecord:
    return ConnectorRecord(id=identifier, connector="jira", entity="issue", external_id=identifier,
                           title=identifier, fields={"key": identifier, **fields}, fact_ids=list(fact_ids))


def _observation_record(identifier: str) -> tuple[ConnectorRecord, str]:
    """A record whose only evidence is a pinned operational observation, and its case id."""
    from worldloom.synthesis.compiler import digest

    subject, tick = "STORE-1/SKU-1", 4
    row_id = "ROW-" + _digest([subject, tick])[:32].upper()
    trigger = {"table": "inventory", "signal": "lost", "title": "Stock availability"}
    provenance = {"recipe_digest": "a" * 64, "program_digest": "b" * 64, "scope": SCOPE,
                  "trigger": trigger, "source_record_ids": [row_id]}
    case = digest(["episode/v1", provenance["recipe_digest"], trigger, row_id])
    return _record(identifier, synthesis_provenance=provenance, subject_entity_id=subject, opened_tick=tick,
                   case_id=case, history=[{"record_id": row_id, "tick": tick, "values": {"lost": 1}, "relations": []}]), case


def test_carries_evidence_is_a_fact_or_a_valid_observation() -> None:
    assert not carries_evidence(_record("plain"))
    assert carries_evidence(_record("fact", fact_ids=("F1",)))
    observed, _ = _observation_record("observed")
    assert carries_evidence(observed)
    # An observation that fails its own contract is not evidence.
    broken = observed.model_copy(update={"fields": {**observed.fields, "opened_tick": 99}})
    assert not carries_evidence(broken)


def test_selection_takes_evidence_first_and_fact_less_records_last() -> None:
    """The fact-less record is first in the pool's own order. It must not be
    chosen while an evidence-bearing record is left, and when the minimum
    exhausts the evidence it is chosen last."""
    factless, first, second = _record("A"), _record("B", fact_ids=("F1",)), _record("C", fact_ids=("F2",))
    pool = [factless, first, second]
    assert _select_sources(pool, 1, ()) == ("B",)
    assert _select_sources(pool, 2, ()) == ("B", "C")
    assert _select_sources(pool, 3, ()) == ("B", "C", "A")
    # Stable: evidence-bearing records keep the pool's order, and repeating
    # the call repeats the answer.
    assert _select_sources([second, factless, first], 2, ()) == ("C", "B")
    assert _select_sources(pool, 3, ()) == _select_sources(list(pool), 3, ())


def test_case_bound_selection_fills_with_evidence_before_fact_less_records() -> None:
    observed, case = _observation_record("C-case")
    pool = [_record("A-factless"), _record("B-fact", fact_ids=("F1",)), observed]
    assert _select_sources(pool, 3, (case,)) == ("C-case", "B-fact", "A-factless")


def test_a_pool_whose_leading_records_all_carry_evidence_selects_what_it_selected_before() -> None:
    pool = [_record("A", fact_ids=("F1",)), _record("B", fact_ids=("F2",)), _record("C")]
    assert _select_sources(pool, 2, ()) == tuple(record.id for record in pool[:2])


def _registry(*sources: SourceRole) -> SpecRegistry:
    builtin = builtin_registry()
    workflow = WorkflowSpec(
        name="grounding_probe", purpose="grounding probe", sources=sources,
        destinations=(DestinationRole(connector="confluence", entities=("page",), operations=(Operation.CREATE,), formats=("markdown",)),),
        content_actions=(ContentAction.SUMMARIZE,), audiences=("analyst",), topologies=("chain",), verification=("readback",),
        prompt_template="Prepare the {purpose} for {company}. Use {sources}. {action_instruction} {output_label} in {destination}. {verification_instruction}.{failure_instruction}",
    )
    return SpecRegistry(builtin.connectors.values(), (workflow,), builtin.processes.values())


PROFILE = CoverageProfile(strengths=2, connector_counts=(1, 2), failures=("none", "permission_denied"))


def test_the_inventory_counts_evidence_bearing_records_per_source() -> None:
    """Measured on `examples/hospital`: ten Jira issues all carrying facts,
    one Salesforce account carrying none, no ServiceNow incidents, and
    messages under the email connector where the roles ask for threads."""
    world = World.load("examples/hospital")
    inventory = groundable_inventory(world, builtin_registry())
    assert inventory[("jira", "issue")] == 10
    assert inventory[("salesforce", "account")] == 0
    assert inventory[("servicenow", "incident")] == 0
    assert inventory[("email", "thread")] == 0
    assert inventory[("sharepoint", "file")] == 4


def test_the_report_names_the_sources_the_world_could_not_ground() -> None:
    world = World.load("examples/hospital")
    registry = _registry(
        SourceRole(connector="jira", entities=("issue",)),
        SourceRole(connector="servicenow", entities=("incident", "change_request")),
        SourceRole(connector="confluence", entities=("page",), minimum=5),
    )
    queries, report = plan_queries(world, registry=registry, profile=PROFILE)
    planned = tuple(queries)
    assert report is not None
    # Incidents: no records. Five pages: the world has four.
    assert report.ungroundable_sources == ("confluence:page", "servicenow:incident")
    assert planned
    assert all("servicenow:incident" not in query.dimensions["source_entities"]
               and "confluence:page" not in query.dimensions["source_entities"] for query in planned)
    assert report.exact and report.complete
    # The candidate space is smaller than the world-free one `space` counts.
    world_free = sum(1 for _ in valid_rows(registry, PROFILE))
    assert report.candidates < world_free


@pytest.mark.parametrize("shapes", [(), default_shapes()])
def test_the_required_set_over_the_groundable_space_is_exact(shapes: tuple[str, ...]) -> None:
    world = World.load("examples/hospital")
    registry = _registry(
        SourceRole(connector="jira", entities=("issue",)),
        SourceRole(connector="servicenow", entities=("incident", "change_request")),
    )
    inventory = groundable_inventory(world, registry)
    rows = list(valid_rows(registry, PROFILE, inventory=inventory))
    if shapes:
        rows = [{**row, "dag_shape": shape} for row in rows for shape in compatible_shapes(row, shapes, inventory=inventory)]
    enumerated = {interaction for row in rows for interaction in _subsets(row, 2)}
    assert required_interactions(registry, PROFILE, 2, shapes, inventory=inventory) == enumerated
    assert ungroundable_sources(registry, inventory) == ("servicenow:incident",)
    assert ungroundable_sources(registry, None) == ()


def test_shapes_that_demand_two_witnesses_are_not_decided_for_a_one_record_source() -> None:
    row = {"source_entities": "jira:issue", "operation": "create", "output_format": "markdown",
           "failure": "none", "destination": "confluence", "destination_entity": "page"}
    one = {("jira", "issue"): 1}
    two = {("jira", "issue"): 2}
    assert "map_read" not in compatible_shapes(row, ("*",), inventory=one)
    assert "conditional" not in compatible_shapes(row, ("*",), inventory=one)
    assert "fan_in" in compatible_shapes(row, ("*",), inventory=one)
    assert {"map_read", "conditional"} <= set(compatible_shapes(row, ("*",), inventory=two))
    assert compatible_shapes(row, ("*",)) == compatible_shapes(row, ("*",), inventory=two)


def test_a_world_that_grounds_no_row_is_refused_by_name() -> None:
    world = World.load("examples/hospital")
    registry = _registry(SourceRole(connector="servicenow", entities=("incident",)))
    with pytest.raises(ValueError, match=r"ungroundable_world: .*servicenow:incident"):
        plan_queries(world, registry=registry, profile=PROFILE)


def test_the_filler_is_a_tripwire_and_destination_fixtures_are_untouched() -> None:
    world = World.load("examples/hospital")
    registry = _registry(SourceRole(connector="jira", entities=("issue",)))
    queries, _ = plan_queries(world, registry=registry, profile=PROFILE, strategy="exhaustive", limit=1)
    query = next(iter(queries))
    source = query.generation.source_requirements[0].model_copy(update={"connector": "servicenow", "entity": "incident"})
    ungrounded = query.model_copy(update={"generation": query.generation.model_copy(update={"source_requirements": (source,)})})
    with pytest.raises(ValueError, match=rf"ungroundable_source: query {query.id} needs 1 servicenow:incident record\(s\)"):
        materialize_corpus(world, (ungrounded,))
    # A record-addressed write still gets the destination fixture it always had.
    mutation = query.generation.mutation.model_copy(update={"operation": "update", "preexisting_record": True})
    addressed = query.model_copy(update={"generation": query.generation.model_copy(update={"mutation": mutation})})
    corpus = materialize_corpus(world, (addressed,))
    destination = corpus.fixtures[0].destination_record_id
    assert destination is not None
    assert any(record.id == destination and record.fields.get("manual_content") for record in corpus.connector_data.records)


def test_the_documented_loop_builds_the_default_profile_on_the_hospital_world(tmp_path: Path) -> None:
    """`enterprise-evals build examples/hospital <out> --limit N --dag-shape '*'`
    is the first command of the evalrun skill. It exited 1 at validate on
    every shipped world and profile."""
    out = tmp_path / "cases"
    result = RUNNER.invoke(app, ["enterprise-evals", "build", "examples/hospital", str(out), "--limit", "12", "--dag-shape", "*"])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["queries"] == 12 and summary["records"] > 0
    assert (out / "manifest.json").exists()
    assert "servicenow:incident" in summary["coverage"]["ungroundable_sources"]
    assert summary["coverage"]["exact"] is True
    rows = [json.loads(line) for line in (out / "queries.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 12
    named = set(summary["coverage"]["ungroundable_sources"])
    assert all(source not in named for row in rows for source in row["dimensions"]["source_entities"].split("+"))


def test_the_cli_refuses_a_profile_the_world_grounds_nothing_of(tmp_path: Path) -> None:
    profile = {
        "name": "incidents-only", "industry": "retail", "company_description": "Incidents.",
        "connectors": ["servicenow", "confluence"], "workflows": ["incident_pack"],
        "additional_workflows": [{
            "name": "incident_pack", "purpose": "incident pack", "process": "service_management",
            "sources": [{"connector": "servicenow", "entities": ["incident"]}],
            "destinations": [{"connector": "confluence", "entities": ["page"], "operations": ["create"], "formats": ["markdown"]}],
            "content_actions": ["summarize"], "audiences": ["analyst"],
            "prompt_template": "Prepare {purpose} for {audience}. Use {sources}. {failure_instruction}",
        }],
    }
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    result = RUNNER.invoke(app, ["enterprise-evals", "build", "examples/hospital", str(tmp_path / "out"),
                                 "--profile", str(path), "--limit", "4"])
    assert result.exit_code == 2, result.output
    assert "ungroundable_world" in result.output and "servicenow:incident" in result.output
    assert not (tmp_path / "out").exists()
