"""Would a person in that seat actually send that message?

Generating a situation is cheap once the occasion and the verb are both
authored data, and cheapness is the hazard: a cross of two tables will happily
produce a request from someone with no standing to make it, for a system they
cannot write to, graded by a shape the verb never claimed. Those are not hard
questions, they are wrong ones, and a set full of them measures nothing.

The rules are executable here rather than trusted, and each is derived from a
declaration the corpus already carries rather than from a second table that
could disagree with the first. They divide by what kind of wrong they are, and
the division is the same one `validate` draws everywhere else.

**Incoherence, so a violation.** The case disagrees with the engine's own
declared tables: an intent nothing declares, a grading shape that is not the
one the intent names, a write intent whose case produces no deliverable. Those
are checked by `_checks`, registered through `register_domain_checks` like
every vertical's group, and they fail a build the way a broken reference does.

**Realism, so a finding.** Whether a particular seat would plausibly ask a
particular thing is a judgement about the world, not a disagreement inside it,
and `validate` answers exactly one question. `findings` returns those as
sentences, the shape `phrasing.findings` and `episode_text.check_overrides`
already use, for a caller that wants to steer a generated set rather than gate
a build. Filing them as violations would make `worldloom validate` red on
every corpus that ever generated a stretchy request, which is a gate people
turn off.

A case carrying no request tuple is skipped by both. For most of this engine's
life there was no request, and those cases are not wrong, they are older.
"""

from __future__ import annotations

from typing import Any

from ..models import EvaluationType
from .intents import intents


def _lobs() -> dict[str, Any]:
    """Every LOB this process holds.

    Read from `lob.installed()`, which is where they actually live: a LOB
    rides the pack and lands in that registry through `packs.archetype_of`.
    A `World` has no LOB attribute at all, and an earlier draft of this module
    read `world._lobs` -- which meant the standing rules below silently never
    ran on any real corpus while reporting a clean check. A check that cannot
    fail is worse than no check, because it also removes the reason to write
    a real one.

    Empty is the ordinary case, not a broken one: a corpus built without a LOB
    pack declares no roles, so there is no standing to check. `findings` says
    that out loud rather than returning an empty list that reads as approval.
    """
    from .. import lob as lob_module

    return dict(lob_module.installed())


def _requests(world: Any) -> list[Any]:
    """Cases carrying a request, through the public collection.

    `world.evaluations`, not `world._evaluations`: a rename of the private
    attribute would otherwise leave this group reporting a clean run over a
    corpus it never looked at.
    """
    cases: Any = getattr(world, "evaluations", None)
    if cases is None:
        cases = getattr(world, "_evaluations", None)
    return [case for case in (cases or ()) if getattr(case, "has_request", False)]


def _standing(role_key: str) -> tuple[bool, tuple[str, ...]]:
    """Whether any installed LOB declares *role_key*, and the kinds it may ask about."""
    from .. import lob as lob_module

    granted: list[str] = []
    known = False
    for installed in _lobs().values():
        if any(role.key == role_key for role in getattr(installed, "roles", ())):
            known = True
        for ask in lob_module.asks_about(installed, role_key):
            for kind in ask.fact_kinds:
                if kind not in granted:
                    granted.append(kind)
    return known, tuple(granted)


def _unreachable_kinds(world: Any, case: Any, granted: tuple[str, ...]) -> set[str]:
    """Fact kinds this case cites that *granted* does not cover.

    Resolved from the world rather than from the case, because a case carries
    fact ids and standing is declared over kinds. A fact id that resolves to
    nothing is not this function's business: the referential check owns that,
    and reporting it twice in two vocabularies would be the second account
    this module exists to avoid.
    """
    from .. import factkinds

    facts = getattr(world, "facts", None)
    if facts is None or not granted:
        return set()
    unreachable: set[str] = set()
    for fact_id in getattr(case, "expected_fact_ids", ()):
        fact = facts.by_id(fact_id) if hasattr(facts, "by_id") else None
        if fact is None:
            continue
        kind = getattr(fact, "kind", None)
        if kind and not any(factkinds.covers(family, kind) for family in granted):
            unreachable.add(kind)
    return unreachable


