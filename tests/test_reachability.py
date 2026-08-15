"""Every entity a company declares reaches something — and the spine now does.

`validate.carried_evidence` closed "a fact minted and carried nowhere". Nothing
ever asked the dual: **a subject declared and reaching nothing**. When this gate
was written it refused, on one-period builds of the four shipped verticals:

    retail       cost centre 2/2 · person 14/23 · service 4/4 · system 5/5
    banking      business unit 3/3 · cost centre 2/2 · person 11/21 ·
                 service 1/4 · site 133/133 · system 4/5
    insurance    business unit 3/3 · category 5/6 · cost centre 2/2 ·
                 person 7/10 · site 29/29 · system 5/5
    procurement  business unit 3/3 · category 6/8 · cost centre 2/2 ·
                 person 7/12 · site 81/81 · system 5/5

Banking, insurance and procurement between them declared 243 sites, 9 business
units and 6 cost centres that no fact named and no document carried, and every
one of those corpora reported clean from `worldloom validate`. Retail was the
only vertical whose organisation was load-bearing, which is also why it minted
588 facts from one period against banking's 58.

Three engines then made their estates real, and the same measurement now reads:

    retail       cost centre 2/2 · person 14/23 · service 4/4 · system 5/5
    banking      person 10/21 · service 1/4 · system 4/5
    insurance    person 2/10
    procurement  person 6/12 · system 5/5

**Every business unit, site, cost centre and category in every shipped vertical
now reaches a compiled document** — 243 sites, 9 units, 6 cost centres and 11
categories that reached nothing before. Volume followed exactly as the finding
predicted it would: banking 58 → 744 facts, insurance 62 → 219, procurement
52 → 217. That is the point of the table above being kept rather than replaced.
It is the before and after of one claim.

What is left is a different class, and worth naming so nobody reads it as the
same debt half-paid. A **system** is the *provenance* of a figure — every fact
in these corpora carries one as `source_system` — not the subject of one; a
**service** is the same thing one layer down; and the unreached **people** are a
roster with no accountability fact of their own. None of the three is a
reporting dimension any of these companies declares itself cut by, which is now
checkable rather than assertable: no populated `axes.Shape` axis on any of the
four industries is sourced from `estate` or `roster`, and every axis that *is*
populated — `division`, `book`, `segment`, `branch`, `office`, `store`,
`category`, `class_of_business` — reaches. `test_the_declared_shape_is_the_one
_that_is_real` pins that as a floor.

The tests below are therefore not a check that the gate passes. They are the
*measurement*, pinned as a **ceiling**: a build that reaches fewer entities than
today fails. A ratchet cannot be satisfied by switching the check off, because
the number it asserts is the count of failures.

`validate.reachability`'s own docstring says why the group is not yet in
`validate.run` and what promoting it costs. The short version: it is the correct
verdict and an untrue statement about *coherence*, which is the question
`worldloom validate` answers, and every corpus here is coherent — what it was
was thin.
"""

from __future__ import annotations

import pytest

from worldloom import archetypes, domains, validate
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose

SEED = 8128
PERIOD = "2026-03"

#: The four shipped verticals, by the archetype a plain `worldloom build` uses.
VERTICALS: dict[str, str] = {
    "retail": "omnichannel_retailer",
    "banking": "midsize_adi",
    "insurance": "midsize_general_insurer",
    "procurement": "midsize_infrastructure_services",
}

#: What each vertical refuses today, as `{kind: (unreached, declared)}`.
#:
#: Measured, not chosen — `worldloom build --seed 8128 --archetype <key>` for
#: each, then `validate.reachability` over what came out. A kind absent from a
#: row reaches everything it declares, which is now true of `business unit`,
#: `site`, `cost centre` and `category` in all four rows.
#:
#: Tightened as each engine landed, and tightening it is the deliverable: these
#: numbers only ever come down. The module docstring keeps what they were, so
#: the diff between the two tables is the wave.
REFUSED: dict[str, dict[str, tuple[int, int]]] = {
    "retail": {
        "cost centre": (2, 2),
        "person": (14, 23),
        "service": (4, 4),
        "system": (5, 5),
    },
    "banking": {
        "person": (10, 21),
        "service": (1, 4),
        "system": (4, 5),
    },
    "insurance": {
        "person": (2, 10),
    },
    "procurement": {
        "person": (6, 12),
        "system": (5, 5),
    },
}

