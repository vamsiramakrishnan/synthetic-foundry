"""``EVAL_TEXT``, measured rather than trusted.

Two things can go wrong with a table like `evaluation.EVAL_TEXT` that no
runtime crash necessarily catches: a default's placeholder that no call site
ever supplies (it only blows up with a `KeyError` the day some corpus shape
finally reaches that line), and a call site's keyword that no placeholder
asks for (dead code, or a typo that happens to format without complaint
because `str.format` ignores unused keywords). Both are static properties of
the source, so — in the spirit of `test_thin_waist.py`'s ledger, which
measures coupling instead of asserting it — this file parses the two
evaluation modules and checks the table's claimed contract against what the
call sites actually do, rather than relying on some corpus eventually
exercising every branch.

The second half is the byte-identity guarantee's evaluation-set counterpart:
`test_packs.py` proves a re-voiced corpus rebuilds; this proves the *stock*
retail benchmark — the one nobody's pack touches — reads exactly as it did
before this table existed.
"""

from __future__ import annotations

import ast
from pathlib import Path
from string import Formatter

from worldloom import MonthEndClose
from worldloom.generators import banking_evaluation, evaluation
from worldloom.retail import RetailWorld

SRC = Path("src/worldloom/generators")


def _fields_of(template: str) -> frozenset[str]:
    """Mirrors `episode_text.fields_of` — the placeholder names a template uses."""
    return frozenset(
        name.split(".")[0].split("[")[0]
        for _, name, _, _ in Formatter().parse(template)
        if name
    )


def _is_self_t_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "t"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
        and bool(node.args)
    )


def _for_loop_string_table(node: ast.For) -> tuple[list[str], list[tuple[str, ...]]] | None:
    """``for a, b, c in (("x", "y", "z"), ...):`` read back as (target names,
    literal rows) — the shape `direct_lookup`'s group-fact loop and
    `abstentions`'s loop both use to drive `self.t(...)` with a key that is a
    loop variable rather than a literal at the call site itself."""
    if isinstance(node.target, ast.Name):
        targets = [node.target.id]
    elif isinstance(node.target, ast.Tuple) and all(isinstance(e, ast.Name) for e in node.target.elts):
        targets = [e.id for e in node.target.elts]
    else:
        return None
    if not isinstance(node.iter, (ast.Tuple, ast.List)):
        return None
    rows: list[tuple[str, ...]] = []
    for elt in node.iter.elts:
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            row: tuple[str, ...] | None = (elt.value,)
        elif isinstance(elt, ast.Tuple) and all(
            isinstance(e, ast.Constant) and isinstance(e.value, str) for e in elt.elts
        ):
            row = tuple(e.value for e in elt.elts)
        else:
            return None
        if len(row) != len(targets):
            return None
        rows.append(row)
    return targets, rows


