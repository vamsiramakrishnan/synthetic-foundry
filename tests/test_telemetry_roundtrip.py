"""W4's own catalogue: four write journeys, four separate evidence groups.

The miner's sample has one journey that writes, and every question built from
it reads one pinned page, so it can never fill train, validation and test
without leaking evidence across them. ``fixtures/telemetry/roundtrip`` holds a
catalogue built for the round trip; these tests keep it importable and keep
the file in step with the script that writes it.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from worldloom.telemetry import import_catalogue

ROOT = Path(__file__).parent / "fixtures" / "telemetry" / "roundtrip"
COMPANY = {"engine": "retail", "identity": {"company_name": "Northwind Grocers"}}


def _builder():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("build_catalogue", ROOT / "build_catalogue.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_fixture_is_what_its_script_writes() -> None:
    """Regenerate with ``python tests/fixtures/telemetry/roundtrip/build_catalogue.py``."""
    on_disk = json.loads((ROOT / "catalogue.json").read_text(encoding="utf-8"))

    assert on_disk == _builder().catalogue()


def test_four_write_journeys_import_with_no_hard_finding() -> None:
    result = import_catalogue((ROOT / "catalogue.json").read_bytes(), COMPANY, cases=12)

    assert result.project is not None
    assert result.report.accepted, [f.message for f in result.report.hard_findings]
    assert [(j.group.value, j.count) for j in result.journeys] == [("write", 3)] * 4


def test_each_journey_pins_a_different_page() -> None:
    """One pinned page per journey is one evidence group per journey: four
    groups, at Studio's three questions each, fill all three splits."""
    result = import_catalogue((ROOT / "catalogue.json").read_bytes(), COMPANY, cases=12)
    assert result.project is not None

    titles = [requirement.selector["title"]
              for case in result.project.use_cases if case.construction is not None
              for requirement in case.construction.requirements]
    assert sorted(titles) == ["leave policy", "sprint retro", "store rollout", "supplier review"]


def test_the_round_trip_scores_full_marks_offline(tmp_path: Path) -> None:
    """W4's proof: the importer's project goes through Studio — build,
    construction, narration, qualification — and the reference agent passes
    every question it produces.

    The coding harness replays a recorded run (``replay_harness.py``), so
    this needs no model and no network. Calibration is set wide open and to
    the minimum: it tunes difficulty against a target agent, which a wiring
    test does not need, and it refuses file-reading tasks anyway, so the run
    stops before freezing and evalrun grades the qualified baseline.
    """
    import shlex
    import sys

    from worldloom.evals.calibration import NoiseVariant
    from worldloom.studio import RunOptions, Studio
    from worldloom.studio.calibration import CompanyCalibrationPlan
    from worldloom.studio.worker import run_job

    result = import_catalogue((ROOT / "catalogue.json").read_bytes(), COMPANY, cases=12)
    assert result.project is not None
    spec = result.project.model_copy(update={
        # Four evidence groups: two practice, one tuning, one final.
        "split_weights": {"train": 2, "validation": 1, "test": 1},
        "calibration": CompanyCalibrationPlan(
            variants=(NoiseVariant(name="clean", budget={}, niche="no added noise"),),
            cohort="reference-claude", target_low=0.0, target_high=1.0, min_support=1,
            max_training_attempts=1, max_holdout_attempts=1, reader_share=0.1, max_turns=8),
    })
    harness = shlex.join([sys.executable, str(ROOT / "replay_harness.py")])
    studio = Studio(tmp_path / "workspace")
    project = studio.store.create(spec)

    foundry = studio.store.enqueue(project["id"], project["revision"], RunOptions(operation="foundry"))
    run_job(studio, foundry["id"], harness_command=harness)
    finished = studio.store.job(foundry["id"])
    assert finished["result"] is not None, finished.get("error")
    stages = finished["result"]["stages"]
    assert {name: stages[name]["status"] for name in ("construction", "narration", "qualification")} \
        == {"construction": "complete", "narration": "complete", "qualification": "complete"}

    evalrun = studio.store.enqueue(project["id"], project["revision"],
                                   RunOptions(operation="evalrun", evalrun_agent="reference"))
    assert run_job(studio, evalrun["id"])
    graded = studio.store.job(evalrun["id"])["result"]
    assert graded["dataset_complete"]
    assert graded["summary"]["cases"] == 12
    assert graded["summary"]["pass_rate"] == 1.0
    assert graded["summary"]["means"]["overall"] == 1.0
