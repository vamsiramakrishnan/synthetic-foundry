"""Tests for the library surface itself: IDs, collections, immutability, CLI."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from worldloom import World
from worldloom.cli import app
from worldloom.ids import Minter, content_key, format_id, id_prefix, is_id, parse_id

runner = CliRunner()


# -- Identifiers -------------------------------------------------------------


def test_ids_are_zero_padded() -> None:
    assert format_id("FACT", 42) == "FACT-0042"
    assert format_id("EV", 7, width=2) == "EV-07"


def test_compound_suffixes_keep_their_kind() -> None:
    """``ART-SNOW-001`` is an ART. A renderer-specific suffix must not change that."""
    assert id_prefix("ART-SNOW-001") == "ART"
    assert id_prefix("ART-STATUS-DRAFT-001") == "ART"
    assert parse_id("BU-FOOD") == ("BU", "FOOD")


def test_malformed_ids_are_rejected() -> None:
    assert not is_id("fact-0001")
    assert not is_id("FACT0001")
    with pytest.raises(ValueError, match="malformed"):
        parse_id("nonsense")


def test_minting_is_sequential_and_per_prefix() -> None:
    minter = Minter()
    assert [minter.next("FACT") for _ in range(3)] == ["FACT-0001", "FACT-0002", "FACT-0003"]
    assert minter.next("EV") == "EV-0001"
    assert minter.peek("FACT") == 3


def test_content_keys_are_stable_across_processes() -> None:
    """Ledger keys must not use Python's randomised string hash."""
    assert content_key("a", 1, None) == content_key("a", 1, None)
    assert content_key("a", 1) != content_key("a", 2)
    assert len(content_key("x")) == 32


# -- Collections -------------------------------------------------------------


@pytest.fixture(scope="module")
def world() -> World:
    return World.load("retail-close")


def test_where_filters_on_equality_and_membership(world: World) -> None:
    finance = world.people.where(function="Finance")
    assert len(finance) == 6

    two_units = world.people.where(business_unit_id=["BU-GM", "BU-DIGITAL"])
    assert {p.business_unit_id for p in two_units} == {"BU-GM", "BU-DIGITAL"}


def test_where_on_a_dotted_path(world: World) -> None:
    in_thousands = world.facts.where(**{"value.unit": "AUD_thousands"})
    assert len(in_thousands) > 20


def test_a_typo_in_where_raises_rather_than_returning_nothing(world: World) -> None:
    """Silently returning an empty set would hide the mistake."""
    with pytest.raises(AttributeError, match="has no attribute 'funktion'"):
        world.people.where(funktion="Finance")


def test_collections_are_immutable(world: World) -> None:
    people = world.people
    filtered = people.where(function="Finance")
    assert len(people) == 20, "filtering must not mutate the source"
    assert filtered is not people


def test_org_chart_helpers(world: World) -> None:
    assert world.people.root().id == "PERSON-0001"
    assert len(world.people.reports_to("PERSON-0001")) == 5

    chain = world.people.chain("PERSON-0012")
    assert [p.id for p in chain] == ["PERSON-0012", "PERSON-0011", "PERSON-0003", "PERSON-0001"]


def test_by_id_and_one_have_sharp_failures(world: World) -> None:
    with pytest.raises(KeyError):
        world.facts.by_id("FACT-9999")
    with pytest.raises(ValueError, match="exactly one"):
        world.people.where(function="Finance").one()


def test_timeline_is_chronological(world: World) -> None:
    moments = [e.occurred_at for e in world.timeline()]
    assert moments == sorted(moments)


def test_repr_is_informative(world: World) -> None:
    assert "Southern Cross Retail Group" in repr(world)
    assert "FactCollection(55" in repr(world.facts)
    assert "Southern Cross Retail Group" in str(world.summary())


def test_dataframe_interop_raises_actionably_when_uninstalled(world: World) -> None:
    try:
        frame = world.people.to_polars()
    except ImportError as exc:
        assert "pip install" in str(exc)
    else:
        assert frame.height == 20


