from __future__ import annotations

import pytest
from pydantic import ValidationError

from worldloom.native_corpus import NativeContent, NativeCorpusPlan
from worldloom.native_tasks import (
    NativeAssertion,
    NativeCitation,
    NativeInput,
    NativeTask,
)
from worldloom.studio.data_creation import (
    DataCreationRequest,
    inspect_simulations,
    propose,
)
from worldloom.studio.models import ProjectSpec, UseCase
from worldloom.studio.native_calibration import NativeCalibrationPlan
from worldloom.studio.service import preset
from worldloom.synthesis import Limits, compile_program, literal, with_parameters


@pytest.fixture
def retail_spec():
    return preset()


@pytest.fixture
def native_spec(retail_spec):
    corpus = NativeCorpusPlan(artifact_id="board-pack", format="docx", title="Board evidence",
        contents=(NativeContent(source_artifact_id="source-one", section_index=0),))
    task = NativeTask(id="read-board", prompt="Read the stated evidence.", use_case_id="operations-review",
        operation="read", inputs=(NativeInput(artifact_id="board-pack", format="docx", path="board.docx"),),
        assertions=(NativeAssertion(id="read", target=NativeCitation(artifact_id="board-pack", locator="paragraph:1")),))
    return ProjectSpec.model_validate({**retail_spec.model_dump(mode="json"),
        "episodes": ["2026-11", "2026-12"], "narration_job": "a" * 32,
        "native_corpus": [corpus.model_dump(mode="json")], "native_tasks": [task.model_dump(mode="json")],
        "native_calibration": NativeCalibrationPlan(cohort="reference").model_dump(mode="json")})


def test_resize_retail_reuses_mechanism_relations_and_parameter_values(retail_spec):
    before = retail_spec.model_dump_json()
    proposal = propose(retail_spec, DataCreationRequest(simulation_target="operations-review", stores=7, products=9, ticks=21))
    program = proposal.spec.use_cases[0].simulation
    assert program is not None
    assert program.parameters == retail_spec.use_cases[0].simulation.parameters
    assert {table.name: table.count for table in program.tables} == {"store": 7, "product": 9, "inventory": 63}
    assert program.tables[-1].relations[0].stride == 9
    assert proposal.summary.simulation.table_rows == {"inventory": 1323, "product": 9, "store": 7}
    assert proposal.summary.simulation.total_rows == compile_program(program).rows == 1339
    assert proposal.summary.simulation.work == compile_program(program).work
    assert proposal.spec.episodes == retail_spec.episodes
    assert proposal.spec.company == retail_spec.company and proposal.spec.seed == retail_spec.seed
    assert retail_spec.model_dump_json() == before


def test_resize_banking_preserves_calibrated_parameters():
    spec = preset("banking", "One Bank")
    program = with_parameters(spec.use_cases[0].simulation, {"payment_pct": 11, "income_shock_pct": 7})
    spec = spec.model_copy(update={"use_cases": (spec.use_cases[0].model_copy(update={"simulation": program}),)})
    proposal = propose(spec, DataCreationRequest(simulation_target="operations-review", borrowers=57, ticks=18))
    resized = proposal.spec.use_cases[0].simulation
    assert resized.parameters == program.parameters
    assert proposal.summary.simulation.dimensions == {"borrowers": 57, "ticks": 18}
    assert proposal.summary.simulation.total_rows == 57 * 19


def test_resize_connected_process_keeps_scopes_start_case_cap_and_parameters():
    spec = preset("retail-connected")
    proposal = propose(spec, DataCreationRequest(simulation_target="retail_process", products=8, ticks=36))
    assert proposal.spec.retail_process.scopes == spec.retail_process.scopes
    assert proposal.spec.retail_process.start == spec.retail_process.start
    assert proposal.spec.retail_process.max_cases == spec.retail_process.max_cases
    assert proposal.spec.retail_process.program.parameters == spec.retail_process.program.parameters
    assert proposal.summary.simulation.table_rows == {"inventory": 864, "product": 8, "store": 3, "supplier": 8}
    assert proposal.summary.simulation.limits.max_rows == 100_000
    assert any("max_cases=48" in item for item in proposal.summary.limitations)


def test_history_replacement_requires_explicit_acknowledgement(native_spec):
    with pytest.raises(ValueError, match="acknowledge_invalidation"):
        propose(native_spec, DataCreationRequest(start_period="2026-11", periods=4))


def test_even_first_history_requires_explicit_acknowledgement(retail_spec):
    with pytest.raises(ValueError, match="acknowledge_invalidation"):
        propose(retail_spec, DataCreationRequest(start_period="2026-11", periods=4))


