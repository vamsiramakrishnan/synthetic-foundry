"""The authoring loop, stated once — every authorable layer is the same machine.

The layers of this repository that a harness authors — a physics probe, a line
of business, a process, a document type, an estate, and the prose itself —
each grew the same shape independently before the shape had a name:

    seed → Session → Brief (context + constraints) → propose → lint →
    refuse-with-findings → revise → accept → resolve → install → replay

That loop is the product's one grammar. ``narrate accept`` is it over prose,
``compose accept`` over an estate, ``act accept`` over a decision; ``lob.py``
and ``process.py`` run it over declarations and import their shared pieces
from here. The invariants below are the protocol, stated once so a fifth
implementation conforms by reading one docstring instead of diffing four:

- **A refusal carries findings a reviser can act on.** *Every* finding, not
  the first — a reviser fixing one violation per round-trip is a reviser
  paying a turn per rule it could not see. Each finding names the thing
  proposed, the rule it broke, and what to do instead, because "invalid" can
  only be guessed at. And nothing is committed on a refusal: the session that
  refused an answer is unchanged, so revision starts from exactly the state
  the proposal was judged against. A refusal is data, not failure — it is the
  harness working.

- **Stages are ordered, and a stage is settled before the next opens.** The
  brief for a later stage carries what earlier stages accepted — a process's
  slots stage sees the accepted steps, a probe's frontier hands over the
  bounds earlier answers established — so every answer is written inside the
  box the accepted work built. ``next_stage`` asks for the first unsettled
  stage; there is no way to answer out of order because the later question
  does not exist yet.

- **Context rides every brief.** The question travels with the company it is
  about — engine, facets, the owning LOB's roles and responsibilities — so a
  harness can answer for *this* world without opening ``src/``. The brief is
  the boundary, exactly as ``requests.json`` is for narration: if something
  is not in the brief, the answer may not rely on it.

- **Only the resolved spec ever replays.** The session, its briefs, and its
  refused answers are working state; what rides a pack or a recipe is the
  resolved artifact, and replay rebuilds from *that*. The conversation is
  never replayed: recording it would be a second account of how the spec came
  to be, free to drift from the first — the same argument ``lob.participation``
  makes against a stored participation table.

Two implementations conform structurally rather than by import, on purpose.
``probe.py``'s brief carries propagated interval bounds and its refusals are
typed ``Rejection``s — both richer than the shared shapes, and flattening them
here would trade information for uniformity. ``doctypes.py`` is the degenerate
instance: a document type is proposed whole, so it has a lint and no session.
Each says so in its own docstring; forcing either onto these types would have
grown them, which is the one outcome extraction is not allowed to have.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field as _field
from pathlib import Path
from typing import Any, NoReturn, TypeVar

from pydantic import BaseModel, ConfigDict

__all__ = ["Brief", "CascadeModel", "Finding", "load", "refuse"]


#: One reason a proposal cannot be accepted, as a sentence a reviser can act
#: on. A plain string rather than a dataclass, deliberately: every lint in the
#: conforming modules returns ``list[str]``, and the discipline that matters —
#: name the thing, the rule, and the fix — lives in the text, where a schema
#: cannot enforce it and a reader cannot miss it.
Finding = str


class CascadeModel(BaseModel):
    """Base for cascade schema objects: seeds, answers, resolved specs.

    Frozen, because an accepted answer is a record and a record that can be
    edited after acceptance is one the lint never saw. ``extra="forbid"``,
    because a misspelled field silently dropped is worse than a refusal: the
    proposal the lint judged would not be the one the author wrote.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


@dataclass(frozen=True)
class Brief:
    """The next question in a cascade, with the context needed to answer it.

    The stage names are each cascade's own (``'roles'``, ``'steps'``, …) —
    the protocol fixes the *shape* of a question, not the questions.
    """

    stage: str
    """Which stage this brief opens. An ``Answer`` echoes it back, so an
    answer to a stale brief is refused by name rather than misapplied."""
    asks: str
    """The question, as instructions a harness can follow without reading the
    source — the rules the stage will enforce belong here, stated before
    anything is proposed, not discovered one refusal at a time."""
    context: dict[str, Any] = _field(default_factory=dict)
    """Everything needed to answer well: the company, and whatever earlier
    stages accepted. The boundary — an answer may not rely on anything
    outside it."""


def refuse(subject: str, findings: Sequence[Finding]) -> NoReturn:
    """Refuse a proposal, naming its findings. Nothing has been committed.

    The first three findings in full and a count of the rest: enough for a
    reviser to start on the concrete violations without the message drowning
    them, and the count says a resubmission fixing only these three is not
    done. The full list is whatever lint produced it — a caller that wants
    every finding as data calls the lint directly, which is why every
    conforming module exposes its lints by name.
    """
    raise ValueError(
        f"{subject} rejected: {'; '.join(findings[:3])}"
        + (f"; and {len(findings) - 3} more" if len(findings) > 3 else "")
    )


SeedT = TypeVar("SeedT", bound=BaseModel)


def load(source: str | Path | dict[str, Any], model: type[SeedT]) -> SeedT:
    """Load a seed from a path, JSON text, or parsed data.

    All three forms, because a seed arrives three ways — a file a harness
    wrote, JSON pasted into a call, a dict built in Python — and a loader
    that accepted fewer would push the conversion onto every caller. The
    existence check decides path-versus-text, so a JSON string is never
    mistaken for a missing file.
    """
    if isinstance(source, (str, Path)) and Path(str(source)).exists():
        source = json.loads(Path(source).read_text(encoding="utf-8"))
    elif isinstance(source, str):
        source = json.loads(source)
    return model.model_validate(source)
