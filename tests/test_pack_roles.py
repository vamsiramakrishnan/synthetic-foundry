"""The organisation as pack data: the rung left open the longest.

`voices` proved an engine can publish its role keys and lint against them; the
table itself stayed a literal in each organisation generator, so a pack could
re-voice the CFO and could not give the company a chief risk officer.
`Pack.roles` carries the whole table and the posts minted per unit, reviewed
on the way into every builder, recorded on the recipe as an SDK table always
was, and left off the wire when unset so every pack corpus already built
embeds the exact document it did.
"""

from __future__ import annotations

import json

import pytest

from worldloom import MonthEndClose, QuarterlyCapitalReturn, domains, packs, roles
from worldloom.banking import BankingWorld
from worldloom.recipe import rebuild
from worldloom.retail import RetailWorld

INSURER = "examples/packs/regional-insurer.json"
MUTUAL = "examples/packs/mutual-bank.json"


def _document(path: str) -> dict:
    return json.loads(open(path, encoding="utf-8").read())


def _with_roles(path: str, engine: str, *, add=(), drop=(), unit_roles=None, voices=None) -> packs.Pack:
    document = _document(path)
    table = [row for row in roles.published(engine)["table"] if row["key"] not in drop]
    table.extend(add)
    document["roles"] = {"table": table}
    if unit_roles is not None:
        document["roles"]["unit_roles"] = unit_roles
    if voices is not None:
        document["voices"] = voices
    return packs.load(document)


CRO = {"key": "cro", "title": "Chief Risk Officer", "function": "Risk", "reports_to": "ceo",
       "voice": {"voice": "guarded, precise", "phrases": ["within appetite"]}}


def test_an_unset_roles_block_stays_off_the_wire_and_the_company_is_the_engines() -> None:
    pack = packs.load(INSURER)
    assert pack.roles is None and "roles" not in packs.to_recipe(pack)
    assert packs.role_table_of(pack) is None and packs.unit_roles_of(pack) is None
    assert packs.voices_of(pack) == dict(pack.voices)
    spec = RetailWorld.from_pack(pack, seed=4242)
    assert spec.role_table is None and spec.unit_roles is None
    assert "role_table" not in spec.build().recipe


def test_every_engine_publishes_its_organisation_as_data() -> None:
    for engine in domains.names():
        published = roles.published(engine)
        keys = {row["key"] for row in published["table"]}
        assert set(published["spine"]) <= keys, engine
        assert keys == set(domains.by_name(engine).role_keys), engine
        assert {spec["suffix"] for spec in published["unit_roles"]} == set(
            domains.by_name(engine).unit_role_suffixes
        ), engine
        assert all(row["reports_to"] is None for row in published["table"] if row["key"] == roles.ROOT)


def test_a_pack_adds_a_role_with_its_own_voice_and_the_corpus_rebuilds_with_it() -> None:
    pack = _with_roles(INSURER, "retail", add=[CRO])
    findings = [f for f in packs.lint(pack) if "roles" in f]
    assert not findings, findings
    world = RetailWorld.from_pack(pack, seed=4242).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    )
    cro = [p for p in world.people if p.title == "Chief Risk Officer"]
    assert len(cro) == 1 and cro[0].function == "Risk"
    assert packs.persona_id_for("cro") in {p.id for p in world.personas}, "the inline voice minted its persona"
    assert len(world.recipe["role_table"]) == len(pack.roles.table)
    assert "unit_roles" not in world.recipe
    again = rebuild(world.recipe)
    assert [(p.title, p.function) for p in again.people] == [(p.title, p.function) for p in world.people]
    assert world.validate().ok


def test_a_spine_key_may_be_retitled_and_moved_but_never_removed() -> None:
    retitled = _document(INSURER)
    table = roles.published("retail")["table"]
    for row in table:
        if row["key"] == "controller":
            row["title"] = "Group Financial Controller and Company Secretary"
    retitled["roles"] = {"table": table}
    pack = packs.load(retitled)
    assert not [f for f in packs.lint(pack) if "roles" in f]
    world = RetailWorld.from_pack(pack, seed=4242).build()
    assert any(p.title == "Group Financial Controller and Company Secretary" for p in world.people)

    without = _with_roles(INSURER, "retail", drop=("controller",))
    findings = packs.lint(without)
    assert any("roles.table['controller']: missing_from_spine" in f for f in findings), findings
    with pytest.raises(ValueError, match="missing_from_spine"):
        RetailWorld.from_pack(without, seed=4242)