# -- CLI ---------------------------------------------------------------------


def test_cli_demo_builds_validates_and_exports(tmp_path) -> None:
    result = runner.invoke(app, ["demo", "retail-close", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "coherent" in result.output
    assert (tmp_path / "retail-close" / "facts.jsonl").is_file()
    assert (tmp_path / "retail-close" / "artifacts" / "incident-rca.md").is_file()


def test_cli_build_generates_validates_and_exports(tmp_path) -> None:
    out = tmp_path / "generated"
    result = runner.invoke(app, ["build", "--seed", "8128", "--period", "2026-03", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "coherent" in result.output
    assert (out / "facts.jsonl").is_file()
    assert (out / "artifact-intents.jsonl").is_file()
    # Generated, not hand-authored: no artifact bodies exist yet.
    assert not (out / "artifacts").exists()


def test_cli_build_is_reproducible(tmp_path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    for target in (first, second):
        assert runner.invoke(app, ["build", "--seed", "77", "--out", str(target)]).exit_code == 0
    for name in ("facts.jsonl", "events.jsonl", "evals.jsonl", "world.json"):
        assert (first / name).read_text() == (second / name).read_text(), name


def test_cli_build_can_force_the_incident_off(tmp_path) -> None:
    result = runner.invoke(app, ["build", "--seed", "8128", "--no-incident", "--out", str(tmp_path / "quiet")])
    assert result.exit_code == 0, result.output
    world = World.load(tmp_path / "quiet")
    assert not world.facts.superseded()
    assert "incident_rca" not in {i.artifact_type for i in world.artifact_intents}


def test_cli_build_renders_when_asked(tmp_path) -> None:
    out = tmp_path / "rendered"
    result = runner.invoke(app, [
        "build", "--seed", "8128", "--incident",
        "-f", "xlsx", "-f", "markdown", "-f", "jira", "-f", "confluence", "-f", "servicenow",
        "--out", str(out),
    ])
    assert result.exit_code == 0, result.output
    assert (out / "artifact-manifest.jsonl").is_file()
    assert (out / "artifact-ir.jsonl").is_file()
    assert list(out.glob("artifacts/*.xlsx")), "the workbook should be rendered"
    assert (out / "jira" / "issues.jsonl").is_file()
    assert (out / "servicenow" / "incident.json").is_file()
    assert (out / "confluence" / "pages.jsonl").is_file()

    assert runner.invoke(app, ["validate", str(out)]).exit_code == 0


def test_cli_rejects_an_unknown_format(tmp_path) -> None:
    result = runner.invoke(app, ["build", "--format", "powerpoint", "--out", str(tmp_path / "x")])
    assert result.exit_code == 2
    assert "unknown format" in result.output


def test_cli_lists_formats() -> None:
    result = runner.invoke(app, ["formats"])
    assert result.exit_code == 0
    assert "xlsx" in result.output and "servicenow" in result.output


def test_cli_validate_passes_on_the_golden_episode() -> None:
    result = runner.invoke(app, ["validate", "retail-close"])
    assert result.exit_code == 0, result.output


def test_cli_reports_a_missing_corpus_without_a_traceback() -> None:
    result = runner.invoke(app, ["validate", "not-a-corpus"])
    assert result.exit_code == 2
    assert "error" in result.output


def test_cli_inspect_lists_each_ledger() -> None:
    result = runner.invoke(app, ["inspect", "retail-close", "--facts", "--events", "--evals", "--lore"])
    assert result.exit_code == 0, result.output
    for expected in ("FACT-0001", "EV-0001", "EVAL-0001", "LORE-0001"):
        assert expected in result.output


def test_cli_evals_export_emits_jsonl(tmp_path) -> None:
    out = tmp_path / "evals.jsonl"
    result = runner.invoke(app, ["evals", "export", "retail-close", "--out", str(out)])
    assert result.exit_code == 0, result.output
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 28
    assert all(line.startswith("{") for line in lines)