#: Entity kinds no vertical may leave unreached, ever again.
#:
#: The ceiling above catches a kind getting *worse*; it cannot catch a kind that
#: is currently perfect going bad, because a ratchet only looks at what is
#: already broken. This is the floor under the reporting spine, and it is stated
#: once for every vertical rather than as an absence from four rows, so that a
#: fifth vertical added to `VERTICALS` inherits the requirement instead of
#: quietly opting out of it by having no row at all.
#:
#: `cost centre` is deliberately **not** here, and the reason is the sharpest
#: single line in this file. Banking, insurance and procurement all closed
#: theirs; retail — the vertical the other three were measured against, and the
#: only one this wave did not touch — is now the sole corpus whose cost centres
#: reach nothing. The reference implementation is the laggard, on exactly the
#: dimension it was the reference for. Adding it here is the next increment and
#: it belongs to whoever owns `generators/finance.py`, not to a widened constant.
LOAD_BEARING: tuple[str, ...] = ("business unit", "site", "category")


def _build(archetype_key: str):  # type: ignore[no-untyped-def]
    """One period of *archetype_key*'s vertical, compiled.

    Through `domains.for_archetype` rather than by naming four world classes,
    because that registry is what the CLI's own build dispatch resolves through
    — so a fifth vertical is measured here by adding one line to `VERTICALS`
    rather than by editing this function. Retail is the one exception and the
    registry says so: it registers `single_episode=None` because its build loops
    closes and threads incident flags through them, so its scenario is named
    here explicitly.
    """
    domain = domains.for_archetype(archetype_key)
    assert domain is not None, archetype_key
    world = domain.world(seed=SEED, archetype=archetypes.get(archetype_key)).build()
    scenario = (
        domain.single_episode(PERIOD)
        if domain.single_episode is not None
        else MonthEndClose(period=PERIOD)
    )
    return world.run(scenario).compile()


@pytest.fixture(scope="module")
def built():  # type: ignore[no-untyped-def]
    """One compiled world per vertical, built on first use and cached.

    Lazy rather than a dict comprehension over all four, which is not a
    performance choice: a module-scoped fixture that builds every vertical up
    front turns one broken engine into an error on every test in this file,
    including the ones that never touch it. Four verticals are four independent
    subjects and a report that says so is worth the eight lines.
    """
    cache: dict[str, object] = {}

    def get(name: str):  # type: ignore[no-untyped-def]
        if name not in cache:
            cache[name] = _build(VERTICALS[name])
        return cache[name]

    return get


def _refusals(world) -> dict[str, tuple[int, int]]:  # type: ignore[no-untyped-def]
    """`{kind: (unreached, declared)}` read back off the report's own text.

    Off the violation rather than recomputed: a test that re-derived the counts
    would pass while the reported message said something else, and the message
    is what a person acts on.
    """
    out: dict[str, tuple[int, int]] = {}
    for violation in validate.reachability(world).violations:
        assert violation.group == "organisation", violation
        kind = violation.code.removesuffix("_reaches_nothing").replace("_", " ")
        head = violation.detail.split(" ")
        out[kind] = (int(head[0]), int(head[2]))
    return out


