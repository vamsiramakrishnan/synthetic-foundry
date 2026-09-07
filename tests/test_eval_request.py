"""The request tuple: a case that says who asked, when, and for what.

Three properties are worth a test each, because each one is a promise made to
somebody outside this repository:

- a case with no request writes exactly the bytes it always did, which is what
  lets this land without a schema bump or a migration step;
- the intent table is closed and self-consistent, so a verb cannot claim a
  grading shape that does not exist or a deliverable it does not produce;
- a situation is derived from declarations, so the same catalogue yields the
  same situations in the same order.
"""
from __future__ import annotations

import json

import pytest

import worldloom
from worldloom import lob as lob_module
from worldloom.evals import intents as intents_module  # the submodule, not the function
from worldloom.evals.plausibility import _checks, findings
from worldloom.models import EvaluationCase, EvaluationType
from worldloom.process_bindings import compile_company, default_company, situations


def _case(**over: object) -> EvaluationCase:
    base: dict[str, object] = {
        "id": "EVAL-1",
        "question": "What was revenue?",
        "evaluation_type": EvaluationType.DIRECT_LOOKUP,
        "expected_fact_ids": ["FACT-1"],
    }
    base.update(over)
    return EvaluationCase(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The wire
# ---------------------------------------------------------------------------


def test_a_case_without_a_request_writes_the_bytes_it_always_did() -> None:
    """The whole reason this needs no schema bump.

    Frozen literally rather than compared against a constructed case: a test
    that built its expectation from the same model would pass just as happily
    if every key were renamed.
    """
    line = json.dumps(_case().model_dump(mode="json"), sort_keys=True)

    assert line == (
        '{"difficulty": "medium", "distractor_artifact_ids": [], "evaluation_type":'
        ' "direct_lookup", "expected_answer": null, "expected_fact_ids": ["FACT-1"],'
        ' "expects_abstention": false, "id": "EVAL-1", "question": "What was'
        ' revenue?", "reasoning": null, "required_artifact_ids": [],'
        ' "temporal_cutoff": null}'
    )


def test_a_request_adds_only_the_keys_it_carries() -> None:
    case = _case(asker="controller", intent="triage_queue")
    written = case.model_dump(mode="json")

    assert written["asker"] == "controller"
    assert written["intent"] == "triage_queue"
    # The five it does not carry stay off the wire entirely, so a partially
    # specified request costs only the keys it actually states.
    for absent in ("asker_person_id", "occasion", "channel", "constraint", "deliverable"):
        assert absent not in written


@pytest.mark.parametrize(
    "over",
    [
        {},
        {"asker": "controller", "intent": "triage_queue"},
        {
            "asker": "cfo",
            "asker_person_id": "PERSON-3",
            "occasion": "PCA-1",
            "intent": "sign_off",
            "evaluation_type": EvaluationType.AUTHORITY_RESOLUTION,
            "channel": "email",
            "constraint": "delegation limit",
            "deliverable": "an approval",
        },
    ],
)
def test_a_case_round_trips_through_the_wire(over: dict[str, object]) -> None:
    case = _case(**over)
    assert EvaluationCase.model_validate(case.model_dump(mode="json")) == case


def test_has_request_distinguishes_a_question_from_a_request() -> None:
    assert not _case().has_request
    assert _case(asker="controller").has_request


@pytest.mark.parametrize(
    ("over", "expected"),
    [
        ({"asker": "   "}, "asker must not be blank"),
        ({"channel": ""}, "channel must not be blank"),
        ({"deliverable": "a memo"}, "a deliverable needs the intent that produces it"),
    ],
)
def test_a_dishonest_request_is_refused(over: dict[str, object], expected: str) -> None:
    """Absent is the only honest spelling of absent.

    A blank string serializes, so it moves bytes and reads downstream as "there
    is an asker" while naming nobody.
    """
    with pytest.raises(ValueError, match=expected):
        _case(**over)


# ---------------------------------------------------------------------------
# The intent table
# ---------------------------------------------------------------------------


def test_the_intent_table_loads_and_is_closed() -> None:
    table = intents_module.intents()

    assert len(table) >= 40
    assert list(table) == sorted(table), "iteration order must not follow the file"
    for intent in table.values():
        assert intent.answer_shape in intents_module.ANSWER_SHAPES
        assert set(intent.activity_types) <= set(intents_module.ACTIVITY_TYPES)
        # The invariant that makes an intent gradable: a write owes an artifact
        # to be graded on, and a read must not be graded against one.
        assert (intent.deliverable is None) == (intent.effect == "read")


def test_every_intent_names_a_grading_shape_that_exists() -> None:
    for intent in intents_module.intents().values():
        assert isinstance(intent.grading, EvaluationType)


def test_only_an_abstention_may_require_no_evidence() -> None:
    for intent in intents_module.intents().values():
        if not intent.evidence_kinds:
            assert intent.grading is EvaluationType.EXPECTED_ABSTENTION


def test_applicability_is_filtered_by_the_activity_type() -> None:
    """The filter is the point: a verb that suited every activity would be a
    verb that describes no particular work."""
    approve = {i.id for i in intents_module.applicable("approve")}
    reconcile = {i.id for i in intents_module.applicable("reconcile")}

    assert "sign_off" in approve and "sign_off" not in reconcile
    assert "reconcile" in reconcile and "reconcile" not in approve
    assert approve != reconcile


def test_an_unknown_activity_type_is_refused_rather_than_answered_emptily() -> None:
    with pytest.raises(ValueError, match="unknown activity type"):
        intents_module.applicable("brainstorm")


def test_an_unknown_intent_is_named_in_the_refusal() -> None:
    with pytest.raises(ValueError, match="unknown intent 'ponder'"):
        intents_module.intent("ponder")


# ---------------------------------------------------------------------------
# Standing: who may ask
# ---------------------------------------------------------------------------


def test_a_role_asks_about_its_own_responsibilities() -> None:
    finance = lob_module.publish()["finance"]
    own = [ask for ask in lob_module.asks_about(finance, "controller") if ask.direction == "own"]

    assert own, "the controller holds responsibilities and so may ask about them"
    assert "financial.revenue" in own[0].fact_kinds
    assert own[0].via == "controller"


def test_a_manager_asks_down_and_a_report_asks_up() -> None:
    finance = lob_module.publish()["finance"]

    directions = {ask.direction for ask in lob_module.asks_about(finance, "cfo")}
    assert "down" in directions, "a manager asks its reports for status"

    directions = {ask.direction for ask in lob_module.asks_about(finance, "controller")}
    assert "up" in directions, "a report asks up for the authority its work needs"


def test_standing_follows_the_dot_boundary() -> None:
    """Answering for a family grants standing over what the family covers."""
    finance = lob_module.publish()["finance"]

    assert lob_module.may_ask_about(finance, "controller", "financial.revenue")
    assert lob_module.may_ask_about(finance, "controller", "financial.revenue.actual")
    assert not lob_module.may_ask_about(finance, "controller", "financial.revenues")


def test_an_unknown_role_may_ask_about_nothing() -> None:
    finance = lob_module.publish()["finance"]
    assert lob_module.asks_about(finance, "nobody_at_all") == ()


def test_asks_about_is_stable() -> None:
    finance = lob_module.publish()["finance"]
    assert lob_module.asks_about(finance, "cfo") == lob_module.asks_about(finance, "cfo")


# ---------------------------------------------------------------------------
# Plausibility
# ---------------------------------------------------------------------------


class _World:
    """A stand-in exposing the public collection the check group reads.

    `evaluations`, not `_evaluations`: an earlier draft read the private
    attribute, and a stand-in that invents whatever the code happens to reach
    for is how a check that never runs on a real corpus still passes its test.
    """

    def __init__(self, cases: tuple[EvaluationCase, ...]) -> None:
        self.evaluations = cases


@pytest.fixture
def no_installed_lob():
    """An empty LOB registry, restored afterwards.

    The registry is process-global, so another test file that installs a pack
    would otherwise decide this one's result. Asserted state has to be arranged,
    not assumed.
    """
    registry = lob_module.installed()
    lob_module._INSTALLED.clear()
    try:
        yield
    finally:
        lob_module._INSTALLED.update(registry)


@pytest.fixture
def installed_finance_lob():
    """Install the finance LOB the way a pack does, then put the registry back.

    Standing is checked against `lob.installed()`, the process registry, so a
    test that wants standing checked has to install something.
    """
    registry = lob_module.installed()
    lob_module.install(list(lob_module.publish().values()))
    try:
        yield lob_module.installed()
    finally:
        lob_module._INSTALLED.clear()
        lob_module._INSTALLED.update(registry)


def test_the_group_is_registered_by_install() -> None:
    worldloom._install()
    from worldloom import validate as validate_module

    assert "eval_plausibility" in validate_module._DOMAIN_CHECKS


def test_a_case_with_no_request_is_not_checked() -> None:
    violations, checks = _checks(_World((_case(),)))
    assert (violations, checks) == ([], 0)


def test_an_intent_that_grades_differently_is_a_violation() -> None:
    case = _case(intent="sign_off", deliverable="an approval")
    violations, _ = _checks(_World((case,)))

    assert [v.code for v in violations] == ["grading_disagrees"]
    assert "authority_resolution" in violations[0].detail


def test_an_undeclared_intent_is_a_violation() -> None:
    violations, _ = _checks(_World((_case(intent="ruminate"),)))
    assert [v.code for v in violations] == ["unknown_intent"]


def test_a_write_intent_owes_a_deliverable() -> None:
    case = _case(intent="sign_off", evaluation_type=EvaluationType.AUTHORITY_RESOLUTION)
    violations, _ = _checks(_World((case,)))
    assert [v.code for v in violations] == ["write_without_deliverable"]


def test_realism_is_a_finding_and_never_a_violation(installed_finance_lob) -> None:
    """A stretchy asker is worth reporting and must not fail a build."""
    world = _World((_case(asker="harbourmaster", intent="triage_queue"),))

    violations, _ = _checks(world)
    assert violations == []

    assert findings(world) == [
        "'EVAL-1' is asked by 'harbourmaster', a role no installed LOB declares"
    ]


def test_a_declared_asker_with_standing_draws_no_finding(installed_finance_lob) -> None:
    world = _World((_case(asker="controller", intent="triage_queue"),))
    assert findings(world) == []


def test_unchecked_standing_is_said_out_loud(no_installed_lob) -> None:
    """Silence would read as approval when in fact nothing was looked at.

    This is the defect the group shipped with in draft: it read an attribute
    no World has, so standing never ran anywhere while the report stayed clean.
    """
    world = _World((_case(asker="controller", intent="triage_queue"),))
    assert findings(world) == [
        "standing was not checked for 1 asker(s): this process holds no"
        " installed LOB to check against"
    ]


def test_the_group_reads_no_attribute_a_real_world_lacks() -> None:
    """The regression that motivated the fix, pinned against a real corpus."""
    from worldloom.evals import plausibility
    from worldloom.world import World

    world = World.load("examples/retail-close")
    assert not hasattr(world, "_lobs"), "if this ever gains one, revisit _lobs()"
    # The public collection is what the group reads, and it exists.
    assert plausibility._requests(world) == []


def test_a_deliverable_that_disagrees_with_its_verb_is_a_violation() -> None:
    case = _case(
        intent="sign_off",
        evaluation_type=EvaluationType.AUTHORITY_RESOLUTION,
        deliverable="a slide deck",
    )
    violations, _ = _checks(_World((case,)))
    assert [v.code for v in violations] == ["deliverable_disagrees"]


def test_a_request_with_no_asker_is_reported(no_installed_lob) -> None:
    world = _World((_case(occasion="PCA-1", intent="triage_queue"),))
    assert findings(world) == ["'EVAL-1' carries a request with no asker"]


# ---------------------------------------------------------------------------
# Situations
# ---------------------------------------------------------------------------


def test_a_situation_is_grounded_in_the_binding_it_came_from() -> None:
    compiled = compile_company(default_company("banking"))
    bindings = {row.id: row for row in compiled.rows}

    for situation in list(situations(compiled))[:200]:
        binding = bindings[situation.occasion]
        assert situation.activity == binding.activity
        assert situation.owner_bu == binding.owner_bu
        assert situation.country == binding.country
        assert situation.system_of_record == binding.sor_product
        assert situation.channel in binding.channels
        # The verb must be one the activity's own type admits.
        assert situation.intent in {i.id for i in intents_module.applicable(binding.type)}


def test_situations_are_derived_and_therefore_stable() -> None:
    compiled = compile_company(default_company("retail"))
    first = [s.key for s in list(situations(compiled))[:500]]
    second = [s.key for s in list(situations(compiled))[:500]]

    assert first == second
    assert len(set(first)) == len(first), "a situation key identifies one situation"


def test_an_exception_verb_carries_the_exception_as_its_constraint() -> None:
    compiled = compile_company(default_company("banking"))
    chases = [s for s in situations(compiled) if s.intent == "chase"]

    assert chases, "chasing is applicable somewhere in a bank"
    with_exception = [s for s in chases if "exception:" in s.constraint]
    assert with_exception, "a chase is grounded in what tripped, not in the control alone"


def test_unbound_rows_do_not_become_situations() -> None:
    """A question naming a unit the company does not have is the fabrication
    this path exists to avoid."""
    compiled = compile_company(default_company("logistics"))
    bindings = {row.id: row for row in compiled.rows}

    for situation in list(situations(compiled))[:300]:
        assert bindings[situation.occasion].binding_status == "bound"


def test_the_factoring_multiplies() -> None:
    """The claim the whole change rests on: situations come from a product of
    authored tables, not from a list somebody typed."""
    compiled = compile_company(default_company("banking"))
    counted = sum(1 for _ in situations(compiled))

    assert counted > 10_000


# ---------------------------------------------------------------------------
# Difficulty as features
# ---------------------------------------------------------------------------


def test_a_question_is_not_a_maximally_vague_request() -> None:
    """Scoring a legacy case as seven unstated slots would make every case in
    every existing corpus look like the hardest thing in the set."""
    from worldloom.evals import difficulty

    assert difficulty.features_for(_case()).unstated_slots == 0
    assert difficulty.features_for(_case(asker="controller")).unstated_slots == 6


def test_features_are_never_reported_as_fitted() -> None:
    """An unfitted number claiming to be measured is worse than the label it
    replaced."""
    from worldloom.evals import difficulty

    assert difficulty.features_for(_case()).fitted is False


def test_difficulty_moves_when_the_situation_moves() -> None:
    from worldloom.evals import difficulty

    easy = difficulty.features_for(_case(asker="a", intent="respond_to_query"))
    harder = difficulty.features_for(
        _case(
            asker="a",
            intent="prepare_pack",
            evaluation_type=EvaluationType.CROSS_ARTIFACT,
            deliverable="the board pack",
            temporal_cutoff=None,
            required_artifact_ids=["A1", "A2", "A3"],
            distractor_artifact_ids=["D1", "D2", "D3", "D4"],
        )
    )
    assert harder.bucket() != easy.bucket() or harder.slice_key() != easy.slice_key()
    assert harder.writes and not easy.writes


def test_the_slice_key_buckets_so_a_slice_has_members() -> None:
    """A slice with one member calibrates nothing."""
    from worldloom.evals import difficulty

    many = difficulty.features_for(_case(required_artifact_ids=[f"A{n}" for n in range(20)]))
    fewer = difficulty.features_for(_case(required_artifact_ids=[f"A{n}" for n in range(9)]))
    assert many.slice_key() == fewer.slice_key()


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


def test_coverage_reports_against_a_denominator_it_names() -> None:
    from worldloom.evals import coverage

    report = coverage.report([_case(), _case(id="E2", asker="controller", intent="chase",
                                             deliverable="a chaser")])
    assert report.cases == 2
    assert report.requests == 1, "a question is not a request"
    assert report.intents_available == len(intents_module.intents())
    assert report.intents_used == 1


def test_coverage_names_what_the_set_does_not_say() -> None:
    """The useful half: a number nobody acts on did not need computing."""
    from worldloom.evals import coverage

    gaps = coverage.report([_case()]).gaps()
    assert any("questions only" in g for g in gaps)

    reads_only = coverage.report([_case(asker="a", intent="triage_queue")]).gaps()
    assert any("only reads" in g for g in reads_only)


def test_available_defers_to_the_binding_coverage_the_generator_saw() -> None:
    from worldloom.evals import coverage

    compiled = compile_company(default_company("retail"))
    counts = coverage.available(compiled)
    assert counts["intents_declared"] == len(intents_module.intents())
    assert counts["situations"] > counts["occasions"]


# ---------------------------------------------------------------------------
# Review findings, each pinned so it cannot come back
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("over", "code"),
    [
        # A sign_off marked as an abstention is graded as a refusal by
        # `evaluate.score`, which branches on the flag and not on the type.
        (
            {
                "intent": "sign_off",
                "evaluation_type": EvaluationType.AUTHORITY_RESOLUTION,
                "deliverable": "an approval",
                "expects_abstention": True,
                "expected_fact_ids": [],
            },
            "abstention_disagrees",
        ),
        # And an abstain that forgets the flag is graded as an ordinary lookup.
        (
            {"intent": "abstain", "evaluation_type": EvaluationType.EXPECTED_ABSTENTION},
            "abstention_disagrees",
        ),
    ],
)
def test_the_abstention_flag_must_agree_with_the_grading_shape(
    over: dict[str, object], code: str
) -> None:
    violations, _ = _checks(_World((_case(**over),)))
    assert code in [v.code for v in violations]


