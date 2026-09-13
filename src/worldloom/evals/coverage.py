"""Does this set span the work, or only the wording?

The diversity measurement this repository already has asks whether two
questions are worded differently. That was the right question while phrasing
was the only lever, and it is the wrong one now: a set can be maximally
diverse in tokens and still ask about one function, at one moment, through one
channel, in one verb.

So the coverage question changes shape. Against what a set *could* have said,
how much did it say? The denominators are all authored data and therefore
countable in advance: forty verbs in the intent table, the activity types a
catalogue binds, the channels its bindings declare, the roles its LOBs seat.
That is what makes this a coverage report rather than a summary, and it is why
every ratio here names its denominator.

Two things are reported and never asserted. **Situations available** is what
the cross of bindings and verbs offers before any rule runs, and **situations
used** is what survived into the set; the gap between them is the plausibility
filter doing its job, and a manifest that hid it would be claiming the filter
was free. And nothing here judges whether a request reads like a person wrote
it. That is the reader check the design puts at the end, a sampled judgement
by a model on the role, the occasion and the request, and it belongs outside
this module because it is the one measurement that cannot be computed.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any, Protocol

from pydantic import Field

from ..models import EvaluationCase, Model
from .intents import ACTIVITY_TYPES, intents


class Requested(Protocol):
    """Anything carrying the request tuple: a corpus case, or an `industry.Request`.

    The report reads the tuple and nothing else, so it measures a derived
    programme before any case enters a world with the same code that measures
    the world afterwards. One measurement, two carriers.
    """

    id: str
    asker: str | None
    occasion: str | None
    intent: str | None
    channel: str | None

    @property
    def has_request(self) -> bool: ...


class CoverageReport(Model):
    """What a set of cases spans, against what it could have spanned."""

    cases: int
    requests: int
    """Cases carrying a request tuple. The rest are questions, and every ratio
    below is against this number, not `cases`."""

    intents_used: int
    intents_available: int
    intent_counts: dict[str, int] = Field(default_factory=dict)

    askers_used: int
    asker_counts: dict[str, int] = Field(default_factory=dict)

    occasions_used: int
    situations_used: int = 0
    """Distinct (occasion, intent, channel) triples the set reached.

    Counted separately from `occasions_used` because `situations_available`
    counts triples too, and dividing occasions by triples understates
    utilisation by as much as the number of verbs per occasion."""
    channels_used: int
    channel_counts: dict[str, int] = Field(default_factory=dict)

    write_share: float
    """Share of requests that change state. A set of only reads is a
    retrieval benchmark wearing a request's clothes."""
    underspecified_share: float
    """Share leaving at least one request slot unstated."""

    situations_available: int | None = None
    """What the catalogue offered, when one was supplied."""

    @property
    def intent_coverage(self) -> float:
        return self.intents_used / self.intents_available if self.intents_available else 0.0

    @property
    def used_share(self) -> float:
        """Situations used over situations available, when both are known.

        Both sides are (occasion, intent, channel) triples. An earlier draft
        put occasions over triples, which reported a tenth of the true share
        wherever an occasion carried ten verbs.
        """
        if not self.situations_available:
            return 0.0
        return self.situations_used / self.situations_available

    def gaps(self) -> list[str]:
        """What this set does not say, as sentences.

        The useful half of a coverage report: a number nobody acts on is a
        number that did not need computing.
        """
        out: list[str] = []
        table = intents()
        unused = sorted(set(table) - set(self.intent_counts))
        if unused:
            shown = ", ".join(unused[:8])
            more = f" and {len(unused) - 8} more" if len(unused) > 8 else ""
            out.append(f"{len(unused)} verbs are never asked: {shown}{more}")
        if self.requests and self.write_share == 0.0:
            out.append("no request changes state; this set only reads")
        if self.requests and not self.askers_used:
            out.append("no request names an asker")
        if self.requests and self.underspecified_share == 0.0:
            out.append(
                "every request is fully specified, so none of them tests"
                " whether the agent asks"
            )
        if self.cases and not self.requests:
            out.append("no case carries a request; this set is questions only")
        return out


def report(
    cases: Iterable[Requested], *, situations_available: int | None = None
) -> CoverageReport:
    """Measure what *cases* spans.

    `situations_available` is the count a catalogue offered, from
    `process_bindings.coverage`, so the report can state what share of the
    available work the set actually reached.
    """
    materialised: Sequence[Requested] = list(cases)
    requests = [case for case in materialised if case.has_request]

    intent_counts = Counter(c.intent for c in requests if c.intent)
    asker_counts = Counter(c.asker for c in requests if c.asker)
    channel_counts = Counter(c.channel for c in requests if c.channel)
    occasions = {c.occasion for c in requests if c.occasion}
    # The same triple `process_bindings.situations` yields, so the numerator
    # and the denominator of `used_share` count the same thing.
    situation_keys = {
        (c.occasion, c.intent, c.channel)
        for c in requests
        if c.occasion and c.intent and c.channel
    }

    table = intents()
    writes = sum(
        1
        for c in requests
        if c.intent and (i := table.get(c.intent)) is not None and i.effect == "write"
    )
    underspecified = sum(
        1
        for c in requests
        if any(getattr(c, name) is None for name in EvaluationCase.REQUEST_FIELDS)
    )
    total = len(requests)

    return CoverageReport(
        cases=len(materialised),
        requests=total,
        intents_used=len(intent_counts),
        intents_available=len(table),
        intent_counts=dict(sorted(intent_counts.items())),
        askers_used=len(asker_counts),
        asker_counts=dict(sorted(asker_counts.items())),
        occasions_used=len(occasions),
        situations_used=len(situation_keys),
        channels_used=len(channel_counts),
        channel_counts=dict(sorted(channel_counts.items())),
        write_share=writes / total if total else 0.0,
        underspecified_share=underspecified / total if total else 0.0,
        situations_available=situations_available,
    )


def available(compiled: Any) -> dict[str, int]:
    """The denominators a compiled catalogue offers, before any set exists.

    Thin by design: it defers to `process_bindings.coverage` so the number a
    report compares against is the same number the generator was offered, and
    adds the activity types the intent table can reach at all.
    """
    from ..process_bindings import coverage as binding_coverage

    counts = dict(binding_coverage(compiled))
    counts["activity_types"] = len(ACTIVITY_TYPES)
    counts["intents_declared"] = len(intents())
    return counts


__all__ = ["CoverageReport", "Requested", "available", "report"]
