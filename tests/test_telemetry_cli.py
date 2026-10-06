"""``worldloom telemetry …`` — the only place a catalogue file is opened.

Everything else in the importer is tested through its functions. These tests
are about the edges only a command has: which files get written, which exit
code a script sees, what is refused before anything is read, and — the one
that matters most — whether ``studio init`` accepts what ``import`` wrote.

    the functions prove       │ these tests add
    ──────────────────────────┼──────────────────────────────────────────
    a project is buildable    │ studio init actually accepts the file
    findings are right        │ --strict turns hard findings into exit 3
    the company is used       │ a missing company is refused, never guessed
    one import works          │ a second does not silently overwrite it
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom.cli import _REFUSALS, app
from worldloom.company import from_document, resolve
from worldloom.studio.models import ProjectSpec

EXAMPLE = (Path(__file__).parent / "fixtures" / "telemetry" / "conformance"
           / "valid" / "example.json")
INVALID = (Path(__file__).parent / "fixtures" / "telemetry" / "conformance"
           / "invalid" / "inv2_depends_on_later_step.json")

WRITES = "cuj_9636dd61a048"


@pytest.fixture
def company(tmp_path: Path) -> Path:
    path = tmp_path / "company.json"
    path.write_text(json.dumps({
        "engine": "retail", "identity": {"company_name": "Northwind Grocers"}}))
    return path


def _run(*args: str | Path) -> object:
    return CliRunner().invoke(app, ["telemetry", *map(str, args)])


def _import(out: Path, company: Path, *extra: str | Path):
    return _run("import", EXAMPLE, "--company", company, "--out", out, *extra)


# ---------------------------------------------------------------------------
# A clean import, and the one check that matters.
# ---------------------------------------------------------------------------


def test_import_writes_four_files_and_exits_zero(tmp_path: Path,
                                                 company: Path) -> None:
    out = tmp_path / "out"

    result = _import(out, company)

    assert result.exit_code == 0, result.output
    assert sorted(path.name for path in out.iterdir()) == [
        "import-receipt.json", "import-report.json", "import-report.md",
        "project.json"]
    assert "1 of 3 journeys, 200 questions" in result.output


def test_studio_init_accepts_what_import_wrote(tmp_path: Path,
                                               company: Path) -> None:
    """The point of the whole wave, end to end through both commands."""
    out = tmp_path / "out"
    assert _import(out, company).exit_code == 0

    created = CliRunner().invoke(app, [
        "studio", "init", str(out / "project.json"),
        "-w", str(tmp_path / "workspace")])

    assert created.exit_code == 0, created.output
    assert json.loads(created.output)["spec"]["use_cases"][0]["id"] == WRITES


def test_the_report_accounts_for_every_journey(tmp_path: Path,
                                               company: Path) -> None:
    out = tmp_path / "out"
    _import(out, company)

    report = json.loads((out / "import-report.json").read_text())

    assert report["schema_version"] == "worldloom.telemetry-import-report/v1"
    assert [(j["cuj_id"], j["group"], j["count"]) for j in report["journeys"]] == [
        ("cuj_3ac134e740af", "lookup", 0),
        ("cuj_80e0d9ce1f1b", "no_world", 0),
        (WRITES, "write", 200)]
    assert report["share_lost"] == pytest.approx(0.511)
    assert report["assumptions"] == {
        "persona": "employee", "audience": "team", "cases": 200, "seed": 8128}


def test_the_readable_report_says_what_was_lost_and_what_was_assumed(
        tmp_path: Path, company: Path) -> None:
    out = tmp_path / "out"
    _import(out, company)

    text = (out / "import-report.md").read_text()

    assert "51.1% of real traffic not represented" in text
    assert "a choice, not a measurement" in text
    assert "`answer_only_unsupported`" in text


def test_the_options_reach_the_project(tmp_path: Path, company: Path) -> None:
    out = tmp_path / "out"

    _import(out, company, "--cases", "40", "--seed", "7",
            "--persona", "analyst")
    project = ProjectSpec.model_validate_json((out / "project.json").read_text())

    assert project.seed == 7
    assert project.use_cases[0].count == 40
    assert project.use_cases[0].construction is not None
    assert project.use_cases[0].construction.persona == "analyst"


def test_json_prints_the_report(tmp_path: Path, company: Path) -> None:
    result = _import(tmp_path / "out", company, "--json")

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["catalogue_id"] == "retail_example_2026.09"


# ---------------------------------------------------------------------------
# Exit codes a script can rely on.
# ---------------------------------------------------------------------------


def test_strict_exits_three_and_writes_no_project(tmp_path: Path,
                                                  company: Path) -> None:
    """The sample's lookup journey is a hard finding, so --strict refuses.
    The report is still written, so the reason can be read."""
    out = tmp_path / "out"

    result = _import(out, company, "--strict")

    assert result.exit_code == 3, result.output
    assert not (out / "project.json").exists()
    assert (out / "import-report.md").exists()
    assert "answer_only_unsupported" in result.output


def test_a_strict_rerun_removes_a_stale_project(tmp_path: Path,
                                                company: Path) -> None:
    """A project left from an earlier run would sit beside a report that
    describes a different import."""
    out = tmp_path / "out"
    _import(out, company)
    assert (out / "project.json").exists()

    _import(out, company, "--overwrite", "--strict")

    assert not (out / "project.json").exists()


def test_nothing_buildable_exits_three(tmp_path: Path, company: Path) -> None:
    payload = json.loads(EXAMPLE.read_text())
    for cuj in payload["cujs"]:
        if cuj["id"] == WRITES:
            # Make the write journey a read; the id is the signature's hash
            # and ignores effect, so the file stays valid.
            next(s for s in cuj["steps"] if s["id"] == "create_epics")[
                "effect"] = "read"
    catalogue = tmp_path / "reads-only.json"
    catalogue.write_text(json.dumps(payload))

    result = _run("import", catalogue, "--company", company,
                  "--out", tmp_path / "out")

    assert result.exit_code == 3, result.output
    assert "nothing in" in result.output
    assert not (tmp_path / "out" / "project.json").exists()


# ---------------------------------------------------------------------------
# Refused before anything is read or written.
# ---------------------------------------------------------------------------


def test_a_missing_company_is_refused_and_never_invented(tmp_path: Path) -> None:
    out = tmp_path / "out"

    result = _run("import", EXAMPLE, "--out", out)

    assert result.exit_code == 2
    assert "--company is required" in result.output
    assert not out.exists()


def test_a_company_without_a_name_is_refused(tmp_path: Path) -> None:
    nameless = tmp_path / "company.json"
    nameless.write_text(json.dumps({"engine": "retail",
                                    "identity": {"company_name": ""}}))

    result = _run("import", EXAMPLE, "--company", nameless,
                  "--out", tmp_path / "out")

    assert result.exit_code == 2
    assert "identity.company_name" in result.output


def test_a_second_import_does_not_silently_replace_the_first(
        tmp_path: Path, company: Path) -> None:
    out = tmp_path / "out"
    _import(out, company)

    again = _import(out, company)
    replaced = _import(out, company, "--overwrite")

    assert again.exit_code == 2
    assert "already exists" in again.output
    assert replaced.exit_code == 0


def test_an_invalid_catalogue_lists_every_reason(tmp_path: Path,
                                                 company: Path) -> None:
    result = _run("import", INVALID, "--company", company,
                  "--out", tmp_path / "out")

    assert result.exit_code == 2
    assert "catalogue refused" in result.output


def test_every_code_this_command_can_refuse_with_is_registered() -> None:
    for code in ("catalogue_rejected", "catalogue_version_unknown",
                 "catalogue_uncompilable", "company_required", "company_unmet",
                 "strict_findings", "destination_exists"):
        assert code in _REFUSALS, code


# ---------------------------------------------------------------------------
# company-template.
# ---------------------------------------------------------------------------


def test_company_template_suggests_and_leaves_the_name_blank(
        tmp_path: Path) -> None:
    out = tmp_path / "company.json"

    result = _run("company-template", EXAMPLE, "--out", out)
    document = json.loads(out.read_text())

    assert result.exit_code == 0, result.output
    assert document == {"archetype": "australian_grocery",
                        "industry": "grocery retail",
                        "identity": {"company_name": ""}}
    assert "matched from industry hint" in result.output


def test_a_filled_in_template_is_a_company_import_accepts(tmp_path: Path) -> None:
    out = tmp_path / "company.json"
    _run("company-template", EXAMPLE, "--out", out)
    document = json.loads(out.read_text())
    document["identity"]["company_name"] = "Northwind Grocers"
    out.write_text(json.dumps(document))

    resolution = resolve(from_document(document))
    result = _run("import", EXAMPLE, "--company", out, "--out", tmp_path / "o")

    assert resolution.conflicts == ()
    assert result.exit_code == 0, result.output


def test_company_template_refuses_to_overwrite(tmp_path: Path) -> None:
    out = tmp_path / "company.json"
    shutil.copy(EXAMPLE, out)

    result = _run("company-template", EXAMPLE, "--out", out)

    assert result.exit_code == 2
    assert "already exists" in result.output
