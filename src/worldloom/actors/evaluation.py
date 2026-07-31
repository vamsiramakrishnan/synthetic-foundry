"""Evaluation families that only exist because actors do.

The test this file has to pass is the one in ``docs/actor-simulation.md`` §A10:
actor simulation must make the corpus *harder*, not merely longer. A question is
only worth generating here if the non-actor corpus could not pose it — so every
family below turns on something the deterministic planner does not produce:

- **temporal knowledge** — who had confirmed the cause *before* the close moved.
  Answerable only because the confirmation and the decision are separate acts by
  separate people with separate timestamps.
- **role authority** — who was entitled to move the close, and who approved.
  Answerable only because the decision record names both.
- **action provenance** — which accepted tool call produced a record.
- **task ownership** — who owns the fix that addresses the control rather than
  the detection.
- **information asymmetry** — what the executive summary left out that the RCA
  carries. Two documents by two authors from two observations.
- **expected abstention** — questions the corpus deliberately cannot answer.

Every candidate is filtered against what an artifact actually carries before it
is emitted. A case citing a fact no document holds is unanswerable, and the
validator is right to refuse it — so it is never generated rather than generated
and then explained away.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..ids import Minter
from ..models import EvaluationCase, EvaluationType
from .models import ActorLedgerEntry, ActorTask, Observation

if TYPE_CHECKING:  # pragma: no cover
    from ..world import World


def _carried(world: World) -> dict[str, list[str]]:
    """Fact id to the artifacts that carry it."""
    out: dict[str, list[str]] = {}
    for intent in world.artifact_intents:
        for fact_id in intent.required_fact_ids:
            out.setdefault(fact_id, []).append(intent.id)
    return out


def _first(world: World, kind: str, *, text_contains: str = "") -> str | None:
    """The earliest fact of *kind*, optionally matching text. ``None`` if absent."""
    for fact in world.facts:
        if fact.kind == kind and text_contains in (fact.text_value or ""):
            return fact.id
    return None


def _last(world: World, kind: str, *, text_contains: str = "") -> str | None:
    found = [
        fact.id
        for fact in world.facts
        if fact.kind == kind and text_contains in (fact.text_value or "")
    ]
    return found[-1] if found else None


def cases(
    minter: Minter,
    *,
    world: World,
    entries: tuple[ActorLedgerEntry, ...],
    observations: tuple[Observation, ...],
    tasks: tuple[ActorTask, ...],
    period: str,
) -> tuple[EvaluationCase, ...]:
    """Generate the actor families this episode can actually support."""
    carried = _carried(world)
    accepted = [entry for entry in entries if entry.result.accepted]
    if not accepted:
        return ()

    out: list[EvaluationCase] = []

    def add(
        question: str,
        kind: EvaluationType,
        fact_ids: list[str | None],
        *,
        difficulty: str = "hard",
        reasoning: str,
        distractors: list[str] | None = None,
    ) -> None:
        """Emit a case, unless the corpus cannot actually answer it."""
        resolved = [f for f in fact_ids if f]
        if len(resolved) != len(fact_ids) or not resolved:
            return
        artifacts: list[str] = []
        for fact_id in resolved:
            if fact_id not in carried:
                return
            artifacts.extend(carried[fact_id])
        required = sorted(set(artifacts))
        misleading = sorted(set(distractors or []) - set(required))
        out.append(
            EvaluationCase(
                id=minter.next("EVAL"),
                question=question,
                evaluation_type=kind,
                expected_fact_ids=resolved,
                required_artifact_ids=required,
                distractor_artifact_ids=misleading,
                difficulty=difficulty,  # type: ignore[arg-type]
                reasoning=reasoning,
            )
        )

    decision = _last(world, "close.decision")
    confirmed = _last(world, "ops.cause_assessment", text_contains="Confirmed")
    dependency = _last(world, "close.dependency")
    control_fix = _first(world, "ops.remediation_owner", text_contains="control failure")
    detection_fix = _first(world, "ops.remediation_owner", text_contains="detection failure")
    classification = _last(world, "ops.root_cause_classification")
    assignee = _last(world, "ops.incident_assignee")

    stale_page = next(
        (i.id for i in world.artifact_intents if i.artifact_type == "confluence_page"), None
    )
    summary = next(
        (i.id for i in world.artifact_intents if i.artifact_type == "executive_summary"), None
    )

    # -- temporal knowledge ------------------------------------------------
    add(
        f"Had the root cause been confirmed before the {period} close date was decided?",
        EvaluationType.TEMPORAL_STATE,
        [confirmed, decision],
        reasoning=(
            "Both records carry their own moment and their own author. Answering "
            "requires ordering two acts by two people, not reading one document."
        ),
        distractors=[stale_page] if stale_page else None,
    )

    # -- role authority ----------------------------------------------------
    add(
        f"Who decided to move the {period} close, and who approved that decision?",
        EvaluationType.AUTHORITY_RESOLUTION,
        [decision],
        reasoning=(
            "The decision record names the accountable role and the approver. The "
            "close calendar states the date and says nothing about who moved it."
        ),
    )

    # -- escalation chain --------------------------------------------------
    add(
        "Who first identified that the incident put the close at risk, and who did they tell?",
        EvaluationType.CAUSAL_MULTI_HOP,
        [dependency],
        reasoning=(
            "The dependency was raised by finance, not by the team that found the "
            "failure — so the chain runs through an escalation rather than through "
            "the incident record."
        ),
    )

    # -- task ownership ----------------------------------------------------
    add(
        "Which remediation addresses the control failure rather than only detection, "
        "and who owns it?",
        EvaluationType.CROSS_ARTIFACT,
        [control_fix],
        reasoning=(
            "Two tickets, and the cheaper one improves detection only. The "
            "distinction is stated on the record rather than inferable from the "
            "titles."
        ),
        distractors=[summary] if summary else None,
    )
    add(
        "Which remediation improves detection without fixing the underlying control?",
        EvaluationType.CROSS_ARTIFACT,
        [detection_fix],
        difficulty="medium",
        reasoning="The counterpart to the control fix, and the one an unwary reader approves.",
    )

    # -- information asymmetry --------------------------------------------
    add(
        "What did the executive summary leave out that the incident review records?",
        # Cross-artifact, not abstention: the answer exists, it is simply in the
        # other document. An abstention case is one the corpus cannot answer at
        # all, and conflating the two teaches a system to refuse when it should
        # go and look.
        EvaluationType.CROSS_ARTIFACT,
        [classification],
        reasoning=(
            "The control failure is in the review and not in the summary. The two "
            "were written by different people from different observations, so the "
            "omission is a citation the CFO did not make rather than an editing rule."
        ),
        distractors=[summary] if summary else None,
    )

    # -- action provenance -------------------------------------------------
    add(
        "Who was the incident assigned to, and by whom?",
        EvaluationType.DIRECT_LOOKUP,
        [assignee],
        difficulty="easy",
        reasoning="The assignment is a committed act with a named actor on both ends.",
    )

    # -- expected abstention ----------------------------------------------
    # Generated only when the episode really did leave this open, which is the
    # point: an abstention case that the corpus could in fact answer is worse
    # than no abstention case, because it trains a system to refuse.
    if not any(task.kind == "remediation" and task.state == "closed" for task in tasks):
        out.append(
            EvaluationCase(
                id=minter.next("EVAL"),
                question=(
                    "Was the remediation that assigns ownership of the mapping table "
                    "completed, and on what date?"
                ),
                evaluation_type=EvaluationType.EXPECTED_ABSTENTION,
                expects_abstention=True,
                difficulty="hard",
                reasoning=(
                    "The ticket was raised and owned; nothing in the corpus records it "
                    "closing. A system that answers has invented a completion."
                ),
            )
        )

    if observations:
        # One question that is only answerable from the observation ledger, and
        # exists to make that ledger load-bearing rather than an appendix.
        watcher = accepted[0].invocation.actor_id
        earliest = min(o.learned_at for o in observations if o.observer_id == watcher)
        add(
            "Which employee was first to have a record of the valuation failure, "
            f"and at what time on {earliest.date().isoformat()}?",
            EvaluationType.TEMPORAL_STATE,
            [_first(world, "ops.feed_status")],
            reasoning=(
                "Answerable from who was paged and when, not from the fact's own "
                "validity — the failure was true before anybody knew it."
            ),
        )

    return tuple(out)


__all__ = ["cases"]
