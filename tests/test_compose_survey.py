"""Commands that survey a corpus must report an unsatisfiable plan, not raise.

Three ways of building a corpus took `worldloom diversity` (and every other
reader of the shape census) down with a traceback, at *any* size — a
35-artifact build was enough:

* any banking corpus, on `capital_return`'s "Capital position" sheet;
* any insurance corpus, on `reserve_triangle_workbook`'s "Book position" sheet;
* a malformed stale draft of an `incident_rca`.

Two different defects wearing one symptom, and they are fixed differently, which
is most of what this file exists to pin.

The first two are a **hole in the component registry**: the `position` and
`decision` roles were declared reachable in ``xlsx`` and had no component that
could actually spell them there at the row counts a workbook sheet arrives with.
That is fixed — the roles now resolve — and `compiler/audit.py` grew a static
check so the next such hole is a warning off the declarations rather than a
traceback three layers downstream.

The third is **not** a hole: an `incident_rca` labelled
``size_profile="small"`` resolves to six required sections against a size-class
cap of four, and every available repair is worse than the report. Widening the
cap deletes the distinction between `small` and `long`; dropping a required
beat ships a document missing part of its argument. Real stale drafts now keep
their final document's size profile, so the fixture below deliberately injects
the malformed label. The composer still refuses, and the *commands* carry on
and say which artifact refused and why — which is the invariant this file
spends most of its assertions on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import RetailWorld, mcp, stats
from worldloom.cli import app
from worldloom.compiler.audit import WARNING, audit
from worldloom.compiler.components import REGISTRY, roles_for
from worldloom.compiler.compose import (
    Composition,
    CompositionError,
    compose,
    try_compose,
)
from worldloom.compiler.plan import DENSITY_POINTS, ArtifactPlan, NarrativeBeat
from worldloom.scenarios import MonthEndClose
from worldloom.world import World

runner = CliRunner()


def _plan(*, beats: list[NarrativeBeat], size_class: str = "small") -> ArtifactPlan:
    return ArtifactPlan(
        intent_id="ART-0001",
        artifact_type="incident_rca",
        audience="technology",
        intent="a plan that cannot be met",
        beats=beats,
        size_class=size_class,  # type: ignore[arg-type]
        density_profile="balanced",
    )


def _beat(key: str, role: str, *, optional: bool = False) -> NarrativeBeat:
    return NarrativeBeat(key=key, purpose=key, evidence=[], semantic_role=role, optional=optional)


# ---------------------------------------------------------------------------
# 1. The registry hole, closed and kept closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["position", "decision"])
def test_a_workbook_sheet_can_be_spelled_for_every_role_it_claims(role: str) -> None:
    """Both roles a real workbook asked for and the registry could not answer.

    ``rows=0`` is the case that mattered and is easy to read as an edge case:
    it is not one. `compose.plan_from_ir` derives a beat's row count from
    `ArtifactSection.fact_ids`, and a workbook sheet's facts live on the table
    *cells*, so a fully-populated sheet arrives with no rows — the normal shape,
    not a degenerate one.
    """
    candidates = roles_for(role, fmt="xlsx")
    assert candidates, f"{role!r} must be reachable in a workbook at all"
    for rows in (0, 1, 5):
        assert any(
            spec.fits(fmt="xlsx", density=DENSITY_POINTS["balanced"], rows=rows)
            for spec in candidates
        ), f"no xlsx component fits {role!r} with {rows} row(s)"


def test_the_sheet_component_is_not_preferred_over_a_grid_it_used_to_lose_to() -> None:
    """The one ordering interaction adding `position` to `xlsx.report_sheet`
    creates, pinned so a later reorder of the registry cannot silently change a
    shape that already composed.

    `xlsx.report_sheet` is declared before `finance.kpi_grid`, and the composer
    takes the first fitting candidate, so an xlsx `position` beat carrying 8-20
    rows now resolves to the sheet where it previously resolved to the grid. No
    corpus produces that beat — every xlsx `position` beat in this repository
    carries zero rows — which is why the change was safe. This test states the
    *behaviour* so that "no corpus produces it" stops being the only thing
    holding it up.
    """
    at_zero = [
        spec.component_id for spec in roles_for("position", fmt="xlsx")
        if spec.fits(fmt="xlsx", density=DENSITY_POINTS["balanced"], rows=0)
    ]
    assert at_zero[0] == "xlsx.report_sheet"
    at_ten = [
        spec.component_id for spec in roles_for("position", fmt="xlsx")
        if spec.fits(fmt="xlsx", density=DENSITY_POINTS["balanced"], rows=10)
    ]
    assert at_ten[0] == "xlsx.report_sheet"
    assert "finance.kpi_grid" in at_ten, "the grid must still be a candidate, just not the first"


def test_the_audit_finds_a_row_coverage_hole_statically() -> None:
    """The check that would have caught the crash from the declarations alone.

    Built by removing the component that closes the hole rather than by
    inventing a broken registry: the finding has to fire on the *real* shape of
    the defect, and a hand-written fixture proves only that the checker agrees
    with whoever wrote the fixture.
    """
    without_sheet = tuple(s for s in REGISTRY if s.component_id != "xlsx.report_sheet")
    codes = {(f.code, f.subject) for f in audit(without_sheet, {})}
    assert ("role_row_coverage_gap", "position/xlsx") in codes

    # And it does not fire for the pair the shipped registry now covers.
    shipped = {(f.code, f.subject) for f in audit()}
    assert ("role_row_coverage_gap", "position/xlsx") not in shipped
    assert ("role_row_coverage_gap", "decision/xlsx") not in shipped


def test_a_coverage_gap_is_a_warning_rather_than_an_error() -> None:
    """On the module's own line between the two severities: a gap is provable
    from the declarations, but calling it *unsatisfiable* would need to know
    that some plan will ask for exactly this role, format, density and row
    count — and static analysis of a registry has no view of a future plan.
    Same argument `unreachable_component` records."""
    findings = [f for f in audit() if f.code == "role_row_coverage_gap"]
    assert findings, "the shipped registry still has holes worth reporting"
    assert all(f.severity == WARNING for f in findings)


def test_a_role_a_format_never_offers_is_not_reported_as_a_gap() -> None:
    """Nothing says every role has to be spellable in every format. Reporting
    each absent combination would emit hundreds of findings about a vocabulary
    nobody asked to be total, which is how a checker teaches people to stop
    reading it."""
    offered = {
        (role, fmt)
        for spec in REGISTRY
        for role in spec.semantic_roles
        for fmt in spec.supported_formats
    }
    for finding in audit():
        if finding.code == "role_row_coverage_gap":
            role, _, fmt = finding.subject.partition("/")
            assert (role, fmt) in offered


# ---------------------------------------------------------------------------
# 2. compose still refuses; try_compose hands the refusal back
# ---------------------------------------------------------------------------


def test_an_over_budget_plan_is_refused_rather_than_trimmed() -> None:
    """The refusal this file argues should stay. Six required beats against a
    cap of four, and the composer must not quietly ship four of them."""
    plan = _plan(beats=[_beat(f"b{i}", "explanation") for i in range(6)])
    with pytest.raises(CompositionError) as caught:
        compose(plan, fmt="docx")
    assert caught.value.code == "over_budget"
    assert caught.value.artifact_type == "incident_rca"
    assert "6" in caught.value.detail and "4" in caught.value.detail


def test_a_composition_error_is_a_value_error_so_old_handlers_still_catch_it() -> None:
    """`cli.py`, the pptx renderer, the pdf renderer and the compiler's own
    tests all wrote `except ValueError` before this class existed. A new
    exception hierarchy would have made every one of them stop catching."""
    plan = _plan(beats=[_beat(f"b{i}", "explanation") for i in range(6)])
    with pytest.raises(ValueError):
        compose(plan, fmt="docx")
    assert issubclass(CompositionError, ValueError)


def test_try_compose_returns_the_refusal_instead_of_raising() -> None:
    over_budget = try_compose(
        _plan(beats=[_beat(f"b{i}", "explanation") for i in range(6)]), fmt="docx"
    )
    assert isinstance(over_budget, CompositionError)
    assert over_budget.code == "over_budget"

    unfittable = try_compose(
        _plan(beats=[_beat("only", "structure")], size_class="long"), fmt="xlsx"
    )
    assert isinstance(unfittable, CompositionError)
    assert unfittable.code == "no_fitting_component"


def test_try_compose_returns_a_composition_when_the_plan_is_satisfiable() -> None:
    """The other half — a wrapper that returned an error for everything would
    pass every test above."""
    result = try_compose(_plan(beats=[_beat("summary", "summary")], size_class="long"), fmt="docx")
    assert isinstance(result, Composition)
    assert result.components


def test_try_compose_does_not_swallow_an_unrelated_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It catches `CompositionError`, not `Exception`. A survey that turned a
    genuine bug into a row in a report would be the worse failure of the two —
    this exists to make a crash reportable, not to make it invisible.

    Provoked by breaking the size-class table rather than by handing `compose`
    bad input, because there is no bad input left to hand it: `ArtifactPlan` is
    validated at construction, so every reachable failure inside `compose` is
    either a `CompositionError` or an internal defect, and an internal defect is
    exactly what must not be caught.
    """
    from worldloom.compiler import compose as compose_module

    monkeypatch.delitem(compose_module._COMPONENT_CAP, "small")
    with pytest.raises(KeyError):
        try_compose(_plan(beats=[_beat("b", "explanation")]), fmt="docx")


