"""ServiceNow encoded queries (``sysparm_query``) to the common filter tree.

Supported: conditions joined by ``^`` (AND), ``^OR`` (OR with the previous
condition, binding tighter than ``^``, as ServiceNow reads it) and ``^NQ`` (a
new query ORed with everything before it); ``ORDERBYfield`` and
``ORDERBYDESCfield``; a trailing ``^EQ``; ``^^`` for a literal caret. Operators:
``= != LIKE NOT LIKE STARTSWITH ENDSWITH IN NOT IN ISEMPTY ISNOTEMPTY ANYTHING
EMPTYSTRING > >= < <= BETWEEN`` (``a@b``, inclusive) and ``ON``/``NOTON``
(``label@start@end``). Values may be ``2026-09-01 10:00:00`` datetimes or
``javascript:gs.*`` date helpers: ``daysAgo``, ``daysAgoStart``, ``daysAgoEnd``,
``hoursAgo``, ``hoursAgoStart``, ``hoursAgoEnd``, ``minutesAgo``, ``monthsAgo``,
``monthsAgoStart``, ``monthsAgoEnd``, ``quartersAgoStart``, ``yearsAgo``,
``beginningOf``/``endOf`` ``Today``, ``Yesterday``, ``Tomorrow``, ``ThisWeek``,
``LastWeek``, ``ThisMonth``, ``LastMonth``, ``ThisQuarter``, ``ThisYear``,
``LastYear``, ``now``, ``nowDateTime`` and ``dateGenerate('2026-01-01','start')``.
Weeks start on Monday, ServiceNow's default. Comparison is case-insensitive.

ServiceNow is lenient where other vendors refuse: a condition on a field the
table does not have, an operator it does not know, or a helper it cannot run is
dropped from the query and the rest still runs (``glide.invalid_query.returns_no_rows``
is false by default). This parser reproduces that: such a condition is left
out of the tree (``a^ORjunk`` is ``a``), and a condition on an unknown field is
left out at binding.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from .ast import (
    TRUE,
    Compare,
    In,
    IsEmpty,
    Node,
    Not,
    Op,
    OrderKey,
    Query,
    TextMatch,
    Value,
    conjoin,
    disjoin,
)
from .clock import add_months, aware, parse_instant, shift, start_of

LANGUAGE = "encoded_query"

_OPERATORS = (
    "ISNOTEMPTY", "ISEMPTY", "ANYTHING", "EMPTYSTRING", "NOT IN", "NOTIN", "NOT LIKE", "NOTLIKE",
    "LIKE", "STARTSWITH", "ENDSWITH", "BETWEEN", "NOTON", "ON", "IN", ">=", "<=", "!=", "=", ">", "<",
)
_CONDITION = re.compile(
    r"^([A-Za-z0-9_.]+?)(" + "|".join(re.escape(op) for op in _OPERATORS) + r")(.*)$",
    re.DOTALL,
)
_HELPER = re.compile(r"^javascript:\s*gs\.(\w+)\(\s*(.*?)\s*\)\s*;?$", re.DOTALL)
_CARET = "\x00"


def _week_start(instant: datetime) -> datetime:
    day = start_of("day", instant)
    return day - timedelta(days=day.weekday())


def _boundary(name: str, clock: datetime) -> datetime | None:
    """``beginningOfLastMonth`` and friends."""

    match = re.fullmatch(r"(beginningOf|endOf)(Today|Yesterday|Tomorrow|ThisWeek|LastWeek|NextWeek|ThisMonth|LastMonth|NextMonth|ThisQuarter|LastQuarter|ThisYear|LastYear|NextYear)", name)
    if match is None:
        return None
    edge, period = match.groups()
    day = start_of("day", clock)
    windows: dict[str, tuple[datetime, datetime]] = {
        "Today": (day, day + timedelta(days=1)),
        "Yesterday": (day - timedelta(days=1), day),
        "Tomorrow": (day + timedelta(days=1), day + timedelta(days=2)),
    }
    week = _week_start(clock)
    windows["ThisWeek"] = (week, week + timedelta(days=7))
    windows["LastWeek"] = (week - timedelta(days=7), week)
    windows["NextWeek"] = (week + timedelta(days=7), week + timedelta(days=14))
    month = start_of("month", clock)
    windows["ThisMonth"] = (month, add_months(month, 1))
    windows["LastMonth"] = (add_months(month, -1), month)
    windows["NextMonth"] = (add_months(month, 1), add_months(month, 2))
    quarter = start_of("quarter", clock)
    windows["ThisQuarter"] = (quarter, add_months(quarter, 3))
    windows["LastQuarter"] = (add_months(quarter, -3), quarter)
    year = start_of("year", clock)
    windows["ThisYear"] = (year, add_months(year, 12))
    windows["LastYear"] = (add_months(year, -12), year)
    windows["NextYear"] = (add_months(year, 12), add_months(year, 24))
    start, end = windows[period]
    return start if edge == "beginningOf" else end - timedelta(seconds=1)


def helper(value: str, clock: datetime) -> datetime | None:
    """A ``javascript:gs.*`` date helper resolved against *clock*, or ``None``."""

    match = _HELPER.match(value.strip())
    if match is None:
        return None
    name, raw_args = match.groups()
    args = [part.strip().strip("'\"") for part in raw_args.split(",")] if raw_args else []
    if name in ("now", "nowDateTime", "nowNoTZ"):
        return clock
    boundary = _boundary(name, clock)
    if boundary is not None:
        return boundary
    if name == "dateGenerate" and args:
        day = parse_instant(args[0], clock.tzinfo)  # type: ignore[arg-type]
        if day is None:
            return None
        moment = args[1] if len(args) > 1 else "start"
        if moment == "start":
            return day
        if moment == "end":
            return day + timedelta(days=1) - timedelta(seconds=1)
        timed = parse_instant(f"{args[0]} {moment}", clock.tzinfo)  # type: ignore[arg-type]
        return timed
    relative = re.fullmatch(r"(days|hours|minutes|months|quarters|years)Ago(Start|End)?", name)
    if relative is None:
        return None
    unit, edge = relative.groups()
    try:
        count = int(args[0]) if args else 0
    except ValueError:
        return None
    letter = {"days": "d", "hours": "h", "minutes": "m", "months": "M", "years": "y"}.get(unit)
    moved = add_months(clock, -3 * count) if unit == "quarters" else shift(clock, -count, letter or "d")
    if edge is None:
        return moved
    calendar = {"days": "day", "months": "month", "quarters": "quarter", "years": "year"}.get(unit)
    if unit == "hours":
        start = moved.replace(minute=0, second=0, microsecond=0)
        return start if edge == "Start" else start + timedelta(minutes=59, seconds=59)
    if unit == "minutes":
        start = moved.replace(second=0, microsecond=0)
        return start if edge == "Start" else start + timedelta(seconds=59)
    assert calendar is not None
    start = start_of(calendar, moved)
    if edge == "Start":
        return start
    following = {"day": start + timedelta(days=1), "month": add_months(start, 1),
                 "quarter": add_months(start, 3), "year": add_months(start, 12)}[calendar]
    return following - timedelta(seconds=1)


class _Parser:
    def __init__(self, text: str, clock: datetime) -> None:
        self.text = text
        self.clock = aware(clock)
        self.order: list[OrderKey] = []

    def value(self, raw: str) -> Value | None:
        raw = raw.replace(_CARET, "^")
        if raw.startswith("javascript:"):
            return helper(raw, self.clock)
        instant = parse_instant(raw, self.clock.tzinfo) if re.match(r"^\d{4}-\d{2}-\d{2}", raw) else None  # type: ignore[arg-type]
        return instant if instant is not None else raw

    def condition(self, text: str) -> Node | None:
        """One condition; ``None`` for an ordering, a terminator, or a condition ServiceNow drops."""

        if text.startswith("ORDERBYDESC"):
            self.order.append(OrderKey(text[len("ORDERBYDESC"):], True))
            return None
        if text.startswith("ORDERBY"):
            self.order.append(OrderKey(text[len("ORDERBY"):], False))
            return None
        if text in ("EQ", ""):
            return None
        match = _CONDITION.match(text)
        if match is None:
            return None
        field, operator, raw = match.groups()
        if operator == "ISEMPTY":
            return IsEmpty(field)
        if operator == "ISNOTEMPTY":
            return Not(IsEmpty(field))
        if operator == "ANYTHING":
            return TRUE
        if operator == "EMPTYSTRING":
            return Compare(field, Op.EQ, "")
        if operator in ("LIKE", "NOT LIKE", "NOTLIKE"):
            node: Node = TextMatch(field, raw.replace(_CARET, "^"), "contains")
            return node if operator == "LIKE" else Not(node)
        if operator in ("STARTSWITH", "ENDSWITH"):
            return TextMatch(field, raw.replace(_CARET, "^"), "startswith" if operator == "STARTSWITH" else "endswith")
        if operator in ("IN", "NOT IN", "NOTIN"):
            members = tuple(part.replace(_CARET, "^").strip() for part in raw.split(",") if part.strip())
            node = In(field, members)
            return node if operator == "IN" else Not(node)
        if operator == "BETWEEN":
            bounds = raw.split("@")
            if len(bounds) != 2:
                return None
            low, high = self.value(bounds[0]), self.value(bounds[1])
            if low is None or high is None:
                return None
            return conjoin([Compare(field, Op.GE, low), Compare(field, Op.LE, high)])
        if operator in ("ON", "NOTON"):
            parts = raw.split("@")
            if len(parts) != 3:
                return None
            start, end = self.value(parts[1]), self.value(parts[2])
            if not isinstance(start, datetime) or not isinstance(end, datetime):
                return None
            node = conjoin([Compare(field, Op.GE, start), Compare(field, Op.LE, end)])
            return node if operator == "ON" else Not(node)
        value = self.value(raw)
        if value is None:
            return None
        if operator == "=" and value == "":
            return IsEmpty(field)
        op = {"=": Op.EQ, "!=": Op.NE, ">": Op.GT, ">=": Op.GE, "<": Op.LT, "<=": Op.LE}[operator]
        return Compare(field, op, value)

    def parse(self) -> Query:
        text = self.text.strip().replace("^^", _CARET)
        segments: list[Node] = []
        for segment in text.split("^NQ"):
            groups: list[list[Node]] = []
            for index, piece in enumerate(segment.split("^")):
                piece = piece.strip()
                is_or = index > 0 and piece.startswith("OR") and not piece.startswith("ORDERBY")
                condition = self.condition(piece[2:] if is_or else piece)
                if condition is None:
                    continue
                if is_or and groups:
                    groups[-1].append(condition)
                else:
                    groups.append([condition])
            if groups:
                segments.append(conjoin([disjoin(group) for group in groups]))
        where = disjoin(segments) if segments else TRUE
        return Query(language=LANGUAGE, where=where, order=tuple(self.order))


def parse(text: str, *, clock: datetime, user: str | None = None) -> Query:
    """Parse one encoded query. Never refuses: what ServiceNow drops, this drops."""

    return _Parser(text, clock).parse()


__all__ = ["LANGUAGE", "helper", "parse"]
