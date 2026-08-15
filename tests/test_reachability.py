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

Three engines then made their estates real, and the same measurement read:

    retail       cost centre 2/2 · person 14/23 · service 4/4 · system 5/5
    banking      person 10/21 · service 1/4 · system 4/5
    insurance    person 2/10
    procurement  person 6/12 · system 5/5

Every business unit, site, cost centre and category in those three now reaches a
compiled document — 243 sites, 9 units, 6 cost centres and 11 categories that
reached nothing before. Volume followed exactly as the finding predicted it
would: banking 58 → 744 facts, insurance 62 → 219, procurement 52 → 217. That is
the point of both tables above being kept rather than replaced. They are the
before and after of one claim, and neither is the live measurement: `REFUSED`
below is, over ten build paths rather than four.

**Then the same question was asked of every company this repository can build,
rather than of four, and the answer was different.** The measurement below is
`REFUSED`, and it is taken over `archetypes.available()` and `examples/packs/`
rather than over a hand-written list of four keys — because a list of four keys
is what let two shipped archetypes, four shipped packs, every `--spec` company
and every future vertical be checked by nothing at all while this file reported
the problem closed. `probe.MEASURES` had the identical defect in the identical
week: a derivation computed over a hand-listed subset is a hand-kept list
wearing a derivation, and it fails silently and in the flattering direction.

What is left is two classes, and they are worth naming separately so nobody
reads them as one debt half-paid.

**The reporting spine** — business unit, site, cost centre, category — is what a
company says it cuts its own performance by. Four of the ten build paths still
leave part of it decorative, and **all four are the retail engine**: its two
archetypes, its pack, and `regional-insurer.json`, which is an insurer whose
`base` is `retail`. The reference implementation is the laggard on the dimension
it was the reference for. All four leave their cost centres decorative; two of
them, `australian_grocery` and `trading-retailer.json`, go further and leave
sites unreached on companies that declare a `store` axis — which is not thinness
but a corpus contradicting itself, and is why those two are marked in `REFUSED`.
Every one is recorded there and ratcheted downward.

**System, service and person are a different class and not a defect.** A system
is the *provenance* of a figure — every fact in these corpora carries one as
`source_system` — not the subject of one; a service is the same thing one layer
down; and the unreached people are a roster with no accountability fact of their
own. None of the three is a reporting dimension any of these companies declares
itself cut by, which is checkable rather than assertable: no populated
`axes.Shape` axis on any shipped industry is sourced from `estate` or `roster`,
and every axis that *is* populated — `division`, `book`, `segment`, `branch`,
`office`, `store`, `category`, `class_of_business` — reaches wherever the spine
does. That distinction is now load-bearing in code rather than in prose: the
violation quotes `axes.shape_of(industry)` when the company declares an axis
over that kind of entity and quotes nothing when it does not, and
`test_the_floor_is_what_the_company_itself_declares` pins that the floor below
is drawn from the quotation rather than from a tuple somebody maintains.

The tests here are therefore not a check that the gate passes. They are the
*measurement*, pinned as a **ceiling**: a build that reaches fewer entities than
today fails. A ratchet cannot be satisfied by switching the check off, because
the number it asserts is the count of failures.

`validate.reachability`'s own docstring carries the argument for why `run`
reports this group as an advisory rather than failing on it, and what would make
part of it a violation. The short version is measured rather than asserted:
filed as violations it fails 67 tests here and reports every corpus this engine
can build as incoherent, mostly on the three kinds the paragraph above says are
not defects.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from worldloom import archetypes, domains, packs, validate
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose

SEED = 8128
PERIOD = "2026-03"

#: Where the shipped industry packs live, relative to this file.
#:
#: Globbed rather than listed, for `BUILD_PATHS`' reason: a pack added to this
#: directory is a company somebody can build, and the previous shape of this
#: file checked none of the four that were already there.
PACK_DIR = Path(__file__).resolve().parent.parent / "examples" / "packs"


