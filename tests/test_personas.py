"""Who a role sounds like, and who gets to decide.

Two properties, and the second exists because the first was violated silently
for three verticals.

**Coverage.** Every role in every engine's own table maps to a persona chosen
for it. There is no way to make that a runtime check without also refusing the
authored role tables `roles.from_shape` exists to allow, so it is a test — and
a test is the better instrument anyway: it fails when the gap is introduced
rather than when a corpus built through it is read.

**Authorability.** A pack could already override the voice and the phrases of a
role's persona. It could not say *which* persona a role writes with, could not
reach `sentence_complexity` or `technical_depth`, and could not introduce a
persona the engine does not ship. All three now go through `PackVoice`, under
the discipline the voice override already had: an unknown role key is skipped,
an unknown persona id is refused, and nothing a pack writes reaches the numeric
temperament.
"""

from __future__ import annotations

import json

import pytest

from worldloom import packs
from worldloom.banking import BankingWorld
from worldloom.generators import banking_org, insurance_org, organisation
from worldloom.retail import RetailWorld

#: One entry per engine: its module, and the suffixes of the per-unit roles
#: `generate` appends to whatever table it is given. Kept beside the engines'
#: own published `unit_role_suffixes` by `test_the_suffix_tables_match_what_the
#: _engines_publish` rather than asserted twice by hand.
ENGINES = (
    ("retail", organisation),
    ("banking", banking_org),
    ("insurance", insurance_org),
)


def persona_ids(module) -> set[str]:
    return {persona[0] for persona in module._PERSONAS}


@pytest.mark.parametrize(("name", "module"), ENGINES)
def test_every_role_in_an_engines_table_maps_to_a_persona(name: str, module) -> None:
    """The property the fallthrough hid.

    `_ROLE_PERSONA` used to be consulted through `.get(role, DEFAULT)` (or, in
    retail, through a chain ending at the *buyer* entry), so a role nobody had
    mapped and a role deliberately left to the default were the same thing to
    read. They are not the same thing: one is a decision, the other is an
    omission that ships as prose in a stranger's register.
    """
    known = persona_ids(module)
    for role, _title, _function, _manager in module._ROLES:
        assert role in module._ROLE_PERSONA, (
            f"{name}: role {role!r} is in the engine's table but not in _ROLE_PERSONA"
        )
        assert module._ROLE_PERSONA[role] in known


@pytest.mark.parametrize(("name", "module"), ENGINES)
def test_every_persona_a_lookup_can_return_exists(name: str, module) -> None:
    """Every layer of `_persona_for`, including the last resort. A default that
    names a persona the engine does not ship raises `KeyError` from inside the
    clone loop, which is a worse failure than the one it was guarding."""
    known = persona_ids(module)
    for table in (module._ROLE_PERSONA, module._UNIT_ROLE_PERSONA, module._FUNCTION_PERSONA):
        for key, persona in table.items():
            assert persona in known, f"{name}: {key!r} names unknown persona {persona!r}"
    assert module._DEFAULT_PERSONA in known


@pytest.mark.parametrize(("name", "module"), ENGINES)
def test_every_function_an_engine_employs_maps_to_a_persona(name: str, module) -> None:
    """The layer that catches an authored table. `roles.review` tells whoever
    writes one that a role's function decides "cost centre and persona"; that
    was only half true until the function table existed, and it is only true at
    all while the table covers the functions the engine actually employs."""
    for _role, _title, function, _manager in module._ROLES:
        assert function in module._FUNCTION_PERSONA, (
            f"{name}: function {function!r} is in the engine's table but has no persona"
        )


@pytest.mark.parametrize(("name", "module"), ENGINES)
def test_the_suffix_table_covers_the_per_unit_roles_the_engine_publishes(
    name: str, module
) -> None:
    """The per-unit roles are the generator's to append, so no author maps
    them and nothing else can. Retail's `_buyer` reached its persona through
    the catch-all default rather than through this table, which is precisely
    what made the default look load-bearing while it was swallowing every
    unmapped role in the world."""
    from worldloom import domains

    suffixes = domains.by_name(name).unit_role_suffixes
    assert set(suffixes) == set(module._UNIT_ROLE_PERSONA), (
        f"{name}: the engine mints {suffixes} per unit but maps"
        f" {tuple(module._UNIT_ROLE_PERSONA)}"
    )


