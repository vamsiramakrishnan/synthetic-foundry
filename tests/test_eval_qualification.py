"""Independent evidence, one-use holdout probes, and honest promotion gates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from worldloom import packkit
from worldloom.evalrun import (
    EvalCase,
    EvalSession,
    ReferenceAgent,
    ScriptedAgent,
    case_from_row,
    run_cases,
    service_for,
)
from worldloom.evalrun.campaign import StageCases, campaign
from worldloom.evalrun.grader import GraderDrift, grader_identity
from worldloom.evalrun.grading import (
    score_case,
    unobserved_outcomes,
    unobserved_plan,
    unobserved_trajectory,
)
from worldloom.evalrun.improve import Improver, improve
from worldloom.evalrun.noise import paired
from worldloom.evalrun.policy import agent_name, pack_record
from worldloom.evalrun.qualification import (
    QualificationExhausted,
    QualificationPolicy,
    QualificationVault,
    audit_splits,
    evidence_components,
    isolated_splits,
    with_record_provenance,
)
from worldloom.evalrun.results import read_run
from worldloom.evalrun.runner import CaseResult, RunReport, case_set_digest
from worldloom.providers import digest


def _case(name: str, *, facts: tuple[str, ...] = (), source: str = "world-a",
          unit: str | None = None) -> EvalCase:
    dimensions = {"source_digest": source, "company_id": "one-company"}
    if unit is not None:
        dimensions["independent_unit"] = unit
    return case_from_row({"id": name, "query": f"Read the facts for {name}.", "expected_fact_ids": list(facts),
                          "expected_dag": {"nodes": [], "edges": []}, "assertions": []},
                         dimensions=dimensions)


def test_components_close_over_shared_evidence_transitively_without_collapsing_a_company() -> None:
    cases = [_case("original", facts=("f1",)), _case("paraphrase", facts=("f1", "f2")),
             _case("different-task", facts=("f2",)), _case("unrelated", facts=("f3",))]
    units = evidence_components(cases)
    assert units["original"] == units["paraphrase"] == units["different-task"]
    assert units["unrelated"] != units["original"]
    assert evidence_components(list(reversed(cases))) == units
    audit = audit_splits(cases[:1], cases[1:])
    assert not audit.isolated and audit.overlapping_units == 1
    assert audit.overlaps[0]["training"] == ["original"]
    assert audit.overlaps[0]["heldout"] == ["different-task", "paraphrase"]


def test_shared_external_ids_in_distinct_source_worlds_do_not_leak() -> None:
    first = _case("same-id", facts=("f1",), source="seed-1")
    first = first.model_copy(update={"dimensions": {**first.dimensions, "source_namespace": "seed-1"}})
    second = _case("same-id", facts=("f1",), source="seed-2")
    second = second.model_copy(update={"dimensions": {**second.dimensions, "source_namespace": "seed-2"}})
    assert audit_splits([first], [second]).isolated


def test_changed_snapshot_does_not_manufacture_independence() -> None:
    assert not audit_splits([_case("original", facts=("f1",), source="old-snapshot")],
                            [_case("variant", facts=("f1",), source="new-snapshot")]).isolated


def test_false_independent_labels_cannot_split_shared_protected_evidence() -> None:
    a = _case("a", facts=("f1",), unit="a")
    b = _case("b", facts=("f1",), unit="b")
    assert not audit_splits([a], [b], unit_dimension="independent_unit").isolated
    missing = _case("missing", facts=("f2",))
    with pytest.raises(ValueError, match="missing independent-unit"):
        evidence_components([missing], unit_dimension="independent_unit")


def test_whole_family_splits_preserve_declared_splits_and_refuse_conflicts() -> None:
    a = _case("a", facts=("f1",))
    b = _case("b", facts=("f1",)).model_copy(update={"dimensions": {"source_digest": "world-a", "split": "test"}})
    assert isolated_splits([a, b], holdout_share=.4) == ((), (a, b))
    a = a.model_copy(update={"dimensions": {"source_digest": "world-a", "split": "train"}})
    with pytest.raises(ValueError, match="declared training and held-out"):
        isolated_splits([a, b], holdout_share=.4)


def test_unknown_provenance_or_independence_is_refused() -> None:
    with pytest.raises(ValueError, match="source_digest"):
        evidence_components([_case("no-source", unit="u").model_copy(update={"dimensions": {}})])
    with pytest.raises(ValueError, match="cannot infer independence"):
        evidence_components([_case("no-evidence")])


def test_record_provenance_is_measured_and_existing_pins_are_not_rewritten() -> None:
    original = _case("a", facts=("f",)).model_copy(update={"dimensions": {}})
    records = [{"fid": "f", "server": "jira", "entity": "issue", "ident": "WL-1"}]
    (pinned,) = with_record_provenance([original], records, namespace="company-world-1")
    assert pinned.row == original.row and pinned.dimensions["source_namespace"] == "company-world-1"
    assert with_record_provenance([pinned], records) == (pinned,)
    with pytest.raises(ValueError, match="source snapshot differs"):
        with_record_provenance([pinned], [{**records[0], "status": "closed"}])


def _vault(root: Path, *, trials: int = 2) -> QualificationVault:
    train = [_case("train", facts=("train-fact",))]
    held = [_case(f"held-{i}", facts=(f"held-fact-{i}",)) for i in range(8)]
    return QualificationVault.open(root, train, held,
                                   policy=QualificationPolicy(trials=trials, min_units=2),
                                   grader=grader_identity())


def test_reservations_are_fresh_bounded_and_exactly_resumable(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    first = vault.reserve(1, champion={"digest": "a", "harness": "one"},
                          candidate={"digest": "b", "harness": "one"}, grader=grader_identity())
    resumed = _vault(tmp_path).reserve(1, champion={"digest": "a", "harness": "one"},
                                     candidate={"digest": "b", "harness": "one"}, grader=grader_identity())
    assert first == resumed and (tmp_path / "trials" / "001.json").is_file()
    with pytest.raises(ValueError, match="different candidate, champion, harness"):
        vault.reserve(1, champion={"digest": "a", "harness": "one"},
                      candidate={"digest": "b", "harness": "different"}, grader=grader_identity())
    second = vault.reserve(2, champion={"digest": "a"}, candidate={"digest": "c"}, grader=grader_identity())
    assert set(first.units.values()).isdisjoint(second.units.values())
    assert {c.id for c in first.cases}.isdisjoint(c.id for c in second.cases)
    assert vault.summary()["trials_spent"] == 2
    with pytest.raises(QualificationExhausted):
        vault.reserve(3, champion={"digest": "a"}, candidate={"digest": "d"}, grader=grader_identity())


def test_seal_pins_requests_provenance_and_policy_and_rejects_undersized_designs(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    train = [_case("train", facts=("train-fact",))]
    changed = [vault.cases[0].model_copy(update={"query": "A changed request"}), *vault.cases[1:]]
    with pytest.raises(ValueError, match="sealed qualification"):
        QualificationVault.open(tmp_path, train, changed, policy=vault.policy, grader=grader_identity())
    with pytest.raises(ValueError, match="independent held-out units"):
        QualificationVault.open(tmp_path / "small", train, vault.cases[:2],
                                policy=vault.policy, grader=grader_identity())
    with pytest.raises(ValueError, match="share protected evidence"):
        QualificationVault.open(tmp_path / "leaked", [vault.cases[0]], vault.cases,
                                policy=vault.policy, grader=grader_identity())


def _report(scores: dict[str, float], *, agent: str) -> RunReport:
    results = []
    for case, value in scores.items():
        grade = score_case(unobserved_plan().model_copy(update={"score": value, "passed": value == 1}),
                           unobserved_trajectory().model_copy(update={"score": value, "passed": value == 1}),
                           unobserved_outcomes().model_copy(update={"score": value, "passed": value == 1}),
                           {"status": "ok" if value == 1 else "fail"})
        results.append(CaseResult(case_id=case, query=case, agent=agent, status="graded", score=grade))
    return RunReport(agent=agent, principal="agent", case_set="same-cohort", results=tuple(results))


def test_many_sibling_queries_cannot_manufacture_independent_gain() -> None:
    left = dict.fromkeys([f"sibling-{i}" for i in range(100)], .0)
    left["unrelated"] = 1.0
    right = {key: 1 - value for key, value in left.items()}
    baseline, candidate = [_report(left, agent="baseline")]*2, [_report(right, agent="candidate")]*2
    naive = paired(baseline, candidate, resamples=500)
    units = {key: "shared-episode" if key.startswith("sibling") else "different-episode" for key in left}
    honest = paired(baseline, candidate, units=units, resamples=500)
    assert naive.overall is not None and naive.overall.mean > .9
    assert honest.overall is not None and honest.overall.mean == .0
    assert honest.overall.cases == honest.independent_units == 2
    assert honest.method == "cluster_bootstrap"
    assert "independent_units" not in naive.model_dump(mode="json")


def test_repeat_bootstrap_preserves_a_batch_wide_stochastic_shock() -> None:
    left = [_report(dict.fromkeys([f"case-{i}" for i in range(20)], .4), agent="a")]*2
    right = [_report(dict.fromkeys([f"case-{i}" for i in range(20)], score), agent="b") for score in (0.0, 1.0)]
    result = paired(left, right, units={f"case-{i}": f"unit-{i}" for i in range(20)}, resamples=500)
    assert result.overall is not None and result.overall.mean == .1
    assert result.overall.ci_low == -.4 and result.overall.ci_high == .6
    assert result.overall.stderr is not None and result.overall.stderr > .3


def test_missing_reservation_index_and_grader_drift_are_refused(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    vault.reserve(1, champion={"digest": "a"}, candidate={"digest": "b"}, grader=grader_identity())
    with pytest.raises(ValueError, match="grader differs"):
        vault.reserve(2, champion={"digest": "a"}, candidate={"digest": "b"}, grader={"digest": "different"})
    vault.reserve(2, champion={"digest": "a"}, candidate={"digest": "b"}, grader=grader_identity())
    (tmp_path / "trials" / "001.json").unlink()
    with pytest.raises(ValueError, match="intact append-only sequence"):
        vault.reserve(3, champion={"digest": "a"}, candidate={"digest": "b"}, grader=grader_identity())


def test_racing_reservation_cannot_overwrite_another_candidate(tmp_path: Path, monkeypatch: Any) -> None:
    vault = _vault(tmp_path)
    first = vault.reserve(1, champion={"digest": "a"}, candidate={"digest": "b"}, grader=grader_identity())
    # The second writer observed an empty directory before the first writer
    # claimed trial 1. Exclusive create must still refuse its stale allocation.
    monkeypatch.setattr(Path, "glob", lambda *_: iter(()))
    with pytest.raises(ValueError, match="already belongs to a different experiment"):
        vault.reserve(1, champion={"digest": "a"}, candidate={"digest": "c"}, grader=grader_identity())
    assert json.loads((tmp_path / "trials" / "001.json").read_text()) == first.reservation


def _runnable_cases() -> tuple[tuple[EvalCase, ...], tuple[dict[str, Any], ...]]:
    rows, records = [], []
    for index in range(12):
        fid = f"record-{index}"
        records.append({"fid": fid, "server": "servicenow", "entity": "incident", "ident": f"INC{index:07d}",
                        "state": "new", "short_description": f"Case {index}"})
        rows.append(case_from_row({"id": f"case-{index}", "query": f"Read incident INC{index:07d}.",
                                   "expected_dag": {"nodes": [{"id": "read", "server": "servicenow",
                                   "tool": "get_record", "fixture": fid, "entity": "incident", "op": "read"}],
                                                    "edges": []},
                                   "assertions": [{"type": "tool_called", "node": "read"},
                                                  {"type": "reads_contain", "node": "read", "records": [fid]}]}))
    return with_record_provenance(rows, records), tuple(records)


class _PolicyAgent:
    def __init__(self, pack: Any, cases: tuple[EvalCase, ...]) -> None:
        self.name = agent_name("qualification-test", pack)
        self.pack_record = pack_record(pack)
        self.reference = ReferenceAgent(cases)
        self.skilled = "verify" in pack.body.skills

    def run(self, task: Any, tools: Any) -> Any:
        return (self.reference if self.skilled else ScriptedAgent([], name="idle")).run(task, tools)


def _proposal(payload: dict[str, Any]) -> dict[str, Any]:
    return {"request_id": payload["request_id"], "message": "revised",
            "proposal": {"name": payload["draft"]["name"], "body": {**payload["draft"]["body"],
                         "skills": {"verify": "Read each requested incident."}}}}


def test_improvement_loop_reserves_before_either_heldout_run_and_reuses_finished_runs(tmp_path: Path) -> None:
    cases, records = _runnable_cases()
    out = tmp_path / "loop"
    calls: list[tuple[str, ...]] = []

    def run(subset: Any, agent: Any) -> Any:
        if all(case.id not in {"case-0", "case-1", "case-2", "case-3"} for case in subset):
            assert (out / "qualification" / "trials" / "001.json").is_file()
        calls.append(tuple(case.id for case in subset))
        return run_cases(service_for(subset, records), subset, agent)

    def invoke() -> Any:
        return improve(packkit.resolve("agent:baseline"), cases[:4], holdout=cases[4:], run=run,
                       agent_for=lambda pack: _PolicyAgent(pack, cases), exchange=_proposal, out=out,
                       rounds=1, repeats=2, ablate=False,
                       qualification=QualificationPolicy(trials=2, min_units=2))

    report = invoke()
    receipt = report.rounds[0]
    assert receipt.decision == "promoted", receipt.reasons
    assert receipt.qualification is not None and receipt.qualification["trial"] == 1
    assert receipt.holdout is not None and receipt.holdout.independent_units == 4
    assert report.qualification is not None and report.qualification["trials_remaining"] == 1
    held_ids = set(json.loads((out / "qualification" / "seal.json").read_text())["tranches"][0])
    paid = tuple(out.glob("runs/*/holdout/trial-1/rep-*/run.json"))
    assert len(paid) == 4
    for path in paid:
        stored = read_run(path.parent)
        assert stored.split == "holdout"
        assert {row.case_id for row in stored.results} == held_ids
    (out / "rounds" / "001.json").unlink()
    (out / "improve.json").unlink()
    calls.clear()
    again = invoke()
    assert not calls and again.rounds[0] == receipt


def test_domain_runner_receives_distinct_repeat_context_and_seals_its_grader(tmp_path: Path) -> None:
    cases, records = _runnable_cases()
    calls: list[tuple[Path, str, int | None, str]] = []

    class DomainRunner:
        revision = "native-byte-grader-v1"

        def __call__(self, *_: Any) -> Any:
            raise AssertionError("domain execution needs an experiment identity")

        def grading_identity(self, rater: Any = None) -> dict[str, Any]:
            parts = {**grader_identity(rater), "native": self.revision,
                     "native_sources": [("parser", "1.0")]}
            parts.pop("digest")
            return {**parts, "digest": digest(parts)}

        def run_experiment(self, subset: Any, agent: Any, *, directory: Path,
                           label: str, repeat: int | None, grader: Any) -> Any:
            calls.append((directory, label, repeat, grader["digest"]))
            assert directory.name == f"rep-{repeat}"
            if label.startswith("holdout/"):
                assert (tmp_path / "qualification" / "trials" / "001.json").is_file()
            return run_cases(service_for(subset, records), subset, agent)

    runner = DomainRunner()
    options = {"run": runner, "agent_for": lambda pack: _PolicyAgent(pack, cases),
               "exchange": _proposal, "out": tmp_path, "rounds": 1, "repeats": 2, "ablate": False,
               "qualification": QualificationPolicy(trials=2, min_units=2)}
    report = improve(packkit.resolve("agent:baseline"), cases[:4], holdout=cases[4:], **options)
    assert report.rounds[0].decision == "promoted"
    assert len(calls) == 8 and len({call[0] for call in calls}) == 8
    assert {call[2] for call in calls} == {1, 2}
    assert {call[3] for call in calls} == {report.grader["digest"]}
    reservation = json.loads((tmp_path / "qualification" / "trials" / "001.json").read_text())
    assert reservation["grader"]["native"] == runner.revision
    (tmp_path / "rounds" / "001.json").unlink()
    (tmp_path / "improve.json").unlink()
    calls.clear()
    resumed = improve(packkit.resolve("agent:baseline"), cases[:4], holdout=cases[4:], **options)
    assert not calls and resumed.rounds[0] == report.rounds[0]
    before = len(calls)
    runner.revision = "native-byte-grader-v2"
    with pytest.raises(ValueError, match="sealed qualification"):
        improve(packkit.resolve("agent:baseline"), cases[:4], holdout=cases[4:], **options)
    assert len(calls) == before


@pytest.mark.parametrize("recompute_digest", [False, True])
def test_domain_grader_is_checked_even_when_reusing_an_in_memory_run(tmp_path: Path,
                                                                   recompute_digest: bool) -> None:
    cases, records = _runnable_cases()

    class DomainRunner:
        revision = "v1"
        first_digest: str | None = None

        def validate_cases(self, subset: Any) -> None:
            if any(not case.dimensions.get("source_digest") for case in subset):
                raise ValueError("domain provenance was dropped")

        def __call__(self, subset: Any, agent: Any) -> Any:
            return run_cases(service_for(subset, records), subset, agent)

        def grading_identity(self, rater: Any = None) -> dict[str, Any]:
            parts = {**grader_identity(rater), "native": self.revision}
            parts.pop("digest")
            if self.first_digest is None:
                self.first_digest = digest(parts)
            # A domain that forgets to recompute its own digest still cannot
            # silently change its declared grading inputs behind a cache.
            return {**parts, "digest": digest(parts) if recompute_digest else self.first_digest}

    runner = DomainRunner()
    improver = Improver(run=runner, agent_for=lambda pack: _PolicyAgent(pack, cases),
                        exchange=_proposal, out=tmp_path)
    grader = improver._grading_identity()
    improver._pinned_run(packkit.resolve("agent:baseline"), cases[:1], "train", grader)
    runner.revision = "v2"
    with pytest.raises(GraderDrift, match="runner's grader"):
        improver._pinned_run(packkit.resolve("agent:baseline"), cases[:1], "train", grader)
    runner.revision = "v1"
    changed = cases[0].model_copy(update={"dimensions": {}})
    assert case_set_digest([changed]) == case_set_digest(cases[:1])
    with pytest.raises(ValueError, match="domain provenance was dropped"):
        improver._pinned_run(packkit.resolve("agent:baseline"), [changed], "train", grader)


def test_ungraded_probe_is_refused_and_still_consumes_the_tranche(tmp_path: Path) -> None:
    cases, _ = _runnable_cases()
    vault = QualificationVault.open(tmp_path, cases[:4], cases[4:],
                                   policy=QualificationPolicy(trials=1, min_units=2), grader=grader_identity())
    trial = vault.reserve(1, champion={"digest": "a"}, candidate={"digest": "b"}, grader=grader_identity())
    before = _report({case.id: .0 for case in trial.cases}, agent="a").model_copy(update={"case_set": case_set_digest(trial.cases)})
    after = _report({case.id: 1.0 for case in trial.cases}, agent="b")
    rows = (after.results[0].model_copy(update={"status": "error", "score": None}), *after.results[1:])
    after = after.model_copy(update={"case_set": case_set_digest(trial.cases), "results": rows})
    improver = Improver(run=lambda *_: before, agent_for=lambda _: None, exchange=lambda _: {}, out=tmp_path,
                        qualification=vault.policy, repeats=2)
    gate = improver._qualified_gate([before]*2, [after]*2, trial=trial, name="holdout", min_delta=0, max_fall=.1)
    assert not gate.passed and any("ungraded cases" in reason for reason in gate.reasons)
    with pytest.raises(QualificationExhausted):
        vault.reserve(2, champion={"digest": "a"}, candidate={"digest": "b"}, grader=grader_identity())


@pytest.mark.parametrize("defect", ["missing_axis", "rare_axis", "nonfinite_score"])
def test_qualification_refuses_unmatched_axes_insufficient_axis_units_and_invalid_scores(tmp_path: Path, defect: str) -> None:
    cases, _ = _runnable_cases()
    vault = QualificationVault.open(tmp_path, cases[:4], cases[4:],
                                   policy=QualificationPolicy(trials=1, min_units=2), grader=grader_identity())
    trial = vault.reserve(1, champion={"digest": "a"}, candidate={"digest": "b"}, grader=grader_identity())

    def report(score: float, agent: str) -> RunReport:
        result = _report({case.id: score for case in trial.cases}, agent=agent)
        return result.model_copy(update={"case_set": case_set_digest(trial.cases),
                                        "results": tuple(row.model_copy(update={"query": case.query})
                                                         for row, case in zip(result.results, trial.cases, strict=True))})

    before, after = report(0.0, "a"), report(1.0, "b")
    if defect == "missing_axis":
        after = after.model_copy(update={"results": tuple(row.model_copy(update={
            "score": row.score.model_copy(update={"observed": ("plan",)})}) for row in after.results)})
    elif defect == "rare_axis":
        def only_one_outcome(result: RunReport) -> RunReport:
            return result.model_copy(update={"results": tuple(row if index == 0 else row.model_copy(update={
                "score": row.score.model_copy(update={"observed": ("plan", "trajectory")})})
                for index, row in enumerate(result.results))})
        before, after = only_one_outcome(before), only_one_outcome(after)
    else:
        after = after.model_copy(update={"results": (after.results[0].model_copy(update={
            "score": after.results[0].score.model_copy(update={"score": float("nan")})}), *after.results[1:])})
    improver = Improver(run=lambda *_: before, agent_for=lambda _: None, exchange=lambda _: {}, out=tmp_path,
                        qualification=vault.policy, repeats=2)
    gate = improver._qualified_gate([before]*2, [after]*2, trial=trial, name="holdout", min_delta=0, max_fall=.1)
    assert not gate.passed, gate
    expected = {"missing_axis": "changed observed axes", "rare_axis": "axis has 1 independent units",
                "nonfinite_score": "invalid score"}[defect]
    assert any(expected in reason for reason in gate.reasons)


def test_opt_in_requires_repeats_and_refuses_cross_split_leakage_before_running(tmp_path: Path) -> None:
    cases, _ = _runnable_cases()
    arguments = dict(champion=packkit.resolve("agent:baseline"), cases=cases[:4], holdout=cases[4:],
                     run=lambda *_: pytest.fail("invalid design executed"), agent_for=lambda _: None,
                     exchange=lambda _: {}, out=tmp_path, rounds=1, qualification=QualificationPolicy(trials=1, min_units=2))
    with pytest.raises(ValueError, match="at least 2 repeats"):
        improve(**arguments, repeats=1)
    arguments["cases"] = (cases[4].model_copy(update={"id": "renamed"}),)
    with pytest.raises(ValueError, match="share protected evidence"):
        improve(**arguments, repeats=2)


def test_sdk_qualification_routes_fresh_heldout_tranches_to_the_heldout_records(tmp_path: Path) -> None:
    pinned, records = _runnable_cases()
    cases = tuple(case.model_copy(update={"dimensions": {}}) for case in pinned)
    train = EvalSession(cases[:4], records[:4])
    held = EvalSession(cases[4:], records[4:])
    loop = train.improver(agent=lambda pack: _PolicyAgent(pack, cases), proposer=_proposal,
                          out=tmp_path, holdout=held, repeats=2, ablate=False,
                          qualification=QualificationPolicy(trials=2, min_units=2))
    report = loop.run("agent:baseline", rounds=1)
    assert report.rounds[0].decision == "promoted", report.rounds[0].reasons
    assert report.rounds[0].holdout is not None and report.rounds[0].holdout.independent_units == 4
    # None of the held incident IDs exists in the training record snapshot.
    for path in tmp_path.glob("runs/*/holdout/trial-1/rep-*/run.json"):
        assert all(row.status == "graded" for row in read_run(path.parent).results)


@pytest.mark.parametrize("qualified", [False, True])
def test_sdk_routing_and_service_cache_pin_requests_and_source_origin(tmp_path: Path,
                                                                    monkeypatch: pytest.MonkeyPatch,
                                                                    qualified: bool) -> None:
    from worldloom.evalrun import session as session_module

    cases, records = _runnable_cases()
    first = cases[0].model_copy(update={"dimensions": {"source_namespace": "world-a"}})
    second = first.model_copy(update={"query": first.query if qualified else "Read the incident again.",
                                      "dimensions": {"source_namespace": "world-b"}})
    training_records = records[:1]
    held_records = ({**records[0], "state": "closed"},)
    loop = EvalSession([first], training_records).improver(
        agent=lambda pack: _PolicyAgent(pack, (first, second)), proposer=_proposal, out=tmp_path,
        holdout=EvalSession([second], held_records),
        qualification=QualificationPolicy(trials=1, min_units=2) if qualified else None)
    served: list[tuple[Any, ...]] = []
    factory = session_module.service_for

    def tracked(cases: Any, records: Any, **options: Any) -> Any:
        served.append(tuple(records))
        return factory(cases, records, **options)

    monkeypatch.setattr(session_module, "service_for", tracked)
    if qualified:
        (first,) = with_record_provenance([first], training_records)
        (second,) = with_record_provenance([second], held_records)
    assert case_set_digest([first]) == case_set_digest([second])
    reference = ReferenceAgent([first])
    loop.run_cases([first], reference)
    loop.run_cases([second], reference)
    assert served == [training_records, held_records]
    assert len(loop._services) == 2


def test_campaign_routes_tranches_and_ledger_never_probes_unreserved_cases(tmp_path: Path) -> None:
    pinned, records = _runnable_cases()
    cases = tuple(case.model_copy(update={"dimensions": {}}) for case in pinned)

    class Builder:
        id = "qualification-routing-test/v1"

        def __call__(self, request: Any) -> StageCases:
            held = cases[4:]
            if request.stage > 1:
                # Case IDs are fresh, but the protected incident evidence is not.
                held = tuple(case.model_copy(update={"id": f"renamed-{case.id}"}) for case in held)
            return StageCases(cases[:4], held, records[:4], records[4:], "independent incident families")

    arguments = {"builder": Builder(), "agent_for": lambda pack: _PolicyAgent(pack, cases),
                 "exchange": _proposal, "out": tmp_path, "rounds": 1, "repeats": 2, "ablate": False,
                 "qualification": QualificationPolicy(trials=2, min_units=2)}
    result = campaign(packkit.resolve("agent:baseline"), stages=1, **arguments)
    stage = result.stages[0]
    assert stage.improve.promotions == 1
    assert stage.held_cases == 8 and stage.ledger.held_cases == 4
    vault = tmp_path / "stages" / "001" / "improve" / "qualification"
    seal = json.loads((vault / "seal.json").read_text())
    assert seal["policy"]["confidence"] == pytest.approx(.975)
    assert json.loads((vault / "trials" / "001.json").read_text())["confidence"] == pytest.approx(.9875)
    assert json.loads((tmp_path / "qualification.json").read_text())["policy"]["confidence"] == .95
    spent = set(seal["tranches"][0])
    for label in ("original", "current"):
        ledger = read_run(tmp_path / "stages" / "001" / "ledger" / label)
        assert {row.case_id for row in ledger.results} == spent
    extended = campaign(packkit.resolve("agent:baseline"), stages=2, **arguments)
    assert extended.stopped == "held_out_overlap"
    assert "reuse" in " ".join(extended.reasons)
    assert not (tmp_path / "stages" / "002" / "improve").exists()
    arguments["qualification"] = QualificationPolicy(trials=2, min_units=2, confidence=.9)
    with pytest.raises(ValueError, match="sealed qualification"):
        campaign(packkit.resolve("agent:baseline"), stages=2, **arguments)
