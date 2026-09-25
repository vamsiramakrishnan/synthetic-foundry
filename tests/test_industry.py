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


@pytest.fixture(scope="module")
def healthcare() -> industry.Programme:
    """The industry whose fifty-eight use cases all read `evidence_reconciliation`
    at `medium` before the capability and the difficulty were read off the rows."""
    return industry.programme("healthcare")


def _bound(derived: industry.Programme) -> list:
    return [row for row in derived.compiled.rows if row.binding_status == "bound"]


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
    # The programme carries one finding, and it is about the missing IN locale,
    # not about standing: every request here is asked by a seat that may ask.
    assert not [finding for finding in telecom.summary.findings if "standing" in finding]
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


def test_a_country_with_no_locale_still_says_so_though_none_is_left(tmp_path: Path) -> None:
    """The gap is closed, and the machinery that stated it still works.

    Every country the shipped industries build in now has a locale
    (`tools/ingest_locales.py` generated the ten that were missing), so no
    shipped programme raises this finding. The refusal is kept and tested
    against a country nobody ships, because the next catalogue to add one is
    the case it exists for: the alternative is a company built quietly in
    Australia with someone else's currency on its records.
    """
    from worldloom.studio.service import Studio

    # A country outside the registry, which is what the finding is for now.
    assert industry.unlocalised(("ZZ", "IN", "AU")) == ("ZZ",)
    assert industry.unlocalised(("AU", "NZ")) == ()
    assert industry.unlocalised(("IN", "SG")) == ()
    assert industry.locale_finding(("AU", "NZ")) is None
    assert industry.locale_finding(("IN", "SG")) is None
    gap = industry.locale_finding(("ZZ",))
    assert gap is not None and "ZZ" in gap and "locales.register" in gap

    # No shipped industry raises it any more, which is the point of the work.
    for name in ("telecom", "retail", "banking", "technology_saas"):
        assert not any(
            "a locale for" in finding
            for finding in industry.programme(name).summary.findings
        ), name

    spec = industry.project("telecom", "Ardent Telecom", lobs=("billing",))
    studio = Studio(tmp_path)
    project = studio.store.create(spec)
    findings = studio.describe(project["id"], project["revision"])["findings"]
    assert [f for f in findings if f["code"] == "locale_missing"] == []
    # A stated limit does not withhold readiness; an unanswered question does.
    assert all(f["acknowledged"] for f in findings)


def test_a_support_unit_is_a_business_unit_and_never_a_revenue_division() -> None:
    """A shared service centre sells nothing, so it earns no revenue share.

    `ownership.materialize_owners` makes it a real unit of the company with no
    trading revenue allocated; `divisions` is the revenue cut alone.
    """
    spec = industry.project("telecom", "Ardent Telecom")
    units = {unit.name for unit in spec.divisions}
    assert spec.structure is not None
    declared = {unit.name: unit.archetype for unit in spec.structure.bus}
    support = {name for name, kind in declared.items() if kind in industry.SUPPORT_ARCHETYPES}
    assert support, "the shipped telecom declares a shared service centre and a group function"
    assert not (units & support), f"support units took revenue: {sorted(units & support)}"
    assert units == set(declared) - support
    # Every declared unit still reaches the company; only the revenue differs.
    assert support <= set(declared)
    assert abs(sum(unit.share for unit in spec.divisions) - 1.0) < 0.02


def test_a_structure_of_only_support_units_still_decomposes() -> None:
    """A pack's shares must sum to one, so an all-support company cuts them flat."""
    from worldloom.process_bindings.models import BusinessUnit, CompanySpec

    structure = CompanySpec(
        name="Shared Services Only",
        industry="telecom",
        operating_model="centralised",
        countries=("IN",),
        bus=(
            BusinessUnit(name="Group Finance", archetype="group_function", countries=("IN",)),
            BusinessUnit(name="Operations", archetype="shared_service_centre", countries=("IN",)),
        ),
    )
    units = industry.divisions(structure)
    assert len(units) == 2
    assert abs(sum(unit.share for unit in units) - 1.0) < 0.02