def test_an_unmapped_role_no_longer_writes_as_a_supermarket_buyer() -> None:
    """The regression itself, stated as the audit found it.

    Retail's lookup ended at `_UNIT_ROLE_PERSONA["buyer"]`, so *every* role the
    key and suffix layers missed — an authored `chief_actuary`, a synthesised
    `role_017`, anything a probe invents — wrote in a merchandising leader's
    register: "commercial, defensive under scrutiny", phrases "range
    architecture" and "category". A chief actuary does not sound like that.
    """
    merch_lead = organisation._ROLE_PERSONA["merch_lead"]
    assert organisation._persona_for("chief_actuary", "Actuarial") != merch_lead
    assert organisation._persona_for("role_017", "Finance") == "PERSONA-FIN-BP"
    assert organisation._persona_for("head_of_claims", "Audit") == "PERSONA-AUDIT"
    # And the role that *is* meant to sound like a merchandising leader still
    # does, by being named rather than by being what was left over.
    assert organisation._persona_for("gm_buyer", "Merchandising") == merch_lead


def test_a_synthesised_organisation_writes_by_function() -> None:
    """The end-to-end shape of the same claim.

    `roles.from_shape` invents `role_001`, `role_002`, … around the spine, and
    every one of them used to write in the merchandising leader's register
    regardless of what it did. They now split by function, which is the only
    thing about an invented role that says anything about how it sounds.
    """
    from worldloom import roles as roles_module

    table = roles_module.to_rows(roles_module.from_shape(
        functions=("Executive", "Finance", "Technology", "Audit"),
        headcount=20, span=4, levels=3, engine="retail",
    ))
    world = RetailWorld(seed=8128, role_table=table).build()
    invented = {
        role: world.people.by_id(person_id)
        for role, person_id in world._roles.items() if role.startswith("role_")
    }
    assert invented, "the shape should have needed more people than the spine holds"
    assert len({person.persona_id for person in invented.values()}) > 1, (
        "invented roles across four functions all wrote with one persona"
    )
    for person in invented.values():
        assert person.persona_id == organisation._FUNCTION_PERSONA[person.function]


# ---------------------------------------------------------------------------
# The pack surface
# ---------------------------------------------------------------------------


def repacked(path: str, voices: dict[str, dict]) -> packs.Pack:
    """A shipped pack with its voices replaced. Loaded through `packs.load` so
    the schema is exercised exactly as an authored file would be."""
    document = json.loads(open(path, encoding="utf-8").read())
    document["voices"] = voices
    return packs.load(document)


INSURER = "examples/packs/regional-insurer.json"
MUTUAL = "examples/packs/mutual-bank.json"


def test_a_pack_can_say_which_persona_a_role_writes_with() -> None:
    """The mapping itself, authorable. `merch_lead` is a retail role the
    insurer pack has no use for as a merchandiser; pointed at the controller's
    persona it writes as one, and no clone is minted — a role writing in a
    register that already exists does not need a second copy of it."""
    pack = repacked(INSURER, {"merch_lead": {"persona": "PERSONA-CONTROLLER"}})
    world = RetailWorld.from_pack(pack, seed=4242).build()
    person = world.people.by_id(world._roles["merch_lead"])
    assert person.persona_id == "PERSONA-CONTROLLER"
    assert not [p for p in world.personas if p.id.startswith("PERSONA-PACK-")]


def test_a_pack_can_add_a_persona_of_its_own() -> None:
    """Voice, both structural dials, and phrases — the four fields a pack may
    author. The temperament is not among them and comes from the base."""
    pack = repacked(INSURER, {
        "merch_lead": {
            "voice": "actuarial, insistent on the full central estimate",
            "sentence_complexity": "high",
            "technical_depth": "high",
            "phrases": ["the central estimate", "development pattern"],
            "persona": "PERSONA-CONTROLLER",
        },
    })
    world = RetailWorld.from_pack(pack, seed=4242).build()
    authored = world.personas.by_id(packs.persona_id_for("merch_lead"))
    base = world.personas.by_id("PERSONA-CONTROLLER")
    assert authored.voice.startswith("actuarial")
    assert authored.sentence_complexity == "high"
    assert authored.technical_depth == "high"
    assert authored.favourite_phrases == ["the central estimate", "development pattern"]
    assert (authored.optimism, authored.risk_tolerance, authored.political_awareness) == (
        base.optimism, base.risk_tolerance, base.political_awareness
    ), "the numeric temperament is withheld from packs and stays the engine's"
    assert base.voice != authored.voice, "the shared persona is cloned, not edited"
    assert world.people.by_id(world._roles["merch_lead"]).persona_id == authored.id


