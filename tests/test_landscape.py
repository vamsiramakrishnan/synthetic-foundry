"""The estate's vocabulary: extracted verbatim, authorable, and per engine.

`generators/estate.py` grows the only technology landscape this tool has, and
until now it could only grow a grocer's — `cli.py` refused ``--estate`` for
every other vertical rather than give a bank a ``click-collect-api``. The
construction was never retail; only the words were. `worldloom.landscape` holds
the words.

Three things this file is for, in the order they matter:

* **The retail vocabulary is the literal it replaced.** Held as a golden below,
  because that is the only non-circular way to say it in-tree: asserting the
  pools against themselves proves nothing, and asserting them against what the
  generator mints proves only that the extraction is self-consistent. The
  golden was captured from the generator *before* the pools moved.
* **A vocabulary is validated, and every rule is shown firing.** Same standard
  `tests/test_estate.py` holds the composition grammar to: a check that has
  never rejected anything proves only that it runs.
* **A bank and an insurer can have an estate at all.** That is the deliverable.
  Insurance is the sharp case — `insurance_org.generate` returns
  ``services=()``, so a reserving corpus had no technology graph whatsoever.
"""

from __future__ import annotations

import dataclasses

import pytest

from worldloom import (
    BankingWorld,
    InsuranceWorld,
    RetailWorld,
    World,
    graphs,
    landscape,
)
from worldloom.banking_scenarios import QuarterlyCapitalReturn
from worldloom.generators import estate as estate_module
from worldloom.insurance_scenarios import QuarterlyReserving
from worldloom.landscape import Landscape
from worldloom.recipe import rebuild
from worldloom.scenarios import MonthEndClose

SEED = 8128


# ---------------------------------------------------------------------------
# The default vocabulary is the literal it replaced
# ---------------------------------------------------------------------------

#: Every service the retail estate mints at ``large``, in the order the
#: generator mints them — bottom-up, so ``data``, then ``platform``, then
#: ``domain``, then ``edge``. Captured from the generator as it stood with the
#: pools hardcoded in `generators/estate.py`. At ``large`` every profile count
#: equals its pool's length, so this list is the four pools concatenated: the
#: golden covers the whole vocabulary and its order, not a sample of it.
RETAIL_SERVICES: tuple[str, ...] = (
    # data
    "sales-feed", "stock-movement-feed", "supplier-master-feed", "price-change-feed",
    "customer-consent-feed", "warehouse-stock-extract", "pos-transaction-stream",
    "forecast-publisher", "colleague-roster-extract", "gl-journal-extract",
    "margin-cube-builder", "basket-analytics-pipeline", "waste-reporting-extract",
    "supplier-invoice-feed", "range-change-feed", "loyalty-event-stream",
    "delivery-telemetry-feed", "store-footfall-feed",
    # platform
    "identity-provider", "config-service", "event-bus", "feature-flags",
    "notification-gateway", "audit-log", "secrets-broker", "api-gateway",
    "job-scheduler", "observability-collector",
    # domain
    "pricing-engine", "promotions-engine", "basket-service", "order-orchestrator",
    "fulfilment-router", "stock-availability", "replenishment-planner",
    "range-planning", "supplier-onboarding", "payments-gateway", "refunds-service",
    "loyalty-points", "delivery-slotting", "returns-processing", "invoice-matching",
    "purchase-order-service", "markdown-optimiser", "space-planning",
    "labour-scheduling", "shrinkage-analytics", "customer-profile",
    "recommendation-service", "search-ranking", "tax-calculation",
    "credit-check-service", "fraud-screening", "warranty-registration",
    "subscription-billing", "gift-card-ledger", "carbon-reporting",
    "allergen-lookup", "recipe-service", "store-locator", "wait-time-estimator",
    # edge
    "storefront-web", "store-colleague-app", "self-checkout-client", "kiosk-ui",
    "customer-account-portal", "click-collect-api", "delivery-tracking-web",
    "loyalty-app", "supplier-portal", "returns-desk-ui", "gift-card-web",
    "price-check-terminal", "warehouse-handheld", "driver-app", "call-centre-console",
    "franchise-portal", "b2b-ordering-api", "in-store-signage",
)