@pytest.mark.parametrize("vertical", sorted(VERTICALS))
def test_the_measured_refusals_are_a_ceiling(built, vertical: str) -> None:  # type: ignore[no-untyped-def]
    """The gate, ratcheted.

    Deliberately asymmetric, and the asymmetry is the whole design. A kind that
    starts refusing when it did not is a straight failure — an entity kind that
    was load-bearing and stopped is a document that stopped reporting on it. A
    kind that refuses *more* than recorded is a regression. A kind that refuses
    *fewer* passes, because that is the work landing.

    Equality was the first rule here and it is wrong in a repository where three
    engines are being made load-bearing in parallel: the first lane to land
    would turn this file red for the other two, and a red suite is a suite
    people stop reading. The cost is that `REFUSED` can drift downward without
    the file saying so, which is why the numbers are also stated in this
    module's docstring — a stale ceiling still catches every regression, and a
    ceiling nobody can land work against catches nothing at all.
    """
    measured = _refusals(built(vertical))
    expected = REFUSED[vertical]

    appeared = sorted(set(measured) - set(expected))
    assert not appeared, (
        f"{vertical} now declares {appeared} that nothing reaches. An entity"
        " kind that was load-bearing and stopped is a document that stopped"
        " reporting on it."
    )
    for kind, (unreached, declared) in sorted(expected.items()):
        got = measured.get(kind, (0, declared))
        assert got[0] <= unreached, (
            f"{vertical}/{kind}: {got[0]} of {got[1]} reach nothing, worse than"
            f" the recorded {unreached} of {declared}. Nobody raises these."
        )


@pytest.mark.parametrize("vertical", sorted(VERTICALS))
def test_the_reporting_spine_is_load_bearing_everywhere(built, vertical: str) -> None:  # type: ignore[no-untyped-def]
    """The positive claim, and the only assertion here that can fail upward.

    Every ceiling above looks at what is already broken, so none of them can see
    a kind that is currently perfect going bad. This one can: it is the floor,
    and it is what makes an estate difficult to quietly abandon. Deleting the
    workbook that reports on branches would leave the banking ceiling perfectly
    satisfied — 133 branches reaching nothing is not "worse than" a row that no
    longer exists — and would fail here on the first run.

    Written as one parametrised claim over all four verticals rather than four
    hand-written assertions, because the interesting property is that it is the
    *same sentence* for every engine. When it was four assertions it could only
    ever have been true of retail.
    """
    measured = _refusals(built(vertical))
    unreached = {k: measured[k] for k in LOAD_BEARING if k in measured}
    assert not unreached, (
        f"{vertical} declares an organisation it does not report on: {unreached}."
        " Units, sites and categories are the dimensions these companies say"
        " they are cut by; a corpus that leaves one decorative is the defect"
        " this module's docstring records three engines being rebuilt to close."
    )


def test_a_grocer_declares_a_store_axis_and_says_nothing_about_44_of_them(built) -> None:  # type: ignore[no-untyped-def]
    """The violation quotes the declaration it contradicts.

    A site reaching nothing is only a defect because the company said it was cut
    that way. Without that quotation the finding reads as this module's opinion
    about how much a corpus ought to contain, which is an argument nobody can
    settle. With it, it is the corpus disagreeing with itself.

    This asked the *bank* the same question until three engines closed their
    estates, and where it moved to is worth recording rather than quietly
    editing. `axes.shape_of('Banking')` still declares its populated `branch`
    axis; all 133 branches now reach, so banking no longer contradicts itself
    and there is no violation left to quote anything. The same is true of every
    other axis-backed kind on all four shipped verticals — which is precisely
    why this had to move to keep testing the mechanism at all, and why the
    kinds still refused there (`system`, `service`, `person`) cannot host it:
    no populated axis on any of those industries is sourced from `estate` or
    `roster`, so their violations correctly quote nothing.

    The grocer keeps it honest and pays for itself twice, because its 44
    distribution centres are also the subject of the exemption tests below: the
    quotation is what makes that exemption an argument the reader can evaluate
    rather than a silenced row.
    """
    grocer = _build("australian_grocery")
    sites = [
        v for v in validate.reachability(grocer).violations
        if v.code == "site_reaches_nothing"
    ]
    assert len(sites) == 1, sites
    assert "'store'" in sites[0].detail
    assert "axes.shape_of('Supermarkets and omnichannel retail')" in sites[0].detail

    # And the half that moving this test could have silently dropped: banking
    # declares the axis it used to contradict, and now agrees with it.
    assert "site" not in _refusals(built("banking"))


