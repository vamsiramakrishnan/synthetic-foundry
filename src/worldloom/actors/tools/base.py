"""The typed tool runtime.

A tool is a deterministic command over world state with four stages, and the
order is the whole design:

    schema → authorise → validate → execute

Schema rejects arguments that are not even the right shape. Authorisation asks
the *policy* whether this role may call this tool, and never asks who the caller
is. Validation checks preconditions against the world and, critically, that every
fact the arguments cite is one the actor actually observed. Only then does
anything change.

Three properties follow from that split and each is load-bearing:

**A rejection leaves no residue.** Nothing is appended until ``execute`` returns,
so a refused call cannot half-mutate. ``ToolResult`` enforces the same thing from
the other side — a rejected result with ids in it will not construct.

**Every mutation is attributable.** ``execute`` returns the ids it created and
nothing else creates ids during an episode, so "which accepted tool call produced
this fact" is answerable by lookup rather than by inference.

**Calling twice changes nothing twice.** Tools declare an idempotency key over
their arguments; a repeat returns the first result. Without it a retry after a
rejected sibling call would open two incidents for one failure, which is a
realistic enterprise defect and a terrible default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar

from ...ids import Minter
from ..models import ActorMessage, ActorObservation, ActorPolicy, ActorTask, ToolResult
from ..policy import domain_of

if TYPE_CHECKING:  # pragma: no cover
    from ...models import ArtifactIntent, CanonicalFact, Employee, EnterpriseEvent
    from ...world import World


class ToolRejection(Exception):
    """Raised by a stage that refuses the call. Carries the code and the detail.

    An exception rather than a returned error because it must be impossible to
    ignore: a validation stage whose refusal can be dropped on the floor by a
    caller that forgot to check is not a validation stage.
    """

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class ArgumentSpec:
    """One argument, described well enough for an actor to fill it in blind.

    ``kind`` is a closed vocabulary rather than a JSON Schema fragment. The set is
    small because the interesting checks are semantic — is this fact one you
    observed, is this person employed — and those are not expressible as a type
    anyway.
    """

    name: str
    kind: str
    """``string``, ``text``, ``number``, ``enum``, ``fact_id``, ``fact_ids``,
    ``person_id``, ``task_id``, ``artifact_type``."""
    description: str
    required: bool = True
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolSpec:
    """What an actor is told about a tool it may call."""

    name: str
    domain: str
    summary: str
    arguments: tuple[ArgumentSpec, ...]
    mutates: bool

    def to_payload(self) -> dict[str, Any]:
        """The description handed to an actor, deterministic in key order."""
        return {
            "name": self.name,
            "domain": self.domain,
            "summary": self.summary,
            "mutates": self.mutates,
            "arguments": [
                {
                    "name": argument.name,
                    "kind": argument.kind,
                    "required": argument.required,
                    "description": argument.description,
                    **({"choices": list(argument.choices)} if argument.choices else {}),
                }
                for argument in self.arguments
            ],
        }


@dataclass
class ToolContext:
    """Everything a tool may touch, and the accumulators it appends to.

    A tool never receives the runtime. It receives this, and the world here is
    the world as of the previous accepted call — which is why an episode reads
    as a sequence of decisions taken on progressively better information rather
    than as one decision taken eight times.
    """

    world: World
    minter: Minter
    actor: Employee
    role_key: str
    policy: ActorPolicy
    observation: ActorObservation
    at: datetime
    period: str
    roles: dict[str, str]
    tasks: tuple[ActorTask, ...] = ()
    messages: tuple[ActorMessage, ...] = ()
    incident_ref: str | None = None
    evidence: frozenset[str] = frozenset()
    """Observation source types this actor has gathered *itself* during this
    episode — the ones that satisfy ``required_evidence``. Being told something
    is not the same as having checked it, and the policy distinguishes them."""

    new_events: list[EnterpriseEvent] = field(default_factory=list)
    new_facts: list[CanonicalFact] = field(default_factory=list)
    new_intents: list[ArtifactIntent] = field(default_factory=list)
    new_tasks: list[ActorTask] = field(default_factory=list)
    new_messages: list[ActorMessage] = field(default_factory=list)

    def fact(self, fact_id: str) -> CanonicalFact:
        """A fact the actor has observed. Anything else is a hard error.

        The one place the observation boundary is enforced against a tool's own
        reads rather than against its arguments — a tool that reached past its
        caller's observation to look something up would leak the world back in
        through the side door.
        """
        if fact_id not in self.observation.visible_fact_ids:
            raise ToolRejection(
                "unobserved_fact",
                f"{fact_id} is not in this actor's observation",
            )
        return self.world.facts.by_id(fact_id)

    def person(self, person_id: str) -> Employee:
        person = self.world.people.get(person_id)
        if person is None:
            raise ToolRejection("unknown_person", f"{person_id} is not an employee")
        if person.left is not None and person.left <= self.at:
            raise ToolRejection(
                "departed_person",
                f"{person_id} had left the company by {self.at.isoformat()}",
            )
        return person


class Tool:
    """Base for every actor tool.

    Subclasses declare their schema and implement ``run``. The three stages
    before it are implemented once, here, because "did anyone remember to check
    the policy" is not a question a reviewer should have to ask per tool.
    """

    name: ClassVar[str] = ""
    domain: ClassVar[str] = "operations"
    summary: ClassVar[str] = ""
    arguments: ClassVar[tuple[ArgumentSpec, ...]] = ()
    mutates: ClassVar[bool] = True
    cites: ClassVar[tuple[str, ...]] = ()
    """Argument names holding fact ids. Every one is checked against the actor's
    observation before ``run`` sees them."""
    grants_evidence: ClassVar[str | None] = None
    """The observation source type calling this tool counts as having gathered.

    Only read tools set it. It is what makes ``required_evidence`` mean "you went
    and looked" rather than "somebody mentioned it to you" — the distinction
    between an engineer who read the ERP logs and one who was told the ERP was
    fine."""

    # -- description -------------------------------------------------------

    @classmethod
    def spec_for(cls, policy: ActorPolicy) -> ToolSpec:
        """This tool as *this role* sees it.

        The default is the whole schema, which is right for a tool whose
        arguments mean the same thing to everyone. It is overridable because
        "never show an actor a tool it cannot call" does not go far enough on
        its own: `draft_artifact` accepts eight artifact types and any given
        role may author three of them, so an actor reading the unnarrowed schema
        has to guess and be refused. A budget spent on refusals is an episode
        that does nothing.
        """
        return cls.spec()

    @classmethod
    def spec(cls) -> ToolSpec:
        return ToolSpec(
            name=cls.name,
            domain=cls.domain,
            summary=cls.summary,
            arguments=cls.arguments,
            mutates=cls.mutates,
        )

    # -- the four stages ---------------------------------------------------

    @classmethod
    def check_schema(cls, arguments: dict[str, Any]) -> dict[str, Any]:
        """Reject anything that is not the declared shape, and normalise."""
        known = {argument.name: argument for argument in cls.arguments}
        for name in arguments:
            if name not in known:
                raise ToolRejection(
                    "unknown_argument",
                    f"{cls.name} takes {sorted(known)}, not {name!r}",
                )
        out: dict[str, Any] = {}
        for name, argument in known.items():
            if name not in arguments:
                if argument.required:
                    raise ToolRejection("missing_argument", f"{cls.name} requires {name!r}")
                continue
            out[name] = _coerce(cls.name, argument, arguments[name])
        return out

    def authorise(self, ctx: ToolContext) -> None:
        """Whether this role may call this tool at all.

        Asks the policy and nothing else. A tool that special-cased a role here
        would be authority written twice, and the copy that is not
        ``policy.py`` is the one that goes stale.
        """
        if not ctx.policy.permits(self.name):
            reason = (
                "prohibited by policy"
                if self.name in ctx.policy.prohibited_actions
                else "not granted to this role"
            )
            raise ToolRejection(
                "not_authorised",
                f"{ctx.role_key} may not call {self.name}: {reason}",
            )
        if self.mutates and self.domain not in ctx.policy.writable_domains:
            raise ToolRejection(
                "domain_not_writable",
                f"{ctx.role_key} may read but not write {self.domain}",
            )

    def evidence_needed(self, arguments: dict[str, Any], ctx: ToolContext) -> tuple[str, ...]:
        """Which gathered-evidence channels this *particular* call requires.

        Argument-dependent, which is why it is here rather than in ``authorise``.
        Recording a first hunch is free and recording a confirmed cause is not,
        and those are the same tool — a gate that could not see the arguments
        would have to block both or neither.
        """
        return tuple(ctx.policy.required_evidence.get(self.name, ()))

    def validate(self, arguments: dict[str, Any], ctx: ToolContext) -> None:
        """Preconditions against world state. Overridden to add more.

        Two shared halves. The observation boundary: every fact an argument cites
        must be one this actor has actually seen — the check that makes "no actor
        cites an unobserved fact" a property of the runtime rather than a hope
        about the model. And the evidence requirement, which is the same idea one
        level up: not merely *have you seen this*, but *did you go and look*.
        """
        for name in self.cites:
            value = arguments.get(name)
            if value is None:
                continue
            for fact_id in [value] if isinstance(value, str) else value:
                if fact_id not in ctx.observation.visible_fact_ids:
                    raise ToolRejection(
                        "unobserved_fact",
                        f"{fact_id} was not observed by {ctx.actor.id} at "
                        f"{ctx.observation.observed_at.isoformat()}",
                    )

        required = self.evidence_needed(arguments, ctx)
        if required and not (set(required) & set(ctx.evidence)):
            raise ToolRejection(
                "insufficient_evidence",
                f"{self.name} requires evidence gathered through {sorted(required)};"
                f" this actor has {sorted(ctx.evidence) or 'none'}",
            )

    def idempotency_key(self, arguments: dict[str, Any], ctx: ToolContext) -> str | None:
        """What makes two calls of this tool the same call.

        The default is the caller plus the whole argument set. The *caller* is
        load-bearing and was not obvious: a controller reading the ledger and a
        CFO reading the same ledger are not one call, and collapsing them means
        the second actor silently receives the first one's result and never
        learns anything. What that looked like downstream was an executive
        summary missing the one figure the CFO had gone to look up.

        ``None`` opts out entirely, which is right for every read: the world
        moves between turns, so the same query at 09:00 and at 16:40 is a
        different question with a different answer.

        Tools whose identity is genuinely narrower than their arguments — one
        incident per failure, whatever wording the analyst used — override it.
        """
        if not self.mutates:
            return None
        parts = "\x1f".join(f"{k}={arguments[k]!r}" for k in sorted(arguments))
        return f"{self.name}|{ctx.actor.id}|{parts}"

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:  # pragma: no cover - abstract
        raise NotImplementedError

    # -- helpers for subclasses -------------------------------------------

    def emit_fact(
        self,
        ctx: ToolContext,
        *,
        kind: str,
        subject: str,
        text: str,
        authority: Any,
        event_id: str | None = None,
        source_system: str | None = None,
        period: str | None = None,
        supersedes: str | None = None,
        lore_ids: list[str] | None = None,
    ) -> CanonicalFact:
        """Append a fact this tool call is responsible for.

        Every fact a tool mints is textual and describes a *decision or a
        record*, never a measurement. Measurements come from the deterministic
        generators; an actor that could mint a number would be authoring
        canonical truth, which is the line this whole package exists to hold.
        """
        from ...models import CanonicalFact

        if domain_of(kind) not in ctx.policy.writable_domains:
            raise ToolRejection(
                "domain_not_writable",
                f"{ctx.role_key} may not record {kind} ({domain_of(kind)})",
            )
        fact = CanonicalFact(
            id=ctx.minter.next("FACT"),
            kind=kind,
            subject=subject,
            period=period,
            text_value=text,
            valid_from=ctx.at,
            authority=authority,
            source_system=source_system,
            event_id=event_id,
            supersedes=supersedes,
            lore_ids=lore_ids or [],
        )
        ctx.new_facts.append(fact)
        return fact

    def emit_event(
        self,
        ctx: ToolContext,
        *,
        kind: str,
        summary: str,
        actors: list[str] | None = None,
        services: list[str] | None = None,
        systems: list[str] | None = None,
        caused_by: list[str] | None = None,
    ) -> EnterpriseEvent:
        from ...models import EnterpriseEvent

        event = EnterpriseEvent(
            id=ctx.minter.next("EV"),
            kind=kind,
            occurred_at=ctx.at,
            summary=summary,
            actors=actors if actors is not None else [ctx.actor.id],
            services=services or [],
            systems=systems or [],
            caused_by=[c for c in (caused_by or []) if c],
        )
        ctx.new_events.append(event)
        return event

    def emit_message(
        self,
        ctx: ToolContext,
        *,
        kind: str,
        recipients: list[str],
        text: str,
        discloses: list[str] | None = None,
        subject_ref: str | None = None,
    ) -> ActorMessage:
        message = ActorMessage(
            id=ctx.minter.next("MSG"),
            kind=kind,
            sent_at=ctx.at,
            sender_id=ctx.actor.id,
            recipient_ids=sorted(set(recipients)),
            subject_ref=subject_ref or ctx.incident_ref,
            text=text,
            disclosed_fact_ids=sorted(set(discloses or [])),
        )
        ctx.new_messages.append(message)
        return message

    def emit_task(
        self,
        ctx: ToolContext,
        *,
        kind: str,
        title: str,
        owner_id: str | None,
        domain: str,
        fact_ids: list[str] | None = None,
        addresses: str | None = None,
        due_at: datetime | None = None,
    ) -> ActorTask:
        task = ActorTask(
            id=ctx.minter.next("TASK"),
            kind=kind,
            title=title,
            created_at=ctx.at,
            created_by=ctx.actor.id,
            owner_id=owner_id,
            due_at=due_at,
            state="assigned" if owner_id else "open",
            domain=domain,
            subject_ref=ctx.incident_ref,
            fact_ids=sorted(set(fact_ids or [])),
            addresses=addresses,
        )
        ctx.new_tasks.append(task)
        return task

    def emit_intent(
        self,
        ctx: ToolContext,
        *,
        artifact_type: str,
        domain: str,
        audience: str,
        fact_ids: list[str],
        event_ids: list[str],
        size: str,
        rationale: str,
        derived_from: list[str] | None = None,
        revises: str | None = None,
        supersedes: str | None = None,
    ) -> ArtifactIntent:
        """Plan a document. The compilers still own its shape and its prose.

        ``draft_artifact`` produces an intent and stops, exactly as the roadmap
        requires: the artifact compiler decides the outline, the narrative
        compiler writes the body under fact constraints, and the renderers make
        the file. An actor that produced a document directly would be choosing
        its structure, its claims, and its numbers in one step, with none of the
        three checked.
        """
        from ...models import ArtifactIntent

        if not fact_ids:
            raise ToolRejection(
                "artifact_without_facts",
                f"a {artifact_type} citing nothing has no date and nothing to say",
            )
        intent = ArtifactIntent(
            id=ctx.minter.next("ART"),
            artifact_type=artifact_type,
            domain=domain,
            audience=audience,
            author_id=ctx.actor.id,
            triggered_by=[e for e in event_ids if e],
            required_fact_ids=fact_ids,
            size_profile=size,  # type: ignore[arg-type]
            rationale=rationale,
            derived_from=[a for a in (derived_from or []) if a],
            revises=revises,
            supersedes=supersedes,
        )
        ctx.new_intents.append(intent)
        return intent


def _coerce(tool_name: str, argument: ArgumentSpec, value: Any) -> Any:
    """Check one argument against its declared kind, and normalise it."""
    kind = argument.kind
    if kind in {"string", "text", "person_id", "task_id", "artifact_type", "fact_id", "enum"}:
        if not isinstance(value, str) or not value:
            raise ToolRejection(
                "bad_argument",
                f"{tool_name}.{argument.name} must be a non-empty string, got {value!r}",
            )
        if kind == "enum" and value not in argument.choices:
            raise ToolRejection(
                "bad_argument",
                f"{tool_name}.{argument.name} must be one of {list(argument.choices)}, got {value!r}",
            )
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ToolRejection(
                "bad_argument", f"{tool_name}.{argument.name} must be a number, got {value!r}"
            )
        return float(value)
    if kind == "fact_ids":
        if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
            raise ToolRejection(
                "bad_argument",
                f"{tool_name}.{argument.name} must be a list of fact ids, got {value!r}",
            )
        # Deduplicated and ordered here rather than in every tool: two calls that
        # cite the same facts in a different order are the same call, and the
        # idempotency key is computed from these values.
        return sorted(set(value))
    raise ToolRejection("bad_argument", f"unknown argument kind {kind!r} on {tool_name}")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    """Register a tool by name. Duplicate names are a programming error."""
    if tool.name in _REGISTRY:
        raise ValueError(f"two tools named {tool.name!r}")
    _REGISTRY[tool.name] = tool
    return tool


def get(name: str) -> Tool:
    tool = _REGISTRY.get(name)
    if tool is None:
        raise ToolRejection("unknown_tool", f"no tool named {name!r}")
    return tool


def available() -> tuple[str, ...]:
    """Every registered tool name, sorted."""
    return tuple(sorted(_REGISTRY))


def catalogue(policy: ActorPolicy) -> tuple[ToolSpec, ...]:
    """The tools this policy grants, in a stable order.

    Built from the policy rather than filtered afterwards, so an actor is never
    shown a tool it cannot call. Showing one would invite the model to try, and
    an episode's tool budget spent on refusals is an episode that does nothing.
    """
    return tuple(
        _REGISTRY[name].spec_for(policy)
        for name in sorted(policy.allowed_tools)
        if name in _REGISTRY and policy.permits(name)
    )


__all__ = [
    "ArgumentSpec",
    "Tool",
    "ToolContext",
    "ToolRejection",
    "ToolSpec",
    "available",
    "catalogue",
    "get",
    "register",
]
