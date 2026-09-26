"""Calendar arithmetic against the evaluation clock.

Every relative date a vendor language can state resolves here, against an
explicit instant: the corpus's as-of time, handed in by the caller. Nothing in
this module reads the wall clock, so ``LAST_N_DAYS:7`` means the same seven
days on every machine and every run.

Weeks start on Sunday, the default of a US-locale Jira, Confluence and
Salesforce org. Month and year arithmetic clamps the day (31 January plus one
month is 28 or 29 February), as each vendor does.
"""

from __future__ import annotations

import calendar
import re
from datetime import UTC, date, datetime, time, timedelta, tzinfo

_ISO = re.compile(
    r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})"
    r"(?:[T ](\d{1,2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6})\d*)?)?)?"
    r"\s*(Z|[+-]\d{2}:?\d{2})?$"
)

_COMPOUND_SHIFT = re.compile(r"^\s*([+-]?)((?:\s*\d+\s*[yMwdhm])+)\s*$")


def aware(clock: datetime) -> datetime:
    """The clock with a timezone; a naive clock is read as UTC."""

    return clock if clock.tzinfo is not None else clock.replace(tzinfo=UTC)


def parse_instant(text: str, tz: tzinfo) -> datetime | None:
    """An ISO-like date or datetime as an aware instant, or ``None``.

    Accepts ``2026-09-01``, ``2026/09/01``, ``2026-09-01 10:00``,
    ``2026-09-01T10:00:00Z`` and ``+08:00`` offsets. A value without an offset
    is read in *tz*, the clock's zone, which is how every vendor reads a
    date typed without one (in the user's, here the corpus's, timezone).
    """

    match = _ISO.match(text.strip())
    if match is None:
        return None
    year, month, day, hour, minute, second, fraction, offset = match.groups()
    try:
        value = datetime(
            int(year), int(month), int(day),
            int(hour or 0), int(minute or 0), int(second or 0),
            int((fraction or "0").ljust(6, "0")),
        )
    except ValueError:
        return None
    if offset is None:
        return value.replace(tzinfo=tz)
    if offset == "Z":
        return value.replace(tzinfo=UTC)
    return datetime.fromisoformat(value.isoformat() + offset[:3] + ":" + offset[-2:])


def as_instant(value: object, tz: tzinfo) -> datetime | None:
    """A record value as an instant, when it is one."""

    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=tz)
    if isinstance(value, date):
        return datetime.combine(value, time(), tzinfo=tz)
    if isinstance(value, str):
        return parse_instant(value, tz)
    return None


def add_months(instant: datetime, months: int) -> datetime:
    total = instant.year * 12 + (instant.month - 1) + months
    year, month = divmod(total, 12)
    day = min(instant.day, calendar.monthrange(year, month + 1)[1])
    return instant.replace(year=year, month=month + 1, day=day)


def shift(instant: datetime, amount: int, unit: str) -> datetime:
    """*instant* moved by *amount* of *unit* (``y M w d h m``, JQL's units)."""

    if unit == "y":
        return add_months(instant, 12 * amount)
    if unit == "M":
        return add_months(instant, amount)
    if unit == "w":
        return instant + timedelta(weeks=amount)
    if unit == "d":
        return instant + timedelta(days=amount)
    if unit == "h":
        return instant + timedelta(hours=amount)
    if unit == "m":
        return instant + timedelta(minutes=amount)
    raise ValueError(f"unknown time unit {unit!r}")


def parse_shift(text: str) -> list[tuple[int, str]] | None:
    """``-7d``, ``4w``, ``-1w 2d`` as ``[(amount, unit), ...]``, or ``None``."""

    match = _COMPOUND_SHIFT.match(text)
    if match is None:
        return None
    sign = -1 if match.group(1) == "-" else 1
    return [(sign * int(amount), unit) for amount, unit in re.findall(r"(\d+)\s*([yMwdhm])", match.group(2))]


def apply_shift(instant: datetime, text: str) -> datetime | None:
    parts = parse_shift(text)
    if parts is None:
        return None
    for amount, unit in parts:
        instant = shift(instant, amount, unit)
    return instant


def start_of(unit: str, instant: datetime) -> datetime:
    """The start of the day, week (Sunday), month, quarter or year holding *instant*."""

    day = instant.replace(hour=0, minute=0, second=0, microsecond=0)
    if unit == "day":
        return day
    if unit == "week":
        return day - timedelta(days=(day.weekday() + 1) % 7)
    if unit == "month":
        return day.replace(day=1)
    if unit == "quarter":
        return day.replace(month=3 * ((day.month - 1) // 3) + 1, day=1)
    if unit == "year":
        return day.replace(month=1, day=1)
    raise ValueError(f"unknown calendar unit {unit!r}")


def next_start(unit: str, instant: datetime) -> datetime:
    """The start of the *unit* after the one holding *instant*."""

    start = start_of(unit, instant)
    if unit == "day":
        return start + timedelta(days=1)
    if unit == "week":
        return start + timedelta(days=7)
    if unit == "month":
        return add_months(start, 1)
    if unit == "quarter":
        return add_months(start, 3)
    return add_months(start, 12)


def end_of(unit: str, instant: datetime) -> datetime:
    """The last representable instant of the *unit* holding *instant*."""

    return next_start(unit, instant) - timedelta(microseconds=1)


def window(unit: str, instant: datetime, count: int = 0) -> tuple[datetime, datetime]:
    """The half-open *unit* window *count* units away from the one holding *instant*."""

    start = start_of(unit, instant)
    step = {"day": (1, "d"), "week": (1, "w"), "month": (1, "M"), "quarter": (3, "M"), "year": (1, "y")}[unit]
    begin = shift(start, step[0] * count, step[1])
    return begin, shift(begin, step[0], step[1])


__all__ = [
    "add_months",
    "apply_shift",
    "as_instant",
    "aware",
    "end_of",
    "next_start",
    "parse_instant",
    "parse_shift",
    "shift",
    "start_of",
    "window",
]
