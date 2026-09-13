"""Industry X, and the whole evaluation programme it implies.

An interview that ends "a federated telecom in India" used to leave every line
of business, every process and every count to be typed by hand. The programme
derives all three from the compiled catalogue and two versioned data files,
and the properties worth pinning are the ones a count rests on: that the
derivation is total (every bound activity has a LOB, every situation a seated
request), that it is honest (every asker has standing, every unemulated system
is named), that it is stable (the same industry yields the same bytes), and
that what it hands the Studio is something the enterprise planner accepts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import worldloom
from worldloom import factkinds, industry, lob
from worldloom.enterprise_specs import apply_scenario_profile, builtin_registry
from worldloom.evals.coverage import report
from worldloom.process_bindings import (
    coverage,
    default_company,
    situations,
)
from worldloom.process_bindings.compiler import resource

INDUSTRIES = tuple(sorted(resource("defaults.json")["DEFAULT_ORGS"]))


@pytest.fixture(autouse=True)
def _installed() -> None:
    worldloom._install()


@pytest.fixture(scope="module")
def telecom() -> industry.Programme:
    return industry.programme("telecom")


# -- lines of business ------------------------------------------------------


def test_a_lob_is_derived_per_function_family_that_owns_a_bound_activity(
    telecom: industry.Programme,
) -> None:
    bound = [row for row in telecom.compiled.rows if row.binding_status == "bound"]
    families = sorted({row.function for row in bound})
    assert (
        list(telecom.summary.lobs) == families == [spec.name for spec in telecom.lobs]
    )
    titles = resource("catalogue.json")["function_families"]
    for spec in telecom.lobs:
        assert spec.title == titles[spec.name]
        assert [role.key for role in spec.roles] == [
            f"{spec.name}_head",
            f"{spec.name}_manager",
            f"{spec.name}_analyst",
        ]
        streams = sorted({row.stream for row in bound if row.function == spec.name})
        for edge in spec.responsibilities:
            assert edge.fact_kinds == [f"process.{stream}" for stream in streams]


def test_derived_lobs_lint_clean_but_for_the_root_convention(
    telecom: industry.Programme,
) -> None:
    """The one finding is the one the shipped library draws too: a LOB is
    rooted at its head, not at the chief executive."""
    assert industry.lint(telecom.lobs) == []
    raw = [finding for spec in telecom.lobs for finding in lob.lint_lob(spec)]
    assert raw and all(industry.ROOT_CONVENTION in finding for finding in raw)


def test_the_stream_kinds_are_registered_from_the_catalogue() -> None:
    kinds = industry.register_kinds()
    names = industry.stream_names()
    assert kinds == tuple(f"process.{stream}" for stream in names)
    assert all(factkinds.resolvable(kind) for kind in kinds)
    assert factkinds.covers("process.order_to_cash", "process.order_to_cash.owner")
    # Idempotent: a second registration is a reload, not a refusal.
    assert industry.register_kinds() == kinds


# -- requests ---------------------------------------------------------------


def test_every_situation_becomes_exactly_one_seated_request(
    telecom: industry.Programme,
) -> None:
    offered = coverage(telecom.compiled)
    assert telecom.summary.situations == offered["situations"] == len(telecom.requests)
    keys = [(s.occasion, s.intent, s.channel) for s in situations(telecom.compiled)]
    assert [(r.occasion, r.intent, r.channel) for r in telecom.requests] == keys
    assert len({r.id for r in telecom.requests}) == len(telecom.requests)


def test_every_asker_is_seated_in_the_family_that_owns_the_binding(
    telecom: industry.Programme,
) -> None:
    rows = {row.id: row for row in telecom.compiled.rows}
    for request in telecom.requests:
        row = rows[request.occasion]
        assert request.lob == row.function
        assert request.asker == f"{row.function}_{industry.SEAT_BY_TYPE[row.type]}"
        assert (
            request.owner == row.owner_bu
            and request.system_of_record == row.sor_product
        )


def test_every_asker_has_standing_over_what_it_asks(
    telecom: industry.Programme,
) -> None:
    """The seat table and the responsibility edges agree, under the same rule
    `evals.plausibility` applies to a corpus."""
    assert industry.standing_findings(telecom.requests, telecom.lobs) == []
    assert telecom.summary.findings == ()
    stranger = telecom.requests[0].model_copy(update={"asker": "ceo"})
    assert industry.standing_findings([stranger], telecom.lobs) == [
        f"{stranger.id!r} is asked by 'ceo', which has no declared reason to ask about {stranger.kind!r}"
    ]


def test_a_request_cites_the_facts_the_catalogue_declares(
    telecom: industry.Programme,
) -> None:
    by_id = {fact.id: fact for fact in telecom.facts}
    grounded = next(
        r for r in telecom.requests if r.grading.value != "expected_abstention"
    )
    assert grounded.expected_fact_ids
    kinds = {by_id[fact_id].kind for fact_id in grounded.expected_fact_ids}
    assert {
        f"process.{grounded.stream}.owner",
        f"process.{grounded.stream}.system_of_record",
    } <= kinds
    assert all(
        by_id[fact_id].subject == grounded.occasion
        for fact_id in grounded.expected_fact_ids
    )
    assert (
        grounded.owner in grounded.expected_answer
        and grounded.system_of_record in grounded.expected_answer
    )
    case = grounded.to_case()
    assert case.expected_fact_ids == list(grounded.expected_fact_ids)
    assert case.asker == grounded.asker and case.has_request
    abstaining = next(r for r in telecom.requests if r.intent == "abstain").to_case()
    assert abstaining.expects_abstention and abstaining.expected_fact_ids == []


def test_the_coverage_report_reads_a_programme_as_it_reads_a_corpus(
    telecom: industry.Programme,
) -> None:
    measured = report(telecom.requests, situations_available=telecom.summary.situations)
    assert (
        measured.situations_used
        == measured.situations_available
        == telecom.summary.situations
    )
    assert measured.used_share == 1.0
    assert measured.intents_used == measured.intents_available
    assert measured.gaps() == []
    assert telecom.coverage() == measured


# -- lines and counts -------------------------------------------------------


def test_the_count_is_derived_per_lob_and_per_stream(
    telecom: industry.Programme,
) -> None:
    summary = telecom.summary
    assert sum(line.situations for line in summary.lines) == summary.situations
    assert sum(summary.by_lob().values()) == summary.situations
    assert summary.reads + summary.writes == summary.situations
    per_lob = {name: 0 for name in summary.lobs}
    for request in telecom.requests:
        per_lob[request.lob] += 1
    assert per_lob == summary.by_lob()
    assert all(line.bindings and line.activities for line in summary.lines)
    assert [line.key for line in summary.lines] == sorted(
        line.key for line in summary.lines
    )


def test_an_unemulated_system_is_named_never_replaced(
    telecom: industry.Programme,
) -> None:
    table = industry.emulated_systems()
    emulated = set(table["products"])
    for line in telecom.summary.lines:
        for product in line.systems:
            if product not in emulated:
                assert any(name.startswith(product) for name in line.unemulated), (
                    line.key,
                    product,
                )
        for source in line.sources:
            connector, entity = source.split(".")
            assert connector in builtin_registry().connectors
            assert entity in {
                e.name for e in builtin_registry().connectors[connector].entities
            }
    assert "SAP S/4HANA" in telecom.summary.unemulated
    assert "channel:system_record" in telecom.summary.unemulated
    unsupported = {line.key for line in telecom.summary.lines if not line.sources}
    assert set(telecom.summary.unsupported_lines) == unsupported


def test_the_emulator_table_names_only_connectors_and_entities_that_exist() -> None:
    table = industry.emulated_systems()
    registry = builtin_registry()
    for product, mapping in table["products"].items():
        connector = registry.connectors[mapping["connector"]]
        entities = {e.name for e in connector.entities}
        assert set(mapping["objects"].values()) <= entities, product
    for channel, mapping in {**table["channels"], **table["destinations"]}.items():
        if mapping is None:
            continue
        connector = registry.connectors[mapping["connector"]]
        entity = connector.entity(mapping["entity"])
        for operation in mapping.get("operations", ()):
            assert operation in {op.value for op in entity.operations}, (
                channel,
                operation,
            )


# -- use cases ---------------------------------------------------------------


def test_a_use_case_per_supported_line_with_the_lines_count(
    telecom: industry.Programme,
) -> None:
    cases = telecom.use_cases()
    supported = [line for line in telecom.summary.lines if line.supported]
    assert len(cases) == len(supported)
    for case, line in zip(cases, supported, strict=True):
        assert case.count == line.situations
        assert case.lob == line.lob and case.owner == line.owners[0]
        assert case.activities == line.activities
        assert case.scenario is not None and case.construction is not None
        sources = {
            f"{role.connector}.{entity}"
            for role in case.scenario.additional_workflows[0].sources
            for entity in role.entities
        }
        assert sources == set(line.sources)
        assert {req.selector["lob"] for req in case.construction.requirements} == {
            line.lob
        }
        # Every scenario is one the enterprise planner accepts as it stands.
        apply_scenario_profile(builtin_registry(), case.scenario)
    assert sum(case.count for case in cases) > 5000


def test_the_count_ceiling_is_applied_and_visible(telecom: industry.Programme) -> None:
    capped = telecom.use_cases(count_ceiling=10)
    assert all(case.count <= 10 for case in capped)
    assert industry.COUNT_CEILING == 100_000


# -- the whole programme, every industry -----------------------------------


@pytest.mark.parametrize("name", INDUSTRIES)
def test_every_shipped_industry_derives_a_complete_honest_programme(name: str) -> None:
    derived = industry.programme(name)
    summary = derived.summary
    assert summary.industry == name and summary.findings == ()
    assert (
        summary.requests
        == summary.situations
        == coverage(derived.compiled)["situations"]
        > 0
    )
    assert summary.facts == len(derived.facts)
    assert len(summary.lobs) == len(derived.lobs) >= 10
    assert set(summary.unsupported_lines) <= {line.key for line in summary.lines}


def test_the_programme_is_a_function_of_the_catalogue(
    telecom: industry.Programme,
) -> None:
    again = industry.programme("telecom")
    assert again.summary == telecom.summary
    assert [r.model_dump(mode="json") for r in again.requests] == [
        r.model_dump(mode="json") for r in telecom.requests
    ]
    assert again.facts == telecom.facts


def test_a_company_spec_of_its_own_derives_its_own_programme() -> None:
    spec = default_company("retail").model_copy(update={"name": "Northstar Retail"})
    derived = industry.programme(spec)
    assert derived.summary.company == "Northstar Retail"
    assert derived.summary.engine == "retail", (
        "retail is a registered domain, so its LOBs ride that engine"
    )
    assert all(spec.engine == "retail" for spec in derived.lobs)
    telecom_engine = industry.programme("telecom").summary.engine
    assert telecom_engine == "", (
        "no engine builds a telecom's world; the programme says so"
    )


def test_export_writes_the_programme_and_reads_back(
    tmp_path: Path, telecom: industry.Programme
) -> None:
    written = telecom.export(tmp_path / "out")
    assert set(written) == {
        "programme.json",
        "lobs.json",
        "facts.jsonl",
        "requests.jsonl",
        "cases.jsonl",
        "use-cases.json",
        "coverage.json",
    }
    summary = industry.IndustryProgramme.model_validate(
        json.loads((tmp_path / "out" / "programme.json").read_text())
    )
    assert summary == telecom.summary
    lines = (
        (tmp_path / "out" / "requests.jsonl").read_text(encoding="utf-8").splitlines()
    )
    assert len(lines) == telecom.summary.requests
    assert industry.Request.model_validate_json(lines[0]) == telecom.requests[0]
    cases = (tmp_path / "out" / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(cases) == telecom.summary.requests


def test_describe_reports_the_headline_numbers() -> None:
    described = industry.describe("telecom")
    assert described["situations"] == described["reads"] + described["writes"]
    assert described["lobs"] == len(described["by_lob"]) and described["findings"] == []
    assert sum(described["intents"].values()) == described["situations"]
