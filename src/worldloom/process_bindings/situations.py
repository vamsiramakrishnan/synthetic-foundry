"""A binding plus a verb is a situation: the occasion a request arrives on.

The compiled catalogue already answers *when work happens and under what*:
each `ActivityBinding` names an activity, the unit and country that own it,
the system it is recorded in, the control that governs it, the named exception
that trips it, and the channels its evidence lands in. What it does not carry
is anyone wanting anything, which is why a question derived from a binding
alone still reads like a quiz item about a process diagram.

`situations` supplies the missing half by crossing each binding with the verbs
that suit its declared activity type. The cross is the point: the catalogue
compiles thousands of bindings and `evals.intents` declares forty verbs, so
the number of distinct occasions stops being the number of question keys
somebody typed and starts being a product of two authored tables.

An asker is deliberately *not* chosen here. Roles live on a LOB and bindings
do not know about LOBs, so seating one is `seat` below, a separate step that
takes the world's own `lob.asks_about` standing rule. Keeping them apart is
what stops this module from inventing a role that the responsibility edges
never granted.

Nothing here draws, samples, or reads a clock. `situations` is a generator
over sorted, declared data, so the same compiled catalogue yields the same
situations in the same order every time.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from ..evals.intents import Intent, applicable
from .models import ActivityBinding, CompiledCatalogue


@dataclass(frozen=True)
class Situation:
    """One occasion, one verb: everything but who is asking and how they say it."""

    occasion: str
    """The binding id. Goes on `EvaluationCase.occasion` verbatim."""
    intent: str
    """The verb's id, from `evals.intents`."""
    channel: str
    """Where the request arrives, from the binding's declared channels."""
    constraint: str
    """What bounds it: the binding's control, and its exception when the verb
    is one that only fires on the exception path."""
    activity: str
    activity_type: str
    stream: str
    owner_bu: str
    country: str
    system_of_record: str
    """The product, not the class: a request names ServiceNow, not ITSM."""
    objects: tuple[str, ...]
    """The record kinds that system holds for this activity."""
    effect: str
    """``read`` or ``write``, copied from the intent so a caller can split
    without loading the intent table again."""

    @property
    def key(self) -> str:
        """A stable identity for this situation, for dedup and for ids."""
        return f"{self.occasion}/{self.intent}/{self.channel}"


#: Verbs that only make sense when something has gone wrong. For these the
#: binding's named exception is the constraint, because "chase the item" and
#: "chase the item that tripped the price-variance check" are different
#: requests and only the second one is grounded in what the catalogue declares.
_EXCEPTION_VERBS: frozenset[str] = frozenset({
    "chase",
    "escalate",
    "explain_variance",
    "find_exception",
    "reject_with_reason",
    "triage_queue",
})


def _constraint_for(binding: ActivityBinding, intent: Intent) -> str:
    control = binding.control.strip()
    exception = binding.exception.strip()
    if intent.id in _EXCEPTION_VERBS and exception:
        return f"{control}; exception: {exception}" if control else exception
    return control


def situations_for(
    binding: ActivityBinding,
    *,
    effect: str | None = None,
    include_optional_channels: bool = False,
) -> Iterator[Situation]:
    """Every situation one binding supports, in intent then channel order.

    `include_optional_channels` widens to the channels the binding says work
    *may* land in as well as those it says it does. Off by default: an
    optional channel is a real possibility and a weaker claim, and a generated
    set should not quietly lean on the weaker one.
    """
    channels: Sequence[str] = binding.channels
    if include_optional_channels:
        channels = tuple(binding.channels) + tuple(binding.channels_optional)
    # Sorted, not declaration order: `channels` is authored per activity and
    # two bindings that list the same channels in different orders must yield
    # the same situations in the same order.
    ordered = sorted(dict.fromkeys(channels))
    if not ordered:
        return
    for intent in applicable(binding.type, effect=effect):  # type: ignore[arg-type]
        for channel in ordered:
            yield Situation(
                occasion=binding.id,
                intent=intent.id,
                channel=channel,
                constraint=_constraint_for(binding, intent),
                activity=binding.activity,
                activity_type=binding.type,
                stream=binding.stream,
                owner_bu=binding.owner_bu,
                country=binding.country,
                system_of_record=binding.sor_product,
                objects=tuple(binding.sor_objects),
                effect=intent.effect,
            )


def situations(
    compiled: CompiledCatalogue,
    *,
    effect: str | None = None,
    include_optional_channels: bool = False,
    bound_only: bool = True,
) -> Iterator[Situation]:
    """Every situation a compiled catalogue supports.

    `bound_only` keeps to the rows the compiler resolved to a real owner and a
    real system. An unbound row is a hole in the catalogue, and a question
    generated from one would name a business unit or a system the company does
    not have, which is the fabrication this whole path exists to avoid.

    Streams a generator rather than a list: the default company for one
    industry already yields tens of thousands of situations, and a caller
    almost always wants a filtered prefix.
    """
    for binding in compiled.rows:
        if bound_only and binding.binding_status != "bound":
            continue
        yield from situations_for(
            binding,
            effect=effect,
            include_optional_channels=include_optional_channels,
        )


def coverage(compiled: CompiledCatalogue, **kwargs: object) -> dict[str, int]:
    """How many situations a catalogue yields, and along which axes.

    Reported rather than asserted: a generated situation is not automatically
    a good question, so the honest thing for a manifest to carry is how many
    were available before any plausibility rule ran.
    """
    totals: dict[str, int] = {}
    intents_seen: set[str] = set()
    channels_seen: set[str] = set()
    occasions_seen: set[str] = set()
    count = 0
    for situation in situations(compiled, **kwargs):  # type: ignore[arg-type]
        count += 1
        intents_seen.add(situation.intent)
        channels_seen.add(situation.channel)
        occasions_seen.add(situation.occasion)
    totals["situations"] = count
    totals["occasions"] = len(occasions_seen)
    totals["intents"] = len(intents_seen)
    totals["channels"] = len(channels_seen)
    return totals


__all__ = ["Situation", "coverage", "situations", "situations_for"]