def test_the_programme_reports_what_it_grounds_not_how_it_can_be_phrased(
    telecom: industry.Programme,
) -> None:
    """A verb and a channel change a request's wording, never its answer.

    So `situations` counts phrasings and overstates the evalset. The honest
    size is `distinct_answers`, and every consumer of a count reads that.
    """
    summary = telecom.summary
    grounded = {request.expected_answer for request in telecom.requests}
    assert summary.distinct_answers == len(grounded)
    # The overstatement is real, not a rounding difference.
    assert summary.distinct_answers < summary.situations
    assert summary.situations > summary.distinct_answers * 2
    # Per line, and summing to the whole.
    assert sum(line.distinct_answers for line in summary.lines) == summary.distinct_answers
    for line in summary.lines:
        assert 0 <= line.distinct_answers <= line.situations
    # A use case never asks for more queries than the line can answer.
    assert sum(case.count for case in telecom.use_cases()) == summary.distinct_answers
    assert industry.describe("telecom")["distinct_answers"] == summary.distinct_answers


def test_lines_derived_without_requests_report_no_distinct_answers(
    telecom: industry.Programme,
) -> None:
    """`lines` is usable without requests; it then says so rather than guessing."""
    bare = industry.lines(telecom.compiled, telecom.lobs)
    assert bare and all(line.distinct_answers == 0 for line in bare)
    assert [line.situations for line in bare] == [
        line.situations for line in telecom.summary.lines
    ]


# -- use cases ---------------------------------------------------------------


def test_a_use_case_per_supported_line_with_the_lines_count(
    telecom: industry.Programme,
) -> None:
    cases = telecom.use_cases()
    supported = [line for line in telecom.summary.lines if line.supported]
    assert len(cases) == len(supported)
    for case, line in zip(cases, supported, strict=True):
        # The count is what the line can distinctly ground, never the larger
        # number of ways to phrase it.
        assert case.count == line.distinct_answers
        assert line.distinct_answers <= line.situations
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
    # The requested total is what the lines ground, not the phrasings over them.
    assert sum(case.count for case in cases) == telecom.summary.distinct_answers
    assert sum(case.count for case in cases) < telecom.summary.situations


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


# -- capability and difficulty, read off the rows ---------------------------


def test_a_use_case_carries_the_capability_and_difficulty_its_rows_justify(
    healthcare: industry.Programme,
) -> None:
    """Every healthcare use case used to be `evidence_reconciliation` at
    `medium`. The rows never said that: they span eight activity types and one
    to three evidence channels, so the derived set spans capabilities and
    difficulties, and each use case wears its own line's."""
    cases = healthcare.use_cases()
    rows = _bound(healthcare)
    # The rows justify a spread: report-only lines, control steps, and evidence
    # in one channel on some activities and in several on others.
    assert {row.type for row in rows} >= {"report", "reconcile", "execute"}
    assert {len(set(row.channels)) > 1 for row in rows} == {True, False}
    capabilities = {case.construction.capability for case in cases}  # type: ignore[union-attr]
    difficulties = {case.construction.difficulty for case in cases}  # type: ignore[union-attr]
    assert len(capabilities) >= 2 and len(difficulties) >= 2
    assert capabilities == {"search", "evidence_reconciliation", "reconcile"}
    assert difficulties == {"medium", "hard"}
    supported = [line for line in healthcare.summary.lines if line.supported]
    for case, line in zip(cases, supported, strict=True):
        assert case.construction is not None
        assert case.construction.capability == line.capability
        assert case.construction.difficulty == line.difficulty
        closing = case.construction.steps[-1]
        assert closing.id == industry.CLOSING_STEP[line.capability]
        assert closing.capability == line.capability
        assert set(closing.depends_on) == {step.id for step in case.construction.steps[:-1]}
        assert case.construction.candidate_count == 1
    # The summary counts the same use cases the same way.
    summary = healthcare.summary
    assert list(summary.capabilities) == list(industry.CAPABILITY_ORDER)
    assert list(summary.difficulties) == list(industry.DIFFICULTY_ORDER)
    assert sum(summary.capabilities.values()) == sum(summary.difficulties.values()) == len(cases)
    assert summary.capabilities == {
        capability: sum(1 for case in cases if case.construction.capability == capability)  # type: ignore[union-attr]
        for capability in industry.CAPABILITY_ORDER
    }
    # A uniform property stays uniform and is said. Every shipped activity
    # declares an exception path, so no use case is easy, and the sentence
    # names that property with its count rather than spreading the label.
    assert all(row.exception.strip() for row in rows)
    assert summary.difficulties["easy"] == 0
    assert [sentence.split(":")[0] for sentence in summary.uniformity] == ["no use case is easy"]
    assert f"{len(rows)} of {len(rows)} bound activities declare an exception path" in summary.uniformity[0]
    # Derived, so the same rows give the same labels, twice.
    again = industry.programme("healthcare")
    assert [case.model_dump(mode="json") for case in again.use_cases()] == [
        case.model_dump(mode="json") for case in cases
    ]


