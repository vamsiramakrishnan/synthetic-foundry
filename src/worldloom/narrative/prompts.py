"""The prompt registry.

Prompts are versioned data, not string literals scattered through the code, because
a prompt version is part of the generation ledger key. Editing a prompt in place
would silently change what a seed produces; bumping its version changes the key and
produces a *different* world, explicitly.

That is the whole reason this file exists. A registry with one template in it would
still be worth having.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import CanonicalFact
from . import references
from .requests import NarrativeRequest


@dataclass(frozen=True)
class Prompt:
    """A versioned prompt template."""

    name: str
    version: str
    template: str

    @property
    def key(self) -> str:
        """How this prompt appears in a ledger key."""
        return f"{self.name}@{self.version}"

    def render(self, request: NarrativeRequest, facts: dict[str, CanonicalFact], *, feedback: str = "") -> str:
        """Fill the template for one request."""
        lines = []
        for fact_id in request.allowed_fact_ids:
            fact = facts.get(fact_id)
            if fact is None:
                continue
            statement = references.describe(fact, request.subjects.get(fact_id))
            required = " (REQUIRED)" if fact_id in request.required_fact_ids else ""
            prior = request.comparators.get(fact_id)
            lines.append(
                f"  {fact_id}  [{fact.authority.value}] {statement}"
                f" (valid from {fact.valid_from.isoformat()})"
                + (f" (prior period: {prior})" if prior else "")
                + required
            )

        traits = ", ".join(f"{name} {value:+.1f}" for name, value in sorted(request.author_traits.items()))

        return self.template.format(
            section=request.section,
            purpose=request.purpose or "  (not stated)",
            persona=f" ({request.persona_label})" if request.persona_label else "",
            traits=f"\nWriting tendencies: {traits}" if traits else "",
            hierarchy="\n".join(f"  {k} — {v}" for k, v in sorted(request.hierarchy.items())) or "  (none)",
            background="\n".join(f"  - {b}" for b in request.background) or "  (none)",
            artifact_type=request.artifact_type.replace("_", " "),
            audience=request.audience.replace("_", " "),
            author_title=request.author_title,
            voice=request.voice,
            target_words=request.target_words,
            cutoff=request.temporal_cutoff.isoformat() if request.temporal_cutoff else "not constrained",
            facts="\n".join(lines) or "  (none)",
            forbidden="\n".join(f"  - {c}" for c in request.forbidden_claims) or "  (none)",
            feedback=f"\nThe previous attempt was rejected:\n{feedback}\n" if feedback else "",
        )


SECTION_PROSE = Prompt(
    name="section_prose",
    # v2 named the entity each figure is about. v3 adds the section's purpose, the
    # standing context that explains the figures, and the prior period — the
    # difference between prose that is legal and prose that argues. The template
    # changed, so the version does; a ledger key is only honest if a changed
    # prompt changes it.
    #
    # v4 makes the rules state what the validator enforces, in step with the
    # same rewording of `handshake.RULES`: the digit rule is lexical (no digit
    # runs anywhere outside a reference, not merely "no restated figures"), and
    # a fact whose validity ended before the cut-off is a past belief. The
    # handshake's rules text is not itself a ledger-key component, but the
    # brief a writer answers under changed on both paths, and this version is
    # the one key component that records which brief that was.
    #
    # v5 adds three sentences: the claim-coverage converse (every reference must
    # be cited by some claim), clarification that job titles and background-only
    # names are not entities, and explanation that a reference substitutes the
    # fact's rendered statement verbatim so prose must write grammar around it.
    # The handshake.RULES changed, so the ledger key must.
    version="5",
    template="""\
Write the "{section}" section of a {artifact_type} for {audience}.

What this section has to do:
{purpose}

You are writing as: {author_title}{persona}
Voice: {voice}{traits}
Target length: about {target_words} words.
You know only what was true at: {cutoff}

Facts you may use. Reference each one as {{{{fact:ID}}}} — never write a figure out:
{facts}

Where a fact carries "prior period: FACT-ID", both are available to cite. That is
how a trend is stated — reference this period and the last, and let the reader see
the movement.

Where each subject sits:
{hierarchy}

Standing context. This explains why the figures look as they do. Reason from it
and allude to it; do not assert it as a finding and do not cite it:
{background}

You must not claim:
{forbidden}
{feedback}
Rules:
- No digits anywhere outside a {{{{fact:ID}}}} reference — the check is lexical.
  Spell any other number (an ordinal, a count) out in words, or leave it out.
- Every assertion must be supported by at least one of the facts above.
- Do not mention anything not present in the facts above.
- Facts marked REQUIRED must appear.
- A fact whose validity had ended by your cut-off is a past belief. Tell it as
  history — never as the current position.
- Write to the purpose. Listing the facts in the order supplied is not the job.
- Weight the facts. Not every one deserves a sentence.

Return the prose, and a list of the claims it makes with the fact IDs supporting each.
""",
)

_REGISTRY: dict[str, Prompt] = {
    SECTION_PROSE.name: SECTION_PROSE,
}


def get(name: str = SECTION_PROSE.name) -> Prompt:
    """Look up a prompt by name."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown prompt {name!r}. Registered: {', '.join(sorted(_REGISTRY))}") from None


def register(prompt: Prompt) -> None:
    """Register a prompt. Bump the version rather than editing one in place."""
    _REGISTRY[prompt.name] = prompt


def versions() -> dict[str, str]:
    """Every registered prompt and its version."""
    return {name: prompt.version for name, prompt in sorted(_REGISTRY.items())}