def test_history_replacement_invalidates_all_native_contracts(native_spec):
    before = native_spec.model_dump_json()
    proposal = propose(native_spec, DataCreationRequest(start_period="2026-11", periods=4, acknowledge_invalidation=True))
    assert proposal.spec.episodes == ("2026-11", "2026-12", "2027-01", "2027-02")
    assert proposal.summary.history.before == native_spec.episodes
    assert proposal.summary.history.after == proposal.spec.episodes
    assert proposal.summary.history.changed
    assert proposal.summary.invalidated.model_dump() == {
        "narration_job": 1, "native_corpus": 1, "native_tasks": 1, "native_calibration": 1}
    assert proposal.spec.narration_job is None and proposal.spec.native_calibration is None
    assert not proposal.spec.native_corpus and not proposal.spec.native_tasks
    assert proposal.spec.company == native_spec.company and proposal.spec.seed == native_spec.seed
    assert proposal.spec.use_cases == native_spec.use_cases
    assert native_spec.model_dump_json() == before


def test_unchanged_history_and_simulation_preserve_native_contracts(native_spec):
    proposal = propose(native_spec, DataCreationRequest(start_period="2026-11", periods=2,
        simulation_target="operations-review", stores=6))
    assert not proposal.summary.history.changed
    assert proposal.summary.invalidated.model_dump() == dict.fromkeys(
        ("narration_job", "native_corpus", "native_tasks", "native_calibration"), 0)
    assert proposal.spec.native_corpus == native_spec.native_corpus
    assert proposal.spec.native_tasks == native_spec.native_tasks
    assert proposal.spec.native_calibration == native_spec.native_calibration
    assert proposal.spec.narration_job == native_spec.narration_job


def test_query_requests_are_not_claimed_as_generated_evals(retail_spec):
    proposal = propose(retail_spec, DataCreationRequest(query_counts={"operations-review": 100_000}))
    assert proposal.spec.use_cases[0].count == 100_000
    assert proposal.summary.requested_queries == {"operations-review": 100_000}
    assert proposal.summary.requested_query_total == 100_000
    assert proposal.summary.simulation is None
    assert any("not measured qualified queries or independent evidence" in item for item in proposal.summary.limitations)
    assert proposal.spec.model_dump(exclude={"use_cases"}) == retail_spec.model_dump(exclude={"use_cases"})


def test_unknown_query_target_refused(retail_spec):
    with pytest.raises(ValueError, match="unknown use cases"):
        propose(retail_spec, DataCreationRequest(query_counts={"missing": 3}))


@pytest.mark.parametrize("target", ["native-review", "draft-review"])
def test_native_only_and_draft_cases_do_not_count_as_connector_demand(native_spec, target):
    native_case = UseCase(id="native-review", title="Read board evidence", objective="Read the board pack", count=777)
    draft_case = UseCase(id="draft-review", title="Unspecified review", objective="Still interviewing", count=9999)
    spec = ProjectSpec.model_validate({**native_spec.model_dump(mode="json"),
        "use_cases": [case.model_dump(mode="json") for case in (*native_spec.use_cases, native_case, draft_case)],
        "native_tasks": [native_spec.native_tasks[0].model_copy(update={"use_case_id": native_case.id}).model_dump(mode="json")]})
    with pytest.raises(ValueError, match="query_counts requires executable connector scenarios"):
        propose(spec, DataCreationRequest(query_counts={target: 100_000}))
    proposal = propose(spec, DataCreationRequest())
    assert proposal.spec == spec
    assert proposal.summary.requested_queries == {"operations-review": 24}
    assert proposal.summary.requested_query_total == 24
    native_only = spec.model_copy(update={"use_cases": (native_case, draft_case)})
    native_proposal = propose(native_only, DataCreationRequest())
    assert native_proposal.summary.requested_queries == {}
    assert native_proposal.summary.requested_query_total == 0
    assert len(native_proposal.spec.native_tasks) == 1


@pytest.mark.parametrize("request_data", [
    {"start_period": "2026-03"}, {"periods": 4}, {"start_period": "2026-13", "periods": 2},
    {"start_period": "9999-12", "periods": 2}, {"start_period": "2026-03", "periods": 121},
    {"start_period": "2026-03", "periods": True}, {"stores": 3},
    {"simulation_target": "operations-review"}, {"simulation_target": "operations-review", "stores": 0},
    {"simulation_target": "operations-review", "stores": True},
    {"simulation_target": "operations-review", "ticks": 10_001},
    {"query_counts": {"operations-review": 100_001}}, {"query_counts": {"operations-review": True}},
    {"query_counts": {"operations-review": 0}}, {"acknowledge_invalidation": "true"},
])
def test_invalid_requests_refused(request_data):
    with pytest.raises(ValidationError):
        DataCreationRequest.model_validate(request_data)


@pytest.mark.parametrize("target", ["missing", "retail_process"])
def test_missing_simulation_target_refused(retail_spec, target):
    with pytest.raises(ValueError, match=r"(existing simulation|no connected)"):
        propose(retail_spec, DataCreationRequest(simulation_target=target, ticks=24))