#: Retail's *industry* names: the edge, domain and data pools, without the
#: platform one. The platform layer is deliberately excluded from the
#: cross-vertical exclusion tests below, because a bank and a grocer really do
#: both run an ``api-gateway`` and an ``audit-log``, and asserting otherwise
#: would be demanding a synonym rather than a vocabulary. What may never be
#: shared is anything that says what the business *does*.
RETAIL_TRADE: frozenset[str] = frozenset(RETAIL_SERVICES) - frozenset(
    landscape.RETAIL.services["platform"]
)

#: The twelve systems, in mint order. The last two are the chokepoints' private
#: backing stores, which is why the order matters and not just the set.
RETAIL_SYSTEMS: tuple[str, ...] = (
    "Workforce Central", "Vendor Exchange", "Warehouse Control", "Transport Desk",
    "People Hub", "Contact Centre Suite", "Range Studio", "Treasury Desk",
    "Property Register", "Learning Exchange", "Loyalty Core", "Insurance Register",
)


def test_the_retail_vocabulary_is_the_literal_it_replaced() -> None:
    """The contract `parameters.Span` and `profiles.Seasonality` both hold to:
    a named default extracted verbatim, so an un-overridden build is the same
    bytes rather than close to them."""
    retail = landscape.RETAIL
    minted = tuple(
        name
        for layer in ("data", "platform", "domain", "edge")
        for name in retail.services[layer]
    )
    assert minted == RETAIL_SERVICES
    assert tuple(name for name, _, _ in retail.systems) == RETAIL_SYSTEMS
    assert retail.chokepoints == 2
    assert retail.profiles == {
        "small":  {"edge": 3, "domain": 5, "platform": 3, "data": 3, "system": 3},
        "medium": {"edge": 8, "domain": 14, "platform": 6, "data": 8, "system": 6},
        "large":  {"edge": 18, "domain": 34, "platform": 10, "data": 18, "system": 12},
    }


def test_the_default_estate_mints_exactly_the_golden() -> None:
    """The vocabulary reaching the generator, not merely sitting in a table.

    An extraction that reordered a pool, dropped a name, or bound the wrong
    layer to the wrong purpose sentence would leave the table above intact and
    change the corpus, which is the failure worth catching here.
    """
    plain = RetailWorld(seed=SEED).build()
    core_services = {s.id for s in plain.services}
    core_systems = {s.id for s in plain.systems}

    grown = RetailWorld(seed=SEED, estate="large").build()
    assert tuple(
        s.name for s in grown.services if s.id not in core_services
    ) == RETAIL_SERVICES
    assert tuple(
        s.name for s in grown.systems if s.id not in core_systems
    ) == RETAIL_SYSTEMS


def test_the_generator_still_publishes_the_engines_own_sizes() -> None:
    """`estate.PROFILES` is what a caller has always read to list what
    ``--estate`` accepts. It moved; the name did not."""
    assert estate_module.PROFILES == dict(landscape.DEFAULT.profiles)
    assert estate_module.CHOKEPOINTS == landscape.DEFAULT.chokepoints


def test_the_default_landscape_is_retails() -> None:
    assert landscape.DEFAULT is landscape.RETAIL


def test_the_engines_own_vocabularies_claim_no_source() -> None:
    """Honestly labelled, `parameters.Span.source`'s rule: these were chosen to
    make three plausible corpora work, not calibrated against anything."""
    assert all(value.source == "" for value in landscape.LANDSCAPES.values())
    assert all(value.about for value in landscape.LANDSCAPES.values())


# ---------------------------------------------------------------------------
# Refusals — each rule shown firing
# ---------------------------------------------------------------------------


def test_an_unknown_vocabulary_is_refused_rather_than_defaulted() -> None:
    """A pack asking for ``bankng`` that silently got the retailer's would build
    a bank running a ``click-collect-api`` and give the author nothing to notice
    it by — which is precisely what the CLI's blanket refusal existed to
    prevent, so reintroducing it here while lifting it there would be perverse."""
    with pytest.raises(KeyError, match="unknown estate vocabulary"):
        landscape.named("bankng")


def test_the_error_names_what_is_known() -> None:
    with pytest.raises(KeyError, match="banking"):
        landscape.named("nope")


def test_an_unknown_profile_size_is_refused_by_every_vocabulary() -> None:
    for value in landscape.LANDSCAPES.values():
        with pytest.raises(ValueError, match="unknown estate profile"):
            value.profile("enormous")


