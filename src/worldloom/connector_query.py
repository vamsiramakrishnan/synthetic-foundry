"""Native connector queries compiled from the shared Worldloom predicate language.

Connector definitions own field bindings and native entity names. This module
owns syntax only. Search construction, emulation and grading therefore speak the
same :class:`worldloom.predicates.Predicate` instead of private filter DSLs.
"""

from __future__ import annotations

import re

from .connector_definition import ConnectorDefinition
from .predicates import FieldPredicate, Predicate, PredicateOp, Scalar

_SUPPORTED_LANGUAGES = frozenset(
    {"jql", "soql", "encoded_query", "cql", "odata", "drive_q", "cypher"}
)


def _native_field(definition: ConnectorDefinition, field: str) -> str:
    return definition.query_fields.get(field, field)


def _semantic_field(definition: ConnectorDefinition, field: str) -> str:
    inverse = {native.casefold(): semantic for semantic, native in definition.query_fields.items()}
    return inverse.get(field.casefold(), field)


def _quote(value: Scalar) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _comparison_token(op: PredicateOp, language: str) -> str:
    symbols = {
        PredicateOp.EQ: "=",
        PredicateOp.NE: "!=",
        PredicateOp.GT: ">",
        PredicateOp.GTE: ">=",
        PredicateOp.LT: "<",
        PredicateOp.LTE: "<=",
    }
    if language == "odata":
        return {
            PredicateOp.EQ: "eq",
            PredicateOp.NE: "ne",
            PredicateOp.GT: "gt",
            PredicateOp.GTE: "ge",
            PredicateOp.LT: "lt",
            PredicateOp.LTE: "le",
        }[op]
    return symbols[op]


def _compile_standard(field: str, item: FieldPredicate, *, language: str) -> str:
    value = item.value
    if item.op is PredicateOp.EQ:
        if value is None:
            return f"{field} is EMPTY" if language == "jql" else f"{field} = null"
        assert not isinstance(value, tuple)
        return f"{field} {_comparison_token(item.op, language)} {_quote(value)}"
    if item.op is PredicateOp.NE:
        if value is None:
            return f"{field} is not EMPTY" if language == "jql" else f"{field} != null"
        assert not isinstance(value, tuple)
        return f"{field} {_comparison_token(item.op, language)} {_quote(value)}"
    if item.op in {PredicateOp.GT, PredicateOp.GTE, PredicateOp.LT, PredicateOp.LTE}:
        assert not isinstance(value, tuple)
        return f"{field} {_comparison_token(item.op, language)} {_quote(value)}"
    if item.op is PredicateOp.IN:
        assert isinstance(value, tuple)
        return f"{field} in ({', '.join(_quote(part) for part in value)})"
    if item.op is PredicateOp.CONTAINS:
        assert not isinstance(value, tuple)
        if not isinstance(value, str):
            raise ValueError(f"contains query requires a string operand for {item.field!r}")
        if language in {"jql", "cql"}:
            return f"{field} ~ {_quote(value)}"
        if language == "soql":
            return f"{field} LIKE {_quote('%' + value + '%')}"
        if language == "odata":
            return f"contains({field},{_quote(value)})"
        if language == "drive_q":
            return f"{field} contains {_quote(value)}"
        if language == "cypher":
            return f"{field} CONTAINS {_quote(value)}"
    raise AssertionError(f"unsupported predicate operator {item.op}")


def _compile_encoded(field: str, item: FieldPredicate) -> str:
    value = item.value
    if item.op is PredicateOp.EQ:
        if value is None:
            return f"{field}ISEMPTY"
        assert not isinstance(value, tuple)
        return f"{field}={_atom(value)}"
    if item.op is PredicateOp.NE:
        if value is None:
            return f"{field}ISNOTEMPTY"
        assert not isinstance(value, tuple)
        return f"{field}!={_atom(value)}"
    if item.op in {PredicateOp.GT, PredicateOp.GTE, PredicateOp.LT, PredicateOp.LTE}:
        assert not isinstance(value, tuple)
        return f"{field}{_comparison_token(item.op, 'standard')}{_atom(value)}"
    if item.op is PredicateOp.IN:
        assert isinstance(value, tuple)
        return f"{field}IN{','.join(_atom(part) for part in value)}"
    if item.op is PredicateOp.CONTAINS:
        assert not isinstance(value, tuple)
        if not isinstance(value, str):
            raise ValueError(f"contains query requires a string operand for {item.field!r}")
        return f"{field}LIKE{value}"
    raise AssertionError(f"unsupported predicate operator {item.op}")


def _atom(value: Scalar) -> str:
    rendered = _quote(value)
    if rendered.startswith("'") and rendered.endswith("'"):
        return rendered[1:-1]
    return rendered


