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
from worldloom import factkinds, industry
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
    from worldloom import functions

    table = functions.load()
    for spec in telecom.lobs:
        assert spec.title == titles[spec.name]
        function = table.function(spec.name)
        expected = ["ceo", f"{spec.name}_head", f"{spec.name}_manager", f"{spec.name}_analyst"]
        if "support" in function.titles:
            expected.append(f"{spec.name}_support")
        assert [role.key for role in spec.roles] == expected
        by_key = {role.key: role for role in spec.roles}
        assert by_key[f"{spec.name}_head"].title == function.titles["head"].title
        assert by_key[f"{spec.name}_analyst"].title == function.titles["professional"].title
        if f"{spec.name}_support" in by_key:
            assert by_key[f"{spec.name}_support"].reports_to == f"{spec.name}_manager"
        streams = sorted({row.stream for row in bound if row.function == spec.name})
        for edge in spec.responsibilities:
            assert edge.fact_kinds == [f"process.{stream}" for stream in streams]
    billing = next(spec for spec in telecom.lobs if spec.name == "billing")
    assert {role.title for role in billing.roles} >= {"Billing Supervisor", "Billing Clerk"}


def test_derived_lobs_are_rooted_at_the_chief_executive_and_lint_clean(
    telecom: industry.Programme,
) -> None:
    """Rooted at `ceo` because that is the convention `lint_roles` asks for and
    a Studio project refuses any finding; `root=None` is the shipped library's
    shape, and draws exactly the convention finding the library draws."""
    assert industry.lint(telecom.lobs) == []
    for spec in telecom.lobs:
        assert spec.roles[0] == industry.ROOT
        assert spec.roles[1].reports_to == "ceo"
    headless = industry.derive_lobs(telecom.compiled, root=None)
    assert all(
        spec.roles[0].key.endswith("_head") and spec.roles[0].reports_to is None
        for spec in headless
    )
    findings = industry.lint(headless)
    assert findings and all(
        "root role should be 'ceo'" in finding for finding in findings
    )


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
    # The chief executive asks down the line, so `ceo` has standing over every
    # family's streams; a role the owning LOB does not declare has none.
    executive = telecom.requests[0].model_copy(update={"asker": "ceo"})
    assert industry.standing_findings([executive], telecom.lobs) == []
    stranger = telecom.requests[0].model_copy(update={"asker": "outsider"})
    assert industry.standing_findings([stranger], telecom.lobs) == [
        f"{stranger.id!r} is asked by 'outsider', which has no declared reason to ask about {stranger.kind!r}"
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
    assert "SAP S/4HANA" in emulated and table["products"]["SAP S/4HANA"]["connector"] == "sor"
    assert not any(name.startswith("SAP") for name in telecom.summary.unemulated)
    assert "channel:system_record" in telecom.summary.unemulated
    unsupported = {line.key for line in telecom.summary.lines if not line.sources}
    assert set(telecom.summary.unsupported_lines) == unsupported == set()


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
        assert case.lob == line.lob
        assert case.owner == (line.owners[0] if len(line.owners) == 1 else "")
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


def test_a_line_several_units_own_names_no_single_owner(
    telecom: industry.Programme,
) -> None:
    """A use case's owner constrains which rows may satisfy it, and a line whose
    activities are bound per unit spans them all."""
    supported = [line for line in telecom.summary.lines if line.supported]
    for case, line in zip(telecom.use_cases(), supported, strict=True):
        assert case.owner == (line.owners[0] if len(line.owners) == 1 else "")
        assert case.construction is not None
        assert ("business_unit" in case.construction.requirements[0].selector) is bool(
            case.owner
        )


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
        "records.jsonl",
    }
    records = (tmp_path / "out" / "records.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(records) == telecom.summary.records == len(telecom.records)
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


def test_record_set_requests_read_their_answers_off_the_records(
    telecom: industry.Programme,
) -> None:
    """An intent whose evidence is a record set is asked about the latest period's
    records and answered from them; one whose evidence is the declaration is not."""
    from worldloom import sor
    from worldloom.evals.intents import intents

    table = intents()
    by_id = {record.id: record for record in telecom.records}
    grounded = [r for r in telecom.requests if r.expected_record_ids]
    assert len(grounded) == telecom.summary.record_requests > 0
    assert telecom.summary.period == sor.ANCHOR_PERIOD and telecom.summary.periods == sor.DEFAULT_PERIODS
    grouped = sor.by_binding(telecom.records)
    for request in telecom.requests:
        intent = table[request.intent]
        if "record_set" in intent.evidence_kinds and request.occasion in grouped:
            assert request.period == sor.ANCHOR_PERIOD and request.expected_record_ids
            cited = [by_id[i] for i in request.expected_record_ids]
            assert all(c.fields["binding_id"] == request.occasion and c.fields["period"] == request.period for c in cited)
            expected, ids = sor.answer(intent.id, intent.answer_shape, grouped[request.occasion][request.period])
            assert (request.expected_answer, request.expected_record_ids) == (expected, ids)
            assert f"Period: {request.period}" in request.brief
            assert "records of" in (request.to_case().reasoning or "")
        else:
            assert request.period is None and request.expected_record_ids == ()
    found = next(r for r in grounded if r.intent == "find_exception")
    assert "tripped" in found.expected_answer
    assert len({r.expected_answer for r in telecom.requests}) > 4 * len({industry._answer(row) for row in telecom.compiled.rows})


def test_describe_reports_the_headline_numbers() -> None:
    described = industry.describe("telecom")
    assert described["situations"] == described["reads"] + described["writes"]
    assert described["lobs"] == len(described["by_lob"]) and described["findings"] == []
    assert sum(described["intents"].values()) == described["situations"]


# -- what a description names ------------------------------------------------


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("a federated telecom in India", "telecom"),
        ("a Bavarian machine-tool maker", "manufacturing"),
        ("a SaaS company with APAC sales", "technology_saas"),
        ("NAICS 517", "telecom"),
        ("a regional bank", "banking"),
        ("a large Australian supermarket group", "retail"),
        ("a scorecard vendor", None),
        ("a planting season", None),
    ],
)
def test_industry_of_matches_the_longest_declared_phrase_at_word_boundaries(
    description: str, expected: str | None
) -> None:
    assert industry.industry_of(description) == expected


