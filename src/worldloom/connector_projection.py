"""How a catalogue record appears on a connector that stands in for its product.

``sor.product_records`` restates a `sor` record on the emulator the
product's line reads (ServiceNow, Salesforce, Jira, ...). Which fields that
connector's objects carry used to be an ``if connector == ...`` chain in
code, so a connector uploaded as a pack could be served but never shown a
catalogue record. A definition now declares it, as data:

    "record_projection": {
      "fields":   {"sys_id": "{key|first:32}", "short_description": "{title}"},
      "entities": {"change_request": {"type": "normal"}}
    }

``fields`` apply to every entity; ``entities`` add or override per entity,
after ``fields``, so key order is the base order then the entity's. A value is
a template string, a list of values or an object of values. A template's
``{name}`` reads the record context (every `sor` record field, plus
``title``, ``external_id``, ``key``, ``body`` and ``stamp``), optionally
through ``|`` filters:

- ``first:N``: the first N characters;
- ``upper``: upper case;
- ``hex``: read as a base-16 integer; ``mod:N``: that integer modulo N;
- ``suffix:TEXT``: TEXT appended (``{function|suffix: team}``);
- ``slug``: lower-case, runs of anything else collapsed to ``-``;
- ``address``: a mail address at the record's company domain.

The filter set is closed and a template is parsed when the definition
loads, so a pack naming an unknown filter or a malformed placeholder is
refused with the definition, not when a world is first projected.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import Field, model_validator

from .models import Model

_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


def _address(name: str, company_id: str) -> str:
    return f"{name} <{_slug(name)}@{_slug(company_id)}.example>"


#: Each filter takes the running value, its argument and the context.
_FILTERS: dict[str, Callable[[Any, str, Mapping[str, Any]], Any]] = {
    "first": lambda value, arg, ctx: str(value)[:int(arg)],
    "upper": lambda value, arg, ctx: str(value).upper(),
    "hex": lambda value, arg, ctx: int(str(value), 16),
    "mod": lambda value, arg, ctx: int(value) % int(arg),
    "suffix": lambda value, arg, ctx: f"{value}{arg}",
    "slug": lambda value, arg, ctx: _slug(str(value)),
    "address": lambda value, arg, ctx: _address(str(value), str(ctx["company_id"])),
}
_NEEDS_ARGUMENT = {"first", "mod", "suffix"}


def _parse(expression: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    name, *steps = expression.split("|")
    if not _NAME.match(name.strip()):
        raise ValueError(f"record projection placeholder {{{expression}}} must start with a field name")
    parsed: list[tuple[str, str]] = []
    for step in steps:
        filter_name, _, argument = step.partition(":")
        filter_name = filter_name.strip()
        if filter_name not in _FILTERS:
            raise ValueError(f"record projection filter {filter_name!r} is unknown; "
                             f"use one of {', '.join(sorted(_FILTERS))}")
        if filter_name in _NEEDS_ARGUMENT and not argument:
            raise ValueError(f"record projection filter {filter_name!r} needs an argument ({filter_name}:N)")
        if filter_name in {"first", "mod"}:
            try:
                int(argument)
            except ValueError:
                raise ValueError(f"record projection filter {filter_name}:{argument} needs a whole number") from None
        parsed.append((filter_name, argument))
    return name.strip(), tuple(parsed)


def _check(value: Any, where: str) -> None:
    if isinstance(value, str):
        for expression in _PLACEHOLDER.findall(value):
            _parse(expression)
    elif isinstance(value, list):
        for item in value:
            _check(item, where)
    elif isinstance(value, dict):
        for key, item in value.items():
            _check(item, f"{where}.{key}")
    else:
        raise ValueError(f"record projection {where}: a value is a template string, a list or an object")


def _render(value: Any, context: Mapping[str, Any]) -> Any:
    if isinstance(value, str):
        def fill(match: re.Match[str]) -> str:
            name, steps = _parse(match.group(1))
            if name not in context:
                raise KeyError(f"record projection reads {name!r}, which the record does not carry")
            out = context[name]
            for filter_name, argument in steps:
                out = _FILTERS[filter_name](out, argument, context)
            return str(out)

        return _PLACEHOLDER.sub(fill, value)
    if isinstance(value, list):
        return [_render(item, context) for item in value]
    return {key: _render(item, context) for key, item in value.items()}


class ConnectorRecordProjection(Model):
    """The fields a connector's objects carry when a catalogue record is restated there."""

    fields: dict[str, Any] = Field(default_factory=dict)
    entities: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _templates_parse(self) -> ConnectorRecordProjection:
        _check(self.fields, "fields")
        for entity, extra in self.entities.items():
            _check(extra, f"entities.{entity}")
        return self

    def project(self, entity: str, context: Mapping[str, Any]) -> dict[str, Any]:
        """The native fields of *entity* for one record *context*, in declared order."""
        return _render({**self.fields, **self.entities.get(entity, {})}, context)


__all__ = ["ConnectorRecordProjection"]
