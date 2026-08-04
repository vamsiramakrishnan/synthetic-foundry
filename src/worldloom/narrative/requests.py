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
    purpose: str = ""
    """What this section has to accomplish. The difference between prose that
    argues and prose that lists."""
    background: list[str] = Field(default_factory=list)
    """Standing context that explains *why* the figures look as they do.

    Lore assertions reachable from the facts supplied. Explicitly not citable and
    explicitly not figures — a writer may reason from them and allude to them, and
    must not assert them as findings. Without this a variance memo can say margin
    fell; with it, the memo can say margin fell for the reason everyone in the
    business already argues about, which is what a real one does."""
    author_traits: dict[str, float] = Field(default_factory=dict)
    """How this specific author writes under pressure, from lore. Signed
    magnitudes: positive is more of the named trait."""
    persona_label: str = ""
    hierarchy: dict[str, str] = Field(default_factory=dict)
    """Subject name to where it sits — "division of Ardent Holdings", "category in
    Australian Food". Lets prose say "the largest division" instead of naming four
    units flatly."""
    comparators: dict[str, str] = Field(default_factory=dict)
    """Fact ID to the ID of the same measure a period earlier.

    Both are in ``allowed_fact_ids``, so a trend claim is written by citing two
    references rather than by restating a movement. This is what makes "the third
    consecutive month of erosion" a sentence the harness will accept."""
    subjects: dict[str, str] = Field(default_factory=dict)
    """Fact ID to the name of the entity it is about.

    Carried on the request rather than looked up, because the contract is that a
    request can be answered without reading this repository — and a figure whose
    subject is an opaque ID cannot be written about at all.
    """
    forbidden_claims: list[str] = Field(default_factory=list)
    terminology: dict[str, str] = Field(default_factory=dict)
    """Term → the world's note on how it is used ("legacy 'department' and new
    'category' are both in use and not interchangeable"). From TERMINOLOGY lore
    constraints — the one constraint kind whose effect *is* prose — so a pack
    that declares its industry's vocabulary sees it reach the writer. Advisory:
    guidance for the author, not a rejection rule, because vocabulary is a
    register question and the validators police facts, not style."""
    target_words: int = 120
    avoid_texts: list[str] = Field(default_factory=list)
    """Prose this section must not resemble, supplied verbatim.

    Carried on the *request* rather than passed alongside it, because it is
    part of what this author knows: "the close pack already says this three
    times, in these words" is a brief, not a scolding. Empty for every ordinary
    narration — it is filled only by ``worldloom refine``, where a measurement
    (`similarity.near_duplicate_pairs`) decided which sections repeat each
    other and handed the offending text back as the constraint.

    Only the ``section_prose_varied`` prompt renders it. The stock prompt has
    no slot for it, so an ordinary narration is unchanged whether this is
    populated or not — which is what keeps every existing corpus byte-identical
    through the addition of the field."""
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