def _valid() -> dict:
    """A minimal well-formed vocabulary, as keyword arguments to mutate."""
    return {
        "services": {
            "edge": ("a-web",), "domain": ("b-service",),
            "platform": ("c-provider",), "data": ("d-feed",),
        },
        "systems": (
            ("One", "First system", "one"),
            ("Two", "Second system", "two"),
        ),
        "purpose": {layer: "Layer: {name}" for layer in landscape.GENERATIVE},
        "profiles": {"only": {"edge": 1, "domain": 1, "platform": 1, "data": 1, "system": 2}},
        "chokepoints": 1,
    }


def test_the_minimal_vocabulary_is_actually_valid() -> None:
    """Otherwise every refusal below passes for the wrong reason."""
    assert Landscape(**_valid()).profile("only")["edge"] == 1


@pytest.mark.parametrize(("label", "mutate", "message"), [
    ("a layer with no names",
     lambda k: k["services"].__setitem__("domain", ()), "no service names"),
    ("a blank name",
     lambda k: k["services"].__setitem__("edge", ("  ",)), "blank service name"),
    ("a purpose sentence with nowhere to put the name",
     lambda k: k["purpose"].__setitem__("data", "A pipeline"), "purpose sentence"),
    ("a layer the construction does not have",
     lambda k: k["services"].__setitem__("mesh", ("e-thing",)), "not layers"),
    ("one name in two layers",
     lambda k: k["services"].__setitem__("domain", ("a-web",)), "more than one layer"),
    ("no systems at all", lambda k: k.__setitem__("systems", ()), "at least one system"),
    ("a system that is not a triple",
     lambda k: k.__setitem__("systems", (("One", "First"),)), "name, purpose"),
    ("two systems with one name",
     lambda k: k.__setitem__("systems", (("One", "a", "x"), ("One", "b", "y"))),
     "share a name"),
    ("two systems of record for one thing",
     lambda k: k.__setitem__("systems", (("One", "a", "x"), ("Two", "b", "x"))),
     "same thing"),
    ("an estate that gates nothing",
     lambda k: k.__setitem__("chokepoints", 0), "at least one chokepoint"),
    ("no sizes", lambda k: k.__setitem__("profiles", {}), "at least one size profile"),
    ("a profile missing a layer",
     lambda k: k["profiles"]["only"].pop("data"), "no count for"),
    ("a profile counting something that is not a layer",
     lambda k: k["profiles"]["only"].__setitem__("mesh", 1), "not layers"),
    ("a negative count",
     lambda k: k["profiles"]["only"].__setitem__("edge", -1), "asks for -1"),
    ("more services than the vocabulary holds",
     lambda k: k["profiles"]["only"].__setitem__("domain", 4), "the pool holds"),
    ("more systems than the vocabulary holds",
     lambda k: k["profiles"]["only"].__setitem__("system", 9), "landscape names"),
    ("too few systems to reserve a private store",
     lambda k: k["profiles"]["only"].__setitem__("system", 1), "it gates nothing"),
    ("fewer platform services than chokepoints",
     lambda k: (k["profiles"]["only"].__setitem__("platform", 0),
                k["services"].__setitem__("platform", ("c-provider",))),
     "meant to be chokepoints"),
])
def test_a_vocabulary_that_would_build_a_worse_estate_is_refused(
    label: str, mutate, message: str,
) -> None:
    """Every rule fires. Two of these are the ones worth having: a profile
    asking for more nodes than the pool holds used to truncate silently, so
    ``--estate large`` returned a medium estate; and a profile with too few
    systems reserves no private backing store, so nothing gates anything and the
    landscape quietly becomes the flat graph `compose.review` refuses outright.
    """
    kwargs = _valid()
    mutate(kwargs)
    with pytest.raises(ValueError, match=message):
        Landscape(**kwargs)


def test_a_vocabulary_that_holds_less_than_large_is_a_legal_vocabulary() -> None:
    """The refusal above is about a profile overreaching its pool, not about
    every vocabulary having to be able to serve every size — a pack shipping one
    small landscape and one size to build it at is fine."""
    assert Landscape(**_valid()).profiles.keys() == {"only"}


# ---------------------------------------------------------------------------
# Banking and insurance can have an estate at all
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def bank() -> World:
    return BankingWorld(seed=SEED, estate="large").build().run(
        QuarterlyCapitalReturn(period="2026-03")
    )


@pytest.fixture(scope="module")
def insurer() -> World:
    return InsuranceWorld(seed=SEED, estate="large").build().run(
        QuarterlyReserving(period="2026-06")
    )


