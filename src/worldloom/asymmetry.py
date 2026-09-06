"""Questions only the knowledge ledger can pose.

Every other evaluation family in this repository asks what the corpus *says*.
These ask **who was in a position to say it, and when** — the question class the
canonical fact ledger structurally cannot support, because a fact carries one
``valid_from`` and knowledge carries one per person.

    The controller had the confirmed root cause at 13:27.
    The platform lead had it at 17:27.
    Which of them could have acted on it during the afternoon?

The answer is not in any document. It is in ``observations.jsonl``, which is
what makes these cases worth generating and what makes that file load-bearing
rather than an appendix. The three families below are the three shapes that
ledger admits:

**first-to-know** — one fact, several observers, one of them earliest.
**the window** — who already held a fact at the moment the last person got it.
**the channel** — *how* somebody came by it, and therefore from whom.

Two rules keep them honest, and both are checked by ``validate`` rather than
trusted here. A case may only cite a fact some document carries, or the question
is unanswerable from the corpus and the harness is right to refuse it. And a
case's ``expected_answer`` is derived from the ledger, never composed: the point
of a benchmark whose answers are computed is that nobody can quietly write one
the corpus does not support.

**This module is a seam, not a wiring point.** ``worldloom.episodes`` and
``generators/evaluation.py`` belong to other work in flight; both can reach this
without either of us editing the other's file. One call, after the episode's
events, facts and artifact intents are in the world:

    from worldloom.conversation import derive
    from worldloom.asymmetry import cases as asymmetry_cases

    conversation = derive(world, minter=minter, roles=roles)
    world = world.extend(
        observations=conversation.observations, messages=conversation.messages
    )
    extra = asymmetry_cases(
        minter,
        world=world,
        observations=conversation.observations,
        messages=conversation.messages,
        period=period,
    )

``cases`` returns ``()`` for a world with no observations, so a caller that
always calls it costs an empty tuple on every corpus built without conversations.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, NamedTuple

from .ids import Minter
from .models import EvaluationCase, EvaluationType

if TYPE_CHECKING:  # pragma: no cover
    from .actors.models import ActorMessage, Observation
    from .models import CanonicalFact
    from .world import World


#: How many facts the asymmetry families are generated for.
#:
#: A cap rather than every candidate: a close mints hundreds of figures that all
#: reach the same four people through the same message at the same second, and
#: three hundred copies of one question shaped differently is padding, not
#: difficulty. The candidates are ranked by how far apart their observers are,
#: so the cap keeps the sharpest ones.
DEFAULT_LIMIT = 3


class _Holder(NamedTuple):
    """One person's earliest hold on one fact."""

    learned_at: datetime
    observer_id: str
    source_type: str
    source_id: str | None


def _carried(world: World) -> dict[str, list[str]]:
    """Fact id to the artifacts that carry it — planned or rendered.

    Both, because a case may be generated at step 1 when nothing is compiled
    yet, and ``validate``'s ``unreachable_answer`` accepts either for the same
    reason: the plan is what will carry the fact into a document.
    """
    out: dict[str, list[str]] = {}
    for intent in world.artifact_intents:
        for fact_id in intent.required_fact_ids:
            out.setdefault(fact_id, []).append(intent.id)
    for artifact in world.artifacts:
        for fact_id in artifact.supporting_fact_ids:
            out.setdefault(fact_id, []).append(artifact.id)
    return {fact_id: sorted(set(ids)) for fact_id, ids in out.items()}


def _holders(observations: tuple[Observation, ...]) -> dict[str, list[_Holder]]:
    """Fact id to who held it and from when, earliest first.

    One entry per person: a second observation of the same fact through a slower
    channel is not a second person knowing it, and counting it would make an
    ordinary re-derivation look like an asymmetry.
    """
    earliest: dict[tuple[str, str], _Holder] = {}
    for record in observations:
        key = (record.fact_id, record.observer_id)
        held = earliest.get(key)
        if held is None or record.learned_at < held.learned_at:
            earliest[key] = _Holder(
                record.learned_at, record.observer_id, record.source_type, record.source_id
            )
    out: dict[str, list[_Holder]] = {}
    for (fact_id, _), holder in earliest.items():
        out.setdefault(fact_id, []).append(holder)
    for holders in out.values():
        # Sorted on the observer id as well as the moment, so two people who
        # learned something in the same second are ordered by something written
        # down rather than by insertion.
        holders.sort(key=lambda h: (h.learned_at, h.observer_id))
    return out


