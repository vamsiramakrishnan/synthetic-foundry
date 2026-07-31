"""Claim validation.

The LLM may choose emphasis and wording. It may not choose reality.

Every generated narrative is checked against the fact ledger before it is accepted,
and a failure is fed back for a retry rather than patched. Seven checks, each
closing a way a plausible document can be wrong:

``bare_number``
    A digit outside a fact reference. The arithmetic rule, enforced lexically: a
    restated figure is a copy, and a copy can drift.
``unsupported_claim``
    A claim citing a fact outside the allowed set — the model reached for
    something it was not given.
``unresolvable_reference``
    A reference to a fact that does not exist.
``required_fact_omitted``
    A fact the artifact exists to convey, missing from every claim.
``not_yet_known``
    A fact that had not yet come into existence at the author's cut-off. This is
    what stops a status page written at 09:30 from citing a cause confirmed at
    13:20.

    The test is ``valid_from <= cutoff``, not ``holds_at(cutoff)``. Those are
    different questions: whether a fact was *true* then, and whether an author
    writing later may *refer* to it. An RCA is largely about a belief that turned
    out to be wrong, so a superseded fact is legitimate material for a document
    written after it expired — it simply cannot be asserted as current.
``forbidden_claim``
    Something this artifact was explicitly told not to say.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import references
from .requests import GeneratedNarrative, NarrativeRequest, Verdict, Violation

if TYPE_CHECKING:  # pragma: no cover
    from ..models import CanonicalFact


def validate(
    request: NarrativeRequest,
    narrative: GeneratedNarrative,
    facts: dict[str, CanonicalFact],
    *,
    entity_names: frozenset[str] = frozenset(),
) -> Verdict:
    """Check a narrative against the facts it was allowed to use."""
    violations: list[Violation] = []
    allowed = set(request.allowed_fact_ids)

    # 1. No bare numerals. Substitution can only protect a figure that was
    #    referenced; one written out directly is already a divergent copy.
    for number in references.bare_numbers(narrative.text):
        violations.append(
            Violation(
                code="bare_number",
                detail=f"prose contains the literal {number!r}; reference the fact instead",
            )
        )

    # 2. Every claim must rest on facts it was given.
    for claim in narrative.claims:
        stray = [f for f in claim.supporting_fact_ids if f not in allowed]
        if stray:
            violations.append(
                Violation(
                    code="unsupported_claim",
                    detail=f"{claim.text[:60]!r} cites {stray}, which is outside the allowed set",
                )
            )

    # 3. Every reference must resolve — and resolve to a fact this author was
    #    actually given. Checking only against the global ledger let prose cite
    #    anything in the world: a reference outside the request resolved fine,
    #    and if the responder simply left it out of `claims` the stray-claim
    #    check above never saw it either. The request is the boundary, so a
    #    reference outside it is the same defect as a claim outside it, and it
    #    was reachable through prose alone.
    for fact_id in references.unresolved(narrative.text, facts):
        violations.append(
            Violation(code="unresolvable_reference", detail=f"{fact_id} does not exist")
        )
    for fact_id in sorted(set(references.referenced(narrative.text))):
        if fact_id in facts and fact_id not in allowed:
            violations.append(
                Violation(
                    code="unsupported_claim",
                    detail=(
                        f"prose references {fact_id}, which exists but is outside"
                        " the facts this request allows"
                    ),
                )
            )

    # 3b. Prose that asserts must be backed. Claim validation only ever inspected
    #     the claims a responder chose to supply, so an empty `claims` list with
    #     the required references sprinkled through the text passed every check —
    #     including prose asserting things the corpus never said. That is the
    #     harness's central promise failing in the one place nobody was looking.
    #
    #     The rule is deliberately about *substance*, not sentence count: a
    #     section carrying prose must carry at least one claim, and its claims
    #     must between them cite every fact the prose references. A tighter rule
    #     — one claim per sentence — would reject legitimate writing, since a
    #     sentence of connective tissue supports nothing and should not have to
    #     pretend otherwise.
    prose = narrative.text.strip()
    if prose and not narrative.claims:
        violations.append(
            Violation(
                code="unsupported_claim",
                detail="prose was supplied with no claims; every assertion must cite its facts",
            )
        )
    elif prose:
        claimed = {f for claim in narrative.claims for f in claim.supporting_fact_ids}
        for fact_id in sorted(set(references.referenced(narrative.text)) - claimed):
            violations.append(
                Violation(
                    code="unsupported_claim",
                    detail=(
                        f"prose references {fact_id} but no claim cites it;"
                        " a figure in the text with nothing standing behind it"
                        " cannot be checked"
                    ),
                )
            )

    # 4. Everything the artifact exists to say must be said.
    cited = {f for claim in narrative.claims for f in claim.supporting_fact_ids}
    cited |= set(references.referenced(narrative.text))
    for fact_id in request.required_fact_ids:
        if fact_id not in cited:
            violations.append(
                Violation(code="required_fact_omitted", detail=f"{fact_id} is required but never used")
            )

    # 5. Nothing the author could not yet know.
    if request.temporal_cutoff is not None:
        for fact_id in sorted(cited):
            fact = facts.get(fact_id)
            if fact is not None and fact.valid_from > request.temporal_cutoff:
                violations.append(
                    Violation(
                        code="not_yet_known",
                        detail=(
                            f"{fact_id} only becomes valid at {fact.valid_from.isoformat()},"
                            f" after the author's cut-off of {request.temporal_cutoff.isoformat()}"
                        ),
                    )
                )

    # 6. Nothing explicitly forbidden.
    lowered = narrative.text.casefold()
    for phrase in request.forbidden_claims:
        if phrase.casefold() in lowered:
            violations.append(
                Violation(code="forbidden_claim", detail=f"prose contains the forbidden phrase {phrase!r}")
            )

    # 7. No invented entities, when the caller supplies the world's names.
    if entity_names:
        prose = references.strip_references(narrative.text)
        for word in _capitalised_runs(prose):
            if word not in entity_names and len(word.split()) > 1:
                violations.append(
                    Violation(code="unknown_entity", detail=f"{word!r} is not an entity in this world")
                )

    return Verdict(accepted=not violations, violations=violations)


#: Function words that begin a sentence and are not part of the name that follows.
#:
#: Without these, "For Australian Food, revenue was …" reads as an entity called
#: "For Australian Food" and is rejected. That is the check working — it is
#: supposed to be suspicious of capitalised runs — but the run it found starts one
#: word too early. Found by the validator refusing prose this repository's own
#: fixture provider had just written.
_SENTENCE_OPENERS = frozenset({"For", "At", "In", "On", "By", "The", "A", "An", "This", "Both"})


def _capitalised_runs(text: str) -> list[str]:
    """Multi-word capitalised runs, as a cheap proxy for named entities.

    Deliberately conservative: it only flags runs of two or more capitalised words,
    because single capitalised words are too often ordinary sentence openings to be
    worth the false positives.
    """
    runs: list[str] = []
    current: list[str] = []
    for token in text.replace("\n", " ").split(" "):
        stripped = token.strip(".,;:()'\"")
        if not current and stripped in _SENTENCE_OPENERS:
            continue
        if stripped[:1].isupper() and stripped[1:2].islower():
            current.append(stripped)
        else:
            if len(current) > 1:
                runs.append(" ".join(current))
            current = []
    if len(current) > 1:
        runs.append(" ".join(current))
    return runs
