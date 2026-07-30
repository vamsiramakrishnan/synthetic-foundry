"""Providers.

A provider turns a request and a prompt into a narrative. That is the entire
interface, and it is deliberately small enough that a real adapter is a thin
wrapper over whatever SDK it needs.

No real provider ships here. The interface plus a deterministic fake is the useful
thing to land first: the whole pipeline — request shaping, claim extraction, the
validation loop, ledger write and replay — is then testable with no API key, no
network, and no spend, and the first real adapter gets written against a contract
that already works.

``DeterministicProvider`` is **not** a stand-in for a language model. It composes
sentences from templates keyed on fact kind. It exists to exercise the contract, not
to write well, and any judgement about narrative quality must wait for a real
adapter. What it does prove is that the contract is satisfiable: it emits fact
references rather than figures, attaches claims, and respects the temporal cut-off.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ..ids import content_key
from .prompts import Prompt
from .requests import GeneratedClaim, GeneratedNarrative, NarrativeRequest

if TYPE_CHECKING:  # pragma: no cover
    from ..models import CanonicalFact


class ProviderError(Exception):
    """Raised when a provider cannot answer."""


@runtime_checkable
class Provider(Protocol):
    """Anything that can turn a request into a narrative."""

    id: str
    """Model identifier. Part of the ledger key, so changing it changes the world."""

    def complete(
        self,
        request: NarrativeRequest,
        prompt: Prompt,
        facts: dict[str, CanonicalFact],
        *,
        feedback: str = "",
    ) -> GeneratedNarrative:
        """Produce prose for *request*. ``feedback`` carries a prior rejection."""
        ...


# ---------------------------------------------------------------------------
# The deterministic fake
# ---------------------------------------------------------------------------

#: Sentence shapes by fact kind prefix. Longest prefix wins.
_SHAPES: tuple[tuple[str, str], ...] = (
    ("financial.revenue.actual", "Revenue for the period was {ref}."),
    ("financial.revenue.budget", "Budgeted revenue was {ref}."),
    ("financial.revenue.variance", "Revenue finished {ref} against plan."),
    ("financial.gross_profit.actual", "Gross profit was {ref}."),
    ("financial.gross_profit.budget", "Gross profit was budgeted at {ref}."),
    ("financial.gross_profit.variance", "Gross profit finished {ref} against plan."),
    ("financial.gross_margin_pct.actual", "Gross margin came in at {ref}."),
    ("financial.gross_margin_pct.budget", "Gross margin was budgeted at {ref}."),
    ("financial.incident_pl_impact", "The impact on the reported result was {ref}."),
    ("metric.online_conversion_rate.actual", "Online conversion ran at {ref}."),
    ("metric.online_conversion_rate.forecast", "Conversion had been forecast at {ref}."),
    ("metric.promotional_depth_margin_impact", "Promotional depth weighed on margin by {ref}."),
    ("metric.gross_margin_variance", "Margin moved {ref} against budget."),
    ("close.due_date", "The close was committed for {ref}."),
    ("close.revised_date", "The revised close date was {ref}."),
    ("close.status", "Close status stood at {ref}."),
    ("close.delay", "The close landed {ref} beyond the committed date."),
    ("ops.feed_status", "The valuation feed reported {ref}."),
    ("ops.incident_opened", "An incident was raised: {ref}."),
    ("ops.cause_ruled_out", "One line of enquiry was closed off: {ref}."),
    ("ops.cause", "The cause was recorded as {ref}."),
    ("ops.affected_records", "The scope was {ref}."),
    ("ops.workaround", "A workaround was applied: {ref}."),
    ("ops.valuation_status", "Valuation status: {ref}."),
    ("ops.root_cause_classification", "The underlying issue was classified as {ref}."),
    ("ops.mapping_table_owner", "Ownership of the mapping table is {ref}."),
    ("ops.previous_similar_incident", "There is precedent: {ref}."),
    ("ops.remediation_addresses", "On remediation scope: {ref}."),
    ("ops.remediation", "Remediation was raised: {ref}."),
)


def _shape(kind: str) -> str:
    """The sentence shape for a fact kind, longest prefix first."""
    best = ""
    for prefix, template in _SHAPES:
        if kind.startswith(prefix) and len(prefix) > len(best):
            best, shape = prefix, template
    return shape if best else "The record notes {ref}."


class DeterministicProvider:
    """A provider with no model behind it.

    Given the same request it returns the same narrative, always, with no clock and
    no randomness beyond a seed derived from the request itself. That makes the
    whole pipeline testable in CI, and it makes a ledger replay test meaningful:
    the recorded output and a fresh generation are comparable because generation is
    itself reproducible.

    It writes plainly and repetitively. That is the point — it is a contract
    fixture, and prose quality is a question for a real adapter.
    """

    id = "deterministic-fake-1"

    def __init__(self, *, respect_cutoff: bool = True) -> None:
        self.respect_cutoff = respect_cutoff
        self.calls = 0
        """How many times this provider was actually asked. A replay leaves it at zero."""

    def complete(
        self,
        request: NarrativeRequest,
        prompt: Prompt,
        facts: dict[str, CanonicalFact],
        *,
        feedback: str = "",
    ) -> GeneratedNarrative:
        self.calls += 1

        usable = []
        for fact_id in request.allowed_fact_ids:
            fact = facts.get(fact_id)
            if fact is None:
                continue
            if (
                self.respect_cutoff
                and request.temporal_cutoff is not None
                and fact.valid_from > request.temporal_cutoff
            ):
                # The author could not have known this yet.
                continue
            usable.append(fact)

        # Required facts first, then enough others to reach a plausible length. A
        # deterministic budget rather than a random one, so output is stable.
        required = [f for f in usable if f.id in request.required_fact_ids]
        optional = [f for f in usable if f.id not in request.required_fact_ids]
        budget = max(len(required), min(len(usable), max(2, request.target_words // 18)))
        chosen = required + optional[: max(0, budget - len(required))]

        sentences: list[str] = []
        claims: list[GeneratedClaim] = []
        for fact in chosen:
            reference = f"{{{{fact:{fact.id}}}}}"
            # A fact that had already expired when the author wrote is history, and
            # must read as history rather than as the current position.
            historical = (
                request.temporal_cutoff is not None
                and fact.valid_to is not None
                and fact.valid_to <= request.temporal_cutoff
            )
            if historical:
                sentence = f"At the time it was recorded as {reference}, which was later superseded."
            else:
                sentence = _shape(fact.kind).format(ref=reference)
            sentences.append(sentence)
            claims.append(GeneratedClaim(text=sentence, supporting_fact_ids=[fact.id]))

        if not sentences:
            sentences.append("Nothing material to report for this section.")

        return GeneratedNarrative(text=" ".join(sentences), claims=claims)

    def __repr__(self) -> str:
        return f"DeterministicProvider(calls={self.calls})"


class UnreachableProvider:
    """A provider that refuses to answer.

    Used to prove replay: regenerate a world whose ledger is present, hand it this,
    and every call must be served from the ledger. A single ``ProviderError`` means
    replay is incomplete.
    """

    id = "deterministic-fake-1"
    """Matches the fake's ID on purpose — a replay must hit the same keys."""

    def complete(self, request, prompt, facts, *, feedback=""):  # type: ignore[no-untyped-def]
        raise ProviderError(
            f"provider unreachable, and no ledger entry for {request.artifact_id}/{request.section}."
            " Replay is incomplete."
        )


