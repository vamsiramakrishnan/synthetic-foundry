"""The role spine: what a model may change about an organisation, and what it may not."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from worldloom import roles as roles_module
from worldloom.roles import ROOT, SPINE, Role, from_shape, measure, review

SRC = Path(__file__).resolve().parents[1] / "src" / "worldloom"

#: Literal `roles["key"]` lookups, excluding `colour_roles`, which is the
#: renderer's palette and has nothing to do with people.
_LOOKUP = re.compile(r'(?<!colour_)roles(?:\.get)?\(?\[\s*"([a-z0-9_]+)"\s*\]')

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


def test_a_synthesised_organisation_has_the_shape_it_was_asked_for() -> None:
    # `measure` is what lets a handshake refuse a claimed shape rather than
    # taking it on trust.
    table = from_shape(
        functions=("Executive", "Finance", "Technology"),
        headcount=40, span=4, levels=4, engine="retail", unit_keys=("north",),
    )
    shape = measure(table)
    assert shape["headcount"] == 40
    assert shape["widest_span"] <= 4
    assert shape["levels"] <= 4


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


def test_rows_round_trip() -> None:
    from worldloom.generators import organisation

    rows = organisation._ROLES
    assert roles_module.to_rows(roles_module.from_rows(rows)) == tuple(rows)