def compile_native(
    definition: ConnectorDefinition,
    predicate: Predicate,
    *,
    entity: str | None = None,
) -> str:
    """Compile one shared predicate into the connector's native query subset."""

    language = definition.query_language
    if language not in _SUPPORTED_LANGUAGES:
        raise ValueError(f"unsupported connector query language {language!r}")
    selected_entity = entity or predicate.entity
    if entity is not None and predicate.entity is not None and entity != predicate.entity:
        raise ValueError(
            f"predicate entity {predicate.entity!r} does not match requested entity {entity!r}"
        )

    clauses = []
    for item in predicate.where:
        field = _native_field(definition, item.field)
        clauses.append(
            _compile_encoded(field, item)
            if language == "encoded_query"
            else _compile_standard(field, item, language=language)
        )

    if language == "jql" and selected_entity is not None:
        # JQL has no FROM clause. Carry the semantic entity through issueType so
        # compile -> parse preserves the Predicate rather than dropping its kind.
        clauses.insert(0, f"issuetype = {_quote(selected_entity)}")

    body = ("^" if language == "encoded_query" else " AND ").join(clauses)
    if language == "soql":
        if selected_entity is None:
            raise ValueError("SOQL compilation requires a predicate or explicit entity")
        source = definition.query_name_for(selected_entity)
        return f"SELECT Id, Name FROM {source}" + (f" WHERE {body}" if body else "")
    if language == "cql" and selected_entity is not None:
        source = definition.query_name_for(selected_entity)
        prefix = f"type = {_quote(source)}"
        return f"{prefix} AND {body}" if body else prefix
    return body


def _split_csv(value: str) -> tuple[Scalar, ...]:
    parts = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    for char in value:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            current.append(char)
            continue
        if quote is not None:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            current.append(char)
            continue
        if char == ",":
            parts.append(_parse_atom("".join(current).strip()))
            current = []
            continue
        current.append(char)
    if current or value.strip():
        parts.append(_parse_atom("".join(current).strip()))
    return tuple(parts)