def _build_paths() -> tuple[str, ...]:
    """Every way this repository can be asked to build a company, enumerated.

    Two families, and both are read off a registry rather than typed out:

    * ``archetype:<key>`` for everything in ``archetypes.available()``, which is
      what ``worldloom build --archetype`` accepts and what a qualified key
      (``midsize_adi+mutual_bank``, ``omnichannel_retailer+5div``) resolves to.
    * ``pack:<file>`` for every JSON file in ``examples/packs``, which is what
      ``--pack`` loads and what a ``--spec`` company is composed into before it
      reaches ``domain.world.from_pack``.

    **This replaced four hand-written archetype keys, and the replacement is the
    point of the lane.** Those four omitted `australian_grocery` and
    `customer_owned_bank` — two shipped archetypes people really build, one of
    which was the worst offender in the repository — and all four packs, and a
    fifth vertical would have been omitted too by simply existing. The property
    worth having is that registering an archetype or dropping a pack in the
    directory is what puts it under this gate, rather than somebody remembering
    that this file exists; it is the same fix `probe.MEASURES` took in the same
    week, for the same defect.

    A qualified archetype is *not* enumerated, and the omission is deliberate
    rather than forgotten: `+wholesale_club` renames a company's words and
    `+5div` widens its unit count, neither of which changes which entities a
    fact can name. Enumerating the cross product would multiply build time by
    the size of two word lists to re-measure the same estate.
    """
    return tuple(
        [f"archetype:{key}" for key in archetypes.available()]
        + [f"pack:{path.name}" for path in sorted(PACK_DIR.glob("*.json"))]
    )


BUILD_PATHS: tuple[str, ...] = _build_paths()


def _default_path(domain_name: str) -> str:
    """The build path a plain ``worldloom build`` takes for one engine.

    Read off ``Domain.default_archetype`` rather than written down, because that
    field exists precisely to answer "which archetype does this domain build
    when a caller names the vertical" — and a second answer to it here would be
    a place for the two to disagree.
    """
    domain = domains.by_name(domain_name)
    assert domain is not None, domain_name
    return f"archetype:{domain.default_archetype}"


RETAIL = _default_path("retail")
BANKING = _default_path("banking")
INSURANCE = _default_path("insurance")
PROCUREMENT = _default_path("procurement")

#: The grocer, named explicitly because it is a *particular* company rather than
#: any engine's default: 1,607 sites of which 44 are distribution centres that
#: sell nothing, which is the only estate in this repository big enough and odd
#: enough to exercise the structural-exemption mechanism against real data.
GROCER = "archetype:australian_grocery"

#: The entity kinds that are a reporting spine — what a company cuts its own
#: performance by, as opposed to what supplies or staffs it.
#:
#: A named tuple and not a derivation, unlike everything else in this file, and
#: the reason is worth stating because the instinct here is to derive it too.
#: The derived half — "does this refusal quote a declared axis" — is applied
#: *alongside* this in `_floor`, and it cannot reach `cost centre`: no
#: registered `axes.Shape` declares one, because a cost centre is not a cut of
#: performance, it is where a charge lands. It is a spine entity all the same —
#: a cost centre nothing charges against is an organisation nothing uses — so it
#: is named here, and the derivation covers the kinds a company can and does
#: declare, including ones no shipped vertical declares yet.
SPINE: tuple[str, ...] = ("business unit", "category", "cost centre", "site")