def test_an_abstention_that_agrees_is_not_a_violation() -> None:
    case = _case(
        intent="abstain",
        evaluation_type=EvaluationType.EXPECTED_ABSTENTION,
        expects_abstention=True,
        expected_fact_ids=[],
    )
    violations, _ = _checks(_World((case,)))
    assert violations == []


class _PeopledWorld(_World):
    """A world that also holds people, for the referential check."""

    def __init__(self, cases, people=()) -> None:  # type: ignore[no-untyped-def]
        super().__init__(cases)
        self.people = people


def test_a_seated_asker_must_name_somebody_the_world_holds() -> None:
    """Referential, so a violation: the same defect as citing a missing fact,
    in a new field the evaluation branch of `validate` never looked at."""

    class _Person:
        id = "PERSON-0001"

    case = _case(asker="controller", asker_person_id="PERSON-9999")
    violations, _ = _checks(_PeopledWorld((case,), people=(_Person(),)))
    assert [v.code for v in violations] == ["asker_not_found"]

    seated = _case(asker="controller", asker_person_id="PERSON-0001")
    violations, _ = _checks(_PeopledWorld((seated,), people=(_Person(),)))
    assert violations == []


def test_standing_is_checked_against_the_facts_the_case_cites(
    installed_finance_lob,
) -> None:
    """The rule `may_ask_about` was added for, which an earlier draft declared
    and never applied: holding some responsibility is not standing to ask this."""
    from worldloom.world import World

    world = World.load("examples/retail-close")
    hr_fact = next(
        (f for f in world.facts if not f.kind.startswith("financial.")), None
    )
    assert hr_fact is not None, "retail-close holds a non-financial fact to ask about"

    case = _case(asker="controller", intent="triage_queue", expected_fact_ids=[hr_fact.id])

    class _Probe(_World):
        def __init__(self) -> None:
            super().__init__((case,))
            self.facts = world.facts

    reported = findings(_Probe())
    assert any(hr_fact.kind in line for line in reported), reported


def test_used_share_divides_like_by_like() -> None:
    """Occasions over triples understated utilisation by the number of verbs
    per occasion."""
    from worldloom.evals import coverage

    cases = [
        _case(id=f"E{n}", occasion="PCA-1", intent=verb, channel="email", deliverable=None)
        for n, verb in enumerate(("triage_queue", "find_exception", "reconcile"))
    ]
    report = coverage.report(cases, situations_available=6)

    assert report.occasions_used == 1
    assert report.situations_used == 3
    assert report.used_share == 0.5


def test_the_difficulty_bucket_reads_the_density_it_declares() -> None:
    from worldloom.evals import difficulty

    clean = difficulty.features_for(_case(required_artifact_ids=["A1"]))
    crowded = difficulty.features_for(
        _case(required_artifact_ids=["A1"], distractor_artifact_ids=["D1", "D2", "D3"])
    )

    assert crowded.distractor_density > clean.distractor_density
    assert crowded.bucket() != clean.bucket() or crowded.slice_key() != clean.slice_key()
