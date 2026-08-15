"""Which documents a company files, and why it is a consequence rather than a list.

`worldloom mosaic -n 5` builds five companies with different headcounts, spans,
reporting depths, estates from nine to a hundred and one nodes, different trading
years and different physics — and before this module's subject existed they filed
*identical paperwork*: the same thirteen artifact types in the same counts,
including exactly three unit commentaries, in all five. Structure had diversified
and the document set, which is the product, had not moved at all.

What these tests hold is the shape of the fix rather than its numbers. Three
independent kinds of demand decide the plan — what the company claims about who
it answers to (`facets.FILING_PREFIX`), what it runs (`planning.EstateReading`),
and where this month sits in its own year — and each is checked here for the
property that makes it safe: it is *off* on a stock build, it is a pure function
of the world, and the type it names is one the compiler has actually been told
about.

The last is the one worth stating plainly. A plan entry for an artifact type no
module declared still compiles: `compile_intent` falls through to `outline`,
`outline` falls through to a one-section stub, and `standing` falls through to
"unreviewed draft". The corpus would carry a document nobody designed and report
success — carried, cited and inert, which is the failure this repository keeps
finding. `facets.unmet` is where that is refused, and
`test_a_filing_for_a_type_nothing_declares_is_reported` is why.
"""

from __future__ import annotations

from collections import Counter

import pytest

from worldloom import (
    MonthEndClose,
    RetailWorld,
    World,
    documents,
    facets,
    profiles,
    scenarios,
)
from worldloom.generators import planning

PERIOD = "2026-03"

#: December on the engine's own trading year — the one month a stock retailer's
#: year is planned around. See `planning.PEAK_TRADING_INDEX`.
PEAK_PERIOD = "2026-12"

#: Every type the filing block can mint. Not derived from `planning`'s source,
#: deliberately: a test that read the answer out of the thing it is testing
#: would pass on a block that minted nothing.
FILING_TYPES = frozenset({
    "service_impact_assessment", "remediation_scope_review", "peak_trading_review",
    "audit_committee_pack", "sponsor_pack", "member_report", "ministerial_brief",
})


def _world(*, period: str = PERIOD, estate: str | None = None,
           facet: dict[str, str] | None = None) -> World:
    claims = facets.resolve(**facet).claims if facet else ()
    built = RetailWorld(seed=8128, estate=estate, lore_claims=claims).build()
    return built.run(MonthEndClose(period=period, include_operational_incident=True))


def _types(world: World) -> Counter:
    return Counter(intent.artifact_type for intent in world.artifact_intents)


# ---------------------------------------------------------------------------
# The floor: nothing fires unless something asks
# ---------------------------------------------------------------------------


def test_a_stock_close_files_none_of_them() -> None:
    """The whole change is a no-op on the default build, and it has to be.

    Byte identity is verified by diffing four archetypes against `git archive
    HEAD`, which is the real gate — this is the cheap version that fails first
    and says which type leaked. A threshold chosen a little lower, or a
    seasonal index a little looser, renumbers every ART id in every corpus this
    project has shipped, including the reference narration in `examples/`.
    """
    assert not FILING_TYPES & set(_types(_world()))


def test_the_estate_thresholds_sit_above_the_estate_the_engine_ships() -> None:
    """Stated as an invariant, not as two integers somebody eyeballed.

    A stock world's nine-node landscape reads 1 downstream of the failed feed
    and 3 resting on the unowned mapping table. Both thresholds are above both
    readings, which is *why* the test above passes — asserting it here means a
    future landscape change that grew the stock estate would fail with a
    diagnosis rather than with a renumbered corpus.
    """
    world = _world()
    episode = _last_episode(world)
    reading = scenarios._estate_reading(world, episode)

    assert reading is not None
    assert reading.incident_reach < planning.IMPACT_ASSESSMENT_REACH
    assert reading.unowned_reach < planning.REMEDIATION_REVIEW_REACH


def test_a_flat_trading_year_never_reaches_the_peak() -> None:
    """A bank or an insurer files no peak review, in any month of any year.

    `flat` is the right trading year for a business whose revenue is a book
    rather than a till, and the seasonal gate has to agree — a premium book
    that files a Christmas trading review is the same class of error as one
    that peaks at Christmas, which is what `profiles` exists to have fixed.
    """
    flat = profiles.named("flat")
    assert all(flat[month] < planning.PEAK_TRADING_INDEX for month in profiles.MONTHS)


