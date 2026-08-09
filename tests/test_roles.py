"""The role spine: what a model may change about an organisation, and what it may not."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from worldloom import roles as roles_module
from worldloom.roles import ROOT, SPINE, Role, from_shape, measure, review

SRC = Path(__file__).resolve().parents[1] / "src" / "worldloom"

#: Every literal role lookup, whatever the mapping is called.
#:
#: `roles[...]` alone is not enough and the first version of this test believed
#: it was — `organisation.generate` resolves `role_ids["merch_lead"]` from the
#: map it has just built, so `merch_lead` was load-bearing and reported free. A
#: synthesised organisation without it raised KeyError from inside the
#: generator, which is precisely the failure the spine exists to make
#: impossible. `colour_roles` is excluded: it is the renderer's palette and has
#: nothing to do with people.
_LOOKUP = re.compile(
    r'(?<!colour_)\b(?:roles|role_ids|_roles|by_role)(?:\.get)?\(?\[\s*"([a-z0-9_]+)"\s*\]'
)

#: A role table row: `("key", "Title", "Function", "manager")`.
_ROW = re.compile(r'^\s*\("([a-z0-9_]+)",\s*"[^"]', re.M)

_TABLES = {
    "retail": "generators/organisation.py",
    "banking": "generators/banking_org.py",
    "insurance": "generators/insurance_org.py",
    "procurement": "generators/procurement_org.py",
}


def _looked_up() -> set[str]:
    found: set[str] = set()
    for path in sorted(SRC.rglob("*.py")):
        found |= set(_LOOKUP.findall(path.read_text()))
    return found


@pytest.mark.parametrize("engine", sorted(SPINE))
def test_the_spine_is_exactly_what_the_code_looks_up(engine: str) -> None:
    """The spine is computed, not maintained.

    A hand-kept list of load-bearing role keys would be wrong within a month
    and would be wrong *silently* — an author would be refused a change that
    was actually safe, or allowed one that crashes an episode. This scan is
    what makes a new `roles["..."]` lookup start constraining authors without
    anyone remembering to update anything.
    """
    declared_rows = set(_ROW.findall((SRC / _TABLES[engine]).read_text()))
    load_bearing = declared_rows & _looked_up()
    assert SPINE[engine] == load_bearing, (
        f"SPINE[{engine!r}] is stale.\n"
        f"  no longer looked up: {sorted(SPINE[engine] - load_bearing)}\n"
        f"  newly looked up:     {sorted(load_bearing - SPINE[engine])}\n"
        "Update roles.SPINE to match — this test computes the truth."
    )


def test_most_of_an_organisation_is_free() -> None:
    """The constraint has to be real and it also has to leave room.

    A spine covering the whole table would mean the layer cannot be authored at
    all, and this asserting nothing would mean it is unconstrained. Retail is
    the tightest engine and still leaves slack.
    """
    rows = set(_ROW.findall((SRC / _TABLES["retail"]).read_text()))
    assert SPINE["retail"] < rows, "the spine must be a strict subset of the table"


# ---------------------------------------------------------------------------
# The grammar
# ---------------------------------------------------------------------------


def valid() -> list[Role]:
    """A minimal retail table that passes: spine, one unit, one root."""
    table = [Role(ROOT, "Chief Executive", "Executive", None)]
    table += [
        Role(key, key.replace("_", " ").title(), "Finance", ROOT)
        for key in sorted(SPINE["retail"]) if key != ROOT
    ]
    table += [
        Role(f"north_{suffix}", f"North {suffix}", "Executive", ROOT)
        for suffix in ("md", "bp", "buyer")
    ]
    return table


def test_a_well_formed_table_is_accepted() -> None:
    assert review(valid(), engine="retail", unit_keys=("north",)) == []


def test_removing_a_spine_role_is_refused_by_name() -> None:
    # The rejection has to say *why* it cannot be removed, or an author
    # reasonably concludes the harness is being precious about a job title.
    table = [role for role in valid() if role.key != "controller"]
    (rejection,) = [r for r in review(table, engine="retail", unit_keys=("north",))
                    if r.rule == "missing_from_spine"]
    assert rejection.subject == "controller"
    assert "KeyError" in rejection.detail


def test_a_spine_role_may_be_retitled_and_moved() -> None:
    """The freedom the spine leaves, asserted rather than assumed."""
    table = [
        Role("controller", "Head of Financial Reporting and Control", "Reporting", "audit")
        if role.key == "controller" else role
        for role in valid()
    ]
    assert review(table, engine="retail", unit_keys=("north",)) == []


def test_a_missing_per_unit_role_is_refused() -> None:
    table = [role for role in valid() if role.key != "north_bp"]
    assert any(r.subject == "north_bp" and r.rule == "missing_from_spine"
               for r in review(table, engine="retail", unit_keys=("north",)))


def test_an_organisation_with_two_roots_is_refused() -> None:
    table = [*valid(), Role("founder", "Founder", "Executive", None)]
    assert any(r.rule == "not_a_tree" for r in review(table, engine="retail", unit_keys=("north",)))


def test_a_root_that_is_not_the_chief_executive_is_refused() -> None:
    table = [Role(role.key, role.title, role.function, "audit" if role.key == ROOT else role.manager)
             for role in valid()]
    table = [Role("audit", "Audit", "Audit", None) if r.key == "audit" else r for r in table]
    rules = {r.rule for r in review(table, engine="retail", unit_keys=("north",))}
    assert "wrong_root" in rules or "reports_in_a_circle" in rules


def test_reporting_to_somebody_who_does_not_exist_is_refused() -> None:
    table = [*valid(), Role("ghost", "Ghost", "Finance", "nobody")]
    (rejection,) = [r for r in review(table, engine="retail", unit_keys=("north",))
                    if r.rule == "unknown_manager"]
    assert rejection.subject == "ghost"


def test_a_reporting_circle_names_who_is_in_it() -> None:
    # A topological sort would say "a cycle exists". That is not something an
    # author can act on.
    table = [
        *valid(),
        Role("a", "A", "Finance", "b"),
        Role("b", "B", "Finance", "a"),
    ]
    circles = [r for r in review(table, engine="retail", unit_keys=("north",))
               if r.rule == "reports_in_a_circle"]
    assert circles
    assert all("a" in r.detail and "b" in r.detail for r in circles)


def test_a_duplicate_role_is_refused() -> None:
    table = [*valid(), Role(ROOT, "Another Chief", "Executive", None)]
    assert any(r.rule == "duplicate_role" for r in review(table, engine="retail", unit_keys=("north",)))


def test_an_untitled_or_functionless_role_is_refused() -> None:
    table = [*valid(), Role("blank", "  ", "  ", ROOT)]
    rules = {r.rule for r in review(table, engine="retail", unit_keys=("north",))}
    assert {"untitled", "no_function"} <= rules


def test_review_reports_every_reason_not_the_first() -> None:
    table = [role for role in valid() if role.key not in {"controller", "audit"}]
    table.append(Role("ghost", "Ghost", "Finance", "nobody"))
    rules = {r.rule for r in review(table, engine="retail", unit_keys=("north",))}
    assert {"missing_from_spine", "unknown_manager"} <= rules


def test_an_unknown_engine_says_which_engines_exist() -> None:
    with pytest.raises(KeyError, match="known:"):
        roles_module.required("logistics")


# ---------------------------------------------------------------------------
# Shape to table
# ---------------------------------------------------------------------------


def test_a_synthesised_organisation_is_buildable_not_merely_plausible() -> None:
    """The whole point of the spine: a model chooses the shape and does not get
    to choose it into something the engine cannot run."""
    table = from_shape(
        functions=("Executive", "Finance", "Technology", "Operations"),
        headcount=40, span=4, levels=4, engine="retail", unit_keys=("north",),
    )
    assert review(list(table), engine="retail", unit_keys=("north",)) == []


@pytest.mark.parametrize(
    ("headcount", "span", "levels"),
    [(23, 5, 4), (40, 4, 5), (60, 8, 3), (35, 3, 6), (90, 9, 4), (200, 6, 5)],
)
def test_a_synthesised_organisation_has_exactly_the_shape_it_was_asked_for(
    headcount: int, span: int, levels: int,
) -> None:
    """All three numbers, not two of them.

    The first version of this asserted `levels <= 4` and passed while building
    trees two levels deep for every shape asked of it — the fill ran out of
    people part-way down and reported success. `measure` exists so a handshake
    can refuse a shape that does not match its claim, which made a synthesiser
    quietly producing one the worst possible caller of it. Measurement caught
    it; an inequality had hidden it.
    """
    table = from_shape(
        functions=("Executive", "Finance", "Technology", "Operations"),
        headcount=headcount, span=span, levels=levels,
        engine="retail", unit_keys=("north",),
    )
    shape = measure(table)
    assert shape["headcount"] == headcount
    assert shape["levels"] == levels
    assert shape["widest_span"] <= span
    assert review(list(table), engine="retail", unit_keys=("north",)) == []


def test_a_tree_deeper_than_it_has_people_for_is_refused() -> None:
    with pytest.raises(ValueError, match="one per level"):
        from_shape(functions=("Executive",), headcount=30, span=2, levels=40,
                   engine="insurance")


def test_the_same_shape_synthesises_the_same_table_every_time() -> None:
    """The remainder goes to the lowest-index manager first, so the tree does
    not depend on iteration order or a seed — this runs inside a build whose
    output must be byte-identical on replay."""
    kwargs = dict(functions=("Executive", "Finance"), headcount=30, span=3,
                  levels=4, engine="retail", unit_keys=("north",))
    first = from_shape(**kwargs)  # type: ignore[arg-type]
    for _ in range(3):
        assert from_shape(**kwargs) == first  # type: ignore[arg-type]


def test_a_shape_too_small_for_the_engine_s_own_lookups_is_refused() -> None:
    # Reported by raising rather than by quietly exceeding the headcount: a
    # caller who asked for eight people and got fifteen has had their claim
    # overruled and should find out here.
    with pytest.raises(ValueError, match="engine's own lookups"):
        from_shape(functions=("Executive",), headcount=8, span=3, levels=3,
                   engine="retail", unit_keys=("north",))


def test_a_shape_that_does_not_fit_says_which_three_numbers_disagree() -> None:
    with pytest.raises(ValueError, match="not independent"):
        from_shape(functions=("Executive",), headcount=500, span=2, levels=2)


def test_span_and_levels_must_be_at_least_one() -> None:
    with pytest.raises(ValueError, match="span"):
        from_shape(functions=("Executive",), headcount=10, span=0, levels=3)
    with pytest.raises(ValueError, match="levels"):
        from_shape(functions=("Executive",), headcount=10, span=3, levels=0)


def test_measuring_the_shipped_retail_table_reports_a_real_organisation() -> None:
    from worldloom.generators import organisation

    shape = measure(roles_module.from_rows(organisation._ROLES))
    assert shape["headcount"] == len(organisation._ROLES)
    assert shape["levels"] >= 2, "a two-level company is not an organisation"


@pytest.mark.parametrize(
    ("headcount", "span", "levels"), [(14, 4, 3), (25, 4, 5), (31, 9, 3)],
)
def test_a_synthesised_organisation_actually_builds_a_world(
    headcount: int, span: int, levels: int,
) -> None:
    """The check `review` cannot make on its own.

    `review` knows the spine; it does not know that the spine was derived by a
    regex. The first version of that regex matched only `roles[...]` and missed
    `role_ids["merch_lead"]`, so a table passing every grammar check raised
    KeyError from inside the generator — the exact failure the spine exists to
    prevent, surviving because nothing built anything. This is the test that
    closes the loop between the two, and it is slow on purpose.
    """
    from worldloom.retail import RetailWorld
    from worldloom.scenarios import MonthEndClose

    table = roles_module.to_rows(from_shape(
        functions=("Executive", "Finance", "Technology", "Operations", "Merchandising"),
        headcount=headcount, span=span, levels=levels, engine="retail",
    ))
    world = RetailWorld(seed=8128, role_table=table).build()
    world = world.run(MonthEndClose(period="2026-03", include_operational_incident=True))
    report = world.validate()
    assert report.ok, [str(v) for v in report.violations[:5]]
    # The per-unit roles are the generator's to append, not an author's to
    # supply — so headcount grows by three per business unit and that is not a
    # broken claim, it is the division of labour.
    assert len(world.people) > headcount


def test_the_extended_name_pools_cap_how_large_an_organisation_can_be() -> None:
    """A ceiling worth stating rather than discovering — moved, not gone.

    This test used to pin the ceiling at the 40-name base pools and assert
    that `base + 20` failed to build. The hospital run measured that bound as
    the binding constraint on headcount, and the vocabulary packs
    (`data/vocab/*.json`, loaded by `locales.py`) removed it: a headcount past
    the base pool now draws from the locale's extended pool, whose head is the
    base pool verbatim so every smaller build keeps its bytes. The *new*
    ceiling is the extended pool's depth (500+ per shipped locale), and it is
    still a documented limit rather than a defect: past it, the same clear
    refusal fires, now naming the deep pool's size. A pack's own
    `Pack.name_pools` still caps a pack build at whatever the pack wrote —
    deliberately never topped up from the locale.
    """
    from worldloom.generators.names import FAMILY, GIVEN
    from worldloom.locales import AUSTRALIA
    from worldloom.retail import RetailWorld

    base_ceiling = min(len(GIVEN), len(FAMILY))
    assert base_ceiling == 40, "if this moved, the guidance below moved with it"

    # The old failing shape now builds, with every person distinctly named.
    table = roles_module.to_rows(from_shape(
        functions=("Executive", "Finance"), headcount=base_ceiling + 20, span=6,
        levels=3, engine="retail",
    ))
    assert review(list(roles_module.from_rows(table)), engine="retail") == []
    world = RetailWorld(seed=8128, role_table=table).build()
    assert len({person.name for person in world.people}) == len(world.people)

    # The bound that remains: the extended pool's own depth.
    ceiling = min(len(AUSTRALIA.given_extended), len(AUSTRALIA.family_extended))
    assert ceiling >= 500
    from worldloom.generators import names as names_module
    from worldloom.rng import Rng

    with pytest.raises(ValueError, match="name pools hold"):
        names_module.people_names(Rng(8128), ceiling + 1, locale=AUSTRALIA)


def test_an_authored_organisation_rebuilds_from_its_recipe() -> None:
    from worldloom import recipe as recipe_module
    from worldloom.retail import RetailWorld

    table = roles_module.to_rows(from_shape(
        functions=("Executive", "Finance", "Technology"),
        headcount=30, span=5, levels=3, engine="retail",
    ))
    built = RetailWorld(seed=8128, role_table=table).build()
    assert "role_table" in built.recipe
    rebuilt = recipe_module.rebuild(built.recipe)
    assert [(p.title, p.function) for p in rebuilt.people] == \
           [(p.title, p.function) for p in built.people]


def test_a_default_build_records_no_role_table() -> None:
    from worldloom.retail import RetailWorld

    assert "role_table" not in RetailWorld(seed=8128).build().recipe


def test_rows_round_trip() -> None:
    from worldloom.generators import organisation

    rows = organisation._ROLES
    assert roles_module.to_rows(roles_module.from_rows(rows)) == tuple(rows)


def test_the_unit_role_key_format_round_trips() -> None:
    """Minting and parsing share one definition, so they cannot disagree."""
    for suffix in roles_module.UNIT_ROLE_SUFFIXES:
        key = roles_module.unit_role_key("north", suffix)
        assert roles_module.parse_unit_role(key) == ("north", suffix)


def test_a_key_that_is_not_a_unit_role_parses_to_none() -> None:
    # `merch_lead` ends in no unit suffix; a bare suffix has no unit key in
    # front of it; and an engine that mints only `_md` must not claim a `_bp`
    # key it never minted — the suffix list is the caller's, which is what
    # lets `domains.Domain.unit_role_suffixes` plug in directly.
    assert roles_module.parse_unit_role("merch_lead") is None
    assert roles_module.parse_unit_role("_md") is None
    assert roles_module.parse_unit_role("personal_bp", ("_md",)) is None
    assert roles_module.parse_unit_role("personal_bp", ("_md", "_bp")) == ("personal", "_bp")


def test_the_unit_role_templates_are_derived_from_the_accessor() -> None:
    """`UNIT_ROLES` is what `required` used to format keys from; deriving it
    through `unit_role_key` is what stops the template and the accessor from
    ever spelling the format differently."""
    assert roles_module.UNIT_ROLES == tuple(
        roles_module.unit_role_key("{unit}", suffix)
        for suffix in roles_module.UNIT_ROLE_SUFFIXES
    )


def test_a_unit_role_spec_mints_the_row_the_generator_used_to_inline() -> None:
    spec = roles_module.UnitRole(
        "_buyer", "Head of Buying, {unit}", "Merchandising", manager_suffix="_md",
    )
    assert spec.row("gm", "General Merchandise") == (
        "gm_buyer", "Head of Buying, General Merchandise", "Merchandising", "gm_md",
    )


def test_the_minted_unit_rows_match_what_the_engines_publish() -> None:
    """`Domain.unit_role_suffixes` is the published claim and `_UNIT_ROLES` is
    what actually gets minted; the same drift-closing comparison
    `test_personas` makes for the persona suffix table."""
    from worldloom import domains
    from worldloom.generators import banking_org, insurance_org, organisation

    for name, module in (
        ("retail", organisation),
        ("banking", banking_org),
        ("insurance", insurance_org),
    ):
        assert tuple(spec.suffix for spec in module._UNIT_ROLES) == \
            domains.by_name(name).unit_role_suffixes, name


def test_authored_unit_roles_flow_through_the_same_accessor() -> None:
    """The seam itself: an extra per-unit row is minted, attached to its unit,
    and managed by its own unit's MD — through `unit_role_key`/`parse_unit_role`,
    with no new string surgery anywhere."""
    from worldloom import archetypes
    from worldloom.generators import organisation
    from worldloom.ids import Minter
    from worldloom.rng import Rng

    org = organisation.generate(
        Rng(8128, "organisation"), Minter(),
        archetype=archetypes.get("omnichannel_retailer"),
        unit_roles=(
            *organisation._UNIT_ROLES,
            roles_module.UnitRole(
                "_ops", "Operations Manager, {unit}", "ServiceOperations",
                manager_suffix="_md",
            ),
        ),
    )
    ops_id = org.roles["gm_ops"]
    person = next(p for p in org.people if p.id == ops_id)
    assert person.business_unit_id == org.roles["unit_gm"]
    assert person.manager_id == org.roles["gm_md"]
    assert person.title == "Operations Manager, General Merchandise"


def test_unit_roles_missing_an_engine_suffix_are_refused_by_name() -> None:
    """The same argument as the spine: the engine looks `{unit}_buyer` up by
    name (`hierarchy.generate`'s buyers), so a set without it must be refused
    up front rather than raise KeyError from inside the build."""
    from worldloom import archetypes
    from worldloom.generators import organisation
    from worldloom.ids import Minter
    from worldloom.rng import Rng

    with pytest.raises(ValueError, match="_buyer"):
        organisation.generate(
            Rng(8128, "organisation"), Minter(),
            archetype=archetypes.get("omnichannel_retailer"),
            unit_roles=organisation._UNIT_ROLES[:2],
        )


def test_passing_the_default_unit_roles_changes_nothing() -> None:
    """`None` means the module's own rows, and passing those rows explicitly
    is the same build — the byte-identity claim, stated at the object level."""
    from worldloom import archetypes
    from worldloom.generators import organisation
    from worldloom.ids import Minter
    from worldloom.rng import Rng

    def build(unit_roles):  # type: ignore[no-untyped-def]
        return organisation.generate(
            Rng(8128, "organisation"), Minter(),
            archetype=archetypes.get("omnichannel_retailer"),
            unit_roles=unit_roles,
        )

    assert build(None) == build(organisation._UNIT_ROLES)


def test_a_synthesised_spine_key_sits_where_its_engine_files_it() -> None:
    """Which function a spine key sits in is read by the engine, so it is closed
    for the reason the key itself is.

    `organisation.generate` builds an access policy from
    `allow_functions=["Finance", "Audit"]` and `world._policy_for("finance")`
    hands it to the workbook and the variance memo. Round-robin by position put
    `audit` in Finance, `cfo` in Technology and `controller` in Merchandising —
    so the author of the variance memo could not read it, and every mosaic world
    of every engine failed `author_cannot_see_own_artifact`. It stayed invisible
    because the check reads *compiled* artifacts and a plan-only mosaic has none.
    """
    from worldloom import roles as roles_module

    for engine in ("retail", "banking", "insurance"):
        shipped = {role.key: role.function for role in roles_module._shipped(engine)}
        table = roles_module.from_shape(
            # Deliberately a function list that shares almost nothing with the
            # engine's own — the caller's set decides where *synthesised* roles
            # go and must not decide where the spine goes.
            functions=["Executive", "Operations", "Commercial"],
            headcount=40, span=5, levels=3, engine=engine,
        )
        for role in table:
            if role.key in shipped:
                assert role.function == shipped[role.key], f"{engine}:{role.key}"

    # And a per-unit key, which is in no shipped table, still takes the
    # caller's rotation rather than raising.
    unit_table = roles_module.from_shape(
        functions=["Executive", "Operations"], headcount=40, span=5, levels=3,
        engine="retail", unit_keys=["gm"],
    )
    placed = {role.key: role.function for role in unit_table}
    assert placed["gm_md"] in {"Executive", "Operations"}


def test_an_invented_role_reports_to_somebody_who_does_its_job() -> None:
    """The measurement: 319 of 407 synthesised people, 78%, reported across a
    function boundary.

    Round-robin dealt the function by position in the tree and the manager by
    position in the level, and the two had nothing to do with each other. It
    produced a "Head of Audit" reporting to a Merchandising Systems Analyst and
    a "Head of Executive" reporting to a platform lead. Nobody has that company,
    and it stops being cosmetic the moment anyone below the spine authors a
    document: a one-to-one minuted between a finance manager and their
    audit-function manager is noise wearing a document's clothes.
    """
    from worldloom import roles as roles_module

    for engine in ("retail", "banking", "insurance"):
        # The engine's own functions, which is what `company._functions_of`
        # passes when a description does not name its departments — so this is
        # the realistic case rather than a contrived one.
        wanted = []
        for role in roles_module._shipped(engine):
            if role.function not in wanted:
                wanted.append(role.function)
        table = roles_module.from_shape(
            functions=wanted, headcount=420, span=8, levels=6, engine=engine,
        )
        function_of = {role.key: role.function for role in table}
        shipped = {role.key for role in roles_module._shipped(engine)}
        crossed = [
            role for role in table
            if role.key not in shipped
            and role.manager not in (None, ROOT)
            and function_of[role.manager] != role.function
        ]
        assert not crossed, f"{engine}: {[r.key for r in crossed[:5]]}"


def test_making_a_subtree_coherent_does_not_move_a_single_reporting_line() -> None:
    """Inheritance rather than "pick a same-function parent", and this is why.

    Choosing the manager by function unbalances the spans — a function with two
    managers at a level would take a third of the tree — and `measure`/`review`
    check the widest span against what the caller claimed, so a shape that was
    accepted yesterday would be refused today. Inheriting instead leaves the
    tree's shape byte-identical and moves only the labels.
    """
    from worldloom import roles as roles_module

    table = roles_module.from_shape(
        functions=["Executive", "Operations", "Commercial"],
        headcount=420, span=8, levels=6, engine="retail",
    )
    shape = roles_module.measure(table)
    assert shape["headcount"] == 420
    assert shape["widest_span"] <= 8
    # The invariant that matters is that every key still hangs where it hung.
    # Pinned as a property of the pairing rather than as a golden list: the
    # manager comes from `parents[index % len(parents)]` and nothing in the
    # function rule may reach it.
    assert [role.manager for role in table] == [
        role.manager for role in roles_module.from_shape(
            functions=["Audit", "Risk"],  # a different rotation entirely
            headcount=420, span=8, levels=6, engine="retail",
        )
    ]


def test_the_caller_s_functions_still_seed_the_organisation() -> None:
    """Inheritance must not turn `functions` into a list nobody reads.

    A synthesised role hanging off the root has no function to inherit — the
    root is Executive and everyone would be — so there the caller's rotation
    still decides, and each subtree carries its seed downwards.
    """
    from worldloom import roles as roles_module

    table = roles_module.from_shape(
        functions=["Claims", "Actuarial", "Distribution"],
        # Small enough that the spine does not fill the first level on its own.
        headcount=40, span=6, levels=3, engine="retail",
    )
    seen = {role.function for role in table}
    assert seen & {"Claims", "Actuarial", "Distribution"}, seen


def test_the_spine_keeps_its_own_reporting_lines() -> None:
    """The engine's table already says who reports to whom, and `from_shape`
    used to throw that away.

    Spine keys were dealt into levels in sorted-key order with whatever parent
    the rotation reached, so `svc_desk` reported to nobody in particular and
    retail's four Technology keys — which sort early — landed at depth 1 with
    the whole tree under them while its ServiceOperations keys sorted late and
    landed at depth 2 with almost none. A 420-person retailer came out 159
    technologists to 14 service operators: the function mix of the company was
    decided by alphabetical order.
    """
    from worldloom import roles as roles_module

    for engine in ("retail", "banking", "insurance"):
        shipped = {role.key: role for role in roles_module._shipped(engine)}
        table = roles_module.from_shape(
            functions=["Executive", "Operations"],
            headcount=200, span=6, levels=5, engine=engine,
        )
        placed = {role.key: role for role in table}
        for key, role in placed.items():
            declared = shipped.get(key)
            if declared is None or declared.manager is None:
                continue
            # The declared manager, or — when this shape does not place it,
            # because `required` returns the spine and `_shipped` is wider —
            # the nearest declared ancestor that it does place.
            cursor = declared.manager
            while cursor is not None and cursor not in placed:
                cursor = shipped[cursor].manager if cursor in shipped else None
            expected = cursor or ROOT
            assert role.manager == expected, f"{engine}:{key} → {role.manager} not {expected}"


def test_a_division_is_a_subtree() -> None:
    """Per-unit roles are in no shipped table, so this function states their
    structure: the MD reports to the chief executive and everyone else in the
    division reports to their MD.

    Deliberately not the dotted line the engines declare — retail's `_bp`
    reports to the group controller — because a synthesised organisation has
    one line per person, and the one that makes a division legible is the solid
    one.
    """
    from worldloom import roles as roles_module

    table = roles_module.from_shape(
        functions=["Executive", "Operations"], headcount=60, span=6, levels=4,
        engine="retail", unit_keys=["north", "south"],
    )
    placed = {role.key: role for role in table}
    for unit in ("north", "south"):
        assert placed[f"{unit}_md"].manager == ROOT
        assert placed[f"{unit}_bp"].manager == f"{unit}_md"
        assert placed[f"{unit}_buyer"].manager == f"{unit}_md"


def test_a_full_manager_pushes_a_report_down_a_level_rather_than_refusing() -> None:
    """An organisation whose top is wide adds a layer; it does not fail to exist.

    The chief executive takes the CFO, the CIO and one managing director per
    division, so a span of three with four divisions cannot seat them all as
    direct reports. Refusing there would reject a shape that fits perfectly
    well — the fill walks down from the declared manager to the first
    descendant with room instead.
    """
    from worldloom import roles as roles_module

    table = roles_module.from_shape(
        functions=["Executive", "Operations"], headcount=90, span=3, levels=6,
        engine="retail", unit_keys=["a", "b", "c", "d"],
    )
    shape = roles_module.measure(table)
    assert shape["headcount"] == 90
    assert shape["widest_span"] <= 3, "nobody was given more reports than the span allows"
    assert roles_module.review(list(table), engine="retail",
                               unit_keys=["a", "b", "c", "d"]) == []
