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
company says it cuts its own performance by, and **all ten build paths now reach
every part of it.** Four did not when the enumeration first ran, and all four
were the retail engine: its two archetypes, its pack, and
`regional-insurer.json`, which is an insurer whose `base` is `retail`. The
reference implementation had become the laggard on the dimension it was the
reference for. Two of them went further and left sites unreached on companies
declaring a `store` axis — not thinness but a corpus contradicting itself.

The retail engine then closed all four, and it closed the sites by minting the
measure rather than by exempting them: a distribution centre has a throughput
and a cost to serve, and the claim that a zero-weight site has nothing to say
was only ever true because the engine cut one measure by site. That is the third
time this repository has faced that choice — insurance's claims centres and
procurement's materials yards were the first two — and the third time minting
won. **This repository now ships no `Structural` exemptions at all.**

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

`validate.reachability`'s own docstring carries the argument for the split that
sits under all of this. Filed wholesale as violations, this group fails 67 tests
and reports every corpus the engine can build as incoherent, mostly on the three
kinds above that are not defects — so `run` reports it as an advisory.

The contradicting subset was then promoted to a violation and **reverted**, and
the revert is the more useful record. Every shipped build path had stopped
contradicting itself, which was the condition named for promoting it; filing it
as a violation still cost nine tests across four files, every one an authored
pack that declares the General insurance shape and models only reserving. Those
corpora do contradict themselves and the findings were right — but the rule that
catches them, *a pack that names a shape must populate every axis of it*, is a
claim about an authored pack and belongs to `packs.lint` when the pack is
written, not to `validate` after a corpus is built. The condition was necessary
and not sufficient, because it was measured over shipped build paths and the
authored fixtures were never in that enumeration.