def _last_episode(world: World):  # type: ignore[no-untyped-def]
    """The episode a world's last close produced, rebuilt from its own facts.

    `MonthEndClose.run` does not keep the `CloseEpisode` on the world, so this
    reconstructs only what `_estate_reading` reads: `had_incident`, the fact
    ids it looks up by name, and the facts themselves.
    """
    from types import SimpleNamespace

    by_kind = {}
    for fact in world.facts:
        by_kind.setdefault(fact.kind, fact)
    return SimpleNamespace(
        had_incident=True,
        facts=tuple(world.facts),
        keys={
            "fact_feed_status": by_kind["ops.feed_status"].id,
            "fact_owner": by_kind["ops.mapping_table_owner"].id,
        },
    )


# ---------------------------------------------------------------------------
# What the company runs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "estate,expected",
    [
        (None, frozenset()),
        ("small", frozenset({"service_impact_assessment"})),
        ("medium", frozenset({"service_impact_assessment", "remediation_scope_review"})),
        ("large", frozenset({"service_impact_assessment", "remediation_scope_review"})),
    ],
)
def test_the_estate_grades_the_incident_paperwork(estate, expected) -> None:
    """Three tiers, and the middle one is the point.

    A graded response rather than a boolean: an estate large enough that nobody
    can name what fell over produces the impact assessment, and only one large
    enough that the *unowned* component has a real readership produces the
    scope review as well. Both readings come off the same graph and they
    genuinely diverge — the small landscape reaches six downstream and fourteen
    onto the mapping table, the medium one fourteen and thirty-four.
    """
    assert FILING_TYPES & set(_types(_world(estate=estate))) == expected


# ---------------------------------------------------------------------------
# What the company sells, at this period
# ---------------------------------------------------------------------------


def test_a_month_the_year_is_planned_around_is_reviewed_on_the_years_terms() -> None:
    december = _types(_world(period=PEAK_PERIOD))
    march = _types(_world(period=PERIOD))

    assert december["peak_trading_review"] == 1
    assert march["peak_trading_review"] == 0
    # And it is an addition rather than a substitution: the variance memo still
    # reports the month against plan. The review exists because "against plan"
    # is the wrong frame *on its own* here, not because it is the wrong frame.
    assert december["cfo_variance_memo"] == 1


# ---------------------------------------------------------------------------
# Who the company answers to
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "facet,filed",
    [
        ({"listing": "listed"}, "audit_committee_pack"),
        ({"governance": "private_equity"}, "sponsor_pack"),
        ({"listing": "mutual"}, "member_report"),
        ({"listing": "state_owned"}, "ministerial_brief"),
    ],
)
def test_a_claim_about_who_the_company_answers_to_puts_a_document_in_the_plan(
    facet, filed
) -> None:
    """Each of these was a claim the corpus made and could not be asked about.

    Two of the four were `wants` entries — "a sponsor reporting pack with its
    own audience and cadence", "a parliamentary or ministerial reporting
    obligation with its own artifact type" — sitting in the registry as
    evidence that a facet implied something nothing implemented. They are
    filings now, and the `wants` entries are gone, because `unmet` reporting a
    capability that works is the same failure in reverse.
    """
    planned = _types(_world(facet=facet))

    assert planned[filed] == 1
    # Only that one. A listed company does not thereby brief a minister, and a
    # facet set that filed everything would be a facet set that said nothing.
    assert FILING_TYPES & set(planned) == {filed}


def test_a_founder_led_company_minutes_nothing() -> None:
    """The only negative filing in the registry, and the reason it is a signed
    magnitude rather than a set of names.

    The close still moved, the escalation still happened, and there is no
    document naming who was in the room. That absence is *evidence* — a harder
    corpus than one where the meeting never took place — and it is only
    expressible as "this company files less of this".
    """
    founder_led = _types(_world(facet={"governance": "founder_led"}))
    stock = _types(_world())

    assert founder_led["meeting_minutes"] == 0
    assert stock["meeting_minutes"] == 1
    # Nothing else moved. A suppression that also dropped the email thread
    # would be a company with no escalation rather than an undocumented one.
    assert set(stock) - set(founder_led) == {"meeting_minutes"}


