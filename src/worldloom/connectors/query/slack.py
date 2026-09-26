"""Slack search modifiers to the common filter tree.

Supported: free-text terms (all must match), ``"quoted phrases"``, ``word*``
prefixes, ``-term`` exclusions; ``in:#channel`` / ``in:channel`` /
``in:<#C123|name>``; ``from:@user`` / ``from:<@U123>`` / ``from:me``;
``before:``, ``after:``, ``on:`` and ``during:`` with ``YYYY-MM-DD``,
``YYYY-MM``, ``YYYY``, ``today`` or ``yesterday`` (``after:`` and ``before:``
exclude the named day, as Slack's do); ``has:x`` and ``is:x``. Repeated ``in:``
or ``from:`` modifiers are alternatives. Any other ``name:value`` is searched
as text, as Slack does. Results rank by relevance when the query has text and
newest first when it has none.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from .ast import (
    ELEMENT,
    AnyOf,
    Compare,
    Node,
    Not,
    Op,
    OrderKey,
    Query,
    TextMatch,
    TimeWindow,
    conjoin,
    disjoin,
)
from .clock import add_months, aware, parse_instant, start_of

LANGUAGE = "slack_search"

_TOKEN = re.compile(r'(-?)(?:([A-Za-z_]+):)?("[^"]*"?|\S+)')
_TIME_FIELD = "timestamp"


def _day_span(value: str, clock: datetime) -> tuple[datetime, datetime] | None:
    folded = value.casefold()
    today = start_of("day", clock)
    if folded == "today":
        return today, today + timedelta(days=1)
    if folded == "yesterday":
        return today - timedelta(days=1), today
    if re.fullmatch(r"\d{4}", value):
        start = today.replace(year=int(value), month=1, day=1)
        return start, add_months(start, 12)
    if re.fullmatch(r"\d{4}-\d{1,2}", value):
        year, month = value.split("-")
        start = today.replace(year=int(year), month=int(month), day=1)
        return start, add_months(start, 1)
    day = parse_instant(value, clock.tzinfo)  # type: ignore[arg-type]
    if day is None or len(value) > 10:
        return None
    return day, day + timedelta(days=1)


def _name(value: str) -> str:
    link = re.fullmatch(r"<[#@]([A-Za-z0-9]+)(?:\|([^>]*))?>", value)
    if link:
        return link.group(2) or link.group(1)
    return value.lstrip("#@")


def parse(text: str, *, clock: datetime, user: str | None = None) -> Query:
    """Parse one Slack search string. Slack refuses nothing: this does not either."""

    clock = aware(clock)
    alternatives: dict[str, list[Node]] = {"in": [], "from": []}
    conditions: list[Node] = []
    has_text = False
    for match in _TOKEN.finditer(text):
        negated, modifier, raw = match.group(1) == "-", match.group(2), match.group(3)
        at = match.start()
        node: Node | None = None
        folded = (modifier or "").casefold()
        if folded in ("in", "from"):
            value = _name(raw)
            if folded == "from" and value.casefold() == "me" and user is not None:
                value = user
            node = Compare(folded, Op.EQ, value, at=at)
            if not negated:
                alternatives[folded].append(node)
                continue
        elif folded in ("before", "after", "on", "during"):
            span = _day_span(raw.strip('"'), clock)
            if span is not None:
                start, end = span
                bounds = {"before": (None, start), "after": (end, None)}.get(folded, (start, end))
                node = TimeWindow(_TIME_FIELD, bounds[0], bounds[1], at=at)
        elif folded in ("has", "is"):
            node = AnyOf(folded, Compare(ELEMENT, Op.EQ, raw), at=at)
        if node is None:
            body = (f"{modifier}:" if modifier else "") + raw
            phrase = body.startswith('"')
            body = body.strip('"')
            if not body:
                continue
            node = TextMatch(None, body, "phrase" if phrase else "terms", at=at, raw=match.group(0))
            has_text = has_text or not negated
        conditions.append(Not(node) if negated else node)
    for name in ("from", "in"):
        if alternatives[name]:
            conditions.insert(0, disjoin(alternatives[name]))
    order = () if has_text else (OrderKey(_TIME_FIELD, True),)
    return Query(language=LANGUAGE, where=conjoin(conditions), order=order)


__all__ = ["LANGUAGE", "parse"]
