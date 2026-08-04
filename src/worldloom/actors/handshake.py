"""The actor handshake.

Worldloom does not call a model, and that does not stop being true when the model
is an employee rather than an author:

    worldloom act requests ./corpus -o decision.json
    # the agent reads what this employee can see, and writes action.json
    worldloom act accept ./corpus --from action.json

One decision at a time, because actor decisions are not independent. Narration
hands an agent every request at once — a memo's third section does not depend on
its second having been written. An episode does: what the controller can see at
09:40 depends on whether the business partner escalated at 09:12, so the
invocations cannot be prepared in advance without deciding the episode first.

**Resuming, without a suspend format.** The obvious way to pause a running
simulation is to serialise its mid-flight state, which would mean a second
on-disk representation of a world and a second thing to keep in step with the
first. There is a better one available here and it costs nothing: the episode is
a pure function of the recipe plus the recorded decisions, so resuming is
*rebuilding*. Each call regenerates the world from `worldloom.recipe`, replays
every decision the ledger already holds — the provider is never asked for those —
and stops at the first decision nobody has taken. The ledger is the save file, and
it was already shipping.

That costs one rebuild per turn. For the retail-close episode that is about forty
rebuilds of a world that takes under a second to make, which is the right trade
for not inventing a state format that can disagree with the corpus.

**Nothing is committed unless the action is legal.** A tool call that exceeds the
role's authority, cites a fact the actor never observed, or breaks a precondition
comes back with the rule it broke, and the world is untouched — the same contract
`narrate accept` has, for the same reason. Rejection is the harness working.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .. import recipe as recipe_module
from ..models import GenerationLedgerEntry
from .models import ActorAction
from .providers import ObservationView
from .tools import base as tool_base

if TYPE_CHECKING:  # pragma: no cover
    from ..world import World

#: Stated in every request, so an agent needs no other source for the contract.
RULES: tuple[str, ...] = (
    "You are this employee, at this moment. Everything you know is in `facts`,"
    " `messages`, and `tasks` below. There is no other context to go and find.",
    "Call exactly one tool, chosen from `tools`. Every tool you are shown is one"
    " your role is permitted to call; there are no others.",
    "Any argument naming a fact must use an id from `facts`. Citing a fact you"
    " were not shown is rejected — you did not see it, so you cannot use it.",
    "Name systems, services, and business units by the ids in `entities`, and"
    " roles by the keys in `roles` and `resources`. Invent no identifier.",
    "You may abstain. Set `tool_name` to null and give an `abstention_reason`."
    " Abstaining is a real answer when nothing legal and useful remains, and it"
    " is recorded as one.",
    "Act as the role would. A service desk analyst raises a ticket and does not"
    " diagnose; a controller decides the calendar and does not touch the incident"
    " record. `title` and `voice` tell you who you are.",
    "You are not writing a document. `draft_artifact` decides that one should"
    " exist and which of the facts you have seen belong in it; its structure and"
    " prose are produced later, under separate constraints.",
    "Prefer the fact you observed over the fact you were told. `learned_via` and"
    " `confidence` on each fact say which is which.",
)


class PendingDecision(Exception):
    """Raised when the episode reaches a decision nobody has taken yet.

    Carries everything the caller needs to either ask for it or resume past it:
    the view the actor would have read, the tools it may call, and the ledger of
    every decision replayed on the way here.
    """

    def __init__(self, view: ObservationView, tools: tuple[tool_base.ToolSpec, ...]) -> None:
        self.view = view
        self.tools = tools
        self.ledger: tuple[GenerationLedgerEntry, ...] = ()
        """Filled in by ``run_episode`` as the exception passes through it."""
        self.entries: tuple = ()
        super().__init__(f"awaiting a decision for {decision_id(view)}")


def decision_id(view: ObservationView) -> str:
    """What an agent answers. Stable across rebuilds, because both halves are."""
    return f"{view.invocation.id}#{view.turn}"


class PausingProvider:
    """Serves supplied actions, and stops the episode at the first one missing.

    The provider the whole handshake is built on. It answers nothing itself: a
    decision is either one the agent has already made — replayed from the ledger
    by the runtime before this is ever called, or handed in as an argument — or
    it is the one the episode is waiting for.
    """

    def __init__(self, actions: dict[str, dict[str, Any]] | None = None, *, model_id: str) -> None:
        self.actions = dict(actions or {})
        self.id = model_id
        self.served: list[str] = []
        """Decision ids this provider actually answered from the supplied set.

        Distinct from what the ledger replayed, and the distinction matters at
        accept time: only a *newly supplied* action can be rejected in a way the
        agent needs to hear about. One replayed from the ledger was accepted when
        it was recorded.
        """

    def act(self, view: ObservationView, tools: tuple[tool_base.ToolSpec, ...]) -> ActorAction:
        identifier = decision_id(view)
        row = self.actions.get(identifier)
        if row is None:
            raise PendingDecision(view, tools)
        self.served.append(identifier)
        return ActorAction(
            invocation_id=view.invocation.id,
            tool_name=row.get("tool_name"),
            arguments=row.get("arguments", {}),
            confidence=float(row.get("confidence", 1.0)),
            abstention_reason=row.get("abstention_reason"),
        )


class Resumption:
    """Where a rebuild got to, and what it produced on the way."""

    def __init__(
        self,
        *,
        pending: PendingDecision | None,
        world: World | None,
        ledger: tuple[GenerationLedgerEntry, ...],
        entries: tuple,
        served: list[str],
    ) -> None:
        self.pending = pending
        self.world = world
        self.ledger = ledger
        self.entries = entries
        self.served = served

    @property
    def complete(self) -> bool:
        """Whether the episode ran to the end with nothing left to decide."""
        return self.pending is None


def model_id_for(world: World) -> str:
    """The actor model id this corpus's episode was started with.

    Pinned in the recipe on the first accepted decision rather than passed on
    every command, because it is part of the ledger key: answering turn nine
    under a different id would miss every key from turns one to eight and
    silently restart the episode from the beginning.
    """
    return world.recipe.get("actor_model_id") or "agent"


def resume(
    world: World,
    *,
    actions: dict[str, dict[str, Any]] | None = None,
    model_id: str | None = None,
) -> Resumption:
    """Rebuild, replay, apply *actions*, and stop at the first undecided turn."""
    if not recipe_module.has_actor_step(world.recipe):
        raise recipe_module.RecipeError(
            "this corpus has no actor episode to drive."
            " Build one with `worldloom build --actors agent`."
        )
    provider = PausingProvider(actions, model_id=model_id or model_id_for(world))
    try:
        rebuilt = recipe_module.rebuild(
            world.recipe, actors=provider, actor_ledger=world._ledger,
            # The same ledger again, under the argument a `Compose` step reads
            # it from. An actor episode on a corpus whose estate a model
            # authored would otherwise fail to rebuild — the composition lives
            # in this ledger, and `rebuild` refuses rather than quietly
            # producing the uncomposed world.
            ledger=world._ledger,
        )
    except PendingDecision as pending:
        return Resumption(
            pending=pending,
            world=None,
            ledger=pending.ledger,
            entries=pending.entries,
            served=provider.served,
        )
    return Resumption(
        pending=None,
        world=rebuilt,
        ledger=rebuilt._ledger,
        entries=rebuilt._actor_ledger,
        served=provider.served,
    )


def requests_document(world: World) -> dict[str, Any]:
    """The next decision, described well enough to answer without this repository."""
    outcome = resume(world)
    if outcome.complete:
        return {"decision": None, "complete": True, "rules": list(RULES)}

    pending = outcome.pending
    assert pending is not None
    view = pending.view
    return {
        "worldloom_seed": world.seed,
        "company": world.company.name,
        "complete": False,
        "rules": list(RULES),
        "response_shape": {
            "actions": [
                {
                    "id": "<the id of the decision you are answering>",
                    "tool_name": "<a name from tools, or null to abstain>",
                    "arguments": {"<argument>": "<value>"},
                    "abstention_reason": "<only when tool_name is null>",
                }
            ]
        },
        "decision": {
            "id": decision_id(view),
            **view.to_payload(),
            "tools": [spec.to_payload() for spec in pending.tools],
        },
    }


def parse_actions(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Read a response document into actions, keyed by decision id."""
    rows = payload.get("actions")
    if not isinstance(rows, list):
        raise ValueError("expected a top-level 'actions' list")

    out: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict) or "id" not in row:
            raise ValueError(f"action {index} has no 'id'")
        if row.get("tool_name") is None and not row.get("abstention_reason"):
            raise ValueError(
                f"action {row['id']}: an abstention must give an abstention_reason"
            )
        out[str(row["id"])] = {
            "tool_name": row.get("tool_name"),
            "arguments": row.get("arguments", {}),
            "confidence": row.get("confidence", 1.0),
            "abstention_reason": row.get("abstention_reason"),
        }
    return out