@pytest.mark.parametrize("connected", [False, True])
def test_reserved_simulation_target_collision_is_visible_and_never_mutated(retail_spec, connected):
    spec = preset("retail-connected") if connected else retail_spec
    collision = retail_spec.use_cases[0].model_copy(update={"id": "retail_process"})
    spec = spec.model_copy(update={"use_cases": (*spec.use_cases, collision)})
    before = spec.model_dump_json()
    with pytest.raises(ValueError, match=r"ambiguous.*reserved connected-process target"):
        propose(spec, DataCreationRequest(simulation_target="retail_process", ticks=30))
    assert spec.model_dump_json() == before
    inspections = [item for item in inspect_simulations(spec) if item.target == "retail_process"]
    assert len(inspections) == (2 if connected else 1)
    assert all(not item.supported and "reserved connected-process target" in item.reason for item in inspections)
    # The same ID remains unambiguous for an ordinary use-case query quota.
    proposal = propose(spec, DataCreationRequest(query_counts={"retail_process": 60}))
    assert proposal.spec.retail_process == spec.retail_process
    assert proposal.summary.requested_queries["retail_process"] == 60


def test_dimensions_must_match_selected_mechanism(retail_spec):
    with pytest.raises(ValueError, match="unsupported dimensions"):
        propose(retail_spec, DataCreationRequest(simulation_target="operations-review", borrowers=5))


@pytest.mark.parametrize("engine,target,dimensions", [
    ("retail", "operations-review", {"stores": 1000, "products": 1000, "ticks": 1000}),
    ("banking", "operations-review", {"borrowers": 100_000, "ticks": 100}),
    ("retail-connected", "retail_process", {"stores": 100, "products": 100, "ticks": 20}),
])
def test_execution_row_limits_apply_before_generation(engine, target, dimensions):
    with pytest.raises(ValueError, match="row_budget"):
        propose(preset(engine), DataCreationRequest(simulation_target=target, **dimensions))


def test_execution_work_limits_apply_before_generation(retail_spec, monkeypatch):
    # The current small mechanisms hit their row limit first. A stricter caller
    # budget still must reach the compiler's work guard, not a hand-written row check.
    monkeypatch.setattr("worldloom.studio.data_creation._limits", lambda target: Limits(max_work=1000))
    with pytest.raises(ValueError, match="work_budget"):
        propose(retail_spec, DataCreationRequest(simulation_target="operations-review", stores=4))


@pytest.mark.parametrize("customization", ["expression", "constraint", "parameter_bounds", "parameter_name", "namespace"])
def test_custom_programs_are_never_overwritten(retail_spec, customization):
    program = retail_spec.use_cases[0].simulation
    document = program.model_dump(mode="json")
    if customization == "expression":
        document["tables"][0]["columns"][0]["expression"] = literal(110).model_dump(mode="json")
    elif customization == "constraint":
        document["tables"][-1]["constraints"] = []
    elif customization == "parameter_bounds":
        document["parameters"][0]["maximum"] = 250
    elif customization == "parameter_name":
        document["parameters"].append({"name": "custom", "value": 1, "minimum": 1, "maximum": 2, "mutable": True})
    else:
        document["namespace"] = "bespoke_inventory"
    custom = program.model_validate(document)
    spec = retail_spec.model_copy(update={"use_cases": (retail_spec.use_cases[0].model_copy(update={"simulation": custom}),)})
    before = spec.model_dump_json()
    with pytest.raises(ValueError, match="custom simulation"):
        propose(spec, DataCreationRequest(simulation_target="operations-review", stores=10))
    assert spec.model_dump_json() == before
    report = inspect_simulations(spec)[0]
    assert not report.supported and "custom simulation" in report.reason
    assert report.total_rows == compile_program(custom).rows
    # It remains legal to adjust unrelated query obligations on a custom program.
    assert propose(spec, DataCreationRequest(query_counts={"operations-review": 50})).spec.use_cases[0].simulation == custom


def test_inspection_exposes_exact_current_dimensions_and_compiler_rows(retail_spec):
    summaries = inspect_simulations(retail_spec)
    assert len(summaries) == 1
    report = summaries[0]
    assert report.target == "operations-review" and report.supported and report.reason is None
    assert report.dimensions == {"stores": 3, "products": 6, "ticks": 24}
    assert report.total_rows == 441
    assert report.model_dump(mode="json")["table_rows"] == {"inventory": 432, "product": 6, "store": 3}


def test_proposal_is_deterministic_no_world_or_simulation_execution(retail_spec, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("sizing must not generate data")

    monkeypatch.setattr("worldloom.studio.service.Studio.snapshot", forbidden)
    monkeypatch.setattr("worldloom.synthesis.engine.Simulator.rows", forbidden)
    request = DataCreationRequest(start_period="2026-03", periods=12, acknowledge_invalidation=True,
        simulation_target="operations-review", products=10, query_counts={"operations-review": 300})
    first = propose(retail_spec, request)
    assert first.model_dump_json() == propose(retail_spec, request).model_dump_json()
    with pytest.raises(ValidationError, match="frozen"):
        first.spec.seed = 42


def test_noop_proposal_preserves_every_contract(native_spec):
    proposal = propose(native_spec, DataCreationRequest())
    assert proposal.spec == native_spec
    assert proposal.summary.requested_query_total == sum(case.count for case in native_spec.use_cases)


def test_model_copy_cannot_bypass_request_validation(retail_spec):
    request = DataCreationRequest().model_copy(update={"query_counts": {"operations-review": -1}})
    with pytest.raises(ValidationError):
        propose(retail_spec, request)
