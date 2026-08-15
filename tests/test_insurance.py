"""The insurance vertical, increment 1: one phase-1 valuation, held to its
contract.

The episode's claims, each pinned: triangle diagonals are append-only
forever; the prior estimate is superseded by the strengthened one with no
marker that it was wrong; ultimate always reconciles to paid + case + IBNR;
the booked reserve always reconciles to the central estimate plus the
remaining margin; the attribution split always sums to the movement it
decomposes; a booked-below-central gap is illegal without a margin decision
memo citing both facts; the booked total is never superseded or closed; a
second `QuarterlyReserving` run refuses, naming increment 2; and the whole
thing replays byte-for-byte from its seed and from its own recipe.

Tamper tests follow the actor-suite and banking-suite convention: every
insurance check is shown *firing*, not just passing, because a check that has
never failed proves only that it compiles.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from typer.testing import CliRunner

from worldloom import (
    Authority,
    InsuranceWorld,
    QuarterlyReserving,
    World,
)
from worldloom.cli import app
from worldloom.evaluate import score
from worldloom.models import EvaluationType

runner = CliRunner()

PERIOD = "2026-06"
SEED = 8128


@pytest.fixture(scope="module")
def world() -> World:
    return InsuranceWorld(seed=SEED).build().run(QuarterlyReserving(period=PERIOD))


@pytest.fixture(scope="module")
def compiled(world: World) -> World:
    return world.compile()


def codes(world: World) -> set[str]:
    return {v.code for v in world.validate().violations}


# ---------------------------------------------------------------------------
# The episode is coherent
# ---------------------------------------------------------------------------


def test_the_episode_is_coherent(compiled: World) -> None:
    report = compiled.validate()
    assert report.ok, "\n".join(str(v) for v in report.violations)


def test_the_shape_of_the_episode(world: World) -> None:
    """The valuation's four artifacts plus the book's, one labelled
    imperfection, and all three mutation disciplines' fact kinds on the record.

    The count is ``4 + 1 + one per business unit``: the four the valuation
    warrants, the underwriting performance pack, and a commentary per division.
    Written as arithmetic rather than as ``8`` because the last term is a
    fan-out — widen the archetype and the right answer moves, which is the
    whole point of it (``insurance_documents``' own docstring).
    """
    units = len(world.business_units)
    assert len(world.artifact_intents) == 4 + 1 + units
    assert {i.artifact_type for i in world.artifact_intents} == {
        "reserve_triangle_workbook", "claims_emergence_note",
        "actuarial_valuation_report", "margin_decision_memo",
        "underwriting_performance_pack", "underwriting_result_commentary",
    }
    assert [i.artifact_type for i in world.artifact_intents][:4] == [
        "reserve_triangle_workbook", "claims_emergence_note",
        "actuarial_valuation_report", "margin_decision_memo",
    ], "ART order is identity; the book's documents are appended, never inserted"
    assert len(world.intentional_errors) == 1
    kinds = {f.kind for f in world.facts}
    assert {"close.due_date", "close.status", "close.delay"} <= kinds
    assert {"claims.paid_to_date", "claims.incurred_to_date",
            "reserves.ultimate", "reserves.ibnr",
            "claims.actual_vs_expected", "reserves.attribution_pattern_change",
            "reserves.attribution_deterioration", "reserves.committee_recommendation",
            "reserves.booked_strengthening", "reserves.margin_released",
            "reserves.held_vs_central_gap", "reserves.booked_total",
            "reserves.philosophy", "reserves.risk_margin_policy_pct"} <= kinds


def test_the_role_handle_is_resolved(world: World) -> None:
    assert "cat_lt_liability" in world._roles
    book = world.categories.by_id(world._roles["cat_lt_liability"])
    assert book.name == "Public and Products Liability"


def test_a_world_without_the_role_handle_is_refused() -> None:
    tampered_roles = InsuranceWorld(seed=SEED).build()
    stripped = replace(tampered_roles, _roles={
        k: v for k, v in tampered_roles._roles.items() if k != "cat_lt_liability"
    })
    with pytest.raises(ValueError, match="long-tail liability book"):
        stripped.run(QuarterlyReserving(period=PERIOD))


# ---------------------------------------------------------------------------
# The three mutation disciplines
# ---------------------------------------------------------------------------


def test_triangle_diagonals_are_append_only(world: World) -> None:
    for kind in ("claims.paid_to_date", "claims.incurred_to_date"):
        for fact in world.facts.where(kind=kind):
            assert fact.valid_to is None
            assert fact.supersedes is None


def test_a_touched_diagonal_trips_the_check(world: World) -> None:
    diagonal = world.facts.where(kind="claims.paid_to_date")[0]
    tampered = replace(world, _facts=tuple(
        f.model_copy(update={"valid_to": f.valid_from + timedelta(days=1)})
        if f.id == diagonal.id else f
        for f in world._facts
    ))
    assert "triangle_touched" in codes(tampered)


def test_the_prior_estimate_is_superseded_without_a_wrongness_marker(world: World) -> None:
    """The discipline this vertical exists to exercise: the superseded prior
    estimate carries no ruled-out fact, no different authority, nothing that
    marks it as having been wrong — only the closed validity window and the
    `supersedes` edge say it is not current."""
    strengthened = next(
        f for f in world.facts.where(kind="reserves.ultimate") if f.supersedes
    )
    prior = world.facts.by_id(strengthened.supersedes)
    assert prior.is_superseded
    assert prior.authority is strengthened.authority is Authority.CONFIRMED
    assert prior.valid_to == strengthened.valid_from


def test_exactly_one_unsuperseded_estimate_per_cohort(world: World) -> None:
    by_period: dict[str, list] = {}
    for fact in world.facts.where(kind="reserves.ultimate"):
        by_period.setdefault(fact.period, []).append(fact)
    for period, group in by_period.items():
        current = [f for f in group if not f.is_superseded]
        assert len(current) == 1, period


def test_a_second_live_estimate_trips_the_chain_check(world: World) -> None:
    strengthened = next(
        f for f in world.facts.where(kind="reserves.ultimate") if f.supersedes
    )
    rival = strengthened.model_copy(update={"id": "FACT-9901", "supersedes": None})
    tampered = replace(world, _facts=(*world._facts, rival))
    assert "estimate_chain_not_singular" in codes(tampered)


def test_booked_total_is_never_superseded(world: World) -> None:
    for fact in world.facts.where(kind="reserves.booked_total"):
        assert fact.valid_to is None
        assert fact.supersedes is None


def test_a_superseded_booked_total_trips_the_permanence_check(world: World) -> None:
    booked = world.facts.where(kind="reserves.booked_total")[-1]
    tampered = replace(world, _facts=tuple(
        f.model_copy(update={"valid_to": f.valid_from + timedelta(days=1)})
        if f.id == booked.id else f
        for f in world._facts
    ))
    assert "booked_total_touched" in codes(tampered)


# ---------------------------------------------------------------------------
# The reconciliation identities
# ---------------------------------------------------------------------------


def test_ultimate_reconciles_to_paid_plus_case_plus_ibnr(world: World) -> None:
    ultimates = world.facts.where(kind="reserves.ultimate")
    assert len(ultimates) == 8  # 4 cohorts x 2 valuations (prior, strengthened)
    assert world.validate().ok


def test_a_broken_ultimate_trips_the_reconciliation_check(world: World) -> None:
    ultimate = next(f for f in world.facts.where(kind="reserves.ultimate") if not f.is_superseded)
    tampered = replace(world, _facts=tuple(
        f.model_copy(update={"value": f.value.model_copy(update={"amount": f.value.amount + 500})})
        if f.id == ultimate.id else f
        for f in world._facts
    ))
    assert "ultimate_does_not_reconcile" in codes(tampered)


def test_booked_reconciles_to_central_plus_margin(world: World) -> None:
    booked = world.facts.where(kind="reserves.booked_total")
    assert len(booked) == 2
    assert world.validate().ok


def test_a_broken_booked_total_trips_the_reconciliation_check(world: World) -> None:
    booked = world.facts.where(kind="reserves.booked_total")[-1]
    tampered = replace(world, _facts=tuple(
        f.model_copy(update={"value": f.value.model_copy(update={"amount": f.value.amount + 500})})
        if f.id == booked.id else f
        for f in world._facts
    ))
    assert "booked_does_not_reconcile" in codes(tampered)


def test_attribution_sums_to_the_movement(world: World) -> None:
    pattern = world.facts.where(kind="reserves.attribution_pattern_change")[0]
    deterioration = world.facts.where(kind="reserves.attribution_deterioration")[0]
    central = sorted(world.facts.where(kind="reserves.central_estimate_total"),
                      key=lambda f: f.valid_from)
    movement = central[-1].value.amount - central[0].value.amount
    assert abs((pattern.value.amount + deterioration.value.amount) - movement) < 1.0
    # Deterioration is the majority share — the premise is a genuine
    # deterioration the corpus confirms, not an artefact split evenly.
    assert deterioration.value.amount > pattern.value.amount


def test_a_broken_attribution_trips_the_check(world: World) -> None:
    pattern = world.facts.where(kind="reserves.attribution_pattern_change")[0]
    tampered = replace(world, _facts=tuple(
        f.model_copy(update={"value": f.value.model_copy(update={"amount": f.value.amount + 500})})
        if f.id == pattern.id else f
        for f in world._facts
    ))
    assert "attribution_does_not_sum" in codes(tampered)


# ---------------------------------------------------------------------------
# The standing gap and its explanation
# ---------------------------------------------------------------------------


def test_the_booked_reserve_sits_below_the_central_estimate(world: World) -> None:
    """The trap `generators.triangles.generate` is sized to guarantee, not
    merely risk: this quarter's margin release exceeds the standing margin."""
    gap = world.facts.where(kind="reserves.held_vs_central_gap")[0]
    assert gap.value.amount > 0
    assert world.validate().ok


def test_the_gap_is_explained_by_the_memo(compiled: World) -> None:
    memo = next(a for a in compiled.artifacts if a.artifact_type == "margin_decision_memo")
    central = compiled.facts.where(kind="reserves.central_estimate_total")[-1]
    booked = compiled.facts.where(kind="reserves.booked_total")[-1]
    assert central.id in memo.supporting_fact_ids
    assert booked.id in memo.supporting_fact_ids


def test_an_unexplained_gap_trips_the_override_check(compiled: World) -> None:
    memo = next(a for a in compiled.artifacts if a.artifact_type == "margin_decision_memo")
    stripped = memo.model_copy(update={
        "supporting_fact_ids": [f for f in memo.supporting_fact_ids
                                 if f not in {
                                     compiled.facts.where(kind="reserves.central_estimate_total")[-1].id,
                                     compiled.facts.where(kind="reserves.booked_total")[-1].id,
                                 }]
    })
    tampered = replace(compiled, _artifacts=tuple(
        stripped if a.id == memo.id else a for a in compiled._artifacts
    ))
    assert "unexplained_override" in codes(tampered)


def test_the_actuary_reports_outside_the_cfo(world: World) -> None:
    """The independent reporting line this vertical needs: the central
    estimate and the booked reserve have to be able to disagree without that
    reading as one function overruling itself."""
    ceo = world.people.by_id(world._roles["ceo"])
    cfo = world.people.by_id(world._roles["cfo"])
    chief_actuary = world.people.by_id(world._roles["chief_actuary"])
    assert chief_actuary.manager_id == ceo.id
    assert chief_actuary.manager_id != cfo.id


# ---------------------------------------------------------------------------
# The phase-1 boundary
# ---------------------------------------------------------------------------


def test_a_second_quarter_refuses_naming_increment_2(world: World) -> None:
    with pytest.raises(ValueError, match="increment 1 implements phase 1 only"):
        world.run(QuarterlyReserving(period="2026-09"))


def test_cli_second_period_refuses_cleanly(tmp_path) -> None:
    """Refused before the first episode runs, and printed rather than raised.

    This test is older than the behaviour it now asserts, and the comment it
    used to carry is worth keeping as a record: the guard raised from inside
    `insurance_scenarios` on the *second* run, the CLI let it propagate, and so
    `CliRunner` found it on `result.exception` with `result.output` empty —
    a `ValueError` traceback in the terminal and no corpus. The test passed,
    because "refuses" and "refuses cleanly" are not the same claim and only one
    of them was being checked.

    `build` now reads the cap the domain already declares — `Domain.max_periods`,
    which existed for `tools/sweep.py` to clamp its periods axis by — so the
    refusal happens at plan time and names the limit. Asserted on `output` with
    `exception` explicitly absent, since that distinction is the entire fix.
    """
    result = runner.invoke(app, [
        "build", "--seed", str(SEED), "--period", PERIOD,
        "--archetype", "midsize_general_insurer", "--periods", "2",
        "--out", str(tmp_path / "x"),
    ])
    assert result.exit_code == 2
    assert "builds at most 1 period(s)" in result.output
    assert not isinstance(result.exception, ValueError)
    # Nothing was written: a refusal that leaves a half-built corpus behind is
    # the thing a plan-time check exists to avoid.
    assert not (tmp_path / "x").exists()


def test_the_cap_is_read_from_the_domain_not_written_into_the_cli() -> None:
    """The declaration is the single source, which is why the message can quote it.

    A CLI that hardcoded "insurance is capped at 1" would be a second place to
    update when increment 2 lands, and the failure mode is a tool that refuses
    a period the engine has learned to build. `tools/sweep.py` reads the same
    field for the same reason.
    """
    from worldloom import domains

    assert domains.for_archetype("midsize_general_insurer").max_periods == 1
    # And the verticals that carry a history declare no cap, rather than a
    # large one — an unmeasured limit is not a limit.
    for key in ("midsize_adi", "midsize_infrastructure_services"):
        assert domains.for_archetype(key).max_periods is None
    # The cap is about `QuarterlyReserving` and not about insurance, which is
    # `test_episode_replaces.py`'s four-quarter build: an authored
    # `QuarterlyValuation` standing in for the built-in is a different grammar
    # with its own limits, and it is not bound by this one.


def test_cli_still_refuses_the_retail_only_flags_for_insurance(tmp_path) -> None:
    result = runner.invoke(app, [
        "build", "--archetype", "midsize_general_insurer", "--incident",
        "--out", str(tmp_path / "x"),
    ])
    assert result.exit_code == 2
    assert "belong(s) to the retail close" in result.output


# ---------------------------------------------------------------------------
# The pinning test: no core check groups reserves.*/claims.* by period
# ---------------------------------------------------------------------------


def test_no_core_check_groups_this_verticals_facts_by_period() -> None:
    """The `fact.period` pun (design record, risk 1) is safe only because
    core period-keyed checks are vocabulary-scoped. This pins that no core
    module's *code* (comments and docstrings stripped — the same discipline
    `test_thin_waist.py` uses, duplicated in miniature here rather than
    imported, since ``tests/`` carries no ``__init__.py`` for a cross-file
    import to resolve against) ever names `reserves.` or `claims.` beside
    `.period` — the exact exception the design record says would be the
    signal a Cohort/population axis extraction is due, not a check to relax.
    """
    import io
    import tokenize
    from pathlib import Path

    # Duplicated from `test_thin_waist.CORE_MODULES` rather than imported
    # across test files (`tests/` carries no `__init__.py`): the two lists
    # must be kept in step by hand, which is an acceptable cost for a pin
    # that only ever grows more modules to check, never fewer.
    CORE_MODULES = (
        "models.py", "world.py", "ids.py", "rng.py", "corpus.py", "collections.py",
        "validate.py", "domains.py", "packs.py", "recipe.py", "cli.py",
        "documents.py",
        # The analysis layer, core by construction: `graphs` backs validator
        # checks that run on every corpus, and neither `series` nor
        # `similarity` knows what industry it is reading.
        "graphs.py", "series.py", "similarity.py",
        "generators/org_builder.py", "generators/cases.py",
        "generators/communications.py", "generators/hierarchy.py",
        "render/__init__.py", "render/markdown.py", "render/xlsx.py",
        "render/docx.py", "render/pptx.py", "render/pdf.py", "render/bundles.py",
        "render/ooxml.py", "render/values.py",
        "evaluate/__init__.py", "evaluate/bm25.py", "evaluate/index.py",
        "evaluate/score.py",
        "narrative/claims.py", "narrative/compiler.py", "narrative/handshake.py",
        "narrative/references.py", "narrative/requests.py",
    )

    def code_only(source: str) -> str:
        out: list[str] = []
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            if token.type not in (tokenize.NL, tokenize.NEWLINE):
                out.append(token.string)
        return " ".join(out)

    src = Path("src/worldloom")
    for module in CORE_MODULES:
        code = code_only((src / module).read_text(encoding="utf-8"))
        assert "reserves." not in code, module
        assert "claims." not in code, module


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------


def test_the_same_seed_rebuilds_the_same_world(world: World) -> None:
    again = InsuranceWorld(seed=SEED).build().run(QuarterlyReserving(period=PERIOD))
    assert [f.model_dump() for f in again.facts] == [f.model_dump() for f in world.facts]
    assert [e.model_dump() for e in again.events] == [e.model_dump() for e in world.events]


def test_the_recipe_rebuilds_the_world(world: World, tmp_path) -> None:
    from worldloom.recipe import rebuild

    exported = world.compile().export(tmp_path / "ins")
    loaded = World.load(exported)
    again = rebuild(loaded.recipe)
    assert [f.model_dump() for f in again.facts] == [f.model_dump() for f in world.facts]


def test_export_then_replay_is_byte_identical(world: World, tmp_path) -> None:
    from worldloom.narrative import DeterministicProvider, UnreachableProvider

    formats = ("xlsx", "docx", "markdown")
    first = world.narrate(DeterministicProvider()).render(*formats)
    first.export(tmp_path / "one")
    rendered = {p.name for p in (tmp_path / "one" / "artifacts").iterdir()}
    assert any(n.startswith("art-0001") and n.endswith(".xlsx") for n in rendered), (
        "the triangle workbook is a source artifact and must render as a real workbook"
    )
    assert not any(n.startswith("art-0001") and n.endswith(".md") for n in rendered), (
        "the workbook is a source artifact; markdown must not shadow it with a flat projection"
    )

    again = InsuranceWorld(seed=SEED).build().run(QuarterlyReserving(period=PERIOD))
    again = again.narrate(UnreachableProvider(), ledger=first._ledger)
    again = again.render(*formats)
    again.export(tmp_path / "two")

    one = sorted((tmp_path / "one").rglob("*"))
    two = sorted((tmp_path / "two").rglob("*"))
    assert [p.relative_to(tmp_path / "one") for p in one] == [
        p.relative_to(tmp_path / "two") for p in two
    ]
    for left, right in zip(one, two):
        if left.is_file():
            assert left.read_bytes() == right.read_bytes(), left.name


def test_cli_dispatches_to_the_insurance_vertical(world: World, tmp_path) -> None:
    out = tmp_path / "insurance-cli"
    result = runner.invoke(app, [
        "build", "--seed", str(SEED), "--period", PERIOD,
        "--archetype", "midsize_general_insurer", "--out", str(out),
    ])
    assert result.exit_code == 0, result.output
    loaded = World.load(out)
    assert [step["period"] for step in loaded.recipe["steps"]] == [PERIOD]
    assert [f.model_dump() for f in loaded.facts] == [f.model_dump() for f in world.facts]


# ---------------------------------------------------------------------------
# Evaluation: all seven families populated and reachable
# ---------------------------------------------------------------------------


def test_every_family_is_populated(world: World) -> None:
    families = {c.evaluation_type for c in world.evaluations}
    assert families == {
        EvaluationType.TEMPORAL_STATE,
        EvaluationType.AUTHORITY_RESOLUTION,
        EvaluationType.CAUSAL_MULTI_HOP,
        EvaluationType.NUMERICAL_COMPARISON,
        EvaluationType.CROSS_ARTIFACT,
        EvaluationType.EXPECTED_ABSTENTION,
        EvaluationType.CITATION_REQUIRED,
    }


def test_every_answer_is_reachable(world: World) -> None:
    reachable: set[str] = set()
    for intent in world.artifact_intents:
        reachable.update(intent.required_fact_ids)
    for case in world.evaluations:
        if not case.expects_abstention:
            assert set(case.expected_fact_ids) <= reachable, case.id


def test_the_authority_family_inverts_for_the_central_estimate_question(world: World) -> None:
    """The design record's sharpest claim, measured: SYSTEM_OF_RECORD
    outranks CONFIRMED (`models.AUTHORITY_RANK`), so a retriever that always
    prefers rank fails the "what did the actuary estimate" question and
    passes the "what is booked" one — the exact inversion, not a tie."""
    from worldloom.models import AUTHORITY_RANK
    from worldloom.narrative import DeterministicProvider

    assert AUTHORITY_RANK[Authority.SYSTEM_OF_RECORD] > AUTHORITY_RANK[Authority.CONFIRMED]

    scored = world.narrate(DeterministicProvider()).render("markdown")
    card = score(scored, k=5)
    central_case = next(
        c for c in scored.evaluations
        if c.evaluation_type is EvaluationType.AUTHORITY_RESOLUTION
        and "central estimate" in c.question
    )
    outcome = next(o for o in card.outcomes if o.case_id == central_case.id)
    assert not outcome.passed