#: What each build path refuses today, as ``{kind: (unreached, declared)}``.
#:
#: Measured, not chosen — one period, seed 8128, no optional flags, through the
#: same registries `_build_paths` enumerates. A kind absent from a row reaches
#: everything it declares, which is now true of the whole spine on six of the
#: ten paths.
#:
#: Tightened as each engine lands, and tightening it is the deliverable: these
#: numbers only ever come down. The module docstring keeps what they were, so
#: the diff between the two tables is the wave.
#:
#: **Every remaining spine entry belongs to one engine.** `omnichannel_retailer`
#: and `australian_grocery` are retail's two archetypes; `trading-retailer.json`
#: is a retail pack; and `regional-insurer.json` is an insurer *built on the
#: retail engine* — its `base` is `retail`, which is why an insurance row
#: appears under a defect the insurance engine does not have. Four rows, one
#: cause, and it belongs to whoever owns `retail.py` and `generators/finance.py`
#: rather than to a widened constant here.
REFUSED: dict[str, dict[str, tuple[int, int]]] = {
    "archetype:australian_grocery": {
        # site quotes the grocer's own declared `store` axis — see
        # `test_a_grocer_declares_a_store_axis_and_says_nothing_about_44_of_them`.
        # It closes either by the retail engine registering the structural
        # exemption these 44 distribution centres have earned, or by minting a
        # measure the estate owns; both are that engine's call to make.
        "cost centre": (2, 2),
        "person": (15, 26),
        "service": (4, 4),
        "site": (44, 1607),
        "system": (5, 5),
    },
    "archetype:customer_owned_bank": {
        "person": (10, 21),
        "service": (1, 4),
        "system": (4, 5),
    },
    "archetype:midsize_adi": {
        "person": (10, 21),
        "service": (1, 4),
        "system": (4, 5),
    },
    "archetype:midsize_general_insurer": {
        "person": (2, 10),
    },
    "archetype:midsize_infrastructure_services": {
        "person": (6, 12),
        "system": (5, 5),
    },
    "archetype:omnichannel_retailer": {
        "cost centre": (2, 2),
        "person": (14, 23),
        "service": (4, 4),
        "system": (5, 5),
    },
    "pack:longtail-insurer.json": {
        "person": (2, 10),
    },
    "pack:mutual-bank.json": {
        "person": (9, 20),
        "service": (1, 4),
        "system": (4, 5),
    },
    "pack:regional-insurer.json": {
        "cost centre": (2, 2),
        "person": (13, 20),
        "service": (4, 4),
        "system": (5, 5),
    },
    "pack:trading-retailer.json": {
        # The other declaration-contradicting row: 5 of 173 sites, the pack's
        # own zero-weight estate, on a company that declares a `store` axis.
        "cost centre": (2, 2),
        "person": (14, 23),
        "service": (4, 4),
        "site": (5, 173),
        "system": (5, 5),
    },
}


def _build(path: str):  # type: ignore[no-untyped-def]
    """One period of *path*'s company, compiled.

    Through `domains.for_archetype` and `Pack.base` rather than by naming world
    classes, because those registries are what the CLI's own build dispatch
    resolves through — so a fifth vertical is measured here by registering
    itself. Retail is the one exception and the registry says so: it registers
    `single_episode=None` because its build loops closes and threads incident
    flags through them, so its scenario is named here explicitly.
    """
    family, _, name = path.partition(":")
    if family == "archetype":
        domain = domains.for_archetype(name)
        assert domain is not None, f"{path} is an archetype no domain claims"
        world = domain.world(seed=SEED, archetype=archetypes.get(name)).build()
    else:
        pack = packs.load(PACK_DIR / name)
        domain = domains.by_name(pack.base)
        assert domain is not None, f"{path} names base {pack.base!r}, no such engine"
        world = domain.world.from_pack(pack, seed=SEED).build()
    scenario = (
        domain.single_episode(PERIOD)
        if domain.single_episode is not None
        else MonthEndClose(period=PERIOD)
    )
    return world.run(scenario).compile()


@pytest.fixture(scope="module")
def built():  # type: ignore[no-untyped-def]
    """One compiled world per build path, built on first use and cached.

    Lazy rather than a dict comprehension over all ten, which is not a
    performance choice — the whole set is about 1.2 seconds — but a reporting
    one: a module-scoped fixture that builds every path up front turns one
    broken engine into an error on every test in this file, including the ones
    that never touch it. Ten build paths are ten independent subjects and a
    report that says which of them broke is worth the eight lines.

    Building a pack installs into process-global registries — document types,
    episode grammar, sheets, LOBs — and this deliberately does **not** snapshot
    and restore them. Restoring `doctypes._INSTALLED` without also restoring the
    five tables `doctypes.install` writes and does not own puts the record and
    its effect out of step, and the next install of the same pack then fails
    naming a cause that does not exist; a partial undo here would be worse than
    none. Worth knowing while reading this: `trading-retailer.json` had no test
    in this repository building it at all before this file did, so its five
    authored types, two episodes and two LOBs reach a process here for the first
    time.
    """
    cache: dict[str, object] = {}

    def get(path: str):  # type: ignore[no-untyped-def]
        if path not in cache:
            cache[path] = _build(path)
        return cache[path]

    return get


