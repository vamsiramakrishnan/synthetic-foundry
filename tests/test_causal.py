"""Causal models: declared, linted, evaluated, recorded, recomputed, replayed.

The property that makes causally-driven mess safe is the same one
``test_messiness.py`` pins for authored mess — every imperfection is
establishable from the corpus — plus one more this file adds: **every derived
value in a trace is recomputable from its recorded parents**, and the
``causal`` validator group refuses a trace that drifted from its own model.
The label "this stale page exists because the error rate rose" is then not the
generator vouching for itself; it is arithmetic anyone holding the corpus can
redo.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import MonthEndClose, RetailWorld, World, causal
from worldloom.cli import app
from worldloom.recipe import rebuild
from worldloom.rng import Rng
from worldloom.scenarios import Departure

runner = CliRunner()


def _model(**changes) -> dict:
    payload = json.loads(json.dumps(causal.TEMPLATE))
    payload.update(changes)
    return payload


# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------


def test_the_template_is_clean() -> None:
    assert causal.lint(causal.from_document(causal.TEMPLATE)) == []


def test_lint_names_every_structural_defect() -> None:
    model = causal.from_document(_model(
        nodes=[
            {"name": "a", "level": 1.0, "parameter": "retail.margin.budget"},  # two sources
            {"name": "b", "depends_on": ["a", "ghost"], "weights": {"a": 1.0}},  # unknown parent, weights mismatch
            {"name": "c", "depends_on": ["d"], "weights": {"d": 1.0}},
            {"name": "d", "depends_on": ["c"], "weights": {"c": 1.0}},  # cycle
            {"name": "e", "parameter": "ops.incident.likelihood"},  # a chance, not a level
            {"name": "f", "level": 0.5, "low": 1.0, "high": 0.0},  # inverted clamp
        ],
        interventions=[{"at": "2026-01", "node": "nobody", "value": 1.0, "reason": "r"}],
        drives=[
            {"node": "a", "imperfection": "staleness", "scale": 1},
            {"node": "b", "imperfection": "staleness", "scale": 1},
            {"node": "zz", "imperfection": "rust", "scale": 1},
        ],
    ))
    findings = "\n".join(causal.lint(model))
    for expected in (
        "exactly one of parameter, level, or depends_on",
        "depends on 'ghost', which is not declared",
        "weights key ['a'] but depends_on is ['a', 'ghost']",
        "not a DAG",
        "a chance",
        "clamp [1.0, 0.0] is inverted",
        "sets 'nobody', which is not declared",
        "reads 'zz', which is not declared",
        "budgets 'rust'",
        "2 drives budget 'staleness'",
    ):
        assert expected in findings, expected


def test_a_driven_node_must_declare_a_non_negative_floor() -> None:
    """A budget is a count. Without the floor, `causal check` passed a model whose
    node could go negative and `build --causal` then failed inside `Messiness`
    (Codex review, PR #40); the sign is now a property of the declaration."""
    unfloored = causal.from_document(_model(
        nodes=[{"name": "rate", "level": 0.1}], interventions=[],
        drives=[{"node": "rate", "imperfection": "staleness", "scale": 10}],
    ))
    assert any("non-negative `low`" in f for f in causal.lint(unfloored))
    negative_floor = causal.from_document(_model(
        nodes=[{"name": "rate", "level": -1.0, "low": -5.0}], interventions=[],
        drives=[{"node": "rate", "imperfection": "staleness", "scale": 10}],
    ))
    assert any("non-negative `low`" in f for f in causal.lint(negative_floor))
    floored = causal.from_document(_model(
        nodes=[{"name": "rate", "level": -1.0, "low": 0.0}], interventions=[],
        drives=[{"node": "rate", "imperfection": "staleness", "scale": 10}],
    ))
    assert causal.lint(floored) == []
    [only] = causal.evaluate(floored, ["2026-01"], rng=Rng(1))
    assert only.values["rate"] == 0.0 and only.budgets == {"staleness": 0}


def test_an_unknown_physics_parameter_is_a_finding() -> None:
    model = causal.from_document(_model(nodes=[{"name": "a", "parameter": "retail.margin.budgt"}]))
    assert any("physics registry does not carry" in f for f in causal.lint(model))


def test_evaluate_refuses_a_model_with_findings() -> None:
    model = causal.from_document(_model(nodes=[{"name": "a", "depends_on": ["a"], "weights": {"a": 1.0}}]))
    with pytest.raises(ValueError, match="lint findings"):
        causal.evaluate(model, ["2026-01"], rng=Rng(1))


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def test_derived_values_are_the_linear_rule_and_interventions_persist() -> None:
    model = causal.from_document(causal.TEMPLATE)
    trace = causal.evaluate(model, ["2026-03", "2026-04", "2026-05"], rng=Rng(8128).derive("causal"))
    march, april, may = trace
    assert march.interventions == [] and april.interventions == [0] and may.interventions == [0]
    assert march.values["manual_touch_rate"] == 0.15
    assert april.values["manual_touch_rate"] == 0.35 == may.values["manual_touch_rate"]
    for period in trace:
        spec = model.node("invoice_error_rate")
        assert period.values["invoice_error_rate"] == causal.recompute(spec, period.values)
    # The cascade: a higher touch rate is a higher error rate is a longer delay.
    assert april.values["invoice_error_rate"] > march.values["invoice_error_rate"]
    assert april.values["payment_delay_days"] > march.values["payment_delay_days"]
    assert april.budgets == {"staleness": round(april.values["invoice_error_rate"] * 20),
                             "disagreement": round(april.values["payment_delay_days"] * 0.25)}


def test_clamps_hold_and_the_order_is_topological_and_sorted() -> None:
    model = causal.from_document(_model(
        nodes=[
            {"name": "z_root", "level": 5.0},
            {"name": "a_leaf", "depends_on": ["z_root"], "weights": {"z_root": 3.0}, "high": 10.0},
        ], interventions=[], drives=[],
    ))
    assert causal.order(model) == ["z_root", "a_leaf"]
    [only] = causal.evaluate(model, ["2026-01"], rng=Rng(1))
    assert only.values["a_leaf"] == 10.0


def test_an_exogenous_draw_is_named_for_its_node_and_period() -> None:
    """Adding a node cannot move another's draws."""
    one = causal.from_document(_model(
        nodes=[{"name": "miss", "parameter": "retail.revenue.miss_pct"}], interventions=[], drives=[],
    ))
    two = causal.from_document(_model(
        nodes=[{"name": "extra", "parameter": "retail.margin.erosion"},
               {"name": "miss", "parameter": "retail.revenue.miss_pct"}], interventions=[], drives=[],
    ))
    a = causal.evaluate(one, ["2026-01", "2026-02"], rng=Rng(3).derive("causal"))
    b = causal.evaluate(two, ["2026-01", "2026-02"], rng=Rng(3).derive("causal"))
    assert [p.values["miss"] for p in a] == [p.values["miss"] for p in b]
    assert a[0].values["miss"] != a[1].values["miss"]


# ---------------------------------------------------------------------------
# On a world
# ---------------------------------------------------------------------------


def _base() -> World:
    return (
        RetailWorld(seed=4242).build()
        .run(MonthEndClose(period="2026-03", include_operational_incident=True))
        .run(Departure("2026-03", "controller"))
        .run(MonthEndClose(period="2026-04", include_operational_incident=True))
        .run(MonthEndClose(period="2026-05"))
    )


@pytest.fixture(scope="module")
def before() -> World:
    return _base()


@pytest.fixture(scope="module")
def after(before: World) -> World:
    return causal.apply(before, causal.TEMPLATE)


def test_a_world_without_a_model_is_untouched(before: World) -> None:
    root = Path(tempfile.mkdtemp()) / "pristine"
    before.export(root)
    assert not (root / "causal.jsonl").exists()
    assert "Causal" not in [step["scenario"] for step in before.recipe["steps"]]
    assert not list(before.causal)


def test_the_trace_is_recorded_events_minted_and_mess_delivered_within_budget(after: World, before: World) -> None:
    [trace] = list(after.causal)
    assert [p.period for p in trace.periods] == ["2026-03", "2026-04", "2026-05"]
    assert trace.budgets == {"disagreement": 6, "staleness": 6}
    for kind, count in trace.delivered.items():
        assert 0 <= count <= trace.budgets[kind]
    assert len(after.intentional_errors) - len(before.intentional_errors) == sum(trace.delivered.values())
    assert trace.delivered["staleness"] > 0, "the world had corrections to be stale about"
    events = {e.id: e for e in after.events}
    [event_id] = trace.event_ids
    assert events[event_id].kind == "causal.intervention"
    assert "ERP migration cut-over" in events[event_id].summary
    assert events[event_id].occurred_at.strftime("%Y-%m") == "2026-04"
    assert [s["scenario"] for s in after.recipe["steps"]][-1] == "Causal"
    assert "Imperfections" not in [s["scenario"] for s in after.recipe["steps"]]


def test_the_world_validates_and_every_imperfection_is_still_establishable(after: World) -> None:
    report = after.validate()
    assert report.ok, [str(v) for v in report.violations]


def test_export_load_and_replay_are_byte_identical(after: World) -> None:
    root = Path(tempfile.mkdtemp()) / "corpus"
    after.export(root)
    assert (root / "causal.jsonl").exists()
    loaded = World.load(root)
    assert list(loaded.causal) == list(after.causal)
    assert loaded.validate().ok
    replayed = rebuild(loaded.recipe)
    again = Path(tempfile.mkdtemp()) / "replayed"
    replayed.export(again)
    for path in sorted(root.iterdir()):
        assert path.read_bytes() == (again / path.name).read_bytes(), path.name


def test_the_validator_refuses_a_trace_that_drifted_from_its_model(after: World) -> None:
    [trace] = list(after.causal)
    first = trace.periods[0]
    tampered_values = {**first.values, "payment_delay_days": first.values["payment_delay_days"] + 1.0}
    tampered = trace.model_copy(update={
        "periods": [first.model_copy(update={"values": tampered_values}), *trace.periods[1:]],
    })
    world = replace(after, _causal=(tampered,))
    report = world.validate()
    codes = {v.code for v in report.violations if v.group == "causal"}
    assert "derived_drift" in codes


def test_the_validator_refuses_over_delivery_and_a_missing_event(after: World) -> None:
    [trace] = list(after.causal)
    over = trace.model_copy(update={"delivered": {**trace.delivered, "staleness": 99}})
    assert "over_delivered" in {v.code for v in replace(after, _causal=(over,)).validate().violations}
    orphaned = trace.model_copy(update={"event_ids": ["EV-9999"]})
    assert "event_missing" in {v.code for v in replace(after, _causal=(orphaned,)).validate().violations}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_check_and_trace(tmp_path: Path) -> None:
    result = runner.invoke(app, ["causal", "check", "--template"])
    assert result.exit_code == 0
    model = tmp_path / "model.json"
    model.write_text(result.output)
    assert runner.invoke(app, ["causal", "check", str(model)]).exit_code == 0
    traced = runner.invoke(app, ["causal", "trace", str(model), "--periods", "3", "--period", "2026-03", "--json"])
    assert traced.exit_code == 0, traced.output
    payload = json.loads(traced.output)
    assert [p["period"] for p in payload] == ["2026-03", "2026-04", "2026-05"]
    assert payload[1]["interventions"] == [0]

    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(_model(nodes=[{"name": "a", "depends_on": ["a"], "weights": {"a": 1.0}}])))
    result = runner.invoke(app, ["causal", "check", str(broken)])
    assert result.exit_code == 1 and "depends on itself" in result.output


def test_cli_build_refuses_a_driving_model_beside_messiness(tmp_path: Path) -> None:
    model = tmp_path / "model.json"
    model.write_text(json.dumps(causal.TEMPLATE))
    result = runner.invoke(app, [
        "build", "--seed", "8128", "--periods", "2", "--causal", str(model),
        "--messiness", "lived_in", "--out", str(tmp_path / "corpus"),
    ])
    assert result.exit_code == 2
    assert "spend" in result.output


def test_cli_build_under_a_model_writes_the_trace_and_validates(tmp_path: Path) -> None:
    model = tmp_path / "model.json"
    model.write_text(json.dumps(causal.TEMPLATE))
    out = tmp_path / "corpus"
    result = runner.invoke(app, [
        "build", "--seed", "8128", "--periods", "3", "--incident", "--causal", str(model), "--out", str(out),
    ])
    assert result.exit_code == 0, result.output
    assert (out / "causal.jsonl").exists()
    assert runner.invoke(app, ["validate", str(out)]).exit_code == 0
    world = World.load(out)
    assert [s["scenario"] for s in world.recipe["steps"]][-1] == "Causal"