# ---------------------------------------------------------------------------
# 3. The commands, on the corpora that used to take them down
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def distractor_corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The 35-artifact build from the bug report, with its old defect injected.

    ``--distractors`` is by far the cheapest way to grow a corpus — thousands of
    artifacts with the fact count unchanged — so it being the axis that crashed
    is what made this worth fixing rather than working around.
    """
    out = tmp_path_factory.mktemp("distractors") / "corpus"
    result = runner.invoke(
        app, ["build", "--seed", "8128", "--incident", "--distractors", "20", "-o", str(out)]
    )
    assert result.exit_code == 0, result.output

    # Stale drafts now preserve the final's document grammar. Keep the survey
    # refusal exercised without making every real distractor corpus malformed:
    # reproduce the historical bad label explicitly in this one fixture.
    world = World.load(str(out))
    rca = next(intent for intent in world.artifact_intents if intent.artifact_type == "incident_rca")
    malformed = rca.model_copy(update={"size_profile": "small"})
    world.extend(artifact_intents=(malformed,)).export(out, overwrite=True)
    return out


@pytest.mark.parametrize("archetype", ["midsize_adi", "midsize_general_insurer"])
def test_diversity_reports_on_a_banking_or_insurance_corpus(
    archetype: str, tmp_path: Path
) -> None:
    """Both verticals crashed on a registry hole; both now report."""
    out = tmp_path / archetype
    built = runner.invoke(app, ["build", "-a", archetype, "--seed", "8128", "-o", str(out)])
    assert built.exit_code == 0, built.output

    result = runner.invoke(app, ["diversity", str(out)])
    assert result.exit_code == 0, result.output
    assert "Diversity —" in result.output
    assert "distinct shape(s)" in result.output


def test_diversity_reports_the_artifacts_it_could_not_compose(distractor_corpus: Path) -> None:
    """The one that is not a registry hole. The command has to finish, name the
    artifact, and say which kind of refusal it was."""
    result = runner.invoke(app, ["diversity", str(distractor_corpus)])
    assert result.exit_code == 0, result.output
    assert "Diversity —" in result.output
    assert "over_budget" in result.output
    assert "incident_rca" in result.output


def test_the_uncomposable_warning_precedes_the_census_it_qualifies(
    distractor_corpus: Path,
) -> None:
    """Order, not merely presence. A reader who takes "10 artifact(s), 9
    distinct shape(s)" away has taken a number computed over a subset, and a
    footnote printed after it has already missed them."""
    output = runner.invoke(app, ["diversity", str(distractor_corpus)]).output
    assert output.index("no composable shape") < output.index("Diversity —")


def test_an_uncomposable_artifact_is_not_a_failing_exit_code(
    distractor_corpus: Path,
) -> None:
    """Nothing here is a failure of `diversity`. A corpus with an unsatisfiable
    plan is still a corpus worth reporting on, and an exit code would make CI
    treat "we measured it" as "we could not"."""
    assert runner.invoke(app, ["diversity", str(distractor_corpus)]).exit_code == 0


def test_measure_corpus_reports_rather_than_crashing(distractor_corpus: Path) -> None:
    """The MCP tool is the census's other front door, and has to survive the
    same corpus `diversity` does — a tool error is data an agent can act on,
    but a refusal to measure a measurable corpus is not."""
    reading = mcp.call("measure_corpus", {"corpus": str(distractor_corpus)})
    assert "error" not in reading, reading
    assert reading["uncomposable"], "the fixture must contain a refusal"


# ---------------------------------------------------------------------------
# 4. The census the two commands now share
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def plain_world() -> World:
    world = RetailWorld(seed=8128).build()
    world = world.run(MonthEndClose(period="2026-03", include_operational_incident=True))
    return world.compile()


def test_the_census_keeps_ids_parallel_to_fingerprints(plain_world: World) -> None:
    """`diversity.collisions` returns *positions*, and a position is only useful
    if it can be turned back into the artifact an author has to open. A census
    that appended an id for a refused artifact would shift every later id by
    one and send readers to the wrong document."""
    shapes = stats.census(plain_world)
    assert len(shapes.fingerprints) == len(shapes.artifact_ids)
    assert len(set(shapes.artifact_ids)) == len(shapes.artifact_ids)


def test_a_refused_artifact_is_absent_from_the_fingerprints_and_named_once() -> None:
    """Counted in exactly one of the two lists. An artifact in neither would
    make the denominator silently wrong, which is the failure the census type
    exists to prevent."""
    world = RetailWorld(seed=8128).build()
    world = world.run(MonthEndClose(period="2026-03", include_operational_incident=True))
    world = world.compile()
    shapes = stats.census(world)
    refused_ids = {row[0] for row in shapes.uncomposable}
    assert refused_ids.isdisjoint(set(shapes.artifact_ids))


def test_measure_carries_the_refusals_rather_than_propagating_them(
    distractor_corpus: Path,
) -> None:
    measurement = stats.measure(World.load(str(distractor_corpus)).compile())
    assert measurement.uncomposable, "the fixture must contain a refusal"
    assert measurement.artifacts == len(stats.census(
        World.load(str(distractor_corpus)).compile()
    ).fingerprints)
    # The shape census is over `artifacts`, so the string a reader sees has to
    # admit the denominator excludes something.
    assert "no composable shape" in str(measurement)
    assert measurement.as_dict()["uncomposable"][0]["code"] == "over_budget"


def test_a_corpus_with_nothing_refused_reports_an_empty_list(plain_world: World) -> None:
    """The quiet case. A field that is only ever exercised when something is
    wrong is a field nobody notices has stopped working."""
    measurement = stats.measure(plain_world)
    assert measurement.uncomposable == ()
    assert "no composable shape" not in str(measurement)
    assert measurement.as_dict()["uncomposable"] == []