def test_the_appendix_does_not_count_as_reaching(built) -> None:  # type: ignore[no-untyped-def]
    """The trap `carried_evidence`'s docstring records, in this direction.

    The supporting-fact appendix is one row per `intent.required_fact_ids`, so a
    check that counted it would be measuring the plan and reporting on the
    corpus. Asserted against the mechanism rather than against an outcome,
    because today the two agree: the appendix carries four facts across the four
    verticals that no visible section does, and every one of their subjects is
    reached by some other fact anyway. So this pins the *rule* — hidden sections
    are not the readable surface — which is what stops the next generator from
    satisfying the gate with an appendix and an empty page.
    """
    world = built("banking")
    surface = validate._Validator(world)._readable_surface()
    everything = {f for ir in world.artifact_irs for f in ir.fact_ids()}

    hidden_only = everything - surface
    assert hidden_only, (
        "banking's appendix carried a fact no visible section did when this was"
        " written; if that is no longer true, the distinction still holds but"
        " this test has stopped demonstrating it"
    )
    for ir in world.artifact_irs:
        for section in ir.sections:
            if section.hidden:
                continue
            for fact_id in section.fact_ids:
                assert fact_id in surface


def test_a_plan_only_corpus_is_checked_zero_times() -> None:  # type: ignore[no-untyped-def]
    """`compiled_evidence`'s early return, and for its reason.

    Nothing is compiled, so there is no readable surface for an entity to be
    missing from, and reporting an estate as unreachable there would be reading
    the absence of documents as a defect in the organisation. `examples/retail-
    close` is exactly this corpus.
    """
    world = RetailWorld(seed=SEED).build()
    report = validate.reachability(world)
    assert report.checks_run == 0
    assert report.ok


# ---------------------------------------------------------------------------
# The exemption mechanism
# ---------------------------------------------------------------------------


#: The exemption a supermarket group's own module should declare, written here.
#:
#: `validate` ships no exemptions at all, on purpose: registering this one from
#: core would put a retail industry name in the thin waist. It belongs beside the
#: generator that mints zero-weight sites, and that module is not this lane's to
#: edit — so it is written out here, exercised against the real 1,607-site
#: estate, and reported for the retail owner to move.
GROCERY_DISTRIBUTION_CENTRES = validate.Structural(
    kind="sites",
    industry="Supermarkets and omnichannel retail",
    holds=lambda site: site.revenue_weight == 0.0,
    reason=(
        "A distribution centre holds stock and sells nothing, which the estate"
        " states positively by giving it a zero revenue weight so that a"
        " store-level P&L does not invent turnover for a warehouse. The retail"
        " engine cuts exactly one measure by site — trading revenue, allocated"
        " by that weight — so there is nothing about a zero-weight site for a"
        " fact to say. Disagree with this by minting a throughput or a"
        " cost-to-serve measure the estate owns, at which point the exemption"
        " should go rather than be widened."
    ),
    declared_by="worldloom/models.py:Site.revenue_weight",
)


@pytest.fixture
def grocery_exemption():  # type: ignore[no-untyped-def]
    validate.register_structural(GROCERY_DISTRIBUTION_CENTRES)
    try:
        yield GROCERY_DISTRIBUTION_CENTRES
    finally:
        validate._STRUCTURAL.pop(
            (GROCERY_DISTRIBUTION_CENTRES.kind,
             GROCERY_DISTRIBUTION_CENTRES.industry,
             GROCERY_DISTRIBUTION_CENTRES.reason),
            None,
        )


def test_core_declares_no_exemptions_of_its_own() -> None:
    """The registry is a seam, not a place core keeps a list.

    An exemption is a claim about one industry's estate, so a core-registered
    one would be core knowing what a distribution centre is — the coupling
    `tests/test_thin_waist.py` exists to ratchet down. And an *unscoped* one, no
    industry at all, would be a claim about every business this repository can
    build; none of the arguments for an exemption survives that generalisation.
    """
    declared = validate.structural_exemptions()
    assert not [x for x in declared if not x.industry], declared


