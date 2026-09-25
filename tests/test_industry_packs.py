"""Industry packs: one per catalogue industry, recognised by its aliases, speaking its own words.

The industry layer used to hold its recognition phrases, its sentences and its
numbers as literals. They are packs now (`_data/packs/industry/<industry>.json`,
and the `industry` fragments of the default prompts, policy and industry
packs), and these tests hold the two promises that move makes: a build that
names no pack says exactly what it said before, and a pack in force changes
what it says.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import worldloom
from worldloom import archetypes, company, domains, industry, packkit, roles, sor
from worldloom.packkit.active import forget_defaults
from worldloom.process_bindings import compile_company, default_company, load_catalogue
from worldloom.process_bindings import compiler as bindings_compiler
from worldloom.process_bindings.models import REVENUE_ARCHETYPES, SUPPORT_ARCHETYPES

#: The phrase table `industry.INDUSTRY_WORDS` declared before the industry
#: packs held it, pinned so a pack edit that drops or moves a phrase fails here.
LEGACY_WORDS: dict[str, str] = {
    "bank": "banking", "lender": "banking", "credit union": "banking",
    "insurer": "insurance", "underwriter": "insurance",
    "retailer": "retail", "supermarket": "retail", "grocery": "retail", "grocer": "retail",
    "consumer goods": "consumer_products", "fmcg": "consumer_products", "packaged goods": "consumer_products",
    "telco": "telecom", "telecommunications": "telecom", "mobile operator": "telecom", "network operator": "telecom",
    "utility": "utilities", "electricity": "utilities", "energy retailer": "utilities", "gas network": "utilities",
    "pharma": "life_sciences", "pharmaceutical": "life_sciences", "biotech": "life_sciences",
    "medical devices": "life_sciences",
    "freight": "logistics", "forwarder": "logistics", "shipping": "logistics", "3pl": "logistics",
    "hospital": "healthcare", "health system": "healthcare", "clinic": "healthcare", "provider network": "healthcare",
    "manufacturer": "manufacturing", "factory": "manufacturing", "machine-tool": "manufacturing",
    "plant": "manufacturing",
    "government": "public_sector", "ministry": "public_sector", "statutory board": "public_sector",
    "agency": "public_sector",
    "saas": "technology_saas", "software": "technology_saas", "technology company": "technology_saas",
    "tech company": "technology_saas",
}

INDUSTRIES = tuple(sorted(load_catalogue()["industry_overlays"]))


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    worldloom._install()
    monkeypatch.setenv("WORLDLOOM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("WORLDLOOM_PACK_PATH", raising=False)
    packkit.refresh()
    forget_defaults()
    yield
    packkit.refresh()
    forget_defaults()


def _envelope(name: str, body: dict) -> dict:
    return {"schema": "worldloom.pack/v1", "kind": "industry", "name": name, "body": body}


@pytest.fixture(scope="module")
def telecom():
    compiled = compile_company(default_company("telecom"))
    periods = sor.periods_ending("2026-06", 2)
    facts = industry.facts(compiled)
    return compiled, periods, facts


# -- the shipped packs ---------------------------------------------------------


@pytest.mark.parametrize("name", INDUSTRIES)
def test_every_catalogue_industry_ships_a_pack_that_lints_clean(name: str) -> None:
    resolved = packkit.resolve(f"industry:{name}")
    assert resolved.chain == ("industry:default", f"industry:{name}")
    assert packkit.lint(resolved) == []
    body = resolved.body
    assert body.industry == name and body.engine in domains.names()
    assert body.aliases and body.terms and body.example is not None
    # The example is the catalogue's own default company, spoken in the
    # locale `industry.project` would build it in.
    countries = default_company(name).countries
    assert body.example.countries == countries and body.example.geo == industry.geo_for(countries)


def test_the_engine_each_pack_names_is_the_one_the_industry_rides_today() -> None:
    for name in INDUSTRIES:
        own = domains.by_name(name)
        assert packkit.resolve(f"industry:{name}").body.engine == (own.name if own else "retail"), name


def test_no_phrase_is_claimed_by_two_shipped_packs() -> None:
    claimed: dict[str, str] = {}
    for name in INDUSTRIES:
        for phrase in packkit.resolve(f"industry:{name}").body.aliases:
            assert phrase not in claimed, f"{phrase!r} is claimed by {claimed.get(phrase)} and {name}"
            claimed[phrase] = name


# -- recognition -----------------------------------------------------------------


def test_every_previously_recognised_phrase_names_the_same_industry() -> None:
    words = industry.industry_words()
    for phrase, key in LEGACY_WORDS.items():
        assert words[phrase] == key and industry.industry_of(f"a {phrase} in Asia") == key, phrase
    assert set(LEGACY_WORDS.items()) <= set(industry.aliases().items())
    # The one phrase added in the move: the archetype table's name for a bank.
    assert set(industry.aliases()) - set(LEGACY_WORDS) == {"deposit-taking institution"}


def test_an_uploaded_pack_is_recognised_by_its_aliases(tmp_path: Path) -> None:
    assert industry.industry_of("an aged care operator") is None
    assert industry.industry_of("a hotel group") is None
    packkit.install(_envelope("aged_care", {"industry": "healthcare", "aliases": ["Aged care operator"]}))
    packkit.install(_envelope("hospitality", {"industry": "hospitality", "engine": "retail",
                                              "aliases": ["hotel group"]}))
    assert industry.industry_of("an aged care operator in Perth") == "healthcare"
    assert industry.industry_of("a hotel group") == "hospitality"
    # A pack in front of the shipped ones has the last word on a phrase.
    packkit.install(_envelope("power", {"industry": "utilities", "aliases": ["plant"]}))
    assert industry.industry_of("a plant") == "utilities"


def test_an_industry_pack_without_an_overlay_or_an_engine_is_refused() -> None:
    with pytest.raises(ValueError, match="names no engine"):
        packkit.install(_envelope("hospitality", {"industry": "hospitality", "aliases": ["hotel group"]}))


# -- the default says what the literals said -------------------------------------


def test_default_sentences_are_the_literals_they_replaced(telecom) -> None:
    """Pinned from the code before the move (`git show 4ea5b26`)."""
    compiled, periods, facts = telecom
    lobs = industry.derive_lobs(compiled)
    assert lobs[0].purpose == "Accounts Payable at default-telecom: 4 activities across Procure to Pay, owned by Network."
    records = sor.records(compiled, company_id=compiled.company, periods=periods, facts=facts)
    assert (len(records), sum("amount" in r.fields for r in records), sum(bool(r.fields["exception"]) for r in records)) \
        == (4476, 1818, 1138)
    requests = list(industry.requests(compiled, lobs, records=records))
    declared = next(r for r in requests if not r.expected_record_ids)
    assert declared.brief == ("Abstain: Request asset (Acquire to Retire) for Network, IN. The record is in ServiceNow."
                              " Constraint: asset class.")
    assert declared.expected_answer == "Network owns Request asset in IN; system of record ServiceNow; control: asset class."
    assert declared.to_case().expected_answer == "Not present in the corpus."
    assert declared.to_case().reasoning.endswith("by abstain; the answer is the catalogue's declaration.")
    grounded = next(r for r in requests if r.expected_record_ids and r.constraint)
    assert grounded.brief == ("Chase: Request asset (Acquire to Retire) for Network, IN. The record is in ServiceNow."
                              " Period: 2026-06. Constraint: asset class; exception: unclassified asset.")
    assert grounded.to_case().reasoning.endswith("by chase; the answer is read off 4 records of 2026-06 in ServiceNow.")
    bare = sor.channel_records(compiled, [], periods=periods[:1], company_id=compiled.company)[0]
    assert bare.fields["body"] == ("Request asset in Acquire to Retire, Network, IN, period 2026-05.\nControl: asset class.\n"
                                   "No system of record holds a record for this step (ITSM).")
    assert bare.fields["created_at"] == "2026-05-15T09:00:00+00:00"
    channels = sor.channel_records(compiled, records, periods=periods, company_id=compiled.company)
    clean = next(c for c in channels if c.fields["record_ids"] and not c.fields["exception"])
    assert clean.fields["body"].splitlines()[2].startswith("Records in Exchange Online: Message ")
    assert clean.fields["body"].splitlines()[3] == "No record tripped the exception this period."
    table = industry.role_table(default_company("telecom"))
    assert table is not None
    assert [row["title"] for row in table["table"] if row["key"] in industry.COMMERCIAL_ROLES] == [
        "Customer Service Director", "Customer Service Administrator"]
    assert [row["title"] for row in table["unit_roles"] if row["suffix"] == industry.COMMERCIAL_UNIT_ROLE] == [
        "Customer Service Manager, {unit}"]
    ladder = [r.title for r in roles.from_shape(functions=["Finance", "Risk"], headcount=40, span=3, levels=6)]
    assert ladder[:6] == ["Chief Executive Officer", "Director of Finance", "Director of Technology", "Head of Finance",
                          "Manager, Finance", "Head of Audit"]
    assert "Lead, Finance" in ladder and ladder[-1] == "Role 027"


def test_the_policy_defaults_are_the_constants_they_replaced() -> None:
    assert (sor.RECORDS_PER_PERIOD, sor.EXCEPTION_EVERY, sor.DEFAULT_PERIODS, sor.ANCHOR_PERIOD, sor.CHANNEL_DAY) == (
        3, 4, 6, "2026-06", 15)
    assert (industry.COUNT_CEILING, industry.NAMED_ACTIVITIES, industry.RECORD_LOOKUP_SLACK) == (100_000, 3, 2)
    assert len(sor.MONEY_KINDS) == 32 and {"Invoice", "Claim", "Shipment"} <= sor.MONEY_KINDS
    assert company.default_functions() == company.FUNCTIONS
    assert archetypes.fallback_engine() == "retail" and archetypes.inspired_by("zzz").key == "omnichannel_retailer"


def test_one_table_says_which_units_trade() -> None:
    assert REVENUE_ARCHETYPES | SUPPORT_ARCHETYPES == set(load_catalogue()["bu_archetypes"])
    assert not REVENUE_ARCHETYPES & SUPPORT_ARCHETYPES
    assert bindings_compiler.BU_ARCHETYPES is REVENUE_ARCHETYPES
    assert industry.SUPPORT_ARCHETYPES is SUPPORT_ARCHETYPES and industry.REVENUE_ARCHETYPES is REVENUE_ARCHETYPES


# -- a pack in force -------------------------------------------------------------


def test_a_programme_with_an_industry_pack_in_force_speaks_its_terms(tmp_path: Path, telecom) -> None:
    compiled, periods, _ = telecom
    root = tmp_path / "packs"
    packkit.install(_envelope("ledger", {"terms": {"record": "entry", "company": "enterprise"}}), root=root)
    with packkit.use("industry:ledger", roots=[root]):
        requests = list(industry.requests(compiled, limit=40))
        assert requests and all(" The entry is in " in r.brief for r in requests)
        lobs = industry.derive_lobs(compiled)
        lines = industry.lines(compiled, lobs)
        rows = [row for row in compiled.rows if row.binding_status == "bound"]
        reconcile = next(line for line in lines if line.capability == "reconcile")
        text = industry.request_for(reconcile, [r for r in rows if (r.function, r.stream) == (reconcile.lob, reconcile.stream)])
        assert f"match the {reconcile.stream_name} entries in " in text
        body = sor.channel_records(compiled, [], periods=periods[:1], company_id=compiled.company)[0].fields["body"]
        assert body.endswith("holds a entry for this step (ITSM).")
        assert "entry's stable identifier" in packkit.template("industry.use_case.prompt")
    assert all(" The record is in " in r.brief for r in industry.requests(compiled, limit=40))


def test_a_shipped_industry_pack_describes_the_company_in_its_own_words() -> None:
    derived = industry.programme("healthcare", periods=1)
    with packkit.use("industry:healthcare"):
        cases = derived.use_cases()
    assert cases and all(" healthcare provider in SG" in case.scenario.company_description for case in cases)
    assert all(" healthcare company in SG" in case.scenario.company_description for case in derived.use_cases())


def test_an_industry_pack_governs_the_record_policy_and_the_derivation_cache(tmp_path: Path, telecom) -> None:
    compiled, periods, _ = telecom
    root = tmp_path / "packs"
    packkit.install(_envelope("sparse", {"policy": {"sor.records_per_period": 1, "sor.exception_every": 1}}), root=root)
    shipped = sor.records(compiled, company_id=compiled.company, periods=periods)
    outside = sor._in_force()
    with packkit.use("industry:sparse", roots=[root]):
        assert sor.RECORDS_PER_PERIOD == 1 and sor._in_force() != outside
        sparse = sor.records(compiled, company_id=compiled.company, periods=periods)
    assert len(sparse) * 3 == len(shipped)
    exceptional = [r for r in sparse if next(row for row in compiled.rows if row.id == r.fields["binding_id"]).exception.strip()]
    assert exceptional and all(r.fields["exception"] for r in exceptional)


def test_an_industry_pack_retitles_the_ladder_and_moves_the_fallbacks(tmp_path: Path) -> None:
    root = tmp_path / "packs"
    packkit.install(_envelope("ministry", {
        "engine": "banking",
        "prompts": {"roles.title.depth.2": "Deputy Secretary, {function}"},
        "policy": {"company.functions": ["Executive", "Policy", "Corporate Services"]},
    }), root=root)
    with packkit.use("industry:ministry", roots=[root]):
        titles = [r.title for r in roles.from_shape(functions=["Finance", "Risk"], headcount=40, span=3, levels=6)]
        assert "Deputy Secretary, Finance" in titles and "Head of Finance" not in titles
        assert company.default_functions() == ("Executive", "Policy", "Corporate Services")
        assert archetypes.inspired_by("an unrecognisable concern").key == "midsize_adi"
    assert archetypes.inspired_by("an unrecognisable concern").key == "omnichannel_retailer"