def test_the_capability_and_the_difficulty_are_functions_of_the_row(
    telecom: industry.Programme,
) -> None:
    """Two rows that differ only in `type` differ in capability and in nothing
    else; two that differ only in `exception` differ in difficulty and in
    nothing else. No draw, no clock, no hash, no position in the set."""
    # Any row whose evidence spreads and whose exception path is declared, made
    # an `execute` so the type is known; every other property stays the row's.
    row = next(
        row for row in _bound(telecom) if len(set(row.channels)) > 1 and row.exception.strip()
    ).model_copy(update={"type": "execute"})
    assert industry.activity_capability(row) == "evidence_reconciliation"
    assert industry.activity_difficulty(row) == "hard"

    # `type` moves the capability and leaves the difficulty where it was.
    report = row.model_copy(update={"type": "report"})
    control = row.model_copy(update={"type": "reconcile"})
    assert industry.activity_capability(report) == "search"
    assert industry.activity_capability(control) == "reconcile"
    assert industry.activity_difficulty(report) == industry.activity_difficulty(row)
    assert industry.activity_difficulty(control) == industry.activity_difficulty(row)
    for kind in ("capture", "approve", "decide", "notify", "escalate"):
        assert industry.activity_capability(row.model_copy(update={"type": kind})) == "evidence_reconciliation"

    # `exception` moves the difficulty and leaves the capability where it was.
    no_exception = row.model_copy(update={"exception": ""})
    assert industry.activity_difficulty(no_exception) == "medium"
    assert industry.activity_capability(no_exception) == industry.activity_capability(row)
    # Whitespace is not an exception path.
    assert industry.activity_difficulty(row.model_copy(update={"exception": "   "})) == "medium"
    # So does the number of channels the evidence lands in; the two together
    # make hard, either alone medium, neither easy.
    one_channel = row.model_copy(update={"channels": ("system_record",)})
    assert industry.activity_difficulty(one_channel) == "medium"
    assert industry.activity_difficulty(one_channel.model_copy(update={"exception": ""})) == "easy"
    # A duplicated channel is still one channel.
    assert industry.activity_difficulty(
        no_exception.model_copy(update={"channels": ("email", "email")})
    ) == "easy"

    # A line takes the most demanding of its rows, in the declared orders.
    assert industry.line_capability([report, row]) == "evidence_reconciliation"
    assert industry.line_capability([report, control]) == "reconcile"
    assert industry.line_capability([report, report]) == "search"
    easy = one_channel.model_copy(update={"exception": ""})
    assert industry.line_difficulty([easy, no_exception]) == "medium"
    assert industry.line_difficulty([easy, row]) == "hard"
    assert industry.line_difficulty([easy]) == "easy"
    with pytest.raises(ValueError, match="no bound activity"):
        industry.line_capability([])