def test_two_claims_about_one_document_sum_rather_than_one_of_them_winning() -> None:
    """The algebra, exercised through a real plan rather than restated here.

    Summing is what `scenarios.density_adjustment` already does, and reusing it
    is the whole argument for carrying filings as `ARTIFACT_DENSITY` constraints
    instead of adding a constraint kind. So it has to be *summing* and not
    last-wins or any-wins: a company that is founder-led and also has somebody
    insisting the escalation is minuted keeps its minutes, and it does so
    because -1.0 and +1.0 cancel, not because one claim was read last.

    Nothing in the shipped registry both files and suppresses one type — this
    builds the pair, because the behaviour has to be right before somebody
    writes a facet that needs it.
    """
    from worldloom.models import ConstraintKind, LoreConstraint, LoreKind

    insists = facets.LoreClaim(
        source="test:minuted",
        kind=LoreKind.NORM,
        assertion="Every decision that moves a group commitment is minuted.",
        constrains=(LoreConstraint(
            kind=ConstraintKind.ARTIFACT_DENSITY,
            target=facets.FILING_PREFIX + "meeting_minutes",
            effect="Somebody in this company insists on a written record",
            magnitude=1.0,
        ),),
    )
    founder_led = facets.resolve(governance="founder_led").claims

    def minutes(claims) -> int:  # type: ignore[no-untyped-def]
        world = RetailWorld(seed=8128, lore_claims=tuple(claims)).build().run(
            MonthEndClose(period=PERIOD, include_operational_incident=True)
        )
        return _types(world)["meeting_minutes"]

    assert minutes(founder_led) == 0
    assert minutes((*founder_led, insists)) == 1
    assert minutes((insists,)) == 1


# ---------------------------------------------------------------------------
# The registry: nothing plans a document nothing can build
# ---------------------------------------------------------------------------


def test_every_type_this_planner_can_file_is_declared() -> None:
    """A plan entry for an undeclared type compiles into a stub carrying an
    authority nobody chose, and reports success. This is the check that stops
    the filing block from being a way to add one.
    """
    assert FILING_TYPES <= documents.declared_types()


def test_every_filing_a_facet_implies_is_declared() -> None:
    """The registry's own claims, checked against the compiler's registry.

    Every consistent combination, not a hand-picked few: the whole point of a
    facet is that it composes, and a filing that only survives when its facet
    is claimed alone is a filing nobody can rely on.
    """
    for chosen in facets.combinations("listing", "governance"):
        resolved = facets.resolve(**chosen)
        for artifact_type, magnitude in facets.filings_from(resolved.lore):
            if magnitude <= 0.0:
                continue
            assert artifact_type in documents.declared_types(), (
                f"{chosen} implies a {artifact_type!r} filing that nothing declares"
            )
        # Said the other way round as well, through the channel a user reads:
        # no combination of claims the registry allows should report a filing
        # as unimplemented, because every one of them is.
        assert not any("filing" in want for want in facets.unmet(resolved))


def test_a_filing_for_a_type_nothing_declares_is_reported() -> None:
    """The `unmet` channel, on a claim the registry does not make.

    Constructed rather than found, because the registry is currently correct —
    and the check has to work on the day somebody registers a facet whose
    filing they have not written a document for, which is exactly when nobody
    is looking.
    """
    from dataclasses import replace

    from worldloom.models import ConstraintKind, LoreConstraint

    resolved = facets.resolve(listing="listed")
    widened = replace(resolved, lore=resolved.lore + (LoreConstraint(
        kind=ConstraintKind.ARTIFACT_DENSITY,
        target=facets.FILING_PREFIX + "quarterly_shareholder_circular",
        effect="A claim whose document nobody has written",
        magnitude=1.0,
    ),))

    reported = facets.unmet(widened)
    assert any("quarterly_shareholder_circular" in want for want in reported)
    # And the honest ones survive alongside it rather than being replaced.
    assert any("analyst consensus" in want for want in reported)


