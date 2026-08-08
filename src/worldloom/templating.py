"""Structural variables in non-prose document parts.

Prose carries ``{{fact:FACT-0004}}`` where a figure belongs, substituted at render
time from the ledger. This module adds ``{{var:...}}`` for the parts of a document
that are not prose: section headings, table and chart titles, column labels, axis
labels, filing names, and ``purpose`` text.

Variables resolve to things the world already holds — company name, period label,
business unit names, locale/currency labels, engine name, fiscal period bounds —
and may never introduce a figure. A second path to a number would be a second source
of truth, which is what ``{{fact:}}`` exists to prevent.

**The one rule that must be enforced**: ``{{var:}}`` may never be used for narrative
prose. This is not a style preference — it is a measured finding: templated prose put
63% of passages into near-duplicate groups. Real model-written prose dropped that to 8%.
An entire subsystem was deleted because its only purpose was fighting repetition that
the template created and no real writer reproduces. See AGENTS.md, "The refine loop that
is deliberately not here".

**Variables-of-variables** (a variable whose resolution itself contains a variable)
are explicitly refused, because an unbounded expansion is a hang and a bounded one
adds complexity that the use cases do not justify. Callers that need multi-level
resolution build it themselves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .world import World

__all__ = ["Variable", "substitute", "unresolved", "resolve_all"]


# Regex to match {{var:...}} references. Captured group is the variable path.
REFERENCE = re.compile(r"\{\{var:(?P<name>[a-z_][a-z0-9_.]*)\}\}")

# Regex for anything that looks like a reference, however malformed.
# Used for validation to catch mistakes early.
REFERENCE_SHAPED = re.compile(r"\{\{var:(?P<name>[^{}]*)\}\}")


@dataclass(frozen=True)
class Variable:
    """A parsed variable reference.

    Attributes:
        name: The variable path, e.g. "company.name" or "period.label"
        text: The original {{var:...}} text it came from
    """
    name: str
    text: str


def referenced(text: str) -> list[str]:
    """Every variable name referenced in *text*, in order, deduplicated."""
    seen: dict[str, None] = {}
    for match in REFERENCE.finditer(text):
        seen.setdefault(match.group("name"), None)
    return list(seen)


def strip_references(text: str) -> str:
    """*text* with every reference removed, for lexical checks on the text itself."""
    return REFERENCE.sub("", text)


def unresolved(text: str) -> list[str]:
    """Every variable name in *text* that is reference-shaped but not well-formed.

    Scans REFERENCE_SHAPED, not REFERENCE: a malformed name ({{var:0001}}) is
    exactly as unresolvable as a well-formed unknown one ({{var:foo_bar}}).
    """
    seen: dict[str, None] = {}
    for match in REFERENCE_SHAPED.finditer(text):
        name = match.group("name")
        # Accept only well-formed names: lowercase start, alphanumeric/underscore/dot
        if not re.match(r"^[a-z_][a-z0-9_.]*$", name):
            seen.setdefault(name, None)
    return list(seen)


def _resolve_variable(name: str, world: World) -> str | None:
    """Resolve a single variable name to a string value, or None if unknown.

    Variable paths are dot-separated and resolve through nested attributes.
    Invalid paths return None (the caller will refuse them as unresolved).

    Numeric values are refused: variables may never introduce a figure, which
    is what {{fact:}} is for. A second path to a number would be a second source
    of truth.
    """
    try:
        # Split the path and traverse
        parts = name.split(".")
        value: Any = world

        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = getattr(value, part, None)

            if value is None:
                return None

        # Ensure the result is a string or can be coerced to one.
        # Numeric values are refused (that's {{fact:}}'s job).
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            # Variables may never introduce a figure — that's {{fact:}}'s job.
            # A second path to a number would be a second source of truth.
            return None
        if value is True or value is False:
            return str(value).lower()
        # Other types are not supported
        return None
    except (AttributeError, TypeError, KeyError):
        return None


def substitute(
    text: str,
    world: World,
) -> tuple[str, list[str]]:
    """Replace every variable reference in *text* with its value from *world*.

    Returns a tuple of (substituted_text, unresolved_names).

    An unresolvable variable is left visible as ``[missing var:NAME]`` and named
    in the unresolved list. A document with a hole in it is a bug worth seeing.

    Variables-of-variables are explicitly refused: if a resolved value contains
    {{var:...}}, it is an error.
    """
    unresolved_vars: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        value = _resolve_variable(name, world)

        if value is None:
            unresolved_vars.append(name)
            return f"[missing var:{name}]"

        # Refuse variables-of-variables
        if REFERENCE.search(value):
            unresolved_vars.append(f"{name} (resolves to templated text)")
            return f"[var:{name} contains {{{{var:...}}}}, not expanded]"

        return value

    substituted = REFERENCE.sub(replace, text)
    return substituted, unresolved_vars


def resolve_all(text: str, world: World) -> str | None:
    """Resolve all variables in *text*, or None if any are unresolved.

    Convenience for callers that want None instead of an (text, unresolved) tuple.
    """
    result, unresolved = substitute(text, world)
    return result if not unresolved else None
