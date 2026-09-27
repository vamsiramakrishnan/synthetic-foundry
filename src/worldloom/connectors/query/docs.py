"""What a search tool tells the agent about its query argument.

A pilot run found most of its call errors were queries the agent could not
have known the grammar of: the tool catalog named a ``query`` parameter and
nothing else, so the agent guessed, often in the wrong vendor's syntax. Each
search tool now states the language its ``query`` is read in, a grammar
summary, two or three examples in that vendor's own syntax and the free-text
form where the real product has one (ServiceNow ``123TEXTQUERY321=``, Jira and
Confluence ``text ~``, Drive ``fullText contains``, KQL bare terms; SOQL has
none, so it says to use ``LIKE``). A tool whose language the evaluator does
not parse (GraphQL, Rovo, the system of record) says to pass a structured
``predicate`` instead, because a query string there is refused.

The words are data (``_data/connectors/_query_docs.json``); every example is
parsed and executed against its connector definition by the tests, so the
catalog never shows a query the evaluator would refuse.
"""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files
from typing import TYPE_CHECKING, Any

from .schema import tool_language

if TYPE_CHECKING:
    from ...connector_definition import ConnectorDefinition

#: The key the structured-predicate help is filed under.
PREDICATE = "predicate"


@cache
def query_docs() -> dict[str, Any]:
    """The parsed ``_query_docs.json``, read once."""

    resource = files("worldloom").joinpath("_data", "connectors", "_query_docs.json")
    loaded: dict[str, Any] = json.loads(resource.read_text(encoding="utf-8"))
    return loaded


def query_help(definition: ConnectorDefinition, tool: str) -> dict[str, Any] | None:
    """The query help for *tool*, or ``None`` when it takes neither a query nor a predicate.

    ``language`` is the evaluator's name for the vendor language (``jql``,
    ``soql``, ...) or ``predicate``; ``argument`` is the parameter the help is
    about. Examples are the tool's own when the data names some (the fields
    differ between two OData connectors), else the language's.
    """

    declared = definition.tool(tool)
    params = set(declared.params)
    if "query" not in params and "predicate" not in params:
        return None
    language = tool_language(definition, tool) if "query" in params else None
    key = language or PREDICATE
    docs = query_docs()
    entry = dict(docs["languages"][key])
    own = docs.get("tools", {}).get(f"{definition.connector}.{declared_name(definition, tool)}", {})
    examples = list(own.get("examples") or entry.get("examples") or ())
    return {
        "language": key,
        "argument": "query" if language is not None else "predicate",
        "name": str(entry["name"]),
        "grammar": str(entry["grammar"]),
        "free_text": str(entry["free_text"]),
        "examples": examples,
        "fields": list(_fields(definition, language)),
    }


def _fields(definition: ConnectorDefinition, language: str | None) -> tuple[str, ...]:
    """The field names this connector's query reads, as the agent must spell them.

    In a vendor language that is the vendor's name (the definition's
    ``query_fields`` values, then the language's own vendor names); in a
    predicate it is the connector's semantic name (the ``query_fields`` keys).
    """

    if language is None:
        return tuple(sorted(definition.query_fields))
    from .errors import language_config

    vendor = [str(value) for value in definition.query_fields.values()]
    vendor.extend(str(name) for name in language_config(language).get("fields", {}))
    return tuple(sorted(dict.fromkeys(vendor), key=str.casefold))


def declared_name(definition: ConnectorDefinition, tool: str) -> str:
    """The tool's canonical name (an alias resolves to the tool it names)."""

    try:
        return str(definition.canonical_tool(tool))
    except KeyError:
        return tool


def describe(help: dict[str, Any] | None) -> str:
    """The help as one paragraph, for a tool description (MCP ``tools/list``)."""

    if help is None:
        return ""
    examples = "; ".join(f"`{example}`" for example in help["examples"])
    return (f" `{help['argument']}` is {help['name']}: {help['grammar']} Free text: {help['free_text']}"
            f" Examples: {examples}.")


__all__ = ["PREDICATE", "declared_name", "describe", "query_docs", "query_help"]