def test_industry_words_come_from_the_catalogue_and_the_declared_table() -> None:
    words = industry.industry_words()
    assert (
        words["telecom"] == "telecom" and words["technology saas"] == "technology_saas"
    )
    assert words["naics 517"] == "telecom" and words["tm forum etom"] == "telecom"
    assert all(key in INDUSTRIES for key in words.values())
    assert set(industry.INDUSTRY_WORDS.items()) <= set(words.items())


def test_the_archetype_resolver_reports_a_match_or_a_miss() -> None:
    from worldloom import archetypes

    assert archetypes.matched("an omnichannel retailer") is not None
    assert archetypes.matched("a regional widget conglomerate") is None
    assert (
        archetypes.inspired_by("a regional widget conglomerate").key
        == "omnichannel_retailer"
    )


def test_a_company_description_is_resolved_and_its_gap_named_precisely() -> None:
    """Three readings, three sentences: a retailer is recognised and owes no
    limitation; a telecom is known to the catalogue but built by no engine, and
    the limitation names the programme that exists; an unknown business is a
    miss and says so."""
    from worldloom import company

    def unmet(description: str) -> tuple[str, ...]:
        return company.resolve(
            company.from_document(
                {"industry": description, "identity": {"company_name": "X"}}
            )
        ).unmet

    assert not any(
        "archetype" in want or "engine for" in want
        for want in unmet("a large Australian retailer")
    )
    telecom = [
        want for want in unmet("a federated telecom in India") if "engine for" in want
    ]
    assert len(telecom) == 1 and "worldloom industry programme telecom" in telecom[0]
    unknown = [
        want for want in unmet("a Bavarian widget maker") if "archetype for" in want
    ]
    assert len(unknown) == 1 and "nothing recognised it" in unknown[0]


# -- a Studio project ----------------------------------------------------------


def test_a_project_carries_the_largest_lobs_and_their_lines_with_derived_counts() -> (
    None
):
    spec = industry.project("telecom", "Ardent Telecom")
    derived = industry.programme(spec.structure, engine="retail")  # type: ignore[arg-type]
    assert spec.structure is not None and spec.structure.name == "Ardent Telecom"
    ranked = sorted(
        derived.summary.by_lob().items(), key=lambda item: (-item[1], item[0])
    )
    supported = {line.lob for line in derived.summary.lines if line.supported}
    assert {lob.name for lob in spec.lobs} == {f for f, _ in ranked if f in supported}
    assert len(spec.lobs) > 4, "every family with a supported line is seated, not a capped few"
    assert all(lob.engine == "retail" for lob in spec.lobs), (
        "no engine builds a telecom; the LOBs ride the resolved engine"
    )
    assert spec.use_cases and all(
        case.lob in {lob.name for lob in spec.lobs} for case in spec.use_cases
    )
    by_key = {line.key: line.situations for line in derived.summary.lines}
    for case in spec.use_cases:
        line = next(
            line
            for line in derived.summary.lines
            if line.lob == case.lob and line.activities == case.activities
        )
        assert case.count == by_key[line.key]
    assert any(
        "worldloom industry programme telecom" in want
        for want in spec.acknowledged_unmet
    )


def test_a_bank_project_seats_every_line_and_the_pack_pool_is_recut(tmp_path: Path) -> None:
    """Twenty-five lines add over a hundred people; the composed pack's pools
    were cut to the bank's own organisation, so the blueprint re-cuts them from
    the locale as each line attaches and the bank keeps its own role table."""
    from worldloom.studio.service import Studio

    spec = industry.project("banking", "Harbour Bank")
    assert len(spec.lobs) > 20
    world, _ = Studio(tmp_path).snapshot(spec)
    assert world.validate().ok
    assert "credit_risk_lead" in world._roles, "the bank's own spine survives the attach"
    assert "ap_support" in world._roles and "treasury_head" in world._roles
    assert len(world._roles) > 100
    names = [person.name for person in world.people]
    assert len(names) == len(set(names))


