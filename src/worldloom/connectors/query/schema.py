"""Which record keys a vendor field name means, derived from connector definitions.

A ``QueryTarget`` is everything evaluation needs to know about the thing being
queried: the vendor's field names mapped to record keys, the fields free text
searches, the defaults a vendor assumes for an absent value (Drive's
``trashed = false``), what an unknown field does (refuse, drop, or search as
text), and the type name the vendor's error messages print.

It is plain data, so an out-of-process provider can build one directly. The
built-in emulator builds one from a ``ConnectorDefinition`` with
``target_for``, in this order of authority: the definition's own
``query_fields`` and field manifests (what the connector says it is), then
the language's vendor names in ``_data/connectors/_query.json``, then any key
the records themselves carry, matched case-insensitively.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, tzinfo
from typing import Any, Literal

from ...connector_definition import ConnectorDefinition
from .errors import language_config, query_config, query_error

UnknownField = Literal["error", "ignore", "text"]

#: The language each ``query_language`` name (and its familiar alias) parses as.
LANGUAGE_ALIASES = {
    "jql": "jql",
    "jira": "jql",
    "soql": "soql",
    "salesforce": "soql",
    "encoded_query": "encoded_query",
    "servicenow": "encoded_query",
    "odata": "odata",
    "graph": "odata",
    "cql": "cql",
    "confluence": "cql",
    "kql": "kql",
    "drive_q": "drive_q",
    "drive": "drive_q",
    "slack_search": "slack_search",
    "slack": "slack_search",
}


def canonical_language(name: str) -> str | None:
    return LANGUAGE_ALIASES.get(name.casefold())


@dataclass(frozen=True)
class QueryTarget:
    """What one query runs against. Keys of ``fields`` and ``defaults`` are case-folded."""

    language: str
    entity: str
    fields: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    text_fields: tuple[str, ...] = ()
    defaults: Mapping[str, Any] = field(default_factory=dict)
    unknown_field: UnknownField = "error"
    record_keys: Mapping[str, str] = field(default_factory=dict)
    """Case-folded record key to the key as the records spell it."""
    timezone: tzinfo = UTC
    """The zone a stored value without an offset is read in."""

    def resolve(self, name: str) -> tuple[str, ...] | None:
        """The record keys *name* may be stored under, first match wins, or ``None``."""

        folded = name.casefold()
        mapped = self.fields.get(folded)
        if mapped:
            return mapped
        if folded in self.record_keys:
            return (self.record_keys[folded],)
        for separator in (".", "/"):
            if separator in name:
                head, _, rest = name.partition(separator)
                head_keys = self.resolve(head)
                if head_keys is not None:
                    return tuple(f"{key}.{rest.replace('/', '.')}" for key in head_keys)
        return None

    def default(self, name: str) -> Any:
        return self.defaults.get(name.casefold())


def _merge(table: dict[str, list[str]], name: str, keys: Iterable[str]) -> None:
    slot = table.setdefault(name.casefold(), [])
    for key in keys:
        if key and key not in slot:
            slot.append(key)


def record_keys(records: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """Every top-level key the records carry, case-folded, first spelling kept."""

    keys: dict[str, str] = {}
    for record in records:
        for key in record:
            if isinstance(key, str):
                keys.setdefault(key.casefold(), key)
    return keys


def tool_language(definition: ConnectorDefinition, tool: str) -> str | None:
    """The language *tool*'s ``query`` argument is written in, or ``None`` when unsupported.

    Most tools speak their connector's ``query_language``. The data file names
    the exceptions: SharePoint's and OneDrive's search endpoints take KQL
    while their list endpoints take OData.
    """

    overrides: Mapping[str, str] = query_config().get("tool_languages", {})
    stated = overrides.get(f"{definition.connector}.{tool}", definition.query_language)
    return canonical_language(stated)


def entity_for_source(definition: ConnectorDefinition, source: str, *, language: str, query: str = "", at: int = 0) -> str:
    """The definition entity a query's own ``FROM`` names, or the vendor's refusal."""

    folded = source.casefold()
    for name, entity in definition.entities.items():
        if (entity.query_name or name).casefold() == folded or name.casefold() == folded:
            return name
    raise query_error(language, "unknown_type", entity=source, query=query, column=at + 1)


def type_name(definition: ConnectorDefinition, language: str, entity: str | None) -> str:
    """The type a vendor's error message prints for *entity*."""

    native = entity or definition.connector
    if entity is not None:
        try:
            native = definition.query_name_for(entity)
        except KeyError:
            native = entity
    template = language_config(language).get("type_name")
    return str(template).format(name=native) if template else native


def target_for(
    definition: ConnectorDefinition,
    *,
    language: str | None = None,
    entity: str | None = None,
    records: Iterable[Mapping[str, Any]] = (),
) -> QueryTarget:
    """The ``QueryTarget`` of *definition*'s *entity* (every entity when ``None``)."""

    resolved = canonical_language(language or definition.query_language)
    if resolved is None:
        raise ValueError(f"unsupported query language {language or definition.query_language!r}")
    config = language_config(resolved)
    table: dict[str, list[str]] = {}
    for semantic, native in sorted(definition.query_fields.items()):
        _merge(table, native, (semantic, native))
    for canonical, payload in sorted(definition.custom_fields.items()):
        _merge(table, payload, (canonical, payload))
    members: tuple[str, ...]
    if entity is None:
        members = tuple(definition.field_manifests)
    else:
        try:
            members = definition.entity_members(entity)
        except KeyError:
            members = ()
    for member in members:
        for manifest_field in definition.field_manifests.get(member, ()):
            names = (manifest_field.id, manifest_field.name, manifest_field.query_name,
                     manifest_field.payload_name, *manifest_field.aliases)
            for name in names:
                if name:
                    _merge(table, name, (manifest_field.canonical, manifest_field.id))
    for name, keys in config.get("fields", {}).items():
        _merge(table, name, keys)
    text_fields = tuple(dict.fromkeys([*config.get("text_fields", ()), *query_config().get("text_fields", ())]))
    try:
        zone = datetime.fromisoformat(definition.clock).tzinfo or UTC
    except ValueError:
        zone = UTC
    return QueryTarget(
        language=resolved,
        entity=type_name(definition, resolved, entity),
        fields={name: tuple(keys) for name, keys in sorted(table.items())},
        text_fields=text_fields,
        defaults={str(name).casefold(): value for name, value in config.get("defaults", {}).items()},
        unknown_field=config.get("unknown_field", "error"),
        record_keys=record_keys(records),
        timezone=zone,
    )


__all__ = [
    "LANGUAGE_ALIASES",
    "QueryTarget",
    "UnknownField",
    "canonical_language",
    "entity_for_source",
    "record_keys",
    "target_for",
    "tool_language",
    "type_name",
]
