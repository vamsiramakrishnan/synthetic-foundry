"""What is asked of a model, and what it must return.

The request is a contract, not a prompt. It names exactly which facts may be
referenced, which must be, what may not be said, and when the author is writing —
so a model that returns something outside those bounds is *rejected* rather than
edited into shape.

The response is structured for the same reason. Free text cannot be validated
against a fact ledger; a list of claims each carrying its supporting fact IDs can.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from ..models import Model


class NarrativeRequest(Model):
    """A request for prose over a bounded set of facts."""

    artifact_id: str
    artifact_type: str
    section: str
    """The heading this prose sits under. Resolved before the request is made."""
    persona_id: str
    voice: str
    audience: str
    author_title: str
    temporal_cutoff: datetime | None = None
    """What the author could know. Facts valid after this are not visible."""
    allowed_fact_ids: list[str] = Field(default_factory=list)
    required_fact_ids: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    target_words: int = 120
    fact_digest: str = ""
    """Content address of the facts supplied, so the ledger key moves when they do."""

    @model_validator(mode="after")
    def _required_must_be_allowed(self) -> NarrativeRequest:
        stray = set(self.required_fact_ids) - set(self.allowed_fact_ids)
        if stray:
            raise ValueError(
                f"{self.artifact_id}/{self.section}: required facts not in the allowed set: {sorted(stray)}"
            )
        return self


class GeneratedClaim(Model):
    """One assertion, with the facts that justify it.

    A claim citing no facts is not a weak claim, it is an invalid one — there is
    nothing to check it against.
    """

    text: str
    supporting_fact_ids: list[str] = Field(min_length=1)


class GeneratedNarrative(Model):
    """Prose plus the claims it makes.

    ``text`` carries ``{{fact:ID}}`` references rather than literal figures. The
    renderer substitutes values from the ledger, so a deck and the workbook it came
    from read the same entry and neither holds a copy.
    """

    text: str
    claims: list[GeneratedClaim] = Field(default_factory=list)


class Violation(Model):
    """One reason a narrative was rejected."""

    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


class Verdict(Model):
    """The outcome of validating a narrative."""

    accepted: bool
    violations: list[Violation] = Field(default_factory=list)

    @property
    def feedback(self) -> str:
        """The violations as text, to hand back on a retry."""
        return "\n".join(f"- {v}" for v in self.violations)