def _checks(world: Any) -> tuple[list, int]:
    """The ``eval_plausibility`` group: a request that agrees with its own tables.

    Only the disagreements a corpus can be wrong about. Whether the asker is a
    realistic choice is `findings`' business, not this group's.
    """
    from ..validate import Violation

    violations: list[Violation] = []
    checks = 0
    cases = _requests(world)
    if not cases:
        return violations, checks

    table = intents()

    def fail(code: str, subject: str, detail: str) -> None:
        violations.append(
            Violation(group="eval_plausibility", code=code, subject=subject, detail=detail)
        )

    people = getattr(world, "people", None)

    for case in cases:
        # Referential, so a violation rather than a finding: `validate` already
        # refuses a case citing a fact or artifact the world does not hold, and
        # a request naming a person it does not hold is the same defect in a
        # new field. The evaluation branch in `validate` checks facts and
        # artifacts only, so without this the provenance could point outside
        # the world and still pass a clean run.
        if case.asker_person_id is not None and people is not None:
            checks += 1
            if not (
                people.by_id(case.asker_person_id)
                if hasattr(people, "by_id")
                else any(getattr(x, "id", None) == case.asker_person_id for x in people)
            ):
                fail(
                    "asker_not_found",
                    case.id,
                    f"asker_person_id {case.asker_person_id!r} names nobody in this world",
                )
        if case.intent is None:
            continue
        checks += 1
        intent = table.get(case.intent)
        if intent is None:
            fail("unknown_intent", case.id, f"intent {case.intent!r} is not declared")
            continue
        checks += 1
        if intent.grading != case.evaluation_type:
            fail(
                "grading_disagrees",
                case.id,
                f"intent {intent.id!r} grades as {intent.grading.value!r} but the"
                f" case is {case.evaluation_type.value!r}",
            )
        # `evaluate.score` and `evaluate.across` branch on `expects_abstention`,
        # not on the evaluation type, so a case whose flag and grading shape
        # disagree is scored under a rule its verb never claimed: a `sign_off`
        # marked as expecting abstention is graded as a refusal, and an
        # `abstain` that forgets the flag is graded as an ordinary lookup.
        # The base model ties the flag to the fact list and to nothing else,
        # so this is the only place the two can be held together.
        checks += 1
        abstains = intent.grading is EvaluationType.EXPECTED_ABSTENTION
        if abstains != case.expects_abstention:
            fail(
                "abstention_disagrees",
                case.id,
                f"intent {intent.id!r} grades as {intent.grading.value!r} but"
                f" expects_abstention is {case.expects_abstention}",
            )
        checks += 1
        if intent.effect == "write" and case.deliverable is None:
            fail(
                "write_without_deliverable",
                case.id,
                f"intent {intent.id!r} writes but the case names no deliverable",
            )
        checks += 1
        if intent.effect == "read" and case.deliverable is not None:
            fail(
                "read_with_deliverable",
                case.id,
                f"intent {intent.id!r} only reads but the case names a deliverable",
            )
        # The intent table already declares what a write produces, so a case
        # naming something else is two accounts of one thing that can disagree
        # with nothing to catch it. The case's wording may differ (it is prose
        # a person would use); what it may not do is name a different kind of
        # artifact from the one the verb is defined to produce.
        checks += 1
        if (
            intent.deliverable is not None
            and case.deliverable is not None
            and intent.deliverable.replace("_", " ") not in case.deliverable.casefold()
        ):
            fail(
                "deliverable_disagrees",
                case.id,
                f"intent {intent.id!r} produces {intent.deliverable!r} but the case"
                f" names {case.deliverable!r}",
            )
    return violations, checks


def findings(world: Any) -> list[str]:
    """Every request this world holds that a person in that seat would not send.

    Sentences naming the case, sorted by case id, in the shape
    `phrasing.findings` uses. An empty list means every request that carries an
    asker has a declared reason to make it.
    """
    out: list[str] = []
    cases = _requests(world)
    if not cases:
        return out
    lobs = _lobs()
    askers = sorted({case.asker for case in cases if case.asker is not None})

    for case in sorted(cases, key=lambda c: c.id):
        if case.asker is None:
            # A request with an occasion and a verb but nobody sending it is
            # exactly the quiz shape this work exists to leave behind, so it is
            # worth saying, once, per case.
            out.append(f"{case.id!r} carries a request with no asker")
            continue
        if not lobs:
            continue
        known, granted = _standing(case.asker)
        if not known:
            out.append(f"{case.id!r} is asked by {case.asker!r}, a role no installed LOB declares")
        elif not granted:
            out.append(
                f"{case.id!r} is asked by {case.asker!r}, which holds no"
                " responsibility and so has no declared reason to ask"
            )
        else:
            # The point of the rule, and the part an earlier draft left out:
            # holding *some* responsibility is not standing to ask *this*.
            # A controller who answers for financial kinds has no declared
            # reason to ask about an HR fact, and `may_ask_about` exists to
            # say so under the dot-boundary rule.
            for kind in sorted(_unreachable_kinds(world, case, granted)):
                out.append(
                    f"{case.id!r} is asked by {case.asker!r}, which answers for"
                    f" {', '.join(granted)} and so has no declared reason to ask"
                    f" about {kind!r}"
                )

    if askers and not lobs:
        # Said once, at the end, rather than per case: without a LOB there is
        # nothing to check standing against, and returning silence would read
        # as "every asker checked out" when in fact none was looked at.
        out.append(
            f"standing was not checked for {len(askers)} asker(s): this process"
            " holds no installed LOB to check against"
        )
    return out


def install() -> None:
    """Register the check group. Idempotent, and called at import.

    Called from the module foot below, the way every other group registers
    (`banking`, `insurance`, `procurement`, `retail`, `cohorts`, `causal`,
    `detail`). Kept as a named function as well so `__init__._install` can
    state the dependency explicitly, since nothing on the way to building or
    loading a world imports this module.
    """
    from .. import validate as _validate

    _validate.register_domain_checks("eval_plausibility", _checks)


install()


__all__ = ["findings", "install"]
