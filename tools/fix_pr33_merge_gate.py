#!/usr/bin/env python3
"""Apply the semantic merge-gate fixes from PR #33 review.

This file is intentionally one-shot. The companion workflow deletes it after the
focused and full regression gates pass, leaving only the reviewed implementation
and tests on the branch.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rewrite(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"expected merge-gate anchor missing in {path}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Candidate requirements must inspect connector payload fields, not just the
# projection envelope.
rewrite(
    "src/worldloom/eval_candidates.py",
    '''def _model_record(item: Any) -> dict[str, Any]:\n    if hasattr(item, "model_dump"):\n        return item.model_dump(mode="json")\n    return vars(item)\n\n\ndef _artifact_records''',
    '''def _model_record(item: Any) -> dict[str, Any]:\n    if hasattr(item, "model_dump"):\n        return item.model_dump(mode="json")\n    return vars(item)\n\n\ndef _predicate_record(item: Any) -> dict[str, Any]:\n    """Flatten connector payload fields without letting them shadow the envelope."""\n\n    record = item if isinstance(item, Mapping) else _model_record(item)\n    nested = record.get("fields")\n    if not isinstance(nested, Mapping):\n        return dict(record)\n    flattened = dict(nested)\n    flattened.update(record)\n    return flattened\n\n\ndef _artifact_records''',
)
rewrite(
    "src/worldloom/eval_candidates.py",
    '''    for item in records:\n        record = item if isinstance(item, Mapping) else _model_record(item)\n        if evaluate(predicate, record):''',
    '''    for item in records:\n        record = _predicate_record(item)\n        if evaluate(predicate, record):''',
)

# Relation requirements use the same predicate evaluator as every other
# requirement. edge_kind is a compatibility alias for the graph model's kind.
rewrite(
    "src/worldloom/eval_candidates.py",
    '''    edge_kind = requirement.selector.get("edge_kind")\n    edges = [\n        edge\n        for edge in realism.graph.edges\n        if edge_kind is None or edge.kind == edge_kind\n    ]''',
    '''    selector = dict(requirement.selector)\n    edge_kind = selector.pop("edge_kind", None)\n    if edge_kind is not None:\n        selector["kind"] = edge_kind\n    predicate = _selector_predicate(selector)\n    edges = [\n        edge\n        for edge in realism.graph.edges\n        if evaluate(predicate, _model_record(edge))\n    ]''',
)

# Eval-specific counts can never waive the world's own coherence invariants.
rewrite(
    "src/worldloom/eval_candidates.py",
    '''    hard = {requirement.id: requirement.hard for requirement in plan.requirements}\n    accepted = all(check.satisfied or not hard[check.requirement_id] for check in checks)''',
    '''    hard = {requirement.id: requirement.hard for requirement in plan.requirements}\n    coherence = world.validate()\n    accepted = coherence.ok and all(\n        check.satisfied or not hard[check.requirement_id] for check in checks\n    )''',
)

# A read/verify capability proof must return the oracle evidence it claims to
# have operated on. Writes are instead proven by side-effect assertions.
rewrite(
    "src/worldloom/eval_instances.py",
    '''                connector=step.connector,\n                operation=step.operation,\n            )''',
    '''                connector=step.connector,\n                operation=step.operation,\n                evidence_ids=fact_ids if step.effect in {"read", "verify"} else (),\n            )''',
)
rewrite(
    "src/worldloom/eval_reference.py",
    '''    elif assertion.type == "capability_invoked":\n        passed = assertion.step_id in by_step''',
    '''    elif assertion.type == "capability_invoked":\n        step = by_step.get(assertion.step_id or "")\n        expected_operation = assertion.operation or assertion.capability\n        operation_ok = bool(\n            step and (expected_operation is None or step.operation == expected_operation)\n        )\n        evidence_ok = bool(\n            step and set(assertion.evidence_ids) <= set(step.output_ids)\n        )\n        passed = operation_ok and evidence_ok''',
)

# Proposal copy rejects every bare figure form: dates, integer/decimal numbers,
# grouped counts, percentages and currency figures. Fact-token IDs stay outside
# the match because identifiers are protected by the boundary lookarounds.
rewrite(
    "src/worldloom/artifact_ecology.py",
    '''    numeric = re.compile(r"(?<![A-Za-z0-9_-])(?:[$£€]?\\d{1,3}(?:,\\d{3})+(?:\\.\\d+)?|[$£€]?\\d+\\.\\d+%?)(?![A-Za-z0-9_-])")''',
    '''    numeric = re.compile(\n        r"(?<![A-Za-z0-9_-])(?:"\n        r"\\d{4}-\\d{2}-\\d{2}"\n        r"|(?:[$£€]\\s*)?(?:\\d{1,3}(?:,\\d{3})+|\\d+)(?:\\.\\d+)?"\n        r"(?:%|\\s*[A-Za-z]{1,8})?"\n        r")(?![A-Za-z0-9_-])"\n    )''',
)

# ServiceNow chronology and notes stop at the current projected state.
rewrite(
    "src/worldloom/artifact_ecology.py",
    '''            final = str(fields.get("state", "")).lower()\n            states = ["New", "In Progress"] + (["Resolved", "Closed"] if final in {"resolved", "closed", "complete"} else [])''',
    '''            final = str(fields.get("state", "New")).strip().lower()\n            state_paths = {\n                "new": ["New"],\n                "open": ["New"],\n                "in progress": ["New", "In Progress"],\n                "in_progress": ["New", "In Progress"],\n                "resolved": ["New", "In Progress", "Resolved"],\n                "closed": ["New", "In Progress", "Resolved", "Closed"],\n                "complete": ["New", "In Progress", "Resolved", "Closed"],\n                "completed": ["New", "In Progress", "Resolved", "Closed"],\n            }\n            states = state_paths.get(final, [str(fields.get("state") or "New")])''',
)
rewrite(
    "src/worldloom/artifact_ecology.py",
    '''            fields.setdefault("state_history", [{"state": state, "sequence": i, "at": at(i * 30)} for i, state in enumerate(states)])\n            fields.setdefault("work_notes", [\n                {"sequence": 1, "at": at(10), "kind": "triage", "text": "Impact confirmed; investigation opened."},\n                {"sequence": 2, "at": at(45), "kind": "diagnosis", "text": "Evidence linked to correlated business event."},\n                {"sequence": 3, "at": at(120), "kind": "closure", "text": "Resolution recorded against source evidence."},\n            ])''',
    '''            fields.setdefault("state_history", [\n                {"state": state, "sequence": i, "at": at(i * 30)}\n                for i, state in enumerate(states)\n            ])\n            notes: list[dict[str, Any]] = []\n            if len(states) >= 2:\n                notes.append({"sequence": 1, "at": at(10), "kind": "triage", "text": "Impact confirmed; investigation opened."})\n            if len(states) >= 3:\n                notes.append({"sequence": 2, "at": at(45), "kind": "diagnosis", "text": "Evidence linked to correlated business event."})\n            if states[-1] == "Closed":\n                notes.append({"sequence": 3, "at": at(120), "kind": "closure", "text": "Resolution recorded against source evidence."})\n            fields.setdefault("work_notes", notes)''',
)

# Ecology semantics must survive the native PDF boundary as durable Info
# metadata, not visible story text.
rewrite(
    "src/worldloom/render/pdf.py",
    '''    buffer = BytesIO()\n    doc = BaseDocTemplate(''',
    '''    buffer = BytesIO()\n    keywords = ["synthetic", "worldloom", f"seed={ir.metadata.get('worldloom_seed', '')}"]\n    if ir.metadata.get("realism_profile"):\n        keywords.append("worldloom-realism=ecology/v1")\n        for key, label in (\n            ("lifecycle_version", "lifecycle"),\n            ("revision", "revision"),\n            ("artifact_family", "family"),\n        ):\n            value = ir.metadata.get(key)\n            if value is not None:\n                keywords.append(f"{label}={value}")\n    doc = BaseDocTemplate(''',
)
rewrite(
    "src/worldloom/render/pdf.py",
    '''        keywords=["synthetic", "worldloom", f"seed={ir.metadata.get('worldloom_seed', '')}"],''',
    '''        keywords=keywords,''',
)

# The metamorphic transform is part of the recipe, including its seed and
# count, so exported worlds rebuild with the same canonical facts.
rewrite(
    "src/worldloom/recipe.py",
    '''    "Compose": ("ledger_key",),\n}''',
    '''    "Compose": ("ledger_key",),\n    "AddIrrelevantFacts": ("seed", "count"),\n}''',
)
rewrite(
    "src/worldloom/world_transforms.py",
    '''    def apply(self, world: World, *, seed: int) -> TransformResult:\n        transform_id = content_key("transform", "add-irrelevant-facts", seed, self.count)\n        if not self.count:\n            return TransformResult(\n                world=world,''',
    '''    def apply(self, world: World, *, seed: int) -> TransformResult:\n        from .recipe import with_step\n\n        transform_id = content_key("transform", "add-irrelevant-facts", seed, self.count)\n        recorded_recipe = with_step(\n            world.recipe, "AddIrrelevantFacts", seed=seed, count=self.count\n        )\n        if not self.count:\n            return TransformResult(\n                world=replace(world, _recipe=recorded_recipe),''',
)
rewrite(
    "src/worldloom/world_transforms.py",
    '''        transformed = replace(world, _facts=world._facts + tuple(additions))''',
    '''        transformed = replace(\n            world,\n            _facts=world._facts + tuple(additions),\n            _recipe=recorded_recipe,\n        )''',
)
rewrite(
    "src/worldloom/recipe.py",
    '''        elif name == "Compose":\n            from . import compose as compose_module\n\n            world = compose_module.replay(\n                world, ledger_key=step["ledger_key"], ledger=ledger,\n            )\n        elif name in _STEP_REGISTRY:''',
    '''        elif name == "Compose":\n            from . import compose as compose_module\n\n            world = compose_module.replay(\n                world, ledger_key=step["ledger_key"], ledger=ledger,\n            )\n        elif name == "AddIrrelevantFacts":\n            from .world_transforms import AddIrrelevantFacts\n\n            world = AddIrrelevantFacts(count=step["count"]).apply(\n                world, seed=step["seed"]\n            ).world\n        elif name in _STEP_REGISTRY:''',
)

# Reproducibility-visible ecology output change belongs under Generation.
rewrite(
    "CHANGELOG.md",
    '''## Unreleased\n\n### Added — source-backed process catalogue''',
    '''## Unreleased\n\n### Generation — artifact ecology v1\n\n- Opt-in `artifact_realism=ecology/v1` changes native artifact metadata, style\n  selection, connector lifecycle history and output bytes for a fixed seed.\n  PDF outputs persist machine-readable realism, lifecycle, revision and family\n  markers. Recipes record replayable metamorphic noise transforms.\n\n### Added — source-backed process catalogue''',
)

# Focused regressions for every semantic review contract except the PDF marker,
# which is already pinned by tests/test_pdf_ecology.py.
tests = ROOT / "tests/test_pr33_merge_gate.py"
if not tests.exists():
    tests.write_text('''from __future__ import annotations\n\nfrom types import SimpleNamespace\n\nimport pytest\n\nfrom worldloom.artifact_ecology import (\n    ArtifactProposal, Surface, enrich_connector_records, review_proposal,\n)\nfrom worldloom.connector_data import ConnectorRecord\nfrom worldloom.eval_candidates import (\n    _check_records, _check_temporal_relation, validate_candidate,\n)\nfrom worldloom.eval_design import (\n    EvalSpec, EvalStepSpec, RequirementKind, WorldRequirement, plan_candidates,\n)\nfrom worldloom.eval_instances import bind_eval_instance\nfrom worldloom.eval_reference import ExecutionStep, ProofStatus, execute_reference\nfrom worldloom.recipe import rebuild\nfrom worldloom.retail import RetailWorld\nfrom worldloom.scenarios import MonthEndClose\nfrom worldloom.world_transforms import AddIrrelevantFacts\n\n\ndef _world(seed: int = 8128):  # type: ignore[no-untyped-def]\n    return RetailWorld(seed=seed).build().run(MonthEndClose(period="2026-03"))\n\n\ndef _spec(*requirements: WorldRequirement) -> EvalSpec:\n    return EvalSpec(\n        id="EVALSPEC-PR33-MERGE-GATE", capability="find_evidence",\n        persona="controller", request_template="Verify the evidence.",\n        steps=(EvalStepSpec(id="find", capability="find_evidence", operation="find", effect="read"),),\n        requirements=requirements, candidate_count=1,\n    )\n\n\ndef test_connector_selectors_see_nested_business_fields() -> None:\n    requirement = WorldRequirement(\n        id="incident", kind=RequirementKind.CONNECTOR,\n        selector={"priority": "1", "state": "Resolved"},\n    )\n    record = ConnectorRecord(\n        id="sn-1", connector="servicenow", entity="incident", external_id="INC-1",\n        title="Incident", fields={"priority": "1", "state": "Resolved"},\n    )\n    check = _check_records(requirement, [record])\n    assert check.satisfied and check.evidence_ids == ("sn-1",)\n\n\ndef test_temporal_selector_matches_requested_endpoints_not_any_edge() -> None:\n    requirement = WorldRequirement(\n        id="relation", kind=RequirementKind.TEMPORAL_RELATION,\n        selector={"edge_kind": "references", "source": "RCA-1", "target": "INC-1"},\n    )\n    realism = SimpleNamespace(graph=SimpleNamespace(edges=(\n        SimpleNamespace(kind="references", source="OTHER", target="INC-1"),\n        SimpleNamespace(kind="references", source="RCA-1", target="INC-1"),\n    )))\n    check = _check_temporal_relation(requirement, realism)\n    assert check.observed == 1\n    assert check.evidence_ids == ("RCA-1->INC-1:references",)\n\n\ndef test_candidate_acceptance_requires_world_coherence(monkeypatch: pytest.MonkeyPatch) -> None:\n    spec = _spec(WorldRequirement(id="facts", kind=RequirementKind.FACT))\n    plan = plan_candidates(spec, count=1)[0]\n    world = _world(plan.seed)\n    monkeypatch.setattr(type(world), "validate", lambda self: SimpleNamespace(ok=False))\n    assert not validate_candidate(plan, spec, world).accepted\n\n\ndef _bound_read():  # type: ignore[no-untyped-def]\n    spec = _spec(WorldRequirement(id="facts", kind=RequirementKind.FACT))\n    plan = plan_candidates(spec, count=1)[0]\n    world = _world(plan.seed)\n    from worldloom.eval_candidates import GeneratedCandidate\n    validation = validate_candidate(plan, spec, world)\n    candidate = GeneratedCandidate(plan=plan, world=world, validation=validation)\n    return world, bind_eval_instance(spec, candidate)\n\n\ndef test_reference_proof_rejects_wrong_operation() -> None:\n    world, instance = _bound_read()\n    proof = execute_reference(\n        instance, world,\n        lambda current, step, bound: (current, ExecutionStep(\n            step_id=step.id, operation="wrong", output_ids=bound.oracle.fact_ids,\n        )),\n    )\n    assert proof.status == ProofStatus.PROVEN_UNSAT\n\n\ndef test_reference_proof_rejects_missing_required_outputs() -> None:\n    world, instance = _bound_read()\n    proof = execute_reference(\n        instance, world,\n        lambda current, step, bound: (current, ExecutionStep(\n            step_id=step.id, operation="find", output_ids=(),\n        )),\n    )\n    assert proof.status == ProofStatus.PROVEN_UNSAT\n\n\n@pytest.mark.parametrize("copy", ["20%", "42", "2026-03-04", "$1,200"])\ndef test_proposal_rejects_bare_figure_forms(copy: str) -> None:\n    world = _world()\n    intent = next(iter(world.artifact_intents))\n    proposal = ArtifactProposal(\n        artifact_id=intent.id, surface=Surface.PDF, family="memo", density="balanced",\n        title_register="sentence", copy_blocks=(f"Unsupported claim {copy}",),\n    )\n    assert "bare_numeric_claim" in {finding.code for finding in review_proposal(world, proposal)}\n\n\ndef test_servicenow_history_stops_at_current_state() -> None:\n    world = _world().extend(recipe={**_world().recipe, "artifact_realism": "ecology/v1"})\n    record = ConnectorRecord(\n        id="sn-resolved", connector="servicenow", entity="incident",\n        external_id="INC-RESOLVED", title="Resolved incident",\n        fields={"state": "Resolved", "priority": "1", "opened_at": "2026-03-01T00:00:00"},\n    )\n    enriched = enrich_connector_records(world, [record])[0]\n    assert enriched.fields["state_history"][-1]["state"] == "Resolved"\n    assert all(note["kind"] != "closure" for note in enriched.fields["work_notes"])\n\n\ndef test_irrelevant_fact_transform_round_trips_through_recipe() -> None:\n    world = _world(seed=91)\n    transformed = AddIrrelevantFacts(2).apply(world, seed=4001).world\n    assert transformed.recipe["steps"][-1] == {\n        "scenario": "AddIrrelevantFacts", "seed": 4001, "count": 2,\n    }\n    replayed = rebuild(transformed.recipe)\n    noise = tuple(fact.id for fact in transformed.facts if fact.kind == "metamorphic_irrelevant_context")\n    replayed_noise = tuple(fact.id for fact in replayed.facts if fact.kind == "metamorphic_irrelevant_context")\n    assert noise == replayed_noise\n''', encoding="utf-8")

print("Applied PR #33 merge-gate semantic fixes and focused regressions.")