def test_the_lint_names_every_other_way_a_table_cannot_be_built() -> None:
    two_roots = _with_roles(INSURER, "retail", add=[{**CRO, "reports_to": None}])
    assert any("not_a_tree" in f for f in packs.lint(two_roots))
    orphan = _with_roles(INSURER, "retail", add=[{**CRO, "reports_to": "nobody"}])
    assert any("unknown_manager" in f for f in packs.lint(orphan))
    twice = _with_roles(INSURER, "retail", add=[CRO], voices={"cro": {"persona": "PERSONA-PACK-CRO"}})
    assert any("carries a voice and voices['cro'] is also set" in f for f in packs.lint(twice))
    # A voice for an authored role is a known role, not a stray key.
    voiced = _with_roles(INSURER, "retail", add=[{k: v for k, v in CRO.items() if k != "voice"}],
                         voices={"cro": {"voice": "terse"}})
    assert not any("names no retail role" in f for f in packs.lint(voiced))


def test_authored_posts_replace_the_per_unit_rows_and_must_keep_the_engines_suffixes() -> None:
    posts = [
        {"suffix": "_md", "title": "Managing Director, {unit}", "function": "Executive", "manager": "ceo"},
        {"suffix": "_bp", "title": "Finance Business Partner, {unit}", "function": "Finance", "manager": "controller"},
        {"suffix": "_buyer", "title": "Head of Buying, {unit}", "function": "Merchandising", "manager_suffix": "_md"},
        {"suffix": "_uw", "title": "Chief Underwriter, {unit}", "function": "Underwriting", "manager_suffix": "_md"},
    ]
    pack = _with_roles(INSURER, "retail", unit_roles=posts)
    assert not [f for f in packs.lint(pack) if "roles" in f]
    world = RetailWorld.from_pack(pack, seed=4242).build()
    underwriters = [p for p in world.people if p.title.startswith("Chief Underwriter, ")]
    assert len(underwriters) == len(pack.units)
    assert world.recipe["unit_roles"][-1]["suffix"] == "_uw"
    again = rebuild(world.recipe)
    assert [(p.title, p.function) for p in again.people] == [(p.title, p.function) for p in world.people]

    short = _with_roles(INSURER, "retail", unit_roles=posts[:1])
    assert any("missing suffix(es): _bp, _buyer" in f for f in packs.lint(short))
    with pytest.raises(ValueError, match="missing suffix"):
        RetailWorld.from_pack(short, seed=4242).build()


def test_the_banking_engine_takes_a_pack_table_and_posts_too() -> None:
    posts = roles.published("banking")["unit_roles"] + [
        {"suffix": "_ops", "title": "Head of Operations, {unit}", "function": "Operations", "manager_suffix": "_md"},
    ]
    pack = _with_roles(MUTUAL, "banking", add=[{"key": "chief_data", "title": "Chief Data Officer",
                                                "function": "Technology", "reports_to": "cio"}],
                       unit_roles=posts)
    assert not [f for f in packs.lint(pack) if "roles" in f]
    world = BankingWorld.from_pack(pack, seed=7).build().run(QuarterlyCapitalReturn(period="2026-03"))
    titles = {p.title for p in world.people}
    assert "Chief Data Officer" in titles and any(t.startswith("Head of Operations, ") for t in titles)
    assert world.validate().ok
    assert [(p.title, p.function) for p in rebuild(world.recipe).people] == [(p.title, p.function) for p in world.people]


def test_a_lob_role_the_table_does_not_contain_is_named() -> None:
    document = _document(INSURER)
    document["lobs"] = [{
        "name": "risk", "title": "Risk", "purpose": "Own the appetite.", "engine": "retail",
        "roles": [{"key": "cro", "title": "Chief Risk Officer", "function": "Risk", "reports_to": "ceo"}],
        "responsibilities": [{"role_key": "cro", "fact_kinds": ["financial.revenue"]}],
    }]
    findings = packs.lint(packs.load(document))
    assert any("lobs['risk'] declares role 'cro', which the company's role table does not contain" in f
               for f in findings), findings
    document["roles"] = {"table": roles.published("retail")["table"] + [{k: v for k, v in CRO.items() if k != "voice"}]}
    assert not any("declares role 'cro'" in f for f in packs.lint(packs.load(document)))
