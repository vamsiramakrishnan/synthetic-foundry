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
            lines.append(
                f"  {fact_id}  [{fact.authority.value}] {statement}"
                f" (valid from {fact.valid_from.isoformat()}){required}"
            )

        return self.template.format(
            section=request.section,
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
    # v2: fact lines now name the entity each figure is about. The template is
    # unchanged, but what it renders is not — and the ledger key is only honest
    # if a changed prompt changes the key. Replaying a v1 corpus against v2
    # therefore regenerates rather than silently serving prose written from a
    # weaker prompt, which is the whole point of versioning this.
    version="2",
    template="""\
Write the "{section}" section of a {artifact_type} for {audience}.

You are writing as: {author_title}
Voice: {voice}
Target length: about {target_words} words.
You know only what was true at: {cutoff}

Facts you may use. Reference each one as {{{{fact:ID}}}} — never write a figure out:
{facts}

You must not claim:
{forbidden}
{feedback}
Rules:
- Every numeric value must appear as a {{{{fact:ID}}}} reference, never as digits.
- Every assertion must be supported by at least one of the facts above.
- Do not mention anything not present in the facts above.
- Facts marked REQUIRED must appear.

Return the prose, and a list of the claims it makes with the fact IDs supporting each.
""",
)

_REGISTRY: dict[str, Prompt] = {SECTION_PROSE.name: SECTION_PROSE}


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
