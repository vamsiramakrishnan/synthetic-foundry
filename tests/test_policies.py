"""The paperwork a company has, rather than the paperwork it produces.

Every document in this corpus was episodic — a close ran, an incident happened,
a return was filed. Measured on a twelve-period, eight-division build: 195
artifacts, of which 96 were the same type with a different division's name on
it, and not one of them was a policy. An assistant asked "what is our expense
approval threshold" had nothing to find, because the company had no rules.

Six properties, and they are the contract. That a standing document is
**derived** — its provisions are facts the document is written from, not
sentences a generator later parses back out. That it is **scaled**, so two
companies do not share a limit. That a revision is **supersession** and puts
two versions of one policy on the shelf. That it **stays coherent** with the
people who sign it. That the corpus **asks** about it. And that a build which
did not ask for policies is byte-for-byte the build that shipped before they
existed.
"""

from __future__ import annotations

import pytest

from worldloom import RetailWorld, policies
from worldloom.scenarios import MonthEndClose

PERIOD = "2026-03"


@pytest.fixture(scope="module")
def governed():  # type: ignore[no-untyped-def]
    return RetailWorld(seed=8128, policies="full").build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    ).compile()


# ---------------------------------------------------------------------------
# 1. Derived, not written
# ---------------------------------------------------------------------------


def test_every_provision_is_a_fact_the_document_cites(governed) -> None:  # type: ignore[no-untyped-def]
    """A clause is a fact the document is written *from*.

    The alternative — prose with numbers in it that something later parses back
    out — is the direction of travel this whole repository runs against, and it
    is what makes a policy unanswerable: a limit stated only in a sentence is a
    limit no evaluation case can be grounded on and no validator can check.
    """
    specs = policies.by_artifact_type()
    facts = {fact.id: fact for fact in governed.facts}
    planned = [i for i in governed.artifact_intents if i.artifact_type in specs]
    assert planned, "the fixture asked for policies and got none"

    for intent in planned:
        assert intent.required_fact_ids, intent.artifact_type
        kinds = {facts[fact_id].kind for fact_id in intent.required_fact_ids}
        assert all(kind.startswith("policy.") for kind in kinds), intent.artifact_type


def test_a_provision_reaches_the_readable_surface(governed) -> None:  # type: ignore[no-untyped-def]
    """The provisions table, and every cell citing the fact it states.

    A figure in a table with no `fact_id` decorates a question rather than
    answering one — the corpus's own reachability check reads cited facts.
    """
    specs = policies.by_artifact_type()
    by_intent = {ir.intent_id: ir for ir in governed._artifact_irs}
    for intent in governed.artifact_intents:
        if intent.artifact_type not in specs:
            continue
        sections = by_intent[intent.id].sections
        provisions = next((s for s in sections if s.heading == "Provisions"), None)
        assert provisions is not None and provisions.table, intent.artifact_type
        assert not provisions.hidden, "a policy's provisions are the readable surface"
        cited = [
            row.cells["provision"].fact_id for row in provisions.table.rows
        ]
        assert all(cited), intent.artifact_type


# ---------------------------------------------------------------------------
# 2. Scaled, not typed
# ---------------------------------------------------------------------------


def test_two_companies_do_not_share_an_expense_limit() -> None:
    """A constant would make every company's handbook the same handbook.

    That is the failure this knob exists to avoid one level up — a corpus whose
    companies differ in structure and not in content — arriving again inside a
    single document.
    """
    from worldloom import archetypes

    def threshold(key: str) -> float:
        world = RetailWorld(
            seed=8128, archetype=archetypes.get(key), policies="core",
        ).build()
        fact = next(
            f for f in world.facts
            if f.kind == "policy.finance.approval_threshold" and f.valid_to is None
        )
        assert fact.value is not None
        return fact.value.amount

    small = threshold("omnichannel_retailer")
    large = threshold("australian_grocery")
    assert small != large, (small, large)


def test_a_money_provision_is_stated_in_currency_not_in_ledger_units(governed) -> None:  # type: ignore[no-untyped-def]
    """A receipt threshold of "4 AUD thousands" is a threshold nobody acts on.

    Every financial figure in this corpus is denominated in the company's own
    money unit because a P&L is read in thousands. A policy is not, and the
    conversion is `policies._PER_UNIT` — which is also the one place this could
    silently go wrong by a factor of a thousand.
    """
    receipt = next(
        f for f in governed.facts
        if f.kind == "policy.finance.receipt_threshold" and f.valid_to is None
    )
    assert receipt.value is not None
    assert receipt.value.unit == governed.company.currency, "bare currency, no scale"
    # A receipt threshold is tens or low hundreds. Bounded loosely rather than
    # pinned, so re-tuning a share does not edit this test — what it catches is
    # the factor-of-a-thousand slip, which no loose bound can hide.
    assert 10 <= receipt.value.amount <= 1_000, receipt.value.amount