def _findings(world) -> dict[str, tuple[int, int, bool]]:  # type: ignore[no-untyped-def]
    """``{kind: (unreached, declared, quotes_a_declaration)}``, off the report.

    Read off the violation rather than recomputed: a test that re-derived the
    counts would pass while the reported message said something else, and the
    message is what a person acts on. The third element is read the same way —
    whether the finding cites `axes.shape_of(...)` — for the same reason. That
    citation is not decoration, it is the difference between "this corpus is
    thin" and "this corpus contradicts its own declared shape", and a test that
    decided which by consulting `axes` itself could pass while the sentence a
    reader sees made neither claim.
    """
    out: dict[str, tuple[int, int, bool]] = {}
    for violation in validate.reachability(world).violations:
        assert violation.group == "organisation", violation
        kind = violation.code.removesuffix("_reaches_nothing").replace("_", " ")
        head = violation.detail.split(" ")
        out[kind] = (int(head[0]), int(head[2]), "axes.shape_of(" in violation.detail)
    return out


def _refusals(world) -> dict[str, tuple[int, int]]:  # type: ignore[no-untyped-def]
    """`_findings` without the citation — ``{kind: (unreached, declared)}``."""
    return {kind: (u, d) for kind, (u, d, _) in _findings(world).items()}


def _floor(findings: dict[str, tuple[int, int, bool]]) -> set[str]:
    """The kinds in *findings* a company may never leave decorative.

    Two clauses, and neither subsumes the other. A kind whose refusal **quotes
    the company's own declared shape** is a contradiction rather than a thin
    patch, whichever kind it happens to be — so a vertical that declares a
    `ward` axis over its roster puts `person` in its own floor without anybody
    editing this file, which a tuple of kind names could never do. And a kind in
    `SPINE` is in the floor whether or not an axis names it, because `cost
    centre` is a reporting entity that no `axes.Shape` declares and the
    derivation alone would silently drop it.
    """
    return {kind for kind, (_, _, quoted) in findings.items() if quoted} | (
        set(findings) & set(SPINE)
    )


@contextmanager
def _without_structural_exemptions() -> Iterator[None]:
    """Measure as if no exemption had been declared, then put them back.

    Needed because an exemption is *supposed* to move to the engine that owns
    the estate it describes — see `GROCERY_DISTRIBUTION_CENTRES` — and on the
    day it does, every test here that measures the unexempted estate would start
    measuring the exempted one and quietly stop testing what it says it tests.
    Two of them assert an estate is refused; those assertions must mean the same
    thing before and after that move.
    """
    saved = dict(validate._STRUCTURAL)
    validate._STRUCTURAL.clear()
    try:
        yield
    finally:
        validate._STRUCTURAL.clear()
        validate._STRUCTURAL.update(saved)


# ---------------------------------------------------------------------------
# What is measured, and that it is everything
# ---------------------------------------------------------------------------


def test_every_company_this_repository_can_build_is_measured_here() -> None:
    """The claim `BUILD_PATHS` makes, asserted rather than assumed.

    "The union of what I enumerated" is trivially satisfied by enumerating less,
    which is exactly how the four hand-written keys this replaced stayed green
    while missing six build paths — so the assertions that matter are the ones a
    shrunken enumeration would fail. Every registered archetype is covered, and
    every registered *domain* is reached by at least one of them, so a vertical
    cannot register an engine and stay unmeasured by owning no archetype anybody
    enumerates. Packs are covered as a directory, and asserted non-empty:
    globbing a directory that has been emptied or moved is the failure mode a
    glob has and a list does not.
    """
    covered = {path.partition(":")[2] for path in BUILD_PATHS if path.startswith("archetype:")}
    assert covered == set(archetypes.available())

    engines = {domains.for_archetype(key).name for key in covered}  # type: ignore[union-attr]
    assert engines == set(domains.names()), (
        f"{sorted(set(domains.names()) - engines)} registered an engine that no"
        " measured archetype builds, so nothing here checks the companies it makes"
    )

    files = {path.partition(":")[2] for path in BUILD_PATHS if path.startswith("pack:")}
    assert files == {path.name for path in PACK_DIR.glob("*.json")}
    assert files, f"no packs found under {PACK_DIR} — the glob is measuring nothing"


