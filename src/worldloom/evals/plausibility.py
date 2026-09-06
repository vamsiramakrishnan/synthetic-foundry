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

from .intents import intents


def _lobs(world: Any) -> dict[str, Any]:
    """Every LOB the world carries, keyed by name, or an empty mapping.

    Tolerant on purpose: LOBs ride the pack, so a world built without one is
    ordinary rather than broken and this module simply has less to say about
    it. `getattr` rather than an attribute access for the same reason the
    causal group uses one, since not every world has been through that seam.
    """
    installed = getattr(world, "_lobs", None)
    if installed is None:
        return {}
    if isinstance(installed, dict):
        return dict(installed)
    return {
        getattr(item, "name", str(index)): item for index, item in enumerate(installed)
    }


def _requests(world: Any) -> list[Any]:
    return [
        case
        for case in getattr(world, "_evaluations", ())
        if getattr(case, "has_request", False)
    ]


def _standing(world: Any, role_key: str) -> tuple[bool, tuple[str, ...]]:
    """Whether any LOB declares *role_key*, and the fact kinds it may ask about."""
    from .. import lob as lob_module

    granted: list[str] = []
    known = False
    for installed in _lobs(world).values():
        if any(role.key == role_key for role in getattr(installed, "roles", ())):
            known = True
        for ask in lob_module.asks_about(installed, role_key):
            for kind in ask.fact_kinds:
                if kind not in granted:
                    granted.append(kind)
    return known, tuple(granted)


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

    for case in cases:
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
    lobs = _lobs(world)

    for case in sorted(cases, key=lambda c: c.id):
        if case.asker is None:
            # A request with an occasion and a verb but nobody sending it is
            # exactly the quiz shape this work exists to leave behind, so it is
            # worth saying, once, per case.
            out.append(f"{case.id!r} carries a request with no asker")
            continue
        if not lobs:
            continue
        known, granted = _standing(world, case.asker)
        if not known:
            out.append(f"{case.id!r} is asked by {case.asker!r}, a role no installed LOB declares")
        elif not granted:
            out.append(
                f"{case.id!r} is asked by {case.asker!r}, which holds no"
                " responsibility and so has no declared reason to ask"
            )
    return out


def install() -> None:
    """Register the check group. Idempotent, and called from ``_install``."""
    from .. import validate as _validate

    _validate.register_domain_checks("eval_plausibility", _checks)


__all__ = ["findings", "install"]
