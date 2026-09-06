"""Source hygiene: nothing in ``src/worldloom`` may smuggle in run-dependence.

The whole product is the promise that a seed rebuilds a corpus byte for byte
— CI regenerates from the ledger and diffs. Everything banned here is a way
that promise quietly breaks: a clock, ``random``/``uuid``, builtin ``hash()``
(salted per process unless ``PYTHONHASHSEED`` is pinned), and *iterating a
set directly* (element order is hash order, so it is run-dependent for the
same reason) — the repo's convention is that every set iteration goes through
``sorted(...)``.

Scanned by AST rather than grep, deliberately: this repo's comments and
docstrings *talk about* these constructs constantly ("no clock, no
``random``…"), and a text scan would either false-positive on the prose or
be weakened until it also misses code. An AST only contains the code.

Two structural allowances, neither a file-level pass:

- ``rng.py`` may import ``random``: it is the one place the stdlib generator
  is wrapped behind explicit seeding, which is the point of the module.
- ``hash(...)`` inside a ``def __hash__`` is fine: a ``__hash__`` result
  lives and dies inside one process (dict/set bookkeeping) and never reaches
  a corpus byte, and implementing ``__hash__`` in terms of member hashes is
  the only sane way to write one. Anywhere *else*, builtin ``hash()`` is a
  corpus-path hazard and stays banned.
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "worldloom"

#: Modules allowed to import ``random``, relative to ``src/worldloom``.
#: Each entry must say why; an entry without a reason is a silent pass.
RANDOM_IMPORT_ALLOWED = {
    # rng.py exists to be the single seeded wrapper around stdlib random —
    # every other module gets randomness by being handed an Rng.
    Path("rng.py"),
}


class _Hygiene(ast.NodeVisitor):
    """Collects violations, tracking whether we are inside ``def __hash__``."""

    def __init__(self, rel: Path) -> None:
        self.rel = rel
        self.violations: list[str] = []
        self._in_hash_dunder = 0

    def _flag(self, node: ast.AST, what: str) -> None:
        # `ast.comprehension` carries no position of its own; its iterable
        # does. Without this the first set-comprehension violation crashed
        # the scanner with an AttributeError instead of naming the line, which
        # is how a real violation in eval_witnesses announced itself.
        located = node.iter if isinstance(node, ast.comprehension) else node
        self.violations.append(f"{self.rel}:{located.lineno}: {what}")

    # -- imports ------------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root == "random" and self.rel not in RANDOM_IMPORT_ALLOWED:
                self._flag(node, f"import {alias.name} (use worldloom.rng)")
            if root == "uuid":
                self._flag(node, f"import {alias.name} (ids come from ids.Minter)")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        root = (node.module or "").split(".")[0]
        if root == "random" and self.rel not in RANDOM_IMPORT_ALLOWED:
            self._flag(node, f"from {node.module} import ... (use worldloom.rng)")
        if root == "uuid":
            self._flag(node, f"from {node.module} import ... (ids come from ids.Minter)")
        if node.module == "time":
            for alias in node.names:
                if alias.name in {"time", "time_ns"}:
                    self._flag(node, f"from time import {alias.name} (a clock)")
        self.generic_visit(node)

    # -- calls ----------------------------------------------------------------

    def _visit_hash_scope(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        # Entered/left with a counter rather than a bool so a nested helper
        # inside __hash__ still counts as inside it — its result feeds the
        # same process-local value.
        if node.name == "__hash__":
            self._in_hash_dunder += 1
            self.generic_visit(node)
            self._in_hash_dunder -= 1
        else:
            self.generic_visit(node)

    visit_FunctionDef = _visit_hash_scope
    visit_AsyncFunctionDef = _visit_hash_scope

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name) and func.id == "hash" and not self._in_hash_dunder:
            # The builtin by name. Content-hashing helpers (`content_hash(...)`,
            # `hashlib.sha256(...)`) are different names or attribute calls and
            # do not trip this, which is why the check is AST-shaped at all.
            self._flag(node, "builtin hash() outside __hash__ (salted per process)")
        if isinstance(func, ast.Attribute):
            # .now()/.utcnow()/.today() are how datetime reads the wall clock,
            # whatever the object is locally called (datetime, dt, self.tz...).
            # Matching the attribute rather than resolving the receiver costs a
            # theoretical false positive on some other object's .now(); today
            # there are none, and a receiver-resolving version would miss
            # aliased imports, which is the direction that hides real bugs.
            if func.attr in {"now", "utcnow", "today"}:
                self._flag(node, f".{func.attr}() reads the wall clock")
            if (
                func.attr in {"time", "time_ns"}
                and isinstance(func.value, ast.Name)
                and func.value.id == "time"
            ):
                self._flag(node, f"time.{func.attr}() reads the wall clock")
        self.generic_visit(node)

    # -- set iteration --------------------------------------------------------

    @staticmethod
    def _is_bare_set(expr: ast.expr) -> bool:
        """A set literal, a set comprehension, or a set(...) call — the
        iterables whose order is hash order. ``sorted(set(...))`` never
        arrives here: the loop's iter is the ``sorted`` call."""
        if isinstance(expr, (ast.Set, ast.SetComp)):
            return True
        return (
            isinstance(expr, ast.Call)
            and isinstance(expr.func, ast.Name)
            and expr.func.id == "set"
        )

    def _visit_for(self, node: ast.For | ast.AsyncFor) -> None:
        if self._is_bare_set(node.iter):
            self._flag(node, "iterating a set directly; wrap it in sorted(...)")
        self.generic_visit(node)

    visit_For = _visit_for
    visit_AsyncFor = _visit_for

    def visit_comprehension(self, node: ast.comprehension) -> None:  # type: ignore[override]
        if self._is_bare_set(node.iter):
            self._flag(node, "comprehension over a set directly; wrap it in sorted(...)")
        self.generic_visit(node)