@pytest.mark.parametrize("path", BUILD_PATHS)
def test_the_measured_refusals_are_a_ceiling(built, path: str) -> None:  # type: ignore[no-untyped-def]
    """The gate, ratcheted.

    Deliberately asymmetric, and the asymmetry is the whole design. A kind that
    starts refusing when it did not is a straight failure — an entity kind that
    was load-bearing and stopped is a document that stopped reporting on it. A
    kind that refuses *more* than recorded is a regression. A kind that refuses
    *fewer* passes, because that is the work landing.

    Equality was the first rule here and it is wrong in a repository where
    engines are made load-bearing in parallel: the first lane to land would turn
    this file red for the others, and a red suite is a suite people stop
    reading. The cost is that `REFUSED` can drift downward without the file
    saying so, which the module docstring's two historical tables bound: they
    record where these numbers came from, so a reader can tell a stale ceiling
    from an honest one. A stale ceiling still catches every regression, and a
    ceiling nobody can land work against catches nothing at all.

    A build path with no row is passed over here rather than pinned to whatever
    it happens to measure on the day it appears, because a ceiling nobody argued
    for is a number, not a claim. It is not thereby unchecked: the floor below
    runs on every path in `BUILD_PATHS`, and that is what a new archetype or a
    new pack is actually covered by.
    """
    recorded = REFUSED.get(path)
    if recorded is None:
        pytest.skip(f"{path} has no recorded ceiling; the floor covers it")

    measured = _refusals(built(path))
    appeared = sorted(set(measured) - set(recorded))
    assert not appeared, (
        f"{path} now declares {appeared} that nothing reaches. An entity kind"
        " that was load-bearing and stopped is a document that stopped reporting"
        " on it."
    )
    for kind, (unreached, declared) in sorted(recorded.items()):
        got = measured.get(kind, (0, declared))
        assert got[0] <= unreached, (
            f"{path}/{kind}: {got[0]} of {got[1]} reach nothing, worse than the"
            f" recorded {unreached} of {declared}. Nobody raises these."
        )


@pytest.mark.parametrize("path", BUILD_PATHS)
def test_the_reporting_spine_is_load_bearing_everywhere(built, path: str) -> None:  # type: ignore[no-untyped-def]
    """The floor, and the only assertion here that can fail upward.

    Every ceiling looks at what is already broken, so none of them can see a
    kind that is currently perfect going bad. This one can. Deleting the
    workbook that reports on branches would leave the banking ceiling perfectly
    satisfied — 133 branches reaching nothing is not "worse than" a row that no
    longer exists — and would fail here on the first run.

    **And it is what covers a company nobody has measured yet.** A path with no
    `REFUSED` row gets an empty one here, so a newly registered archetype or a
    pack dropped into `examples/packs` fails this the moment its estate is
    decorative, with no edit to this file. That is the difference between this
    shape and the four hand-written keys it replaced, under which a fifth
    vertical was checked by nothing at all.

    The four rows that do carry spine debt are all one engine's, and the message
    says so rather than making the next reader diff two tables to find out.
    """
    findings = _findings(built(path))
    recorded = REFUSED.get(path, {})
    for kind in sorted(_floor(findings)):
        unreached, declared, quoted = findings[kind]
        debt = recorded.get(kind)
        assert debt is not None, (
            f"{path} declares {unreached} of {declared} {kind}(s) that nothing"
            " reports on. Units, sites, categories and cost centres are the"
            " dimensions a company says it is cut by; a corpus that leaves one"
            " decorative is the defect this module's docstring records three"
            " engines being rebuilt to close."
            + (
                " This one contradicts the company's own declared shape — the"
                " finding quotes the axis back."
                if quoted
                else ""
            )
        )
        assert unreached <= debt[0], (
            f"{path}/{kind}: {unreached} of {declared} reach nothing, worse than"
            f" the recorded {debt[0]} of {debt[1]}."
        )