def _gap(delta: timedelta) -> str:
    """A duration as an English phrase. Whole minutes; nothing here is finer."""
    minutes = int(delta.total_seconds() // 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts = [
        f"{value} {unit}{'' if value == 1 else 's'}"
        for value, unit in ((days, "day"), (hours, "hour"), (minutes, "minute"))
        if value
    ]
    return ", ".join(parts) if parts else "under a minute"


def _subject(fact: CanonicalFact, names: dict[str, str]) -> str:
    """The fact, named the way a question can refer to it without answering it.

    Deliberately the kind and its subject rather than the value: these families
    ask *when somebody knew*, and a question that spells the figure out is a
    lookup wearing a temporal question's clothes.
    """
    return f"{fact.kind} for {names.get(fact.subject, fact.subject)}"


def _who(world: World, person_id: str) -> str:
    person = world.people.get(person_id)
    return f"{person.name} ({person.title})" if person is not None else person_id


def cases(
    minter: Minter,
    *,
    world: World,
    observations: tuple[Observation, ...],
    messages: tuple[ActorMessage, ...] = (),
    period: str,
    limit: int = DEFAULT_LIMIT,
    eligible: frozenset[str] | None = None,
) -> tuple[EvaluationCase, ...]:
    """The information-asymmetry cases this episode's knowledge ledger supports.

    Empty when there is no ledger, when nothing it records is carried by a
    document, or when every observer of every carried fact learned it at the same
    moment — which is a world with no asymmetry in it, and generating a question
    about one anyway is how a benchmark comes to have answers the corpus does not
    hold.

    ``observations`` should be the *whole* ledger: an answer is a set of people
    and it is wrong if half of them are missing. ``eligible`` narrows which facts
    may be *asked about*, which is the separate question a multi-period corpus
    needs — pass the facts this period newly put in front of somebody and the
    second close asks about the second close instead of repeating the first.
    """
    if not observations:
        return ()

    carried = _carried(world)
    holders = _holders(observations)
    facts = {fact.id: fact for fact in world.facts}
    names = world.entity_names()
    by_message = {message.id: message for message in messages}

    candidates = [
        (fact_id, held)
        for fact_id, held in holders.items()
        if fact_id in carried
        and fact_id in facts
        and (eligible is None or fact_id in eligible)
        and len(held) >= 2
        and held[-1].learned_at > held[0].learned_at
        # Every evaluation cut-off must sit inside the expected fact's own
        # validity window.  A superseded policy can still be learned later as
        # history, but asking who knew it then while grading against it as the
        # current answer violates the corpus-wide temporal contract.
        and facts[fact_id].holds_at(held[0].learned_at)
        and facts[fact_id].holds_at(held[-1].learned_at)
    ]
    # Widest spread first, then most observers, then the id — so the selection
    # is a property of the world rather than of dictionary order, and a rebuild
    # asks the same three questions.
    candidates.sort(
        key=lambda row: (
            -(row[1][-1].learned_at - row[1][0].learned_at).total_seconds(),
            -len(row[1]),
            row[0],
        )
    )

    def told_by(held: list[_Holder]) -> _Holder | None:
        """The observer who was *told*, if any. Only a message has an informant."""
        return next(
            (
                holder
                for holder in held
                if holder.source_type == "message" and holder.source_id in by_message
            ),
            None,
        )

    selected = candidates[:limit]
    # A family that never fires is a family nobody has proven. Ranking on spread
    # alone puts the widest-spread facts first, and those are the ones everybody
    # reaches through the slow duty channel — so the channel family, which is the
    # one that makes `messages.jsonl` load-bearing, would be generated by exactly
    # zero corpora. One slot is given to the best candidate that supports it.
    if selected and not any(told_by(held) for _, held in selected):
        substitute = next((row for row in candidates if told_by(row[1])), None)
        if substitute is not None:
            selected = selected[: max(limit - 1, 0)] + [substitute]

    out: list[EvaluationCase] = []
    for fact_id, held in selected:
        fact = facts[fact_id]
        subject = _subject(fact, names)
        sources = sorted(carried[fact_id])
        first, last = held[0], held[-1]
        ahead = [holder for holder in held if holder.learned_at < last.learned_at]
        # Everyone who held it at the earliest moment, not the one the sort put
        # in front. Two people paged by the same event learn it in the same
        # second, and an answer that named only the lower person id would mark a
        # correct response wrong for a tie the corpus itself does not break.
        earliest = [
            holder for holder in held if holder.learned_at == first.learned_at
        ]

        out.append(
            EvaluationCase(
                id=minter.next("EVAL"),
                question=(
                    f"Which employee was first to have a record of {subject},"
                    f" and when in {period}?"
                ),
                evaluation_type=EvaluationType.TEMPORAL_STATE,
                expected_answer=(
                    "; ".join(
                        f"{_who(world, holder.observer_id)} via {holder.source_type}"
                        for holder in earliest
                    )
                    + f", at {first.learned_at.isoformat()}."
                ),
                expected_fact_ids=[fact_id],
                required_artifact_ids=sources,
                temporal_cutoff=first.learned_at,
                difficulty="hard",
                reasoning=(
                    "The fact's own validity says when it became true, not when"
                    " anybody found out. Answering means reading the knowledge"
                    " ledger, where this fact reached"
                    f" {len(held)} employees over {_gap(last.learned_at - first.learned_at)}."
                ),
            )
        )

        out.append(
            EvaluationCase(
                id=minter.next("EVAL"),
                question=(
                    f"By the time {_who(world, last.observer_id)} came to know"
                    f" {subject}, who in the company already held it?"
                ),
                evaluation_type=EvaluationType.CAUSAL_MULTI_HOP,
                expected_answer=(
                    "; ".join(
                        f"{_who(world, holder.observer_id)} from"
                        f" {holder.learned_at.isoformat()}"
                        for holder in ahead
                    )
                    + "."
                ),
                expected_fact_ids=[fact_id],
                required_artifact_ids=sources,
                temporal_cutoff=last.learned_at,
                difficulty="hard",
                reasoning=(
                    "The asymmetry question proper: everyone named could have"
                    " acted on this before the last person heard of it. No"
                    " document states the set — it is the join of the fact"
                    " against who had observed it by that moment."
                ),
            )
        )

        # The channel, and therefore the informant. Only where somebody was
        # genuinely *told*: for an observer who owned the system or witnessed the
        # event there is no informant, and asking who told them would have no
        # answer but "nobody", which reads as a trick rather than a question.
        told = told_by(held)
        if told is None:
            continue
        message = by_message[told.source_id or ""]
        out.append(
            EvaluationCase(
                id=minter.next("EVAL"),
                question=(
                    f"How did {_who(world, told.observer_id)} come to know"
                    f" {subject} — who told them, and when?"
                ),
                evaluation_type=EvaluationType.AUTHORITY_RESOLUTION,
                expected_answer=(
                    f"{_who(world, message.sender_id)} told them at"
                    f" {message.sent_at.isoformat()}, in a {message.kind}"
                    f" about {message.subject_ref}."
                ),
                expected_fact_ids=[fact_id],
                required_artifact_ids=sources,
                temporal_cutoff=told.learned_at,
                difficulty="hard",
                reasoning=(
                    "Being told beat every channel this employee's own role"
                    " reaches — for a fact outside their readable domains it is"
                    " the only one that delivers at all. The route is the answer,"
                    " and it is recorded on the message rather than inferable"
                    " from any document either party wrote."
                ),
            )
        )

    return tuple(out)


__all__ = ["DEFAULT_LIMIT", "cases"]