class Acceptance:
    """The verdict on one submission."""

    def __init__(
        self,
        *,
        world: World | None,
        rejections: dict[str, str],
        applied: list[str],
        complete: bool,
        model_id: str,
    ) -> None:
        self.world = world
        self.rejections = rejections
        self.applied = applied
        self.complete = complete
        self.model_id = model_id

    @property
    def accepted(self) -> bool:
        return not self.rejections


def accept(
    world: World,
    actions: dict[str, dict[str, Any]],
    *,
    model_id: str | None = None,
) -> Acceptance:
    """Validate and commit *actions*, or return every rule they broke.

    Commits the *ledger*, not a finished world, while the episode is still
    running. That is not a shortcut — mid-episode there is no finished world to
    write, and the ledger is what the next call replays from. When the last
    decision lands, the rebuilt world is complete and is returned whole.
    """
    pinned = world.recipe.get("actor_model_id")
    chosen = model_id or pinned or "agent"
    if pinned and model_id and model_id != pinned:
        raise ValueError(
            f"this episode was started under model id {pinned!r}."
            f" Answering under {model_id!r} would miss every key recorded so far"
            " and silently restart it. Use the original id, or rebuild the corpus."
        )

    outcome = resume(world, actions=actions, model_id=chosen)

    # Only a newly supplied action can be rejected in a way the agent needs to
    # hear about; anything replayed from the ledger was accepted when recorded.
    ordinals = {entry.key: entry.ordinal for entry in outcome.ledger}
    rejections: dict[str, str] = {}
    for entry in outcome.entries:
        if entry.result.accepted or entry.action.tool_name is None:
            continue
        identifier = f"{entry.invocation.id}#{ordinals.get(entry.key, entry.sequence)}"
        if identifier in outcome.served:
            rejections[identifier] = entry.result.rejection_reason or "rejected"

    unknown = sorted(set(actions) - set(outcome.served))
    for identifier in unknown:
        rejections[identifier] = (
            "no decision with this id was pending. Run `worldloom act requests`"
            " and answer the decision it names."
        )

    if rejections:
        return Acceptance(
            world=None, rejections=rejections, applied=[], complete=False, model_id=chosen
        )

    updated_recipe = {**world.recipe, "actor_model_id": chosen}
    if outcome.complete:
        assert outcome.world is not None
        from dataclasses import replace as _replace

        # The finished world already carries a recipe its own scenarios rebuilt;
        # only the model id has to be carried across, because that is a property
        # of who answered rather than of what was run.
        committed = _replace(
            outcome.world, _recipe={**outcome.world.recipe, "actor_model_id": chosen}
        )
    else:
        # Mid-episode: merge by key, the same way narration does. A decision
        # replayed and re-recorded must not appear twice, or "which call produced
        # this" has two answers.
        merged = {entry.key: entry for entry in world._ledger}
        merged.update({entry.key: entry for entry in outcome.ledger})
        from dataclasses import replace as _replace

        committed = _replace(world, _ledger=tuple(merged.values()), _recipe=updated_recipe)

    return Acceptance(
        world=committed,
        rejections={},
        applied=list(outcome.served),
        complete=outcome.complete,
        model_id=chosen,
    )


def dump(document: dict[str, Any]) -> str:
    """Serialise a decision document."""
    import json

    return json.dumps(document, indent=2) + "\n"


__all__ = [
    "Acceptance",
    "PausingProvider",
    "PendingDecision",
    "RULES",
    "Resumption",
    "accept",
    "decision_id",
    "dump",
    "model_id_for",
    "parse_actions",
    "requests_document",
    "resume",
]