def test_uniformity_names_the_property_that_keeps_a_value_out(
    healthcare: industry.Programme,
) -> None:
    """The honest output of a uniform property is uniform, plus a sentence
    saying which property. Strip the exception paths and the sentence follows
    the rows: the set gains easy, loses hard, and says why."""
    rows = _bound(healthcare)
    lines = healthcare.summary.lines
    assert industry.uniformity(lines, rows) == healthcare.summary.uniformity
    assert [s.split(":")[0] for s in healthcare.summary.uniformity] == ["no use case is easy"]

    stripped = tuple(row.model_copy(update={"exception": ""}) for row in healthcare.compiled.rows)
    relined = industry.lines(
        healthcare.compiled.model_copy(update={"rows": stripped}), healthcare.lobs
    )
    assert {line.difficulty for line in relined} == {"easy", "medium"}
    assert {line.capability for line in relined} == {line.capability for line in lines}
    sentences = industry.uniformity(relined, stripped)
    assert [s.split(":")[0] for s in sentences] == ["no use case is hard"]
    assert f"0 of {len(rows)} bound activities declare an exception path" in sentences[0]

    # A single-type catalogue cannot search or reconcile, and says so once each.
    executes = tuple(row.model_copy(update={"type": "execute"}) for row in healthcare.compiled.rows)
    relined = industry.lines(
        healthcare.compiled.model_copy(update={"rows": executes}), healthcare.lobs
    )
    sentences = industry.uniformity(relined, executes)
    assert [s.split(":")[0] for s in sentences] == [
        "no use case is a search",
        "no use case reconciles",
        "no use case is easy",
    ]
    assert "no bound activity is read-only (type report)" in sentences[0]
    assert "no bound activity is a control step (type reconcile)" in sentences[1]

    # Nothing to say when there is nothing to say it about.
    assert industry.uniformity((), rows) == ()


def test_a_use_case_request_reads_as_a_request_and_names_only_what_the_rows_carry(
    healthcare: industry.Programme,
) -> None:
    """`work admit to discharge for Billing (Corporate Services; SG)` was a slug
    with spaces in it. The request now names the activities, the owning units,
    the countries, the stream and the systems, every one of them the rows' own,
    with the verb the line's capability supplies, and leaves no placeholder."""
    cases = healthcare.use_cases()
    supported = [line for line in healthcare.summary.lines if line.supported]
    by_line: dict[tuple[str, str], list] = {}
    for row in _bound(healthcare):
        by_line.setdefault((row.function, row.stream), []).append(row)
    verbs = {"search": "Report on ", "reconcile": "Reconcile ", "evidence_reconciliation": "Move "}
    for case, line in zip(cases, supported, strict=True):
        assert case.construction is not None
        text = case.construction.request_template
        assert text == industry.request_for(line, by_line[(line.lob, line.stream)])
        names = list(dict.fromkeys(row.activity for row in by_line[(line.lob, line.stream)]))
        # Every activity when the line lists them, the first and the last when
        # it counts them: a twelve-activity line is a sentence, not a dump.
        named = names if len(names) <= industry.NAMED_ACTIVITIES else [names[0], names[-1]]
        assert all(name in text for name in named), text
        if len(names) > industry.NAMED_ACTIVITIES:
            assert f"({len(names)} activities)" in text, text
        assert all(owner in text for owner in line.owners), text
        assert all(country in text for country in line.countries), text
        assert line.stream_name in text, text
        assert all(system in text for system in line.systems), text
        assert text.startswith(verbs[line.capability]), text
        assert text.endswith("."), text
        for placeholder in ("{", "}", "<", ">", "TODO", "TBD", "..."):
            assert placeholder not in text, text
        assert not text.startswith("work "), text
    assert any(len(line.activities) > industry.NAMED_ACTIVITIES for line in supported)


# -- the whole programme, every industry -----------------------------------


@pytest.mark.parametrize("name", INDUSTRIES)
def test_every_shipped_industry_derives_a_complete_honest_programme(name: str) -> None:
    derived = industry.programme(name)
    summary = derived.summary
    assert summary.industry == name
    # Findings are for things the programme cannot make honest. The only one a
    # shipped industry still raises is the locale gap for TH and VN, which no
    # library publishes a deep enough name pool to close; everything else, the
    # measured employment included, is answered.
    assert all(finding.startswith("a locale for ") for finding in summary.findings)
    for finding in summary.findings:
        assert "TH" in finding or "VN" in finding, finding
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
        "evalrun-cases.jsonl",
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
    assert described["lobs"] == len(described["by_lob"])
    assert described["findings"] == []
    assert sum(described["intents"].values()) == described["situations"]
    # What the use cases span, and the sentence for what they cannot show.
    assert list(described["capabilities"]) == list(industry.CAPABILITY_ORDER)
    assert list(described["difficulties"]) == list(industry.DIFFICULTY_ORDER)
    assert sum(described["capabilities"].values()) == described["lines"] - len(described["unsupported_lines"])
    assert described["difficulties"]["easy"] == 0 and described["uniformity"]


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
    assert set(industry.aliases().items()) <= set(words.items())


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
    by_key = {line.key: line.distinct_answers for line in derived.summary.lines}
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

    # Audit reads ServiceNow and compliance reads Salesforce: their records
    # are the catalogue's, restated on the emulator the line reads.
    spec = industry.project("telecom", "Ardent Telecom", lobs=("billing", "audit", "compliance"))
    # Only the units that sell are revenue divisions.
    assert [unit.key for unit in spec.divisions] == ["consumer_mobile", "enterprise"]
    assert abs(sum(unit.share for unit in spec.divisions) - 1.0) < 0.01
    world, _ = Studio(tmp_path).snapshot(spec)
    # The snapshot forms the support units the structure declares, with no
    # trading revenue: the company is every unit, the revenue is two of them.
    assert [(unit.name, unit.kind) for unit in world.business_units] == [
        ("Consumer Mobile", "customer_segment"),
        ("Enterprise", "customer_segment"),
        ("Group Finance", "support"),
        ("Network", "support"),
    ]
    # Having formed them once, ownership has nothing left to form.
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