def test_a_ladder_that_does_not_climb_is_refused() -> None:
    """A delegation of authority whose director limit sits below its manager
    limit is a document nobody can comply with — and scaling limits off revenue
    is exactly the operation that can produce one, because two rungs a decimal
    place apart round to the same figure at a small enough company.

    Refused rather than clamped: a library that quietly repaired its own ladder
    would hide the fact that the ladder was wrong for that company.
    """
    broken = policies.PolicySpec(
        name="broken", artifact_type="delegation_of_authority", title="Broken",
        area="corporate", domain="governance", audience="all_staff",
        owner="cfo", approver="ceo", purpose="x",
        clauses=(
            policies.Clause("manager_limit", "Manager", unit="currency", amount=100.0),
            policies.Clause("director_limit", "Director", unit="currency", amount=100.0),
        ),
    )
    with pytest.raises(ValueError, match="does not sit above"):
        policies._mint(
            broken, minter=__import__("worldloom").ids.Minter(), company_id="CO-1",
            revenue=1e9, currency="AUD",
            at=__import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc),
            roles={}, joined={},
        )


# ---------------------------------------------------------------------------
# 3. A revision is supersession
# ---------------------------------------------------------------------------


def test_a_revised_policy_leaves_both_versions_on_the_shelf(governed) -> None:  # type: ignore[no-untyped-def]
    """Two documents, one current, and only a date tells them apart.

    Minting the superseded *facts* alone was not enough and the corpus said so:
    the old threshold sat in the ledger and in no artifact, so
    `evaluation.answerable` dropped the question about it — correctly, and that
    drop is what found this.
    """
    chain = [i for i in governed.artifact_intents if i.supersedes]
    assert chain, "no policy carries a supersession edge"
    for intent in chain:
        earlier = governed.artifact_intents.by_id(intent.supersedes)
        assert earlier.artifact_type == intent.artifact_type, "same document, two versions"
        assert set(earlier.required_fact_ids).isdisjoint(intent.required_fact_ids)

    stale = [f for f in governed.facts
             if f.kind.startswith("policy.") and f.valid_to is not None]
    assert stale, "a revision that closed no window is not a revision"
    for fact in stale:
        current = next(f for f in governed.facts
                       if f.kind == fact.kind and f.valid_to is None)
        assert current.supersedes == fact.id


def test_a_policy_is_never_dated_before_whoever_signed_it(governed) -> None:  # type: ignore[no-untyped-def]
    """Clamped forward, never back — `form_units`' rule about a unit and its
    leader, and `validate.author_not_yet_employed` catches the violation the
    moment it is not applied. Found exactly that way: the superseded expense
    policy dated five years back was signed by a controller who joined three
    years ago."""
    report = governed.validate()
    assert not [v for v in report.violations if v.code == "author_not_yet_employed"], \
        report.violations[:3]


# ---------------------------------------------------------------------------
# 4. The corpus asks about it
# ---------------------------------------------------------------------------


def test_the_questions_an_assistant_is_actually_asked(governed) -> None:  # type: ignore[no-untyped-def]
    """"What is our expense approval threshold" is the query a real archive gets
    most, and this corpus could not state it, let alone answer it."""
    questions = {case.question: case for case in governed.evaluations}
    asked = [q for q in questions if "threshold" in q or "leave" in q or "keep" in q]
    assert len(asked) >= 3, sorted(questions)

    # And the hard one: the figure that moved.
    temporal = [c for c in governed.evaluations
                if "before the current version" in c.question]
    assert temporal, "a revision nobody asks about teaches nothing"
    assert temporal[0].difficulty == "hard"


# ---------------------------------------------------------------------------
# 5. Off by default
# ---------------------------------------------------------------------------


def test_a_build_that_asked_for_nothing_is_untouched() -> None:
    """A strict no-op — the same object back, not an equal one.

    `--estate` and `--master-data`'s guarantee, and the reason every corpus
    built before this module existed is byte-for-byte what it was.
    """
    world = RetailWorld(seed=8128).build()
    assert policies.applied(world, None) is world
    assert policies.applied(world, "none") is world
    assert not [f for f in world.facts if f.kind.startswith("policy.")]


def test_an_unknown_level_is_refused_naming_what_is_on_offer() -> None:
    with pytest.raises(ValueError, match="unknown policy level"):
        policies.check_level("everything")


def test_the_level_rides_the_recipe_and_replays() -> None:
    """The *level*, never the documents: what a policy says is derived from the
    company's own revenue and role table, so recording the level re-runs the
    same derivation while recording the documents would freeze a copy of what
    the library said that day."""
    from worldloom.recipe import rebuild

    world = RetailWorld(seed=8128, policies="core").build()
    assert world._recipe["policies"] == "core"
    again = rebuild(world._recipe)
    assert [f.model_dump() for f in again.facts] == [f.model_dump() for f in world.facts]
    assert [i.model_dump() for i in again.artifact_intents] == \
        [i.model_dump() for i in world.artifact_intents]


def test_raising_the_level_only_ever_adds() -> None:
    """Each level is a superset of the one before, so a corpus regenerated at a
    higher level still contains every document it had."""
    core = {spec.name for spec in policies.selected("core")}
    full = {spec.name for spec in policies.selected("full")}
    assert core < full


def test_an_area_is_claimed_once() -> None:
    """`locales.register`'s rule: a name is claimed once, so a collision is a
    wiring error and not an override — a company whose handbook was generated
    yesterday still generates the same handbook."""
    with pytest.raises(ValueError, match="already registered"):
        policies.register("finance", ())
