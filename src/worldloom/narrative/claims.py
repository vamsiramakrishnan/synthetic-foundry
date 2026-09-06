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
    from ..world import World


def known_entity_names(world: World) -> frozenset[str]:
    """Every name prose may treat as an entity of this world.

    One definition, shared by the compiler and the handshake, because two
    hand-maintained copies is how categories went missing from both: the list
    was written when only companies, units, people, and systems were ever
    named in prose, and the banking vertical's product books — categories —
    were rejected as inventions by a validator that had simply never been told
    they exist.
    """
    return frozenset(
        [world.company.name]
        + [unit.name for unit in world.business_units]
        + [person.name for person in world.people]
        + [system.name for system in world.systems]
        + [category.name for category in world.categories]
        + [site.name for site in world.sites]
    )

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
        # Name the fix, not just the failure. The first harness-driven run
        # showed a model truncating ids ({{fact:0015}} for FACT-0015) and then
        # burning every retry the same way, because "0015 does not exist" says
        # what is wrong without saying what right looks like. When exactly one
        # allowed id ends with the broken fragment, the feedback can say so.
        candidates = [known for known in request.allowed_fact_ids if known.endswith(fact_id)] if fact_id else []
        hint = (
            f" — write the id exactly as supplied: {{{{fact:{candidates[0]}}}}}"
            if len(candidates) == 1
            else " — references carry the id exactly as supplied, e.g. {{fact:FACT-0001}}"
        )
        violations.append(
            Violation(code="unresolvable_reference", detail=f"{fact_id} does not exist{hint}")
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
            if fact is not None and (fact.valid_from > request.temporal_cutoff or fact.recorded_at > request.temporal_cutoff):
                violations.append(
                    Violation(
                        code="not_yet_known",
                        detail=(
                            f"{fact_id} is valid from {fact.valid_from.isoformat()} and recorded at {fact.recorded_at.isoformat()},"
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
    #
    # A run that sits *inside* a known name is that name, seen through the
    # extractor's acronym blind spot: `_capitalised_runs` breaks a run at an
    # all-caps token, so "SME Secured Lending" surfaces as "Secured Lending" —
    # found when the banking vertical's own fixture provider was refused for
    # naming a product book the world genuinely contains. Containment is
    # checked instead of teaching the extractor acronyms, because widening the
    # matcher would start flagging ordinary prose like "CFO Approved" as an
    # entity, and a validator that rejects real names is worse than one that
    # is lenient about fragments of them.
    if entity_names:
        prose = references.strip_references(narrative.text)
        for word in _capitalised_runs(prose):
            # A possessive is the entity, not a new one. Found live, by the
            # first harness-driven narration run: Gemini wrote "Meridian
            # Retail Group's revenue", the run extractor captured the "'s",
            # and the containment rule cannot save it — the possessive is
            # *longer* than the name it belongs to, not a fragment of it.
            word = word.removesuffix("'s").removesuffix("’s").rstrip("'’")
            if len(word.split()) > 1 and word not in entity_names and not any(
                word in name for name in entity_names
            ):
                # One more chance before rejecting: drop the run's first word.
                # A capitalised sentence-opener fused to a real name ("Within
                # Mobile Ordering, conversion held") is the dominant false
                # positive once sentence boundaries are handled, and the
                # opener allow-list below only helps for the nine words it
                # happens to list — "In Mobile Ordering" passed while "Within
                # Mobile Ordering" was rejected, which is an allow-list
                # failing the only way allow-lists do. Dropping exactly one
                # word generalises it. Not more than one: English does not
                # stack Title Case function words in front of a name
                # mid-sentence, and every further dropped word widens the
                # escape until any invented compound whose tail brushes a
                # real name walks through — "Meridian Ordering Taskforce"
                # must still be flagged even though "Ordering" sits inside a
                # real "Mobile Ordering".
                remainder = word.split(" ", 1)[1]
                if remainder in entity_names or any(
                    remainder in name for name in entity_names
                ):
                    continue
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
#:
#: The list is kept for the runs it stops from *forming* ("The Board" never
#: becomes a run at all), but it is not the general rule: an opener it does not
#: list is handled at flag time by dropping the run's first word — see the
#: containment escape in ``validate`` — so the list no longer needs to grow a
#: word every time a writer opens a sentence differently.
_SENTENCE_OPENERS = frozenset({"For", "At", "In", "On", "By", "The", "A", "An", "This", "Both"})


def _capitalised_runs(text: str) -> list[str]:
    """Multi-word capitalised runs, as a cheap proxy for named entities.

    Deliberately conservative: it only flags runs of two or more capitalised words,
    because single capitalised words are too often ordinary sentence openings to be
    worth the false positives.

    A run never crosses a sentence boundary. It used to: the terminal full stop
    was stripped *before* the capitalisation test, so "Margin held in Food
    Halls. Promotional depth was agreed centrally." surfaced the run 'Food
    Halls Promotional' — a real entity name welded to the next sentence's first
    word, rejected as an invention. Five independent writers hit this against
    real names, so the run now closes at ``.``, ``!`` or ``?`` on the raw
    token. Abbreviations and ellipses get no special handling because the
    compiled corpus contains neither (checked against every example artifact),
    and even a name with an internal "St." would survive the split: each
    fragment of a real name passes the containment test on its own.
    """
    runs: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if len(current) > 1:
            runs.append(" ".join(current))
        current.clear()

    for token in text.replace("\n", " ").split(" "):
        stripped = token.strip(".,;:()'\"")
        if not current and stripped in _SENTENCE_OPENERS:
            continue
        if stripped[:1].isupper() and stripped[1:2].islower():
            current.append(stripped)
            # Trailing quotes and parens are not the sentence's last word —
            # 'Halls.)' still ends the sentence — so peel them before asking.
            if token.rstrip("()'\"’").endswith((".", "!", "?")):
                flush()
        else:
            flush()
    flush()
    return runs