def test_a_project_derives_from_a_described_company_and_rederives_keeping_its_selection(tmp_path: Path) -> None:
    """The interview settles the company; the catalogue derives the rest."""
    from worldloom.process_bindings import BusinessUnit, CompanySpec

    described = CompanySpec(
        name="Ardent Telecom", industry="telecom", operating_model="federated", countries=("IN",),
        bus=(
            BusinessUnit(name="Consumer", archetype="customer_segment"),
            BusinessUnit(name="Enterprise", archetype="customer_segment"),
            BusinessUnit(name="Shared Services", archetype="shared_service_centre"),
        ),
    )
    spec = industry.project(described, lobs=("billing",))
    assert spec.structure == described
    # Shared Services is a declared business unit and not a revenue division.
    assert [unit.name for unit in spec.divisions] == ["Consumer", "Enterprise"]
    assert [lob.name for lob in spec.lobs] == ["billing"]
    assert spec.use_cases and all(case.lob == "billing" for case in spec.use_cases)
    # The company operates in IN and is therefore spelled there: rupees, an
    # April financial year, Indian names and cities, and lakh digit grouping.
    # It used to say "australia", which was the geography gap in one field.
    assert spec.company == {"industry": "telecom", "identity": {"company_name": "Ardent Telecom"}, "geo": "india"}
    assert industry.project(described, lobs=("billing",)) == spec
    with pytest.raises(ValueError, match="names 'Ardent Telecom'"):
        industry.project(described, "Other Co")
    with pytest.raises(ValueError, match="needs the company's name"):
        industry.project("telecom")
    # A re-derivation keeps what is not derived and the families seated now.
    changed = described.model_copy(update={"bus": (*described.bus, BusinessUnit(name="Wholesale", archetype="customer_segment"))})
    again = industry.rederive(spec.model_copy(update={"structure": changed, "episodes": ("2026-03",)}))
    assert again.episodes == ("2026-03",) and again.seed == spec.seed
    assert [unit.name for unit in again.divisions] == ["Consumer", "Enterprise", "Wholesale"]
    assert [lob.name for lob in again.lobs] == ["billing"]
    assert again == industry.rederive(spec.model_copy(update={"structure": changed, "episodes": ("2026-03",)}))
    everything = industry.rederive(spec.model_copy(update={"lobs": ()}))
    assert len(everything.lobs) > 1
    with pytest.raises(ValueError, match="has none"):
        industry.rederive(spec.model_copy(update={"structure": None, "divisions": (), "lobs": (), "use_cases": ()}))
    # The locale follows the first country that has one, and every country the
    # shipped industries build in now does.
    assert industry.geo_for(("IN",)) == "india"
    assert industry.geo_for(("SG", "DE")) == "singapore"
    assert industry.geo_for(("ZZ", "DE")) == "germany"


