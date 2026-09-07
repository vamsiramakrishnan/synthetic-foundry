"""The work shape of a request: what the asker wants done.

`EvaluationType` says how an answer is *checked* — a direct lookup, a
numerical comparison, an expected abstention. All eight of its values are
retrieval shapes, which is the right vocabulary for grading and the wrong one
for describing work. Nobody in an enterprise asks for a cross-artifact
retrieval; they ask someone to chase an approval, close out a change, or
justify a decision they are about to sign.

This module carries the other half: an `Intent` is a verb a person in a seat
would actually use, and it declares what a correct response has to contain.
The two vocabularies stay separate on purpose. Intent is the *work* shape,
`EvaluationType` stays the *grading* shape, and each intent names which
grading shape checks it, so adding a verb never adds a grader.

The table is authored data (`_data/evals/intents.json`, schema
`worldloom.eval-intents/v1`) rather than a literal here, for the reason
`narrative/prompts` and the connector definitions are data: the schema name
carries a version, so a change to what an intent means is a new version
instead of an edit that silently reinterprets every corpus already scored
against it.

`applicable` is the filter that makes the table usable. A process binding
already declares its activity `type` (capture, approve, execute, reconcile,
notify, escalate, decide, report), and most verbs only make sense for some of
them: you sign off on an approval step, you triage a capture queue, and
neither sentence works with the other's verb. Filtering by that declared type
is what keeps a generated situation plausible without anyone hand-listing
which questions suit which activity.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal

from pydantic import Field, model_validator

from ..models import EvaluationType, Model

INTENT_SCHEMA: Literal["worldloom.eval-intents/v1"] = "worldloom.eval-intents/v1"

#: The activity types a process binding may declare. Closed, and identical to
#: the vocabulary `process_bindings` compiles, because an intent that claimed
#: applicability to a type no binding carries could never be selected and
#: would look like coverage without being any.
ACTIVITY_TYPES: tuple[str, ...] = (
    "approve",
    "capture",
    "decide",
    "escalate",
    "execute",
    "notify",
    "reconcile",
    "report",
)

#: What a correct response looks like before anything grades it. Deliberately
#: coarse: this says whether the asker expects a number, a ranking or a
#: document, not how good the document is.
ANSWER_SHAPES: tuple[str, ...] = (
    "comparison",
    "decision",
    "document",
    "list",
    "message",
    "narrative",
    "ranked_list",
    "record_change",
    "refusal",
    "value",
)


class Intent(Model):
    """One verb an asker would use, and what answering it requires."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    """Stable key. Appears on an `EvaluationCase`, so it is a wire value."""
    verb: str = Field(min_length=1)
    """How a person says it, for rendering the request surface."""
    effect: Literal["read", "write"]
    """Whether answering changes state. A write intent owes a deliverable."""
    answer_shape: str
    """One of `ANSWER_SHAPES`."""
    evidence_kinds: tuple[str, ...] = ()
    """What the answer must rest on. Empty only for an abstention."""
    deliverable: str | None = None
    """What a write produces. `None` exactly when the effect is a read."""
    grading: EvaluationType
    """Which existing grading shape checks this verb."""
    assertions: tuple[str, ...] = ()
    """What a grader asserts beyond the grading shape's own rule."""
    failure_mode: str = Field(min_length=1)
    """The mistake this intent is posed to catch. The reason it earns a row."""
    activity_types: tuple[str, ...] = ()
    """Binding activity types this verb suits. Empty means every type."""

    @model_validator(mode="after")
    def _closed_vocabularies(self) -> Intent:
        if self.answer_shape not in ANSWER_SHAPES:
            raise ValueError(f"{self.id}: unknown answer shape {self.answer_shape!r}")
        unknown = [t for t in self.activity_types if t not in ACTIVITY_TYPES]
        if unknown:
            raise ValueError(f"{self.id}: unknown activity type {unknown[0]!r}")
        # A write with nothing to show for it cannot be graded by inspecting
        # the world afterwards, and a read that claims a deliverable would be
        # graded against an artifact it was never asked to produce.
        if (self.deliverable is None) != (self.effect == "read"):
            raise ValueError(
                f"{self.id}: a write intent needs a deliverable and a read intent"
                " must not declare one"
            )
        if self.effect == "read" and self.answer_shape == "record_change":
            raise ValueError(f"{self.id}: a read cannot answer with a record change")
        if not self.evidence_kinds and self.grading is not EvaluationType.EXPECTED_ABSTENTION:
            raise ValueError(f"{self.id}: only an abstention may require no evidence")
        return self

    def suits(self, activity_type: str) -> bool:
        """Whether this verb makes sense for an activity of *activity_type*."""
        return not self.activity_types or activity_type in self.activity_types


def _parse(payload: str) -> dict[str, Intent]:
    raw: dict[str, Any] = json.loads(payload)
    schema = raw.get("schema")
    if schema != INTENT_SCHEMA:
        raise ValueError(f"expected schema {INTENT_SCHEMA!r}, found {schema!r}")
    intents = [Intent.model_validate(row) for row in raw.get("intents", ())]
    table: dict[str, Intent] = {}
    for intent in intents:
        if intent.id in table:
            raise ValueError(f"duplicate intent {intent.id!r}")
        table[intent.id] = intent
    if not table:
        raise ValueError("the intent table is empty")
    return dict(sorted(table.items()))


@lru_cache(maxsize=1)
def intents() -> dict[str, Intent]:
    """The authored intent table, keyed by id in sorted order.

    Sorted rather than file order because this dictionary is iterated to build
    situations, and iteration order that follows an editor's cursor is exactly
    the kind of accident `AGENTS.md` bans from reaching output.
    """
    resource = files("worldloom").joinpath("_data", "evals", "intents.json")
    return _parse(resource.read_text(encoding="utf-8"))


def intent(intent_id: str) -> Intent:
    """One intent by id, or a `ValueError` naming what was asked for."""
    table = intents()
    if intent_id not in table:
        raise ValueError(f"unknown intent {intent_id!r}")
    return table[intent_id]


def applicable(
    activity_type: str, *, effect: Literal["read", "write"] | None = None
) -> tuple[Intent, ...]:
    """The intents that suit an activity of *activity_type*, in id order.

    `effect` narrows further, for a caller that wants only the verbs which
    change state (or only those which do not). An unknown activity type is a
    `ValueError` rather than an empty tuple: silently returning nothing would
    read downstream as "this binding supports no work", which is never true.
    """
    if activity_type not in ACTIVITY_TYPES:
        raise ValueError(f"unknown activity type {activity_type!r}")
    return tuple(
        i
        for i in intents().values()
        if i.suits(activity_type) and (effect is None or i.effect == effect)
    )


__all__ = [
    "ACTIVITY_TYPES",
    "ANSWER_SHAPES",
    "INTENT_SCHEMA",
    "Intent",
    "applicable",
    "intent",
    "intents",
]
