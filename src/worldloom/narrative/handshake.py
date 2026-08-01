"""The agent handshake.

Worldloom does not call a model. It hands an agent a bounded request and checks
what comes back:

    worldloom narrate requests ./corpus -o requests.json
    # the agent writes prose into responses.json
    worldloom narrate accept ./corpus --from responses.json

The request is self-describing on purpose. An agent should be able to answer it
without reading this repository: it carries the facts it may use, which are
required, what the author knew and when, the voice to write in, and the rules in
full. Nothing is implied by convention.

Rejection is the interesting half. A violation comes back naming the rule and the
offending text, so the agent can fix it and resubmit — the same loop a provider
adapter would run, with the agent in the loop instead of behind an API.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from . import references
from .claims import known_entity_names, validate
from .compiler import _request_for
from .requests import (
    GeneratedClaim,
    GeneratedNarrative,
    NarrativeRequest,
    Verdict,
    Violation,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..models import CanonicalFact
    from ..world import World

#: Stated in every request, so an agent needs no other source for the contract.
RULES: tuple[str, ...] = (
    "Write only the prose for this one section. No heading, no preamble.",
    "Every number, date, and amount must appear as a {{fact:ID}} reference using an"
    " ID from `facts` below. Never write a figure, percentage, or date as digits —"
    " a restated number is a copy that can drift from the ledger.",
    "Every assertion you make must be supported by at least one of the facts below,"
    " and you must list your claims with the fact IDs supporting each.",
    "Do not mention any organisation, person, system, or metric that is not in the"
    " facts below.",
    "Facts marked `required: true` must appear.",
    "You know only what the facts below say, as of `knows_as_of`. Do not anticipate"
    " anything discovered later.",
    "A fact marked `superseded: true` was believed at the time and later proved"
    " wrong. You may refer to it as a past belief, never as the current position.",
    # The rules above are prohibitions. These four are the ones that make prose
    # good rather than merely legal — a section that satisfies every constraint
    # and says nothing is a section that passed validation and failed its job.
    "`purpose` is the section's job. Write to it. A section that lists the facts"
    " in the order supplied has not done its job even if every rule above is"
    " satisfied.",
    "`background` is standing context that explains why the figures look as they"
    " do. Reason from it and allude to it. Do not assert it as a finding, do not"
    " cite it, and never present it as something the facts establish.",
    "Where a fact has `prior_period_fact`, both are available to cite. That is how"
    " a trend is stated: reference this period and the last, and let the reader see"
    " the movement, rather than describing a movement in words the ledger cannot"
    " check.",
    "Not every fact deserves a sentence. Weight them. A division that performed to"
    " plan warrants a clause; the one that did not warrants the paragraph.",
)


def _fact_payload(
    fact: CanonicalFact,
    *,
    required: bool,
    subject: str | None = None,
    comparator: str | None = None,
) -> dict[str, Any]:
    return {
        "id": fact.id,
        "subject": subject or fact.subject,
        "period": fact.period or "",
        **({"prior_period_fact": comparator} if comparator else {}),
        "statement": references.describe(fact, subject),
        "kind": fact.kind,
        "authority": fact.authority.value,
        "valid_from": fact.valid_from.isoformat(),
        "superseded": fact.is_superseded,
        "required": required,
    }


def _request_payload(request: NarrativeRequest, facts: dict[str, CanonicalFact]) -> dict[str, Any]:
    return {
        "id": f"{request.artifact_id}/{request.section}",
        "artifact_id": request.artifact_id,
        "artifact_type": request.artifact_type,
        "section": request.section,
        "written_by": request.author_title,
        "purpose": request.purpose,
        "voice": request.voice,
        "persona": request.persona_label,
        "author_traits": dict(request.author_traits),
        "audience": request.audience,
        "background": list(request.background),
        "hierarchy": dict(request.hierarchy),
        "target_words": request.target_words,
        "knows_as_of": request.temporal_cutoff.isoformat() if request.temporal_cutoff else None,
        "must_not_claim": list(request.forbidden_claims),
        "facts": [
            _fact_payload(
                facts[f],
                required=f in request.required_fact_ids,
                subject=request.subjects.get(f),
                comparator=request.comparators.get(f),
            )
            for f in request.allowed_fact_ids
            if f in facts
        ],
    }


def pending(world: World) -> list[NarrativeRequest]:
    """Every section still awaiting prose, as a bounded request."""
    facts = {fact.id: fact for fact in world.facts}
    out: list[NarrativeRequest] = []
    for ir in world.artifact_irs:
        for section in ir.sections:
            if not section.awaiting_prose:
                continue
            request = _request_for(world, ir, section, facts)
            if request.allowed_fact_ids:
                out.append(request)
    return out


def requests_document(world: World) -> dict[str, Any]:
    """The full request set, ready to hand to an agent."""
    from . import prompts

    facts = {fact.id: fact for fact in world.facts}
    items = pending(world)
    return {
        "worldloom_seed": world.seed,
        "prompt_version": prompts.SECTION_PROSE.key,
        "company": world.company.name,
        "period": world.period,
        "rules": list(RULES),
        "reference_syntax": "{{fact:FACT-0001}}",
        "response_shape": {
            "responses": [
                {
                    "id": "<the id of the request you are answering>",
                    "text": "<prose, with {{fact:ID}} references>",
                    "claims": [
                        {"text": "<one assertion>", "supporting_fact_ids": ["FACT-0001"]}
                    ],
                }
            ]
        },
        "requests": [_request_payload(request, facts) for request in items],
    }


def parse_responses(payload: dict[str, Any]) -> dict[str, GeneratedNarrative]:
    """Read a response document into narratives, keyed by request ID."""
    rows = payload.get("responses")
    if not isinstance(rows, list):
        raise ValueError("expected a top-level 'responses' list")

    out: dict[str, GeneratedNarrative] = {}
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict) or "id" not in row:
            raise ValueError(f"response {index} has no 'id'")
        identifier = row["id"]
        try:
            out[identifier] = GeneratedNarrative(
                text=row.get("text", ""),
                claims=[
                    GeneratedClaim(
                        text=claim.get("text", ""),
                        supporting_fact_ids=list(claim.get("supporting_fact_ids", [])),
                    )
                    for claim in row.get("claims", [])
                ],
            )
        except Exception as exc:
            raise ValueError(f"response {identifier!r} is not valid: {exc}") from exc
    return out


def review(
    world: World, responses: dict[str, GeneratedNarrative]
) -> dict[str, Verdict]:
    """Validate every response, returning a verdict per request ID.

    Reviews the whole set rather than stopping at the first failure: an agent
    fixing five violations in one pass beats five round trips.
    """
    facts = {fact.id: fact for fact in world.facts}
    entity_names = known_entity_names(world)

    verdicts: dict[str, Verdict] = {}
    for request in pending(world):
        identifier = f"{request.artifact_id}/{request.section}"
        narrative = responses.get(identifier)
        if narrative is None:
            verdicts[identifier] = Verdict(
                accepted=False,
                violations=[
                    Violation(
                        code="missing_response",
                        detail="no response was supplied for this request",
                    )
                ],
            )
            continue
        verdicts[identifier] = validate(request, narrative, facts, entity_names=entity_names)
    return verdicts


def dump(document: dict[str, Any]) -> str:
    """Serialise a request document."""
    return json.dumps(document, indent=2) + "\n"