def _parse_atom(raw: str) -> Scalar:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].replace("\\'", "'").replace("\\\\", "\\")
    lowered = value.casefold()
    if lowered in {"null", "empty"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _parse_bound_atom(definition: ConnectorDefinition, field: str, raw: str) -> Scalar:
    """Parse an atom while respecting a definition's declared string domains."""

    value = raw.strip()
    options = definition.options.get(field)
    if options and value in options:
        return value
    return _parse_atom(raw)


def _split_bound_csv(
    definition: ConnectorDefinition, field: str, raw: str
) -> tuple[Scalar, ...]:
    if field in definition.options:
        return tuple(part.strip().strip("'\"") for part in raw.split(",") if part.strip())
    return _split_csv(raw)


def _infer_entity(definition: ConnectorDefinition, native: str) -> str | None:
    target = native.casefold()
    matches = [
        entity
        for entity, item in definition.entities.items()
        if (item.query_name or entity).casefold() == target
    ]
    return matches[0] if len(matches) == 1 else None


def _split_clauses(language: str, query: str) -> list[str]:
    if language == "encoded_query":
        return [part.strip() for part in query.split("^") if part.strip()]
    return [
        part.strip()
        for part in re.split(r"\s+AND\s+", query, flags=re.IGNORECASE)
        if part.strip()
    ]


def _parse_standard_clause(
    definition: ConnectorDefinition,
    language: str,
    clause: str,
) -> FieldPredicate:
    contains_function = re.fullmatch(
        r"contains\(\s*([A-Za-z_][\w.\[\]/]*)\s*,\s*(.+)\s*\)",
        clause,
        flags=re.IGNORECASE,
    )
    if contains_function:
        field = _semantic_field(definition, contains_function.group(1))
        value = _parse_atom(contains_function.group(2))
        return FieldPredicate(field=field, op=PredicateOp.CONTAINS, value=value)

    like = re.fullmatch(
        r"([A-Za-z_][\w.\[\]/]*)\s+LIKE\s+(.+)", clause, flags=re.IGNORECASE
    )
    if like:
        field = _semantic_field(definition, like.group(1))
        parsed = _parse_atom(like.group(2))
        value = parsed.strip("%") if isinstance(parsed, str) else parsed
        return FieldPredicate(field=field, op=PredicateOp.CONTAINS, value=value)

    contains = re.fullmatch(
        r"([A-Za-z_][\w.\[\]/]*)\s+(?:~|contains)\s+(.+)",
        clause,
        flags=re.IGNORECASE,
    )
    if contains:
        field = _semantic_field(definition, contains.group(1))
        return FieldPredicate(
            field=field,
            op=PredicateOp.CONTAINS,
            value=_parse_atom(contains.group(2)),
        )

    empty = re.fullmatch(
        r"([A-Za-z_][\w.\[\]/]*)\s+is\s+(not\s+)?EMPTY",
        clause,
        flags=re.IGNORECASE,
    )
    if empty:
        field = _semantic_field(definition, empty.group(1))
        return FieldPredicate(
            field=field,
            op=PredicateOp.NE if empty.group(2) else PredicateOp.EQ,
            value=None,
        )

    member = re.fullmatch(
        r"([A-Za-z_][\w.\[\]/]*)\s+in\s*\((.*)\)",
        clause,
        flags=re.IGNORECASE,
    )
    if member:
        field = _semantic_field(definition, member.group(1))
        return FieldPredicate(
            field=field,
            op=PredicateOp.IN,
            value=_split_bound_csv(definition, field, member.group(2)),
        )

    comparison = re.fullmatch(
        r"([A-Za-z_][\w.\[\]/]*)\s*(>=|<=|!=|=|>|<|eq|ne|gt|ge|lt|le)\s*(.+)",
        clause,
        flags=re.IGNORECASE,
    )
    if comparison:
        op = {
            "=": PredicateOp.EQ,
            "eq": PredicateOp.EQ,
            "!=": PredicateOp.NE,
            "ne": PredicateOp.NE,
            ">": PredicateOp.GT,
            "gt": PredicateOp.GT,
            ">=": PredicateOp.GTE,
            "ge": PredicateOp.GTE,
            "<": PredicateOp.LT,
            "lt": PredicateOp.LT,
            "<=": PredicateOp.LTE,
            "le": PredicateOp.LTE,
        }[comparison.group(2).casefold()]
        field = _semantic_field(definition, comparison.group(1))
        return FieldPredicate(
            field=field,
            op=op,
            value=_parse_bound_atom(definition, field, comparison.group(3)),
        )
    raise ValueError(f"unsupported {language} query clause {clause!r}")


def _parse_encoded_clause(
    definition: ConnectorDefinition, clause: str
) -> FieldPredicate:
    special = re.fullmatch(
        r"([A-Za-z_][\w.]*)\s*(ISNOTEMPTY|ISEMPTY|LIKE|IN)(.*)",
        clause,
        flags=re.IGNORECASE,
    )
    if special:
        field = _semantic_field(definition, special.group(1))
        op = special.group(2).upper()
        raw = special.group(3).strip()
        if op == "ISNOTEMPTY":
            return FieldPredicate(field=field, op=PredicateOp.NE, value=None)
        if op == "ISEMPTY":
            return FieldPredicate(field=field, op=PredicateOp.EQ, value=None)
        if op == "LIKE":
            return FieldPredicate(field=field, op=PredicateOp.CONTAINS, value=raw)
        return FieldPredicate(
            field=field,
            op=PredicateOp.IN,
            value=_split_bound_csv(definition, field, raw),
        )

    comparison = re.fullmatch(r"([A-Za-z_][\w.]*)\s*(>=|<=|!=|=|>|<)(.*)", clause)
    if comparison:
        op = {
            "=": PredicateOp.EQ,
            "!=": PredicateOp.NE,
            ">": PredicateOp.GT,
            ">=": PredicateOp.GTE,
            "<": PredicateOp.LT,
            "<=": PredicateOp.LTE,
        }[comparison.group(2)]
        field = _semantic_field(definition, comparison.group(1))
        return FieldPredicate(
            field=field,
            op=op,
            value=_parse_bound_atom(definition, field, comparison.group(3)),
        )
    raise ValueError(f"unsupported encoded query clause {clause!r}")


def parse_native(
    definition: ConnectorDefinition,
    query: str,
    *,
    entity: str | None = None,
) -> Predicate:
    """Parse the supported conjunctive native-query subset back to a Predicate."""

    language = definition.query_language
    if language not in _SUPPORTED_LANGUAGES:
        raise ValueError(f"unsupported connector query language {language!r}")
    body = query.strip()
    inferred = entity

    if language == "soql":
        match = re.fullmatch(
            r"SELECT\s+.+?\s+FROM\s+([A-Za-z_][\w.]*)\s*(?:WHERE\s+(.+))?",
            body,
            flags=re.IGNORECASE,
        )
        if match is None:
            raise ValueError(f"unsupported SOQL query {query!r}")
        inferred = inferred or _infer_entity(definition, match.group(1))
        body = match.group(2) or ""
    elif language == "cql":
        match = re.match(
            r"type\s*=\s*('(?:\\.|[^'])*'|\"(?:\\.|[^\"])*\"|[\w-]+)\s*(?:AND\s*)?",
            body,
            flags=re.IGNORECASE,
        )
        if match is not None:
            native_entity = _parse_atom(match.group(1))
            if isinstance(native_entity, str):
                inferred = inferred or _infer_entity(definition, native_entity)
            body = body[match.end() :]
    elif language == "jql":
        match = re.match(
            r"issuetype\s*=\s*('(?:\\.|[^'])*'|\"(?:\\.|[^\"])*\"|[\w-]+)\s*(?:AND\s*)?",
            body,
            flags=re.IGNORECASE,
        )
        if match is not None:
            native_entity = _parse_atom(match.group(1))
            if isinstance(native_entity, str):
                inferred = inferred or native_entity
            body = body[match.end() :]

    clauses = _split_clauses(language, body)
    parsed = tuple(
        _parse_encoded_clause(definition, clause)
        if language == "encoded_query"
        else _parse_standard_clause(definition, language, clause)
        for clause in clauses
    )
    return Predicate(entity=inferred, where=parsed)


__all__ = ["compile_native", "parse_native"]