def test_attaching_a_lob_recuts_a_composed_pool_but_leaves_an_authored_one() -> None:
    from worldloom import company, lob, sdk

    document = {"industry": "retail", "identity": {"company_name": "Northstar Retail"}, "geo": "australia"}
    resolution = company.resolve(company.from_document(document))
    blueprint = sdk.from_resolution(resolution, seed=8128)
    before = blueprint.pack_source.name_pools.given
    big = lob.Lob(
        name="wide", title="Wide", purpose="Many people.", engine=resolution.engine,
        roles=[industry.ROOT, *[lob.RoleSpec(key=f"w{i}", title=f"W {i}", function="Wide", reports_to="ceo") for i in range(60)]],
        responsibilities=[],
    )
    grown = blueprint.lob(big)
    after = grown.pack_source.name_pools.given
    assert len(after) > len(before) and after[: len(before)] == before
    authored = blueprint.pack_source.model_copy(
        update={"name_pools": blueprint.pack_source.name_pools.model_copy(update={"given": ["Ada", "Bea", "Cy"]})}
    )
    from dataclasses import replace

    kept = replace(blueprint, pack_source=authored).lob(big)
    assert kept.pack_source.name_pools.given == ["Ada", "Bea", "Cy"]


def test_a_project_takes_an_explicit_lob_selection_and_refuses_an_unknown_one() -> None:
    spec = industry.project("retail", "Northstar Retail", lobs=("billing", "ap"))
    assert [lob.name for lob in spec.lobs] == ["ap", "billing"]
    assert spec.acknowledged_unmet == ()
    with pytest.raises(ValueError, match="no derived LOB is named"):
        industry.project("retail", "Northstar Retail", lobs=("wizardry",))


def test_a_project_builds_into_a_world_that_seats_its_lobs(tmp_path: Path) -> None:
    from worldloom.studio.service import Studio

    spec = industry.project("retail", "Northstar Retail")
    world, _ = Studio(tmp_path).snapshot(spec)
    for lob in spec.lobs:
        assert (
            f"{lob.name}_head" in world._roles and f"{lob.name}_analyst" in world._roles
        )
    assert world.validate().ok


def test_the_studio_preset_starts_any_catalogue_industry_from_its_programme() -> None:
    from worldloom.studio.service import Studio, preset

    spec = preset("telecom", "Ardent Telecom")
    assert spec == industry.project("telecom", "Ardent Telecom")
    with pytest.raises(ValueError, match="derived programme"):
        preset("alchemy", "Gold Co")
    headline = Studio._programme_headline(spec.model_dump(mode="json"))
    assert (
        headline is not None
        and headline["industry"] == "telecom"
        and headline["situations"] == 5550
    )
    assert (
        Studio._programme_headline({"company": {"industry": "a Bavarian widget maker"}})
        is None
    )
    assert (
        Studio._programme_headline({"company": {"industry": "a regional bank"}})[
            "industry"
        ]
        == "banking"
    )  # type: ignore[index]


def test_a_project_meets_its_own_evidence_requirements_from_the_world(tmp_path: Path) -> None:
    """Every hard connector requirement a catalogue project declares is satisfied
    by the records the world projects, so construction has nothing to refuse."""
    from worldloom.eval_candidates import check_requirement
    from worldloom.eval_design import RequirementKind
    from worldloom.process_bindings.ownership import materialize_owners
    from worldloom.studio.construction import restore_generator
    from worldloom.studio.service import Studio

    spec = industry.project("telecom", "Ardent Telecom", lobs=("billing",))
    assert [unit.key for unit in spec.divisions] == ["consumer_mobile", "enterprise", "network", "group_finance"]
    assert abs(sum(unit.share for unit in spec.divisions) - 1.0) < 0.01
    world, _ = Studio(tmp_path).snapshot(spec)
    # The support units the structure declares are the world's own, so
    # ownership has nothing to form and the world is returned as it is.
    assert materialize_owners(restore_generator(world), spec.structure) is not None  # type: ignore[arg-type]
    assert len(materialize_owners(restore_generator(world), spec.structure).business_units) == len(world.business_units)  # type: ignore[arg-type]
    checked = 0
    for use_case in spec.use_cases:
        assert use_case.construction is not None
        for requirement in use_case.construction.requirements:
            if requirement.kind is not RequirementKind.CONNECTOR or not requirement.hard:
                continue
            check = check_requirement(requirement, world)
            assert check.satisfied, (requirement.id, check.detail)
            assert requirement.selector["lob"] == use_case.lob
            checked += 1
    assert checked >= 2 * len(spec.use_cases)