def test_two_roles_can_share_one_authored_persona() -> None:
    """What makes it a persona rather than a per-role voice: the id is
    derivable, so a second role remaps onto it."""
    pack = repacked(INSURER, {
        "merch_lead": {"voice": "actuarial, unhurried", "technical_depth": "high"},
        "merch_analyst": {"persona": packs.persona_id_for("merch_lead")},
    })
    world = RetailWorld.from_pack(pack, seed=4242).build()
    shared = packs.persona_id_for("merch_lead")
    assert world.people.by_id(world._roles["merch_analyst"]).persona_id == shared
    assert world.people.by_id(world._roles["merch_lead"]).persona_id == shared
    assert len([p for p in world.personas if p.id.startswith("PERSONA-PACK-")]) == 1


def test_an_unknown_persona_id_is_refused() -> None:
    """Refused, not ignored. Left to fall back, a dangling id reads as "the
    role kept its default" — the same silent miss the fallthrough was."""
    pack = repacked(INSURER, {"merch_lead": {"persona": "PERSONA-DOES-NOT-EXIST"}})
    with pytest.raises(ValueError, match="PERSONA-DOES-NOT-EXIST"):
        RetailWorld.from_pack(pack, seed=4242).build()


def test_a_clone_may_not_be_based_on_another_pack_persona() -> None:
    """Temperament is inherited and a pack may not author it, so a clone's base
    must be an engine persona. That refusal is also what makes a chain — or a
    cycle — of clones unrepresentable rather than merely discouraged."""
    pack = repacked(INSURER, {
        "merch_lead": {"voice": "actuarial, unhurried"},
        "merch_analyst": {
            "voice": "borrowed", "persona": packs.persona_id_for("merch_lead"),
        },
    })
    with pytest.raises(ValueError, match="persona this world has"):
        RetailWorld.from_pack(pack, seed=4242).build()


def test_the_lint_names_a_pack_internal_persona_mistake() -> None:
    """Both refusals above are fatal at build time, so the lint naming them is
    the difference between an author reading their mistake and hitting it.
    Whether a `persona` names one of the *engine's* ids is not decidable here —
    no domain publishes them — and the build refuses that one by name."""
    dangling = repacked(INSURER, {"merch_lead": {"persona": "PERSONA-PACK-NOBODY"}})
    assert any("no role in this pack defines" in f for f in packs.lint(dangling))

    chained = repacked(INSURER, {
        "merch_lead": {"voice": "actuarial"},
        "merch_analyst": {"voice": "borrowed", "persona": packs.persona_id_for("merch_lead")},
    })
    assert any("must be one" in f for f in packs.lint(chained))


def test_an_unknown_role_key_is_still_only_skipped() -> None:
    """The existing override discipline, unchanged by the additions: a pack
    naming a role the engine does not have is over-specifying, and an orphan
    persona would be worse than an ignored line. The lint says so; the build
    carries on."""
    pack = repacked(INSURER, {"chief_actuary": {"voice": "formal", "persona": "PERSONA-AUDIT"}})
    assert any("names no retail role" in f for f in packs.lint(pack))
    world = RetailWorld.from_pack(pack, seed=4242).build()
    assert not [p for p in world.personas if p.id.startswith("PERSONA-PACK-")]


def test_the_banking_engine_takes_the_same_overrides() -> None:
    """The three engines duplicate the persona machinery deliberately (see
    `banking_org`'s docstring on why they are three machines), which is exactly
    why the pack surface has to be tested against more than one of them."""
    pack = repacked(MUTUAL, {
        "treasurer": {"persona": "PERSONA-BANK-AUDIT"},
        "liquidity_analyst": {"voice": "unhurried, exact", "sentence_complexity": "high"},
    })
    world = BankingWorld.from_pack(pack, seed=7).build()
    assert world.people.by_id(world._roles["treasurer"]).persona_id == "PERSONA-BANK-AUDIT"
    authored = world.personas.by_id(packs.persona_id_for("liquidity_analyst"))
    assert authored.sentence_complexity == "high"
    assert authored.optimism == world.personas.by_id("PERSONA-TREASURY").optimism


def test_a_pack_that_says_nothing_new_is_unchanged() -> None:
    """The override discipline's other half: every field added here defaults to
    "keep", so a pack written before they existed builds the same world."""
    pack = packs.load(INSURER)
    world = RetailWorld.from_pack(pack, seed=4242).build()
    cfo = world.people.by_id(world._roles["cfo"])
    assert cfo.persona_id == packs.persona_id_for("cfo")
    voiced = world.personas.by_id(cfo.persona_id)
    base = world.personas.by_id("PERSONA-CFO")
    assert (voiced.sentence_complexity, voiced.technical_depth) == (
        base.sentence_complexity, base.technical_depth
    )