def test_the_process_kinds_are_in_the_registry_of_a_process_that_never_imported_industry() -> None:
    """A project written by one process lints the same in another: the
    catalogue's `process.<stream>` kinds are registry data, not an import."""
    import subprocess
    import sys

    code = (
        "import sys\n"
        "from worldloom import factkinds\n"
        "assert 'worldloom.industry' not in sys.modules\n"
        "assert factkinds.resolvable('process.order_to_cash')\n"
        "assert factkinds.get('process.usage_to_bill').generated_by == 'worldloom.industry'\n"
        "print(len([k for k in factkinds.names() if k.startswith('process.')]))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert int(result.stdout.strip()) == len(industry.stream_names())
    # Registering the same catalogue again is a harmless reload.
    assert set(industry.register_kinds()) <= set(factkinds.names())


def test_an_engine_less_industry_seats_its_revenue_function_in_the_commercial_seats(tmp_path: Path) -> None:
    """A telecom's commercial seats are Customer Service, titled from O*NET,
    not retail's merchandising; a retailer keeps its own organisation."""
    from worldloom.process_bindings import compile_company, default_company
    from worldloom.studio.service import Studio

    assert industry.revenue_function(compile_company(default_company("telecom"))) == "customer_service"
    assert industry.revenue_function(compile_company(default_company("logistics"))) == "fulfilment"
    assert industry.role_table(default_company("retail", name="R")) is None
    table = industry.role_table(default_company("telecom", name="T"))
    assert table is not None
    rows = {row["key"]: row for row in table["table"]}
    assert rows["merch_lead"]["title"] == "Customer Service Director" and rows["merch_lead"]["function"] == "Customer Service"
    assert rows["merch_analyst"]["title"] == "Customer Service Administrator"
    assert rows["merch_lead"]["reports_to"] == "gm_md" and rows["cfo"]["title"] == "Group Chief Financial Officer"
    buyer = next(post for post in table["unit_roles"] if post["suffix"] == "_buyer")
    assert buyer["title"] == "Customer Service Manager, {unit}" and buyer["manager_suffix"] == "_md"
    assert buyer["kinds"] == ["customer_segment"]
    assert {row["key"] for row in table["table"]} == {role.key for role in __import__("worldloom.roles", fromlist=["x"])._shipped("retail")}
    spec = industry.project("telecom", "Ardent Telecom", lobs=("billing",))
    world, _ = Studio(tmp_path).snapshot(spec)
    titles = [person.title for person in world.people]
    assert "Customer Service Director" in titles and "Customer Service Manager, Consumer Mobile" in titles
    # A support unit sells nothing, so no per-unit commercial or finance post
    # is minted inside it; it is led by an existing group executive instead.
    assert not any(title.endswith(", Group Finance") or title.endswith(", Network") for title in titles)
    units = {unit.name: unit for unit in world.business_units}
    assert units["Group Finance"].kind == "support" and units["Network"].kind == "support"
    ceo = next(person for person in world.people if person.title == "Group Chief Executive Officer")
    assert units["Group Finance"].leader_id == ceo.id
    assert not any("Merchandising" in title or "Buying" in title for title in titles)
    assert "Head of Billing" in titles
    assert world.validate().ok


def test_record_requests_run_as_evalrun_cases_over_the_companys_records(tmp_path: Path) -> None:
    """The evalset the catalogue implies is runnable: each record request is an
    `evalrun` case whose plan searches the company's records, whose outcome is
    the records the search must return and the answer read off them, and
    whose reference run passes wherever the rubric can be graded without a model."""
    from typer.testing import CliRunner

    from worldloom.cli import app
    from worldloom.enterprise_rows import runtime_records
    from worldloom.evalrun.agents import ReferenceAgent
    from worldloom.evalrun.contract import CASE_SET_FILE, is_case_set, read_case_set
    from worldloom.evalrun.rater import JUDGE_ONLY, GroundedRater
    from worldloom.evalrun.runner import run_cases, service_for
    from worldloom.evalrun.session import EvalSession
    from worldloom.process_bindings import BusinessUnit, CompanySpec

    company = CompanySpec(name="Ardent Telecom", industry="telecom", operating_model="centralised", countries=("IN",),
                          bus=(BusinessUnit(name="Consumer", archetype="customer_segment"),
                               BusinessUnit(name="Group Finance", archetype="group_function")))
    derived = industry.programme(company)
    cases = derived.evalrun_cases()
    assert len(cases) == derived.summary.record_requests > 0
    assert cases == industry.evalrun_cases(derived)
    first = cases[0]
    request = next(r for r in derived.requests if r.id == first.id)
    assert first.query == request.brief and first.outcomes.answer is not None
    assert first.outcomes.answer.golden == request.expected_answer and first.outcomes.answer.rubric is request.grading
    assert all(node.connector == "sor" and node.kind == "search" for node in first.plan.nodes)
    assert first.row["expected_answer"] == request.expected_answer and first.row["shape"] == industry.RECORD_LOOKUP_SHAPE
    assert set(request.expected_record_ids) <= set(first.outcomes.unstructured.required_records if first.outcomes.unstructured else ()) | {
        rid for assertion in first.row["assertions"] for rid in assertion["records"]}
    assert first.dimensions["lob"] == request.lob and first.dimensions["intent"] == request.intent
    declaration_only = next(r for r in derived.requests if not r.expected_record_ids)
    with pytest.raises(ValueError, match="declaration"):
        industry.evalrun_row(declaration_only, derived.records)
    # The reference run is the ceiling: every gradable case passes, the
    # judge-only shapes stay ungraded rather than green.
    subset = [case for case in cases if case.outcomes.answer.rubric not in JUDGE_ONLY][:3] + [
        case for case in cases if case.outcomes.answer.rubric in JUDGE_ONLY][:1]
    service = service_for(subset, runtime_records(list(derived.records)))
    report = run_cases(service, subset, ReferenceAgent(subset), rater=GroundedRater())
    by_id = {result.case_id: result for result in report.results}
    for case in subset:
        result = by_id[case.id]
        assert result.score is not None and result.score.plan.score == 1.0 and result.score.trajectory.score == 1.0
        assert result.score.assertion_status == "ok", result.score.assertion_fails
        if case.outcomes.answer.rubric in JUDGE_ONLY:
            assert not result.score.passed
        else:
            assert result.score.passed, (case.id, result.score.outcomes)
    # The export writes the case set beside the records, and the CLI and the SDK read it back.
    written = derived.export(tmp_path / "programme")
    assert CASE_SET_FILE in written and is_case_set(tmp_path / "programme")
    read, records = read_case_set(tmp_path / "programme")
    assert read == cases and len(records) == len(derived.records) and records[0]["fid"] == derived.records[0].id
    session = EvalSession.from_export(tmp_path / "programme", limit=2)
    assert session.cases == cases[:2]
    runner = CliRunner()
    result = runner.invoke(app, ["evalrun", "run", str(tmp_path / "programme"), "--out", str(tmp_path / "run"),
                                 "--limit", "2", "--rater", "grounded", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["cases"] == 2


# -- a function is not an industry ------------------------------------------


def test_a_function_and_a_stream_are_told_apart_from_an_industry() -> None:
    """The three are asked for in the same words, and only one builds a company."""
    assert industry.industry_of("a regional bank") == "banking"
    assert industry.function_of("a regional bank") is None
    assert industry.function_of("a procurement company") == "procurement"
    assert industry.function_of("accounts payable outsourcing") == "ap"
    assert industry.stream_of("procure to pay") == "procure_to_pay"
    assert industry.stream_of("Order to Cash") == "order_to_cash"
    # A stream is not folded into one family: the catalogue's own activity
    # ownership says `procure_to_pay` spans several.
    assert industry.function_of("procure to pay") is None


def test_naming_a_function_where_an_industry_belongs_says_so() -> None:
    finding = industry.function_finding("a procurement company")
    assert finding is not None
    assert "is a function, not an industry" in finding
    assert "lobs=('procurement',)" in finding
    # An industry is not a finding, and neither is a phrase naming nothing.
    assert industry.function_finding("a regional bank") is None
    assert industry.function_finding("a scorecard vendor") is None


def test_naming_a_value_stream_names_the_families_it_crosses() -> None:
    finding = industry.function_finding("procure to pay")
    assert finding is not None and "value stream, not an industry" in finding
    owners = {
        activity[3]
        for activity in industry.load_catalogue()["value_streams"]["procure_to_pay"]["activities"]
    }
    assert all(owner in finding for owner in owners)


def test_every_shipped_industry_names_an_industry_not_a_function() -> None:
    """The twelve are industries. None of them is a function family."""
    for name in INDUSTRIES:
        assert industry.function_of(name.replace("_", " ")) is None, name