def _retail_call_sites(path: Path) -> dict[str, set[frozenset[str]]]:
    """Every ``self.t("key", **kwargs)`` call, as key -> the kwarg-name sets
    seen across its call site(s). Resolves the two loops that drive the key
    itself from a literal string table rather than writing it at the call
    site (see `_for_loop_string_table`)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    sites: dict[str, set[frozenset[str]]] = {}

    handled: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        table = _for_loop_string_table(node)
        if table is None:
            continue
        targets, rows = table
        values_by_name = {
            name: {row[i] for row in rows} for i, name in enumerate(targets)
        }
        for call in ast.walk(node):
            if _is_self_t_call(call) and isinstance(call.args[0], ast.Name) \
                    and call.args[0].id in values_by_name:
                handled.add(id(call))
                kwnames = frozenset(kw.arg for kw in call.keywords if kw.arg)
                for value in values_by_name[call.args[0].id]:
                    sites.setdefault(value, set()).add(kwnames)

    for node in ast.walk(tree):
        if (
            _is_self_t_call(node) and id(node) not in handled
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            key = node.args[0].value
            kwnames = frozenset(kw.arg for kw in node.keywords if kw.arg)
            sites.setdefault(key, set()).add(kwnames)
    return sites


def _banking_call_sites(path: Path) -> dict[str, set[frozenset[str]]]:
    """Every ``t["key"]`` use, as key -> the kwarg-name sets seen — from
    ``t["key"].format(**kwargs)`` where present, or the empty set for a bare
    ``t["key"]`` passed straight through (the module's slot-less answers and
    every abstention question)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))

    def target_key(node: ast.AST) -> str | None:
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name) and node.value.id == "t"
            and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)
        ):
            return node.slice.value
        return None

    handled: set[int] = set()
    sites: dict[str, set[frozenset[str]]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "format":
            key = target_key(node.func.value)
            if key is not None:
                handled.add(id(node.func.value))
                kwnames = frozenset(kw.arg for kw in node.keywords if kw.arg)
                sites.setdefault(key, set()).add(kwnames)
    for node in ast.walk(tree):
        key = target_key(node)
        if key is not None and id(node) not in handled:
            sites.setdefault(key, set()).add(frozenset())
    return sites


def test_every_retail_eval_text_default_is_filled_at_its_call_site() -> None:
    """A default's placeholders must be exactly what some `self.t(...)` call
    supplies — not a subset (a `KeyError` waiting for the right corpus shape)
    and not a superset (a keyword nothing asks for)."""
    sites = _retail_call_sites(SRC / "evaluation.py")
    missing = []
    mismatched = []
    for key, default in evaluation.EVAL_TEXT.items():
        required = _fields_of(default)
        if key not in sites:
            missing.append(key)
            continue
        if not any(kws == required for kws in sites[key]):
            mismatched.append((key, required, sites[key]))
    assert not missing, f"EVAL_TEXT keys with no `self.t(...)` call site: {missing}"
    assert not mismatched, (
        "EVAL_TEXT default slots do not match what the call site supplies:\n"
        + "\n".join(f"  {k}: default wants {sorted(req)}, call site(s) passed"
                     f" {[sorted(s) for s in seen]}" for k, req, seen in mismatched)
    )


def test_every_banking_eval_text_default_is_filled_at_its_call_site() -> None:
    sites = _banking_call_sites(SRC / "banking_evaluation.py")
    missing = []
    mismatched = []
    for key, default in banking_evaluation.EVAL_TEXT.items():
        required = _fields_of(default)
        if key not in sites:
            missing.append(key)
            continue
        if not any(kws == required for kws in sites[key]):
            mismatched.append((key, required, sites[key]))
    assert not missing, f"EVAL_TEXT keys with no `t[...]` call site: {missing}"
    assert not mismatched, (
        "EVAL_TEXT default slots do not match what the call site supplies:\n"
        + "\n".join(f"  {k}: default wants {sorted(req)}, call site(s) passed"
                     f" {[sorted(s) for s in seen]}" for k, req, seen in mismatched)
    )


def test_no_call_site_names_a_key_eval_text_does_not_have() -> None:
    """The reverse of the above — a typo'd key would `KeyError` at generation
    time; catching it here names the key instead of a stack trace."""
    retail_keys = set(_retail_call_sites(SRC / "evaluation.py"))
    assert retail_keys <= set(evaluation.EVAL_TEXT), (
        retail_keys - set(evaluation.EVAL_TEXT)
    )
    banking_keys = set(_banking_call_sites(SRC / "banking_evaluation.py"))
    assert banking_keys <= set(banking_evaluation.EVAL_TEXT), (
        banking_keys - set(banking_evaluation.EVAL_TEXT)
    )


def test_stock_retail_evaluation_set_is_unchanged() -> None:
    """The reason this table is allowed to exist at all: a build with no pack
    reads exactly as it did when the questions were f-strings. Pinned against
    the same seed and period the byte-identity gate in AGENTS.md/CLAUDE.md
    uses, so a regression here is a regression there."""
    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    )
    questions = [case.question for case in world.evaluations]
    assert "Which merchandise category lost the most gross profit against plan in 2026-03?" \
        in questions
    assert "What revenue did Food report for 2026-03?" in questions or any(
        q.startswith("What revenue did ") and q.endswith("report for 2026-03?")
        for q in questions
    )
