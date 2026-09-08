"""Difficulty as features of the situation, not as a word somebody chose.

`EvaluationCase.difficulty` is a three-value label, and a label is an opinion.
It cannot be checked, it does not move when the corpus around it moves, and
two cases marked `hard` for different reasons are indistinguishable to anyone
trying to slice a result.

`eval_metrics` already settled the right shape for this and says so in its
first line: expose stable structural features, key a slice off them, and
estimate a pass rate per agent cohort from observed runs rather than asserting
a number. What it did not have was any feature of the *request*, because until
now a case had no request. This module supplies those, on the same contract,
so `DifficultyCalibrator` can consume them through a versioned feature contract.
Request and eval-plan slices have separate namespaces; similar key spellings
cannot silently pool observations from different measurement contracts.

The label stays. It is demoted to what it honestly is, a coarse bucket derived
from the features. `RequestFeatures.fitted` stays `False`: structural labels
do not become measurements. `DifficultyCalibrator` returns a separate estimate
with cohort observations, support and uncertainty.

Nothing here reads a clock or draws. Every feature is a function of the case,
the situation it came from, and optionally the world it was built against.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ..models import EvaluationCase, Model
from .intents import intents


class RequestFeatures(Model):
    """What makes one request harder than another, stated so it can be checked."""

    evidence_kinds: int = Field(ge=0)
    """How many distinct kinds of evidence the verb rests on. A request needing
    a policy and an approval and a record set is a wider gather than one
    needing a single fact."""
    facts_required: int = Field(ge=0)
    """How many canonical facts the answer cites."""
    artifacts_required: int = Field(ge=0)
    distractor_density: float = Field(ge=0.0, allow_inf_nan=False)
    """Distractor artifacts per required artifact. The near-miss pressure."""
    writes: bool = False
    """Whether answering changes state, which is the difference between being
    wrong and being wrong in the system of record."""
    cross_channel: bool = False
    """Whether the request arrives somewhere other than where its evidence
    lives, so the asker has to go and get it."""
    temporal: bool = False
    """Whether a cutoff is in force, so a superseded reading is reachable."""
    unstated_slots: int = Field(ge=0, le=7)
    """How many of the seven request fields the asker left unsaid. The
    underspecification the design names, counted rather than judged.

    Zero for a case carrying no request at all. A question is not a maximally
    vague request, it is a different object, and scoring it as seven unstated
    slots would make every legacy case in every corpus look like the hardest
    thing in the set."""
    standing: bool = True
    """Whether the asker has a declared reason to ask. `False` is not harder,
    it is wrong, and it is `plausibility`'s business; carried here so a slice
    can exclude it."""

    def slice_key(self) -> str:
        """Stable coarse slice, in `EvalFeatures.slice_key`'s spelling.

        Deliberately lossy: a slice with one member calibrates nothing, so the
        continuous features are bucketed before they reach the key.
        """
        density = "0" if self.distractor_density == 0 else ("1" if self.distractor_density < 1 else "2")
        return (
            f"e{self.evidence_kinds}:f{min(self.facts_required, 5)}:"
            f"a{min(self.artifacts_required, 5)}:x{density}:"
            f"w{int(self.writes)}:c{int(self.cross_channel)}:"
            f"t{int(self.temporal)}:u{self.unstated_slots}"
        )

    @property
    def fitted(self) -> bool:
        """Whether these features have been fitted to observed pass rates.

        Always `False`. The honest state until a cohort has run, and a
        property rather than a field so no caller can serialize a `True` that
        no measurement earned. `DifficultyCalibrator` is what changes it, by
        producing an estimate keyed on `slice_key`.
        """
        return False

    def bucket(self) -> str:
        """The coarse label, derived rather than chosen.

        A stand-in for `EvaluationCase.difficulty` that at least moves when the
        situation moves. It is not a measurement and does not pretend to be:
        `fitted` says so, and `DifficultyCalibrator.estimate` is what a caller
        should use once a cohort has been run.
        """
        # Bounded the way `slice_key` buckets it, so a case with a thousand
        # distractors is "hard" rather than off the scale. Declaring
        # `distractor_density` as the near-miss pressure and then omitting it
        # here would make the label disagree with the feature beside it.
        density = 0 if self.distractor_density == 0 else (1 if self.distractor_density < 1 else 2)
        weight = (
            self.evidence_kinds
            + min(self.facts_required, 5)
            + min(self.artifacts_required, 5)
            + density
            + (2 if self.writes else 0)
            + (2 if self.cross_channel else 0)
            + (2 if self.temporal else 0)
            + self.unstated_slots
        )
        if weight <= 4:
            return "easy"
        return "medium" if weight <= 9 else "hard"


def features_for(
    case: EvaluationCase, *, situation: Any = None, world: Any = None
) -> RequestFeatures:
    """The features of one case, as far as what is to hand can tell.

    `situation` supplies where the evidence lives, so that a request arriving
    by email about a record in ServiceNow is known to cross a boundary.
    `world` supplies the LOBs, so standing can be checked. Both are optional
    and their absence narrows what is claimed rather than guessing: a caller
    with neither still gets the features that come off the case alone.
    """
    table = intents()
    intent = table.get(case.intent) if case.intent else None

    required = len(case.required_artifact_ids)
    distractors = len(case.distractor_artifact_ids)
    density = distractors / required if required else float(distractors)

    cross_channel = False
    if situation is not None and case.channel is not None:
        # The system of record is where the evidence is; the channel is where
        # the request arrived. Different means the asker must go and get it.
        cross_channel = case.channel not in {"system_record", getattr(situation, "system_of_record", "")}

    standing = True
    if case.asker is not None and world is not None:
        # `world` is accepted for symmetry with the other feature sources and
        # to mark that standing is a property of the corpus, but the LOB
        # registry is process-global, so the lookup does not take it.
        from .plausibility import _standing

        known, granted = _standing(case.asker)
        standing = bool(known and granted)

    return RequestFeatures(
        evidence_kinds=len(intent.evidence_kinds) if intent else 0,
        facts_required=len(case.expected_fact_ids),
        artifacts_required=required,
        distractor_density=density,
        writes=bool(intent and intent.effect == "write"),
        cross_channel=cross_channel,
        temporal=case.temporal_cutoff is not None,
        unstated_slots=(
            sum(1 for name in EvaluationCase.REQUEST_FIELDS if getattr(case, name) is None)
            if case.has_request
            else 0
        ),
        standing=standing,
    )


__all__ = ["RequestFeatures", "features_for"]
