"""The ten rules a catalogue must obey that its JSON Schema cannot express.

A schema checks *shape*: is this field a string, is that one between 0 and 1.
It cannot check whether a file agrees with itself — whether a step points at a
connector that was declared, whether the shares add up, whether an id is really
the hash it claims to be. Those ten cross-checks live here.

    schema  ─▶ "every field has the right type"
    this    ─▶ "and the file does not contradict itself"

Both sides of the handoff run the same ten. The miner runs them before writing
a catalogue; Worldloom runs them before reading one. The codes ``inv1`` …
``inv10`` are shared vocabulary, so when the two disagree about a file they can
at least name the disagreement identically.

Every check runs. None short-circuits, and none stops the next — a catalogue
with four problems reports four, because someone has to go and fix them, and
finding them one rebuild at a time is how a day disappears.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterator
from typing import TYPE_CHECKING

from .report import Finding, hard

if TYPE_CHECKING:  # Type-only, so :mod:`.catalogue` can import us back.
    from .catalogue import Catalogue, Cuj, Step

#: How far the shares in ``inv9`` may drift from their target. The miner rounds
#: each share to three decimals independently, so a sum of fifty of them can
#: miss 1.0 by more than any one of them does. One part in a hundred is the
#: documented allowance.
SHARE_TOLERANCE = 0.01

#: Anything the miner's sanitizer leaves behind when it had to remove text:
#: ``[EMAIL_REDACTED]``, ``[NAME_REDACTED]``, and the same pattern for whatever
#: else it learns to find. A template needing redaction is supposed to be
#: dropped, not cleaned and emitted, so finding one of these means the file
#: carries text that was never meant to cross the boundary.
REDACTION_MARKER = re.compile(r"\[[A-Z][A-Z0-9_]*_REDACTED\]")


def step_token(step: Step) -> str:
    """One step as it appears in a journey's signature.

    A tool step is ``connector.entity.operation``; a capability step is
    ``~capability``. Step ids, effects, dependencies, argument fields and
    presence are all left out — deliberately. The id must survive the journey
    being re-mined next month with slightly different step names or an extra
    optional step's presence shifting, and it only can if those never enter
    the hash.
    """
    if step.connector is not None:
        return f"{step.connector}.{step.entity}.{step.operation}"
    return f"~{step.capability}"


def signature(cuj: Cuj) -> str:
    """The canonical signature a journey's id is hashed from.

    Step tokens joined with ``|`` — except for an answer-only journey, which
    has no business tool call to be recognised by and is identified by its
    intent cluster instead. There the cluster *replaces* the steps rather than
    joining them, so two answer-only journeys in the same cluster collapse to
    one identity however their model-only steps happen to differ.
    """
    if cuj.anchor == "domain_cluster" and cuj.cluster is not None:
        return f"cluster:{cuj.cluster.cluster_id}"
    return "|".join(step_token(step) for step in cuj.steps)


def cuj_id(cuj: Cuj) -> str:
    """The id a journey should have: ``cuj_`` + first 12 hex of SHA-256.

    Deliberately not Python's ``hash()``, which is salted per process and would
    give a different answer every run.
    """
    hexdigest = hashlib.sha256(signature(cuj).encode("utf-8")).hexdigest()
    return f"cuj_{hexdigest[:12]}"


# --------------------------------------------------------------------------
# inv1 — steps only reach declared tools.
# --------------------------------------------------------------------------


def inv1_steps_declared(catalogue: Catalogue) -> Iterator[Finding]:
    """Every tool step's connector, entity and operation was declared.

    A step reaching a tool the catalogue never listed means the world builder
    would have nothing to construct that tool from.
    """
    declared = {
        (connector.key, entity.name, operation)
        for connector in catalogue.connectors
        for entity in connector.entities
        for operation in entity.operations
    }
    for cuj in catalogue.cujs:
        for step in cuj.steps:
            if step.connector is None:
                continue
            triple = (step.connector, step.entity, step.operation)
            if triple not in declared:
                yield hard(
                    "inv1",
                    f"step {step.id!r} uses "
                    f"{step.connector}.{step.entity}.{step.operation}, which "
                    f"is not declared in connectors[].entities[]",
                    cuj_id=cuj.id,
                    detail={"step": step.id,
                            "connector": str(step.connector),
                            "entity": str(step.entity),
                            "operation": str(step.operation)})


# --------------------------------------------------------------------------
# inv2 — dependencies point backwards.
# --------------------------------------------------------------------------


def inv2_depends_on_earlier(catalogue: Catalogue) -> Iterator[Finding]:
    """``depends_on`` names only *earlier* steps of the same journey.

    Steps are an ordered list, so "earlier" is simply "already seen". Checking
    it this way rejects an unknown step id and a cycle with the same test: a
    step cannot consume what has not been produced yet, and a step certainly
    cannot consume itself.
    """
    for cuj in catalogue.cujs:
        seen: set[str] = set()
        for step in cuj.steps:
            for dependency in step.depends_on:
                if dependency not in seen:
                    yield hard(
                        "inv2",
                        f"step {step.id!r} depends on {dependency!r}, which is "
                        f"not an earlier step of this CUJ",
                        cuj_id=cuj.id,
                        detail={"step": step.id, "depends_on": dependency})
            seen.add(step.id)


# --------------------------------------------------------------------------
# inv3 — slots bind to real arguments.
# --------------------------------------------------------------------------


def inv3_slots_resolve(catalogue: Catalogue) -> Iterator[Finding]:
    """Each slot names a step of the same journey, and a field that step takes.

    Two separate failures: pointing at a step that does not exist, and pointing
    at a real step but a field it never receives. Both leave a hole that cannot
    be filled when the template is bound to a built world.
    """
    for cuj in catalogue.cujs:
        steps = {step.id: step for step in cuj.steps}
        for phrasing in cuj.phrasings:
            for slot in phrasing.slots:
                step = steps.get(slot.step_id)
                if step is None:
                    yield hard(
                        "inv3",
                        f"slot {slot.name!r} names step {slot.step_id!r}, "
                        f"which is not a step of this CUJ",
                        cuj_id=cuj.id,
                        detail={"slot": slot.name, "step": slot.step_id})
                elif slot.field not in step.argument_fields:
                    yield hard(
                        "inv3",
                        f"slot {slot.name!r} binds to field {slot.field!r}, "
                        f"which is not in step {slot.step_id!r}'s "
                        f"argument_fields",
                        cuj_id=cuj.id,
                        detail={"slot": slot.name, "step": slot.step_id,
                                "field": slot.field})


# --------------------------------------------------------------------------
# inv4 — failures are attributed to real steps.
# --------------------------------------------------------------------------


def inv4_failure_steps_exist(catalogue: Catalogue) -> Iterator[Finding]:
    """A failure mode's ``step_id``, when it has one, names a step that exists.

    ``step_id`` is optional, because not every failure can be attributed. But
    an attribution that points nowhere is worse than none: the generator would
    be asked to break a step it cannot find.
    """
    for cuj in catalogue.cujs:
        step_ids = {step.id for step in cuj.steps}
        for failure in cuj.failure_modes:
            if failure.step_id is not None and failure.step_id not in step_ids:
                yield hard(
                    "inv4",
                    f"failure mode {failure.mode.value!r} is attributed to "
                    f"step {failure.step_id!r}, which is not a step of this CUJ",
                    cuj_id=cuj.id,
                    detail={"mode": failure.mode.value,
                            "step": failure.step_id})


# --------------------------------------------------------------------------
# inv5, inv6, inv7 — the privacy promises, re-checked.
# --------------------------------------------------------------------------


def inv5_min_support(catalogue: Catalogue) -> Iterator[Finding]:
    """Nothing rarer than ``min_support`` was emitted.

    This is the k-anonymity floor, and the reason it is checked on *both* the
    journey and each phrasing: a journey seen by enough people can still carry
    a template only one of them ever used, and that template is the one that
    identifies them.
    """
    floor = catalogue.privacy.min_support
    for cuj in catalogue.cujs:
        if cuj.support.sessions < floor:
            yield hard(
                "inv5",
                f"CUJ was seen in {cuj.support.sessions} sessions, below "
                f"privacy.min_support of {floor}",
                cuj_id=cuj.id,
                detail={"sessions": str(cuj.support.sessions),
                        "min_support": str(floor)})
        for phrasing in cuj.phrasings:
            if phrasing.support < floor:
                yield hard(
                    "inv5",
                    f"phrasing has support {phrasing.support}, below "
                    f"privacy.min_support of {floor}",
                    cuj_id=cuj.id,
                    detail={"support": str(phrasing.support),
                            "min_support": str(floor)})


def inv6_text_policy_none(catalogue: Catalogue) -> Iterator[Finding]:
    """``text_policy: none`` means no phrasings at all, anywhere.

    The policy is the operator's instruction that no request text may leave,
    however sanitized. A single template under it is a broken promise, not a
    rounding error.
    """
    if catalogue.privacy.text_policy != "none":
        return
    for cuj in catalogue.cujs:
        if cuj.phrasings:
            yield hard(
                "inv6",
                f"privacy.text_policy is 'none', but this CUJ carries "
                f"{len(cuj.phrasings)} phrasing(s)",
                cuj_id=cuj.id,
                detail={"phrasings": str(len(cuj.phrasings))})


def inv7_no_redaction_markers(catalogue: Catalogue) -> Iterator[Finding]:
    """No template carries a redaction marker.

    The rule is drop, not clean. A marker means the sanitizer found something
    private in that request and the template was emitted anyway — so the
    template's *shape* was built around text nobody approved, and what the
    marker replaced may still be inferable from everything around it.
    """
    for cuj in catalogue.cujs:
        for phrasing in cuj.phrasings:
            markers = REDACTION_MARKER.findall(phrasing.template)
            if markers:
                yield hard(
                    "inv7",
                    f"phrasing template contains redaction marker(s) "
                    f"{', '.join(sorted(set(markers)))}; a template that "
                    f"needed redaction must be dropped, not emitted",
                    cuj_id=cuj.id,
                    detail={"markers": ",".join(sorted(set(markers)))})


# --------------------------------------------------------------------------
# inv8 — ids are what they claim to be.
# --------------------------------------------------------------------------


def inv8_ids_recomputed(catalogue: Catalogue) -> Iterator[Finding]:
    """Every journey id is recomputed from its steps, not trusted.

    The id is the only thing tying this month's catalogue to last month's, so
    it is the one field where accepting the producer's word costs the most. The
    check is cheap and the recipe is fixed; there is no reason not to redo it.
    """
    for cuj in catalogue.cujs:
        expected = cuj_id(cuj)
        if cuj.id != expected:
            yield hard(
                "inv8",
                f"id {cuj.id!r} does not match its signature, which hashes to "
                f"{expected!r}",
                cuj_id=cuj.id,
                detail={"declared": cuj.id, "computed": expected,
                        "signature": signature(cuj)})


# --------------------------------------------------------------------------
# inv9, inv10 — the arithmetic.
# --------------------------------------------------------------------------


def inv9_shares_add_up(catalogue: Catalogue) -> Iterator[Finding]:
    """Coverage accounts for all the traffic, and for the right traffic.

    Two sums, each answering a different question. The three shares together
    ask *was any traffic lost?* — every curated session is either covered by a
    journey, suppressed as too rare, or unclassified, with nothing left over.
    The second asks *is the covered share the journeys we actually got?* — if
    the journeys' own shares do not reconstruct it, the header is describing a
    catalogue other than the one attached.
    """
    coverage = catalogue.coverage
    total = (coverage.covered_share + coverage.suppressed_share
             + coverage.unclassified_share)
    # NaN compares false with everything, so ``abs(nan - 1) > tolerance`` is
    # False and the sum would pass. The loader refuses NaN before this runs;
    # the guard keeps this rule true on its own, for any caller.
    if not math.isfinite(total) or abs(total - 1.0) > SHARE_TOLERANCE:
        yield hard(
            "inv9",
            f"coverage shares sum to {total:.4f}, not 1 "
            f"(tolerance {SHARE_TOLERANCE})",
            detail={"covered": f"{coverage.covered_share}",
                    "suppressed": f"{coverage.suppressed_share}",
                    "unclassified": f"{coverage.unclassified_share}",
                    "sum": f"{total:.4f}"})

    emitted = sum(cuj.support.share for cuj in catalogue.cujs)
    if abs(coverage.covered_share - emitted) > SHARE_TOLERANCE:
        yield hard(
            "inv9",
            f"coverage.covered_share is {coverage.covered_share}, but the "
            f"CUJs' shares sum to {emitted:.4f} "
            f"(tolerance {SHARE_TOLERANCE})",
            detail={"covered_share": f"{coverage.covered_share}",
                    "cuj_share_sum": f"{emitted:.4f}"})


def inv10_histograms_agree(catalogue: Catalogue) -> Iterator[Finding]:
    """Each journey's histograms count the same queries.

    Outcomes and hardness are two ways of labelling the same set of queries —
    how each one ended, and how hard each one was — so both must total
    ``support.queries``. When they disagree, some queries were labelled by one
    classifier and not the other, and any weighting drawn from either is off by
    the difference.
    """
    for cuj in catalogue.cujs:
        queries = cuj.support.queries
        for name, histogram in (("outcomes", cuj.outcomes),
                                ("hardness", cuj.hardness)):
            total = sum(histogram.values())
            if total != queries:
                yield hard(
                    "inv10",
                    f"{name} counts sum to {total}, but support.queries is "
                    f"{queries}",
                    cuj_id=cuj.id,
                    detail={"histogram": name, "sum": str(total),
                            "queries": str(queries)})


#: Run in numeric order, so a catalogue breaking several rules reports them in
#: an order that does not depend on how a dict happened to iterate.
CHECKS = (
    inv1_steps_declared,
    inv2_depends_on_earlier,
    inv3_slots_resolve,
    inv4_failure_steps_exist,
    inv5_min_support,
    inv6_text_policy_none,
    inv7_no_redaction_markers,
    inv8_ids_recomputed,
    inv9_shares_add_up,
    inv10_histograms_agree,
)


def check(catalogue: Catalogue) -> tuple[Finding, ...]:
    """Run all ten and return every failure, in ``inv1`` … ``inv10`` order.

    Assumes the catalogue is already shape-checked — these add up shares and
    resolve step ids, which only mean anything once the types are known good.
    """
    return tuple(finding for rule in CHECKS for finding in rule(catalogue))
