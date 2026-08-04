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


def test_the_default_name_pools_cap_how_large_an_organisation_can_be() -> None:
    """A ceiling worth stating rather than discovering.

    `from_shape` will happily synthesise nine hundred people and `review` will
    pass it, because neither knows the engine draws distinct names from a pool
    of forty. The build then fails — clearly, which is why this is a documented
    limit rather than a defect — but an author reading `from_shape`'s docstring
    has no way to anticipate it. A pack raises the ceiling through
    `Pack.name_pools`; nothing else does.
    """
    from worldloom.generators.names import FAMILY, GIVEN
    from worldloom.retail import RetailWorld

    ceiling = min(len(GIVEN), len(FAMILY))
    assert ceiling == 40, "if this moved, the guidance below moved with it"

    table = roles_module.to_rows(from_shape(
        functions=("Executive", "Finance"), headcount=ceiling + 20, span=6,
        levels=3, engine="retail",
    ))
    assert review(list(roles_module.from_rows(table)), engine="retail") == []
    with pytest.raises(ValueError, match="name pools hold"):
        RetailWorld(seed=8128, role_table=table).build()


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