class ViolatingProvider:
    """A provider that breaks the rules on its first attempt, then complies.

    Exists so the validation loop is proven to reject rather than assumed to. A loop
    that has never rejected anything is not a loop, it is a pass-through.
    """

    id = "violating-fake-1"

    def __init__(self, *, violations: int = 1) -> None:
        self.violations = violations
        self.calls = 0

    def complete(
        self,
        request: NarrativeRequest,
        prompt: Prompt,
        facts: dict[str, CanonicalFact],
        *,
        feedback: str = "",
    ) -> GeneratedNarrative:
        self.calls += 1
        if self.calls <= self.violations:
            # A restated figure and an unsupported claim: the two failures that
            # matter most, together.
            return GeneratedNarrative(
                text="Revenue finished 2.48% below plan, which is a material miss.",
                claims=[
                    GeneratedClaim(
                        text="Revenue finished 2.48% below plan.",
                        supporting_fact_ids=["FACT-9999"],
                    )
                ],
            )
        return DeterministicProvider().complete(request, prompt, facts, feedback=feedback)


def digest(facts: list[CanonicalFact]) -> str:
    """A content address for the facts supplied to a request.

    Includes values, not only IDs, so that correcting a figure changes the ledger
    key and the prose about it is regenerated rather than replayed stale.
    """
    parts: list[str] = []
    for fact in sorted(facts, key=lambda f: f.id):
        rendered = fact.text_value if fact.text_value else (
            f"{fact.value.amount}:{fact.value.unit}" if fact.value else ""
        )
        parts.append(f"{fact.id}|{fact.kind}|{rendered}|{fact.valid_from.isoformat()}")
    return content_key(*parts)