`test_a_declaration_is_what_turns_a_reading_into_a_contradiction` keeps the
mechanism exercised on a declaration this file makes, so whichever layer the
rule eventually lands in, the part that classifies is already true and tested.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from worldloom import archetypes, axes, domains, packs, registries, validate
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
        "person": (15, 26),
        "service": (4, 4),
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
        "person": (13, 20),
        "service": (4, 4),
        "system": (5, 5),
    },
    "pack:trading-retailer.json": {
        "person": (14, 23),
        "service": (4, 4),
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
    episode grammar, sheets, LOBs — and the whole module runs inside
    `registries.scoped()` so none of it outlives the file.

    That wrapper is new and the reason it is safe now is worth keeping. This
    fixture deliberately restored *nothing* when it was written, on the grounds
    that a partial undo is worse than none: restoring `doctypes._INSTALLED`
    without the five tables `doctypes.install` writes and does not own puts the
    record and its effect out of step, and the next install of the same pack
    then fails naming a cause that does not exist. That argument was correct and
    is now obsolete — `registries` has every one of those tables declared beside
    the code that writes it, so the undo is complete rather than partial. The
    objection was to partiality, not to restoring.

    It mattered: this file was measured leaving five document types, three LOBs
    and three episodes behind for every test that ran after it. Worth knowing
    while reading this — `trading-retailer.json` had no test in this repository
    building it at all before this file did, so its five authored types, two
    episodes and two LOBs reach a process here for the first time.
    """
    cache: dict[str, object] = {}

    def get(path: str):  # type: ignore[no-untyped-def]
        if path not in cache:
            cache[path] = _build(path)
        return cache[path]

    with registries.scoped():
        yield get


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

    **The tripwire this test used to carry has fired, and this is the rewrite it
    asked for — though not the one it predicted.** It asserted that some build
    path still quoted a declared axis, with a message saying that if none did,
    the subset had reached its floor and belonged in `validate.run` as a
    violation. The retail engine closed its two — `australian_grocery`'s 44
    distribution centres and `trading-retailer.json`'s 5 — and the assertion
    went red on exactly the condition it named.

    The promotion was then tried and reverted, and the reason is recorded at the
    `as_advisory` call in `validate.run`: it cost nine tests across four files,
    all authored packs that declare a shape and populate none of it, which is a
    claim about a *pack* rather than about a corpus. So the tripwire's condition
    turned out to be necessary and not sufficient — it was measured over shipped
    build paths, and authored fixtures were never in that enumeration.

    What survives is the stronger half: no company this repository *builds*
    contradicts its own declared shape, and that is worth asserting on its own
    account whether or not a gate ever rests on it.

    Measured with no exemption registered, so that a later exemption cannot
    quietly satisfy this by hiding a contradiction rather than closing one.
    """
    with _without_structural_exemptions():
        measured = {path: _findings(built(path)) for path in BUILD_PATHS}

    quoting = {
        path: {k for k, (_, _, q) in findings.items() if q}
        for path, findings in measured.items()
    }
    contradicting = {path: kinds for path, kinds in quoting.items() if kinds}
    assert not contradicting, (
        f"{sorted(contradicting)} declare a dimension and report on none of it."
        " Either an engine stopped reporting on an estate, or a new company"
        " declares an axis nothing populates. This is the sharpest finding this"
        " module produces — not thinness but a corpus disagreeing with itself —"
        " and every shipped build path was clear of it when this was written."
    )

    # No floor kind refuses anywhere now, so the two clauses cannot be told
    # apart by what they catch on a shipped corpus — they both catch nothing,
    # which is the wave landing rather than either of them being wrong. What
    # separates them is therefore asserted structurally, and that was always the
    # stronger form of the argument.
    #
    # `_KIND_LABELS` maps each checked collection to the `axes.Source` that
    # supplies it and gives `cost_centres` none at all, so no shape any industry
    # could ever register would make a cost centre quote a declaration. The
    # derived clause is not behind on cost centres, it is *blind* to them — and
    # that is the whole justification for a named tuple sitting beside a
    # derivation in a file whose standing argument is that derivations beat
    # lists. `SPINE` is the exception that earns itself.
    assert not any(_floor(f) for f in measured.values()), (
        "a floor kind refuses on some build path, which the ceiling above should"
        " have caught first — if this fires alone, `_floor` and `REFUSED`"
        " disagree about what a floor kind is"
    )
    sourceless = {
        label for label, source in validate._KIND_LABELS.values() if source is None
    }
    assert sourceless & set(SPINE), (
        "every spine kind now has an `axes.Source`, so the derivation can reach"
        " all of them and `SPINE` is redundant"
    )
    assert "cost centre" in sourceless


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


@contextmanager
def _declaring(industry: str, axis: axes.Axis) -> Iterator[None]:
    """Give *industry* one more populated axis, then put its shape back.

    The mechanism below needs a company that declares a dimension and reports on
    none of it, and **no corpus this repository builds is one any more** — which
    is the wave landing, not a gap. Rather than starve a real corpus of facts to
    manufacture one, this adds the missing half from the other side: a real
    refusal that quotes nothing today is made to quote something by declaring
    the axis it would contradict.

    That is the truer construction. Stripping facts would test that the check
    notices an absence, which is not in doubt; this tests the thing the
    promotion actually turns on — that *the company's own declaration* is what
    converts a reading into a verdict.
    """
    shape = axes.shape_of(industry)
    assert shape is not None, industry
    saved = dict(axes._REGISTRY)
    axes._REGISTRY[industry] = replace(shape, axes=(*shape.axes, axis))
    try:
        yield
    finally:
        axes._REGISTRY.clear()
        axes._REGISTRY.update(saved)


def test_a_declaration_is_what_turns_a_reading_into_a_contradiction(built) -> None:  # type: ignore[no-untyped-def]
    """One corpus, one finding, two classifications, and the declaration is the
    whole of the difference.

    Retail leaves 14 of 23 people unreached and that is **not** a defect: a
    person is a roster entry, not a reporting dimension, and no shipped industry
    declares an axis sourced from `roster`. Declare that same company to be cut
    by its people, change nothing else, and the identical finding starts quoting
    the declaration back — because the company has now said two incompatible
    things about itself, which is the only thing this module means by
    incoherent.

    **This is the mechanism a promotion would rest on, and the promotion was
    tried and reverted.** With every shipped build path agreeing with its own
    declared shape, filing the contradicting subset as violations cost nine
    tests across four files — every one an authored pack that declares the
    General insurance shape and models only reserving. Those corpora really do
    contradict themselves, so the findings were right; the *rule* was aimed
    wrong. "A pack that names a shape must populate every axis of it" is a claim
    about an authored pack, which `packs.lint` can make when the pack is
    written, and not one `validate` should make after a corpus is built.

    So the classification stays available and unused by `run`, and this asserts
    it rather than the exit code — the part that is true regardless of where the
    rule eventually lands.
    """
    world = built(RETAIL)
    by_roster = axes.Axis(
        name="crew", label="Crew", source="roster",
        populated_by="tests/test_reachability.py",
    )

    plain = [
        v for v in validate.reachability(world).violations
        if v.code == "person_reaches_nothing"
    ]
    assert len(plain) == 1, plain
    assert not validate.contradicts_declared_shape(plain[0])

    with _declaring(world.company.industry, by_roster):
        declared = [
            v for v in validate.reachability(world).violations
            if v.code == "person_reaches_nothing"
        ]
    assert len(declared) == 1, declared
    assert "'crew'" in declared[0].detail
    assert f"axes.shape_of({world.company.industry!r})" in declared[0].detail
    assert validate.contradicts_declared_shape(declared[0])

    # And `run` files both as readings today, which is the reverted decision
    # stated as behaviour rather than left in a comment.
    report = world.validate()
    assert report.ok
    assert any(v.code == "person_reaches_nothing" for v in report.advisories)
    assert not [v for v in report.violations if v.group == "organisation"]


def test_the_marker_is_what_run_classifies_on() -> None:
    """The round trip, so the writer and the reader cannot drift apart.

    `reachability` writes `DECLARATION_QUOTED` into a finding and
    `contradicts_declared_shape` reads it back to decide violation or advisory.
    Written as a literal in both places, a reworded message would demote every
    contradiction to an advisory and **nothing would fail** — the findings would
    still be reported, the counts would still be right, and only the exit code
    would quietly stop meaning what it says.

    So this asserts the constant is what the message actually contains, rather
    than asserting the string equals itself.
    """
    quoting = validate.Violation(
        group="organisation", code="site_reaches_nothing", subject="CO-0001",
        detail=(
            "3 of 9 site(s) are named as the subject of no fact… This company's"
            " declared shape is cut by 'store' — see"
            " `axes.shape_of('Retail')` — so the declaration and the corpus"
            " disagree about whether that dimension exists."
        ),
    )
    thin = validate.Violation(
        group="organisation", code="cost_centre_reaches_nothing", subject="CO-0001",
        detail="2 of 2 cost centre(s) are named as the subject of no fact…",
    )
    assert validate.contradicts_declared_shape(quoting)
    assert not validate.contradicts_declared_shape(thin)
    assert validate.DECLARATION_QUOTED in quoting.detail


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


#: A synthetic exemption, and the reason this file no longer carries a real one.
#:
#: It used to hold `GROCERY_DISTRIBUTION_CENTRES`: an argued `Structural` for the
#: grocer's 44 zero-weight distribution centres, written here because the lane
#: that needed it could not edit the retail module, and marked for the retail
#: owner to move. **The retail owner deleted it instead**, and the reason is the
#: better half of this mechanism's story.
#:
#: That exemption's own reason text named the condition for its own removal —
#: "disagree with this by minting a throughput or a cost-to-serve measure the
#: estate owns, at which point the exemption should go rather than be widened" —
#: and the retail engine did exactly that. A warehouse has a throughput and a
#: cost to serve; the claim that "there is nothing about a zero-weight site for a
#: fact to say" was only ever true because the engine cut one measure by site.
#: Two other engines had already reached the same conclusion about claims centres
#: and materials yards.
#:
#: So **this repository ships no `Structural` exemptions at all**, and every
#: candidate for one has been closed by minting the measure. That is the strongest
#: available statement about the mechanism, and it leaves these tests with no real
#: subject — hence a synthetic one. It is scoped to an industry nothing builds, so
#: it cannot silence a finding on a shipped corpus while claiming to test the
#: machinery that would.
NOWHERE = "Test fixtures, incorporated"

SYNTHETIC = validate.Structural(
    kind="services",
    industry=NOWHERE,
    holds=lambda service: service.criticality_tier > 1,
    reason=(
        "A service below the top criticality tier is not one this company holds"
        " anybody to account for, so no accountability fact names it. Stated"
        " over the entity's own declared field rather than over its id, which is"
        " the difference between a declaration and an allowlist — and the field"
        " is one the estate sets deliberately, so the claim is checkable."
    ),
    declared_by="tests/test_reachability.py",
)


def _key(exemption: validate.Structural) -> tuple[str, str, str]:
    return (exemption.kind, exemption.industry, exemption.reason)


@pytest.fixture
def synthetic_exemption():  # type: ignore[no-untyped-def]
    """`SYNTHETIC`, registered for one test and removed again."""
    validate.register_structural(SYNTHETIC)
    try:
        yield SYNTHETIC
    finally:
        validate._STRUCTURAL.pop(_key(SYNTHETIC), None)


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


def test_an_exemption_is_scoped_to_the_industry_it_argues_about(
    built, synthetic_exemption,
) -> None:  # type: ignore[no-untyped-def]
    """The scoping, and the events that proved it was the right rule.

    `SYNTHETIC` matches a system that is the system of record for nothing, and
    every shipped vertical has some — so an *unscoped* version of it would
    silence a real finding on four engines at once. Scoped to an industry
    nothing builds, it reaches none of them, which is what this asserts.

    That is not a hypothetical. The same predicate written one industry wider is
    the mistake this repository came within one lane of making three times: the
    grocer's distribution centres, insurance's claims centres and procurement's
    materials yards all carry `revenue_weight == 0`, and an exemption broad
    enough to cover the first would have covered all three. Every one of them
    was closed instead by minting the measure the site actually owns. An
    exemption written that wide would have closed the finding **by agreeing with
    it**, and the estates would still be scenery.
    """
    would_match = 0
    for path in BUILD_PATHS:
        world = built(path)
        industry = world.company.industry
        assert industry != NOWHERE
        matched = [
            s for s in world.services
            if synthetic_exemption.covers("services", industry, s)
        ]
        assert not matched, f"a foreign industry's exemption reached {path}"
        would_match += len([s for s in world.services if s.criticality_tier > 1])

    # And the predicate is not vacuous — on some path it *would* have matched
    # had the industry agreed, which is what makes the scoping the active
    # ingredient rather than the exemption being empty everywhere anyway.
    # Counted across paths rather than asserted on each: the grocer's five
    # systems are each the system of record for something, so a per-path
    # assertion would fail on a corpus that is simply well-specified.
    assert would_match > 0, (
        "no shipped company has a service below the top criticality tier, so"
        " this exemption could not have silenced anything and the scoping above"
        " proves nothing"
    )


def test_an_exemption_removes_exactly_what_it_declares(built, synthetic_exemption) -> None:  # type: ignore[no-untyped-def]
    """The control: a mechanism that changed nothing when removed is not one.

    Measured on a corpus relabelled into the exemption's own industry, since no
    shipped company is in it. Services are the right subject and one of the only
    honest ones left — the spine kinds this file was built to chase all reach
    now, so an exemption over one would have nothing to remove.
    """
    world = built(RETAIL)
    relabelled = world.extend(
        company=world.company.model_copy(update={"industry": NOWHERE}),
    )
    covered = [s for s in relabelled.services if s.criticality_tier > 1]
    assert covered, "the fixture needs a service the exemption can cover"

    with _without_structural_exemptions():
        before = _refusals(relabelled)
    after = _refusals(relabelled)

    assert before["service"][0] == len(relabelled.services)
    assert after["service"][0] == len(relabelled.services) - len(covered)


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