def test_the_floor_is_what_the_company_itself_declares(built) -> None:  # type: ignore[no-untyped-def]
    """Both halves of `_floor` fire on real corpora, and they are not the same.

    Two clauses that always agreed would mean one of them should go, so each is
    asserted to reach something the other does not on some build path measured
    here. The derived clause fires on a company that contradicts its own
    declared shape; the named clause fires on `cost centre`, which no
    `axes.Shape` declares and which the derivation therefore cannot see — that
    asymmetry is the entire argument for `SPINE` existing beside the derivation
    rather than being replaced by it.

    The derived clause's *other* value cannot be asserted today because nothing
    exercises it yet, and it is stated rather than smuggled in: a vertical that
    declares a populated axis sourced from `roster` or `estate` would put
    `person`, `service` or `system` into its own floor, which the named tuple
    could never do without making those kinds a defect on the four verticals
    where they are not one.

    Measured with no exemption registered, so that the day the grocer's
    distribution centres are properly exempted this still demonstrates the
    mechanism rather than silently testing an empty set.
    """
    with _without_structural_exemptions():
        measured = {path: _findings(built(path)) for path in BUILD_PATHS}

    quoting = {
        path: {k for k, (_, _, q) in findings.items() if q}
        for path, findings in measured.items()
    }
    assert any(quoting.values()), (
        "no build path produces a refusal that quotes a declared axis, so the"
        " derived half of the floor is checking nothing. This is a deliberate"
        " tripwire rather than a nuisance: if every company this repository"
        " builds now agrees with its own declared shape, the axis-contradicting"
        " subset has reached its floor and belongs in `validate.run` as a"
        " *violation* — see `validate.reachability`'s last paragraph, which"
        " states the argument and names this as the condition. Promote it, then"
        " rewrite this test to assert the promotion instead of the gap."
    )

    named_only = {
        path: _floor(findings) - quoting[path] for path, findings in measured.items()
    }
    assert any(named_only.values()), (
        "every floor kind now quotes a declaration, so `SPINE` adds nothing the"
        " derivation does not already reach and should be deleted rather than"
        " maintained"
    )

    # And the structural reason it adds something, rather than the observation
    # that it happens to today. `_KIND_LABELS` maps each checked collection to
    # the `axes.Source` that supplies it, and gives `cost_centres` none at all —
    # so no shape any industry could register would ever make a cost centre
    # quote a declaration, and the derived clause is not merely behind on it, it
    # is structurally blind to it. That is the whole justification for a named
    # tuple sitting beside a derivation in a file whose argument is that
    # derivations beat lists.
    sourceless = {
        label for label, source in validate._KIND_LABELS.values() if source is None
    }
    assert sourceless & set(SPINE), (
        "every spine kind now has an `axes.Source`, so the derivation can reach"
        " all of them and `SPINE` is redundant"
    )
    assert any(kinds & sourceless for kinds in named_only.values())


# ---------------------------------------------------------------------------
# What `validate` does with it
# ---------------------------------------------------------------------------


def test_validate_reports_the_organisation_without_ruling_on_it(built) -> None:  # type: ignore[no-untyped-def]
    """The promotion this lane actually made, and its exact boundary.

    Before it, `reachability` ran nowhere except this file, so the only person
    who could learn that a company's estate was decorative was somebody who
    already knew the check existed — which is not the person asking. It now runs
    inside `validate.run`, on every corpus, and files into `advisories`: the
    findings are reported, `ok` is untouched, and `checks_run` counts them
    because they ran.

    The asymmetry between the two lists is the assertion. Every organisation
    finding is an advisory and none is a violation, so no corpus can be failed
    by this group; and the advisories are exactly what the standalone verdict
    reports, so the two callers cannot drift into disagreeing about what the
    corpus contains.
    """
    world = built(RETAIL)
    report = world.validate()

    assert report.ok, report.violations
    assert not [v for v in report.violations if v.group == "organisation"]
    assert report.advisories
    assert {v.group for v in report.advisories} == {"organisation"}
    assert {v.code for v in report.advisories} == {
        f"{kind.replace(' ', '_')}_reaches_nothing" for kind in _refusals(world)
    }
    # `by_group` is the failure report; an advisory must never appear in it.
    assert "organisation" not in report.by_group()