def test_a_banking_estate_builds_and_validates(bank: World) -> None:
    report = bank.validate()
    assert report.ok, "\n".join(str(v) for v in report.violations)


def test_a_banking_estate_is_acyclic_by_construction(bank: World) -> None:
    """The layering, unchanged: this is the property the whole exercise was not
    allowed to cost, and a vertical it had never been run for is where a
    construction that only worked by luck would show."""
    assert graphs.cycles(graphs.dependency_graph(bank)) == ()


def test_a_banking_estate_has_chokepoints(bank: World) -> None:
    """Placed, not hoped for. The private backing store is what puts a shared
    platform service on the single path to something."""
    gated = dict(graphs.chokepoints(graphs.dependency_graph(bank)))
    names = {s.id: s.name for s in bank.services}
    assert {names.get(node) for node in gated} >= {"identity-provider", "entitlements-service"}


def test_a_banking_estate_is_a_landscape_rather_than_a_prop_list(bank: World) -> None:
    reading = graphs.analyse(bank)
    assert len(reading.services) > 30
    # Five layers cap a strictly stratified estate at four hops. Anything past
    # that is the same-layer calls, which is what makes it a landscape.
    assert graphs._hops(reading.longest_dependency_chain) > 4


def test_a_bank_speaks_banking(bank: World) -> None:
    """The deliverable. A bank whose landscape is called ``pricing-engine`` and
    ``click-collect-api`` is worse than a thin one — which is exactly why
    ``--estate`` was refused rather than mis-served."""
    names = {s.name for s in bank.services}
    assert {"rwa-capital-engine", "collateral-valuation-sync"} <= names, "the episode's own"
    assert {"credit-decision-engine", "provisioning-engine", "collateral-revaluation-feed"} <= names
    assert not names & RETAIL_TRADE


def test_the_banking_estate_extends_the_episodes_world_rather_than_a_parallel_one(
    bank: World,
) -> None:
    """`generators/regulatory.py` names five systems and four services by role
    handle. A second ``rwa-capital-engine``, or a second collateral register
    under another name, would make the corpus ambiguous about which one the
    reconciliation break ran through."""
    core = BankingWorld(seed=SEED).build()
    core_names = {s.name for s in core.services} | {s.name for s in core.systems}
    grown_only = [s for s in bank.services if s.id not in {c.id for c in core.services}]
    assert not {s.name for s in grown_only} & core_names


def test_an_insurer_had_no_technology_graph_at_all_before_this() -> None:
    """The sharpest case for the whole change. Not a thin estate — none."""
    assert list(InsuranceWorld(seed=SEED).build().services) == []


def test_an_insurance_estate_builds_validates_and_gates(insurer: World) -> None:
    report = insurer.validate()
    assert report.ok, "\n".join(str(v) for v in report.violations)
    assert graphs.cycles(graphs.dependency_graph(insurer)) == ()
    gated = dict(graphs.chokepoints(graphs.dependency_graph(insurer)))
    names = {s.id: s.name for s in insurer.services}
    # The document store, and that is the claim this vocabulary makes about the
    # industry: a policy schedule, a claim file, an assessor's report and the
    # correspondence trail are one object to every part of an insurer, and there
    # is exactly one of it.
    assert "document-store" in {names.get(node) for node in gated}


def test_an_insurer_speaks_insurance(insurer: World) -> None:
    names = {s.name for s in insurer.services}
    assert {"reserving-engine", "development-triangle-builder", "claims-triage-service"} <= names
    assert not names & RETAIL_TRADE


def test_the_smallest_profile_still_gates_something() -> None:
    """``small`` mints three systems and reserves two, which leaves exactly one
    shared. The arithmetic is tight enough to be worth a test rather than a
    reading of `Landscape.__post_init__`."""
    for world in (BankingWorld(seed=SEED, estate="small"),
                  InsuranceWorld(seed=SEED, estate="small")):
        built = world.build()
        assert graphs.chokepoints(graphs.dependency_graph(built))
        assert built.validate().ok


def test_owners_are_the_people_who_already_own_something(insurer: World) -> None:
    """An insurer's role table has no technology roles, so service ownership
    goes to the three who own its systems of record. The alternative — falling
    through to whoever the table lists first — is how a corpus ends up with the
    chief actuary owning nothing and the CEO owning the event bus."""
    eligible = {
        insurer._roles[key]
        for key in ("chief_actuary", "claims_director", "financial_controller")
    }
    assert {s.owner_id for s in insurer.services} <= eligible