@lru_cache(maxsize=1)
def _scan() -> tuple[str, ...]:
    violations: list[str] = []
    files = sorted(SRC.rglob("*.py"))
    assert files, f"nothing to scan under {SRC} — the test is pointed at the wrong tree"
    for path in files:
        visitor = _Hygiene(path.relative_to(SRC))
        visitor.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        violations.extend(visitor.violations)
    return tuple(violations)


def _matching(*needles: str) -> list[str]:
    return [v for v in _scan() if any(n in v for n in needles)]


def test_no_stdlib_random_outside_rng() -> None:
    assert _matching("worldloom.rng") == []


def test_no_uuid() -> None:
    assert _matching("ids.Minter") == []


def test_no_wall_clock() -> None:
    assert _matching("wall clock") == []


def test_no_builtin_hash_outside_hash_dunder() -> None:
    assert _matching("salted per process") == []


def test_no_direct_set_iteration() -> None:
    assert _matching("sorted(...)") == []


def test_the_allowances_are_still_load_bearing() -> None:
    """The two structural passes must keep covering something real.

    If rng.py stops importing random, or nobody implements ``__hash__`` with
    the builtin any more, the allowance is dead code in this test and should
    be deleted rather than left as a hole the next violation walks through.
    """
    rng = SRC / "rng.py"
    tree = ast.parse(rng.read_text(encoding="utf-8"))
    assert any(
        isinstance(n, ast.Import) and any(a.name == "random" for a in n.names)
        for n in ast.walk(tree)
    ), "rng.py no longer imports random; remove RANDOM_IMPORT_ALLOWED's entry"

    def uses_builtin_hash_inside_hash_dunder(path: Path) -> bool:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef) and node.name == "__hash__":
                for inner in ast.walk(node):
                    if (
                        isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Name)
                        and inner.func.id == "hash"
                    ):
                        return True
        return False

    assert any(
        uses_builtin_hash_inside_hash_dunder(path) for path in sorted(SRC.rglob("*.py"))
    ), "no __hash__ uses builtin hash() any more; delete the __hash__ allowance"