def test_the_advisory_channel_cannot_fail_a_corpus(built) -> None:  # type: ignore[no-untyped-def]
    """The property that makes the previous test a design rather than a default.

    A severity that could change a verdict is not a second severity, it is a
    violation with a softer name — and the first thing anyone would reach for
    when this group starts refusing something inconvenient is to widen whatever
    made it advisory. So the invariant is asserted directly, on the corpus with
    the most advisories in the repository: a report is `ok` exactly when it has
    no violations, whatever else it carries.
    """
    with _without_structural_exemptions():
        report = built(GROCER).validate()
    assert report.advisories, "the grocer is the densest advisory case here"
    assert report.ok is (not report.violations)
    assert bool(report) is report.ok
    report.raise_if_failed()  # advisories alone must not raise


def test_a_plan_only_corpus_is_checked_zero_times() -> None:  # type: ignore[no-untyped-def]
    """`compiled_evidence`'s early return, and for its reason.

    Nothing is compiled, so there is no readable surface for an entity to be
    missing from, and reporting an estate as unreachable there would be reading
    the absence of documents as a defect in the organisation. `examples/retail-
    close` is exactly this corpus — which is also why running this group inside
    `validate` left that corpus's check count untouched at 1,283, the number
    `tests/test_validate_packs.py` pins as `PACKLESS_CHECKS`.
    """
    world = RetailWorld(seed=SEED).build()
    report = validate.reachability(world)
    assert report.checks_run == 0
    assert report.ok

    full = world.validate()
    assert not full.advisories, "a plan-only corpus has nothing to advise about"


# ---------------------------------------------------------------------------
# The particular corpora that keep the mechanism honest
# ---------------------------------------------------------------------------


def test_a_grocer_declares_a_store_axis_and_says_nothing_about_44_of_them(built) -> None:  # type: ignore[no-untyped-def]
    """The violation quotes the declaration it contradicts.

    A site reaching nothing is only a defect because the company said it was cut
    that way. Without that quotation the finding reads as this module's opinion
    about how much a corpus ought to contain, which is an argument nobody can
    settle. With it, it is the corpus disagreeing with itself — and it is what
    `_floor` reads to decide which findings are a contradiction rather than a
    thin patch, so this is the test under that whole mechanism.

    This asked the *bank* the same question until three engines closed their
    estates, and where it moved to is worth recording rather than quietly
    editing. `axes.shape_of('Banking')` still declares its populated `branch`
    axis; all 133 branches now reach, so banking no longer contradicts itself
    and there is no violation left to quote anything. The same is true of every
    other axis-backed kind on all four shipped verticals — which is precisely
    why this had to move to keep testing the mechanism at all, and why the kinds
    still refused there (`system`, `service`, `person`) cannot host it: no
    populated axis on any of those industries is sourced from `estate` or
    `roster`, so their violations correctly quote nothing.

    Measured with exemptions cleared, because the 44 sites this quotes are the
    same 44 the exemption below covers, and the day that exemption moves into
    the retail engine and is registered at import this would otherwise measure
    an empty list and pass without testing anything.
    """
    grocer = built(GROCER)
    with _without_structural_exemptions():
        sites = [
            v for v in validate.reachability(grocer).violations
            if v.code == "site_reaches_nothing"
        ]
    assert len(sites) == 1, sites
    assert "'store'" in sites[0].detail
    assert f"axes.shape_of({grocer.company.industry!r})" in sites[0].detail

    # And the half that moving this test could have silently dropped: banking
    # declares the axis it used to contradict, and now agrees with it.
    assert "site" not in _refusals(built(BANKING))