def test_a_suppression_of_an_undeclared_type_is_not_reported() -> None:
    """"This company files fewer of X" is satisfied by X not existing.

    Only a claim that a document *exists* can be unmet, and reporting the other
    direction would fill `unmet` with noise — which is how a channel whose
    whole value is that everything in it is real stops being read.
    """
    from dataclasses import replace

    from worldloom.models import ConstraintKind, LoreConstraint

    resolved = facets.resolve(listing="listed")
    widened = replace(resolved, lore=resolved.lore + (LoreConstraint(
        kind=ConstraintKind.ARTIFACT_DENSITY,
        target=facets.FILING_PREFIX + "nothing_writes_this",
        effect="Fewer of a document that does not exist",
        magnitude=-1.0,
    ),))

    assert not any("nothing_writes_this" in want for want in facets.unmet(widened))


# ---------------------------------------------------------------------------
# Determinism and replay
# ---------------------------------------------------------------------------


def test_the_plan_is_a_function_of_the_world_and_nothing_else() -> None:
    """No clock, no `random`, no set iteration — and no new `Rng` stream either.

    Every gate reads an integer or a float the world already fixed, which is
    what let this block be added without reshuffling anything downstream of an
    existing stream. Two builds of one description must agree exactly, ids
    included.
    """
    first = _world(estate="large", facet={"listing": "listed"})
    second = _world(estate="large", facet={"listing": "listed"})

    assert [(i.id, i.artifact_type, i.author_id, tuple(i.required_fact_ids))
            for i in first.artifact_intents] == \
           [(i.id, i.artifact_type, i.author_id, tuple(i.required_fact_ids))
            for i in second.artifact_intents]


def test_a_filed_corpus_compiles_and_agrees_with_itself() -> None:
    """Every filing this change can plan, in one world, compiled and validated.

    The combination is deliberately the largest one available — a listed
    company with a full estate closing its peak month — because the filings are
    independent and a bug where two of them collide (an id, an author who
    cannot see their own document, a fact cited before it existed) only shows
    up when they are all present.

    Built from `lore_claims` rather than through `--facet`, and the difference
    matters here: the flag settles *every* facet at its registry default, so
    `--facet listing=listed` also asserts `trading_pattern=steady` and puts a
    flat year on the builder — under which no month reaches the peak and this
    world would file three of the four. Passing the claims alone carries the
    filing consequence and leaves the trading year the engine's, which is what
    lets one world exercise all four.
    """
    world = RetailWorld(
        seed=8128, estate="large",
        lore_claims=facets.resolve(listing="listed").claims,
    ).build().run(
        MonthEndClose(period=PEAK_PERIOD, include_operational_incident=True)
    ).compile()

    planned = _types(world)
    assert planned["service_impact_assessment"] == 1
    assert planned["remediation_scope_review"] == 1
    assert planned["peak_trading_review"] == 1
    assert planned["audit_committee_pack"] == 1

    report = world.validate()
    assert report.ok, report.violations[:5]

    # Compiled, not merely intended: every filing has an IR with at least one
    # section that is not the hidden appendix. A filing that compiled to
    # nothing but its supporting-facts table would be a document with no
    # document in it, which the intent count alone cannot tell apart.
    by_intent = {ir.intent_id: ir for ir in world.artifact_irs}
    for intent in world.artifact_intents:
        if intent.artifact_type not in FILING_TYPES:
            continue
        sections = [s for s in by_intent[intent.id].sections if not s.hidden]
        assert sections, f"{intent.id} ({intent.artifact_type}) compiled to nothing"


def test_the_filings_survive_a_rebuild_from_the_recipe() -> None:
    """Replay is what makes a filing a consequence rather than a flag.

    A facet's filings ride the recipe as `lore_claims` — the claims, not the
    commitments they became — so a corpus rebuilt after the facet registry
    moves underneath it plans the same documents. The estate and the trading
    year ride it as themselves. Nothing new had to be recorded for any of this,
    and that is the argument for carrying the decision in lore rather than in a
    new recipe key.
    """
    from worldloom.recipe import rebuild

    original = _world(estate="medium", facet={"governance": "private_equity"})
    again = rebuild(original.recipe)

    assert _types(again) == _types(original)
    assert _types(again)["sponsor_pack"] == 1
    assert [i.id for i in again.artifact_intents] == \
           [i.id for i in original.artifact_intents]
