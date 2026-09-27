"""Vendor-shaped query errors, with their text kept in data.

Every refusal a vendor gives a malformed or out-of-schema query has a message
and a response body an agent reads and reacts to. An agent that has learned to
fix ``Field 'foo' does not exist or you do not have permission to view it.``
should meet exactly that sentence, so the templates live in
``_data/connectors/_query.json`` beside the connector definitions, not in code.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from importlib.resources import files
from typing import Any


class QueryError(ValueError):
    """A query the vendor would refuse, carrying the vendor's own answer.

    ``status`` is the HTTP status, ``message`` the human-readable text, and
    ``body`` the response body the vendor sends (``errorMessages`` for Jira, a
    list of ``{message, errorCode}`` for Salesforce, and so on).
    """

    def __init__(self, language: str, kind: str, status: int, message: str, body: Any) -> None:
        super().__init__(message)
        self.language = language
        self.kind = kind
        self.status = status
        self.message = message
        self.body = body


@lru_cache(maxsize=1)
def query_config() -> Mapping[str, Any]:
    """The parsed ``_query.json``, read once."""

    resource = files("worldloom").joinpath("_data", "connectors", "_query.json")
    loaded: Mapping[str, Any] = json.loads(resource.read_text(encoding="utf-8"))
    return loaded


def language_config(language: str) -> Mapping[str, Any]:
    languages: Mapping[str, Any] = query_config()["languages"]
    try:
        config: Mapping[str, Any] = languages[language]
    except KeyError:
        raise ValueError(f"unsupported query language {language!r}") from None
    return config


class _Blank(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return ""


def _fill(template: Any, values: Mapping[str, Any]) -> Any:
    if isinstance(template, str):
        return template.format_map(_Blank(values))
    if isinstance(template, list):
        return [_fill(item, values) for item in template]
    if isinstance(template, dict):
        return {key: _fill(value, values) for key, value in template.items()}
    return template


def query_error(language: str, kind: str, **values: Any) -> QueryError:
    """The vendor's refusal of *kind* (``parse``, ``unknown_field``, ...).

    A language that states no template for *kind* answers with its ``parse``
    template, which every language states: the vendor does refuse the query,
    it just does not say more than that it could not read it.
    """

    errors: Mapping[str, Any] = language_config(language)["errors"]
    template = errors.get(kind) or errors["parse"]
    # A caret under the offending column, the way Salesforce prints one.
    values.setdefault("context", values.get("query", ""))
    column = values.get("column")
    values.setdefault("marker", " " * (int(column) - 1) + "^" if isinstance(column, int) and column > 0 else "^")
    message = _fill(template["message"], values)
    body = _fill(template["body"], {**values, "message": message})
    return QueryError(language, kind, int(template["status"]), message, body)


__all__ = ["QueryError", "language_config", "query_config", "query_error"]