def test_the_appendix_does_not_count_as_reaching(built) -> None:  # type: ignore[no-untyped-def]
    """The trap `carried_evidence`'s docstring records, in this direction.

    The supporting-fact appendix is one row per `intent.required_fact_ids`, so a
    check that counted it would be measuring the plan and reporting on the
    corpus. Asserted against the mechanism rather than against an outcome,
    because today the two agree: the appendix carries a handful of facts across
    the shipped verticals that no visible section does, and every one of their
    subjects is reached by some other fact anyway. So this pins the *rule* —
    hidden sections are not the readable surface — which is what stops the next
    generator from satisfying the gate with an appendix and an empty page.
    """
    world = built(BANKING)
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
#:
#: `grocery_exemption` below already prefers a registered one over this, so the
#: day the retail engine declares it, these tests exercise *that* declaration
#: and this constant becomes dead weight to delete rather than a second copy
#: quietly disagreeing with the first.
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


def _key(exemption: validate.Structural) -> tuple[str, str, str]:
    return (exemption.kind, exemption.industry, exemption.reason)


@pytest.fixture
def grocery_exemption(built):  # type: ignore[no-untyped-def]
    """The grocer's distribution-centre exemption, wherever it is declared.

    Prefers one the retail engine has already registered at import over the copy
    in this file, which is what lets the constant above move without these tests
    moving with it. The tests that matter here are the ones proving the
    exemption is *narrow* — that it does not reach insurance's claims centres or
    procurement's materials yards — and those are worth keeping whichever module
    ends up owning the declaration; written against `structural_exemptions()`
    rather than against a constant, they survive the move unedited.
    """
    industry = built(GROCER).company.industry
    already = [
        x for x in validate.structural_exemptions()
        if x.kind == "sites" and x.industry == industry
    ]
    if already:
        yield already[0]
        return
    validate.register_structural(GROCERY_DISTRIBUTION_CENTRES)
    try:
        yield GROCERY_DISTRIBUTION_CENTRES
    finally:
        validate._STRUCTURAL.pop(_key(GROCERY_DISTRIBUTION_CENTRES), None)


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

    Asserted as "exactly the zero-weight sites, some but not all of the estate"
    rather than as the literal 44 of 1,607: the retail engine is under active
    work on this very estate, and a count pinned here would make somebody
    growing the grocer's warehousing think they had broken the exemption.
    """
    dc = grocery_exemption
    grocer = built(GROCER)
    exempt = [s for s in grocer.sites if dc.covers("sites", grocer.company.industry, s)]
    zero = [s for s in grocer.sites if s.revenue_weight == 0.0]
    assert exempt == zero, "the exemption is exactly the estate's zero-weight sites"
    assert 0 < len(exempt) < len(grocer.sites)
    assert "site" not in _refusals(grocer)

    for path in (INSURANCE, PROCUREMENT):
        world = built(path)
        others = [s for s in world.sites if s.revenue_weight == 0.0]
        assert others, path
        assert not [
            s for s in others if dc.covers("sites", world.company.industry, s)
        ], f"the grocer's exemption reached {path}"


def test_without_the_exemption_the_estate_is_refused(built) -> None:  # type: ignore[no-untyped-def]
    """The control, and the reason the exemption is not decoration.

    Undeclared, those same sites are a refusal on a corpus whose estate is
    otherwise the one working example in this repository. A mechanism that
    changed nothing when removed would not be a mechanism.

    Tied to the exemption's own coverage rather than to the number 44, so that
    it keeps saying the same thing after the retail engine has been through this
    estate: what is refused with no exemption declared is precisely what the
    exemption declares.
    """
    grocer = built(GROCER)
    zero = [s for s in grocer.sites if s.revenue_weight == 0.0]
    with _without_structural_exemptions():
        refused = _refusals(grocer)
    assert refused["site"] == (len(zero), len(grocer.sites))


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
    world = built(RETAIL)
    for exemption in validate.structural_exemptions():
        for centre in world.cost_centres:
            assert exemption.covers(
                "cost_centres", world.company.industry, centre) is False
