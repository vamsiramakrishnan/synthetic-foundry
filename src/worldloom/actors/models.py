"""The actor boundary.

These are to the actor runtime what ``worldloom.models`` is to the world: the
only vocabulary the subsystems share. Observation, invocation, action, and
result are four objects and one direction of travel —

    world → observation → invocation → action → tool result → world

— and nothing crosses that boundary sideways. In particular an actor never
receives a ``World``. It receives an ``ActorObservation``, which names ids, and a
rendered view built from those ids and nothing else. That is not a convention
kept by discipline: ``ActorProvider.act`` is not given a world to read.

Everything here is frozen and serialisable, because the execution ledger ships
with the corpus. "Which tool call produced this fact, from which observation, by
whom, and what was rejected on the way" has to be answerable from files on disk
long after the process that generated them exited.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from ..models import Model


class Observation(Model):
    """One employee learning one fact at one moment.

    Canonical facts say what is true. This says who knew it, when, and how they
    came to know — which is a different ledger and cannot be derived from the
    first. A fact valid from 08:15 is not thereby known to the CFO at 08:15, and
    a corpus that cannot tell those apart cannot pose an information-asymmetry
    question at all.

    ``confidence`` is about the *channel*, not the fact: a system of record the
    observer owns is worth more than the same figure heard second-hand in a work
    note, and an actor weighing two accounts should be able to see which is
    which.
    """

    id: str
    observer_id: str
    fact_id: str
    learned_at: datetime
    source_type: str
    """How it was learned: ``participant``, ``system_of_record``, ``duty``,
    ``message``, or ``artifact``. See ``observation.py`` for what each admits."""
    source_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class ActorMessage(Model):
    """Something one employee told others, and the facts it carried.

    Not in the roadmap's boundary list, and required by it: ``ActorObservation``
    carries ``message_ids``, and without an object for a message there is
    nothing for that field to name. It is also the only mechanism by which a
    fact reaches somebody who neither witnessed it nor owns the system that
    recorded it — remove it and knowledge either spreads by magic or does not
    spread at all.
    """

    id: str
    kind: str
    """``work_note``, ``evidence_request``, ``escalation``, ``assignment``,
    ``decision``."""
    sent_at: datetime
    sender_id: str
    recipient_ids: list[str] = Field(default_factory=list)
    subject_ref: str | None = None
    """What it is about — an incident reference, a task id, an artifact id."""
    text: str = ""
    disclosed_fact_ids: list[str] = Field(default_factory=list)
    """Facts this message put in front of its recipients. This is the payload:
    a message with no disclosure moves no knowledge."""


class ActorTask(Model):
    """Work owed by a named person, created by an accepted tool call.

    Deliberately not an ``ArtifactIntent``: a task is an obligation that outlives
    the document describing it, and the questions worth asking about one — who
    owns it, when was it assigned, did it survive a departure — are about the
    obligation rather than about any record of it.
    """

    id: str
    kind: str
    title: str
    created_at: datetime
    created_by: str
    owner_id: str | None = None
    due_at: datetime | None = None
    state: str = "open"
    """``open``, ``assigned``, or ``closed``."""
    domain: str = "operations"
    """Which function's work this is. Carried on the task rather than inferred
    from its ``kind``, because who can see a ticket is a permission question and
    a permission decided by a string prefix is one waiting to be wrong."""
    subject_ref: str | None = None
    fact_ids: list[str] = Field(default_factory=list)
    """Facts that justify the task existing."""
    addresses: str | None = None
    """What this task actually fixes — ``control`` or ``detection``.

    The distinction the RCA is required to make explicit, carried on the task
    itself so a reader cannot mistake improved detection for a fixed control by
    reading the ticket alone.
    """


class ActorObservation(Model):
    """Everything one actor can see at one moment. The whole of its world.

    Ids only. The rendered payload an actor actually reads is built from these
    ids by ``observation.view``, so there is exactly one place that decides what
    a role may look at, and it is not the provider.
    """

    id: str
    actor_id: str
    role_key: str
    observed_at: datetime
    trigger_event_id: str | None = None
    visible_fact_ids: list[str] = Field(default_factory=list)
    visible_artifact_ids: list[str] = Field(default_factory=list)
    message_ids: list[str] = Field(default_factory=list)
    task_ids: list[str] = Field(default_factory=list)
    obligation_ids: list[str] = Field(default_factory=list)
    """Tasks this actor personally owns. A subset of ``task_ids`` — the ones that
    are *theirs* rather than merely visible, which is what an actor deciding what
    to do next actually needs."""


class ActorInvocation(Model):
    """One bounded opportunity to act.

    Every field except the ids is a limit. That is the point: an episode with no
    budget is a simulation that can run forever, and the roadmap's seventh design
    rule exists because the failure mode is not that actors do nothing, it is
    that they do too much.
    """

    id: str
    actor_id: str
    role_key: str
    observation_id: str
    trigger_event_id: str | None = None
    available_tools: list[str] = Field(default_factory=list)
    max_tool_calls: int = Field(ge=1)
    max_turns: int = Field(ge=1)
    deadline: datetime


class ActorAction(Model):
    """What an actor chose. Not what happened.

    ``tool_name`` of ``None`` is an abstention, and abstention is a first-class
    answer rather than a failure: an actor with nothing legal and useful to do
    should say so, and the corpus should record that it did. An
    expected-abstention evaluation family is only meaningful if abstaining is
    something the runtime can represent.
    """

    invocation_id: str
    tool_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    abstention_reason: str | None = None

    @model_validator(mode="after")
    def _abstention_is_explained(self) -> ActorAction:
        if self.tool_name is None and not self.abstention_reason:
            raise ValueError("an abstention must say why; a silent no-op is unauditable")
        return self


class ToolResult(Model):
    """What the runtime decided an action changed.

    A rejection carries empty id lists by construction, which is the
    ``rejected actions leave no state residue`` invariant expressed as a type
    rather than as a check that has to be remembered.
    """

    accepted: bool
    event_ids: list[str] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)
    artifact_intent_ids: list[str] = Field(default_factory=list)
    task_ids: list[str] = Field(default_factory=list)
    message_ids: list[str] = Field(default_factory=list)
    """Added to the roadmap's shape for the same reason ``ActorMessage`` exists:
    a tool that tells somebody something has to be able to say so."""
    rejection_reason: str | None = None

    @model_validator(mode="after")
    def _rejection_changes_nothing(self) -> ToolResult:
        if not self.accepted:
            if self.event_ids or self.fact_ids or self.artifact_intent_ids or self.task_ids or self.message_ids:
                raise ValueError("a rejected tool call cannot have changed anything")
            if not self.rejection_reason:
                raise ValueError("a rejection must name the rule it broke")
        return self


class ActorPolicy(Model):
    """What a role may see and do. Authority as data, not as prompt text.

    The separation the roadmap insists on: ``Persona`` is how someone writes,
    ``Employee.title`` is where they sit, and this is what they are permitted to
    do. Conflating the third into the first is how a multi-agent system ends up
    enforcing authority by asking a model nicely.
    """

    role_key: str
    allowed_tools: list[str] = Field(default_factory=list)
    readable_domains: list[str] = Field(default_factory=list)
    writable_domains: list[str] = Field(default_factory=list)
    approval_limits: dict[str, float] = Field(default_factory=dict)
    required_evidence: dict[str, list[str]] = Field(default_factory=dict)
    """Tool name to the observation source types its arguments must rest on.
    Confirming a root cause needs evidence the actor actually gathered."""
    prohibited_actions: list[str] = Field(default_factory=list)
    """Checked before ``allowed_tools`` and wins. A deny that can be overridden
    by an allow somewhere else is not a deny — the same precedence
    ``AccessPolicy`` already uses for artifacts."""

    def permits(self, tool_name: str) -> bool:
        """Whether this role may call *tool_name* at all."""
        if tool_name in self.prohibited_actions:
            return False
        return tool_name in self.allowed_tools


class DecisionRight(Model):
    """Who is accountable for a class of decision, and who else has standing.

    First-class because "may this person decide this" is not answerable from a
    tool allow-list alone: a controller may call ``decide_close_schedule``, but
    whether the CFO had to approve it is a fact about the decision type, not
    about the caller.
    """

    decision_type: str
    accountable_role: str
    approver_roles: list[str] = Field(default_factory=list)
    veto_roles: list[str] = Field(default_factory=list)
    consulted_roles: list[str] = Field(default_factory=list)


class TriggerRoute(Model):
    """Which roles an event wakes, and how much rope they get."""

    event_kind: str
    eligible_roles: list[str] = Field(default_factory=list)
    required_conditions: list[str] = Field(default_factory=list)
    """Named predicates resolved by the scheduler. Deliberately a closed
    vocabulary rather than an expression language — see ``scheduler.CONDITIONS``,
    and ``ConstraintKind`` for the same argument made about lore."""
    max_actors: int = Field(default=1, ge=1)
    max_tool_calls: int = Field(default=3, ge=1)
    deadline_minutes: int = Field(default=120, ge=1)


class ActorLedgerEntry(Model):
    """One invocation turn, in full: what was seen, chosen, and changed.

    The execution ledger is append-only and includes rejections. A ledger that
    recorded only accepted calls would answer "what happened" and lose "what was
    attempted and refused", which is the half that proves the policy is load-
    bearing rather than decorative.

    ``key`` is the content address of the *generative* call that produced the
    action, shared with the entry in the generation ledger. That is what ties an
    auditable execution record to a replayable decision without storing the
    decision twice.
    """

    id: str
    key: str
    sequence: int
    invocation: ActorInvocation
    observation: ActorObservation
    action: ActorAction
    result: ToolResult
    acted_at: datetime

    # There is deliberately no `replayed` flag here. Whether an action came from
    # the ledger or from a provider is a property of the *run*, not of the
    # corpus — and a field that differs between a fresh generation and a replay
    # would put a byte of run history into a file the replay test diffs, turning
    # the determinism proof into a permanent failure. The count is reported by
    # `ActorEpisode` instead, the same way narration reports its own.


__all__ = [
    "ActorAction",
    "ActorInvocation",
    "ActorLedgerEntry",
    "ActorMessage",
    "ActorObservation",
    "ActorPolicy",
    "ActorTask",
    "DecisionRight",
    "Observation",
    "ToolResult",
    "TriggerRoute",
]