def test_owners_skips_a_role_the_organisation_does_not_have() -> None:
    """A pack-authored role table is free not to include one, and refusing to
    build over a missing key would make the flag depend on a table the author
    may never have seen."""
    assert estate_module.owners({"a": "P-1"}, "a", "absent") == ("P-1",)


# ---------------------------------------------------------------------------
# The recipe carries it, and replays it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("world", "scenario", "period"), [
    (BankingWorld, QuarterlyCapitalReturn, "2026-03"),
    (InsuranceWorld, QuarterlyReserving, "2026-06"),
])
def test_the_recipe_carries_and_replays_a_verticals_estate(
    world, scenario, period: str, tmp_path,
) -> None:
    built = world(seed=SEED, estate="medium").build().run(scenario(period=period))
    loaded = World.load(built.compile().export(tmp_path / "grown"))
    assert loaded.recipe["estate"] == "medium"

    again = rebuild(loaded.recipe)
    assert [s.model_dump() for s in again.services] == [
        s.model_dump() for s in built.services
    ]
    assert [s.model_dump() for s in again.systems] == [
        s.model_dump() for s in built.systems
    ]


@pytest.mark.parametrize("world", [BankingWorld, InsuranceWorld])
def test_a_default_recipe_carries_no_estate_key(world, tmp_path) -> None:
    """The rule every conditional recipe key follows: a key written
    unconditionally puts a new field in every recipe ever written for a value
    that changes nothing, and the default-build byte diff is what catches it."""
    scenario = {BankingWorld: (QuarterlyCapitalReturn, "2026-03"),
                InsuranceWorld: (QuarterlyReserving, "2026-06")}[world]
    built = world(seed=SEED).build().run(scenario[0](period=scenario[1]))
    loaded = World.load(built.compile().export(tmp_path / "plain"))
    assert "estate" not in loaded.recipe


def test_a_pack_built_estate_replays(tmp_path) -> None:
    """The gap this change closed. A pack-built retailer could always be given
    ``--estate`` — the CLI rebinds the builder after ``from_pack`` — and the
    recipe recorded it, but ``rebuild`` only passed it on the *archetype*
    branch. So a pack corpus with a hundred-node landscape rebuilt into one with
    nine and reported success.
    """
    import json
    import pathlib

    from worldloom import packs

    source = pathlib.Path("examples/packs/regional-insurer.json")
    pack = packs.load(json.loads(source.read_text()))
    built = RetailWorld.from_pack(pack, seed=SEED)
    built = dataclasses.replace(built, estate="medium").build().run(
        MonthEndClose(period="2026-03")
    )

    loaded = World.load(built.compile().export(tmp_path / "packed"))
    assert loaded.recipe["estate"] == "medium"
    again = rebuild(loaded.recipe)
    assert [s.model_dump() for s in again.services] == [
        s.model_dump() for s in built.services
    ]
    assert len(list(again.services)) > 9, "the estate has to survive the round trip"


def test_a_recipe_recording_an_estate_meets_a_spec_that_cannot_carry_one() -> None:
    """Refused, never silently dropped — `_under` and `_with_roles`'s posture.
    The corpus was built with that landscape, and rebuilding it without would be
    a smaller world reported as the same one."""
    from worldloom.recipe import RecipeError, _with_estate

    @dataclasses.dataclass(frozen=True)
    class Spec:
        seed: int

    assert _with_estate(Spec(seed=1), None) == Spec(seed=1)
    with pytest.raises(RecipeError, match="does not accept one"):
        _with_estate(Spec(seed=1), "medium")


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------


def test_every_vocabulary_publishes_as_json_and_round_trips() -> None:
    """An author cannot choose what they cannot see — `parameters.publish`'s
    reason, and `landscape.from_document` is the seam a pack authors through."""
    import json

    published = landscape.publish()
    assert sorted(published) == sorted(landscape.LANDSCAPES)
    for name, payload in json.loads(json.dumps(published)).items():
        assert landscape.from_document(payload) == landscape.LANDSCAPES[name]
    assert landscape.from_document("banking") is landscape.BANKING


def test_a_document_missing_a_whole_section_is_refused() -> None:
    with pytest.raises(ValueError, match="services, systems, purpose and profiles"):
        landscape.from_document({"services": {}, "systems": []})