def test_the_exemption_is_narrow_and_earns_its_place(built, grocery_exemption) -> None:  # type: ignore[no-untyped-def]
    """One declared exemption, and what it deliberately does not cover.

    `Site.revenue_weight == 0` in a supermarket group covers 44 distribution
    centres of a 1,607-site estate — sites the archetype states sell nothing —
    and it is the only reason that estate is not refused.

    The same predicate also matches insurance's claims centres and procurement's
    materials yards, and it does not touch them, because the exemption is scoped
    to the industry it is an argument about. That scoping has since been proved
    the right call by events rather than by argument: a claims centre owns a
    claims count and a materials yard owns held materials, both engines went and
    minted exactly those, and both kinds of site now reach. An exemption written
    one industry wider would have declared them structural and made that work
    unnecessary — it would have closed the finding by agreeing with it.

    That contrast is the test. An exemption that covered every zero-weight site
    everywhere would be a blanket wearing a reason.
    """
    dc = grocery_exemption
    grocer = _build("australian_grocery")
    exempt = [s for s in grocer.sites if dc.covers("sites", grocer.company.industry, s)]
    assert len(exempt) == 44, len(exempt)
    assert all(s.revenue_weight == 0.0 for s in exempt)
    assert "site" not in _refusals(grocer)

    for vertical in ("insurance", "procurement"):
        world = built(vertical)
        zero = [s for s in world.sites if s.revenue_weight == 0.0]
        assert zero, vertical
        assert not [
            s for s in zero if dc.covers("sites", world.company.industry, s)
        ], f"the grocer's exemption reached {vertical}"


def test_without_the_exemption_the_estate_is_refused() -> None:
    """The control, and the reason the exemption is not decoration.

    Undeclared, those same 44 sites are a refusal on a corpus whose estate is
    otherwise the one working example in this repository. A mechanism that
    changed nothing when removed would not be a mechanism.
    """
    grocer = _build("australian_grocery")
    assert _refusals(grocer)["site"] == (44, 1607)


def test_an_exemption_must_carry_a_reason_and_a_known_kind() -> None:
    """The two ways a declaration stops being one.

    A reason is what separates this from an allowlist — an entry with none is
    "SITE-0114 is fine", which tells the next reader nothing about the next
    entity. And an exemption naming a kind nothing checks is a sentence no code
    reads, the same defect `axes.lint` reports as an axis nothing populates.
    """
    with pytest.raises(ValueError, match="reason"):
        validate.register_structural(
            validate.Structural(
                kind="sites", industry="", holds=lambda e: True,
                reason="   ", declared_by="tests/test_reachability.py",
            )
        )
    with pytest.raises(ValueError, match="entity kind"):
        validate.register_structural(
            validate.Structural(
                kind="warehouses", industry="", holds=lambda e: True,
                reason="a reason", declared_by="tests/test_reachability.py",
            )
        )


def test_two_sources_for_one_exemption_is_refused() -> None:
    """`register_domain_checks`' posture, for the same reason.

    An exemption is only worth anything if a reader can open `declared_by` and
    find the declaration the predicate reads. Two answers to that means import
    order decides what a corpus may leave unreachable.
    """
    claim = dict(
        kind="cost_centres", industry="Nowhere Ltd",
        reason="a cost centre that exists only to be charged against",
    )
    first = validate.Structural(
        holds=lambda e: True, declared_by="tests/test_reachability.py", **claim)
    validate.register_structural(first)
    try:
        validate.register_structural(first)  # idempotent
        with pytest.raises(ValueError, match="already exempted"):
            validate.register_structural(
                validate.Structural(
                    holds=lambda e: False, declared_by="somewhere/else.py", **claim)
            )
    finally:
        validate._STRUCTURAL.pop(
            (claim["kind"], claim["industry"], claim["reason"]), None)


def test_a_site_predicate_is_never_run_over_a_cost_centre(built) -> None:  # type: ignore[no-untyped-def]
    """Found by the check itself, on its first run.

    `holds` reads a field that exists on one collection, so applying every
    declared exemption to every kind does not quietly return False — it raises
    `AttributeError` off pydantic when a site's `revenue_weight` is asked of a
    `CostCentre`. Hence `covers` compares the kind first, and hence this test.
    """
    world = built("retail")
    for exemption in validate.structural_exemptions():
        for centre in world.cost_centres:
            assert exemption.covers(
                "cost_centres", world.company.industry, centre) is False
