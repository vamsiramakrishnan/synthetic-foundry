"""Service-management tools.

What the service desk and the incident commander can actually do to a ticket.

The division of labour with the deterministic operational generator is the thing
to hold onto: ``operations.generate`` decides that the valuation pipeline failed
and what was really wrong with it, because that is the world's physics. These
tools decide *the ticket* — when it was raised, at what priority, who it went to,
what was written in the work notes, and who therefore knew. None of that is
physics, all of it is judgement under incomplete information, and all of it is
what an enterprise corpus is actually made of.
"""

from __future__ import annotations

from typing import Any

from ...models import Authority
from ..models import ToolResult
from .base import ArgumentSpec, Tool, ToolContext, ToolRejection, register

#: Kinds a search may surface. Narrow on purpose: an actor searching the incident
#: system learns about incidents, not about the group's margin.
_SEARCHABLE = ("ops.incident_opened", "ops.previous_similar_incident", "ops.feed_status")


class SearchIncidents(Tool):
    """Look up incident records. A read, and the way an actor learns there is precedent."""

    name = "search_incidents"
    domain = "operations"
    mutates = False
    summary = (
        "Search the incident system. Discloses matching incident records to you, "
        "including comparable earlier failures."
    )
    arguments = (
        ArgumentSpec("query", "string", "Free text matched against incident records."),
    )
    grants_evidence = "system_of_record"

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        needle = arguments["query"].lower()
        # Searching the incident system finds incident records, whether or not
        # this actor had already come to know them some other way. What it
        # cannot do is find things the system does not hold — the domain gate
        # below is why a search is not a way around an access policy.
        found = [
            fact.id
            for fact in ctx.world.facts
            if fact.valid_from <= ctx.at
            and any(fact.kind.startswith(prefix) for prefix in _SEARCHABLE)
            and (needle in (fact.text_value or "").lower() or needle in fact.subject.lower())
        ]
        message = self.emit_message(
            ctx,
            kind="system_response",
            recipients=[ctx.actor.id],
            text=f"Incident search for {arguments['query']!r} returned {len(found)} record(s).",
            discloses=found,
        )
        return ToolResult(accepted=True, message_ids=[message.id])


class CreateIncident(Tool):
    """Open the ticket. One per failure, whatever wording the analyst chose."""

    name = "create_incident"
    domain = "operations"
    summary = (
        "Record an incident against a service at a priority, and notify the "
        "responders. Cite the facts that evidence the failure."
    )
    arguments = (
        ArgumentSpec("service_id", "string", "The affected service."),
        ArgumentSpec("priority", "enum", "Incident priority.", choices=("P1", "P2", "P3", "P4")),
        ArgumentSpec("summary", "text", "One line, as it appears on the ticket."),
        ArgumentSpec("evidence_fact_ids", "fact_ids", "Facts evidencing the failure."),
        ArgumentSpec("notify_role_keys", "fact_ids", "Roles to notify.", required=False),
    )
    cites = ("evidence_fact_ids",)

    def idempotency_key(self, arguments: dict[str, Any], ctx: ToolContext) -> str:
        # One incident per service per episode. Keyed on the service rather than
        # the whole argument set because an analyst who retries with a better
        # summary has not found a second failure, and a corpus with two tickets
        # for one outage is a defect the roadmap explicitly asks us not to
        # generate by accident.
        return f"create_incident|{arguments['service_id']}"

    def validate(self, arguments: dict[str, Any], ctx: ToolContext) -> None:
        super().validate(arguments, ctx)
        if ctx.world.services.get(arguments["service_id"]) is None:
            raise ToolRejection("unknown_service", f"{arguments['service_id']} is not a service")
        if not arguments["evidence_fact_ids"]:
            raise ToolRejection(
                "no_evidence", "an incident must cite at least one fact evidencing the failure"
            )

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        service = ctx.world.services.by_id(arguments["service_id"])
        evidence = arguments["evidence_fact_ids"]
        event = self.emit_event(
            ctx,
            kind="incident_recorded",
            summary=(
                f"{ctx.actor.title} recorded the incident against {service.name} at "
                f"{arguments['priority']}: {arguments['summary']}"
            ),
            services=[service.id],
        )
        state = self.emit_fact(
            ctx,
            kind="ops.incident_state",
            subject=service.id,
            text=f"triage at {arguments['priority']}",
            authority=Authority.SYSTEM_OF_RECORD,
            event_id=event.id,
            period=ctx.period,
        )
        recipients = [
            ctx.roles[key]
            for key in arguments.get("notify_role_keys", [])
            if key in ctx.roles
        ]
        message = self.emit_message(
            ctx,
            kind="escalation",
            recipients=recipients or [ctx.actor.id],
            text=f"{arguments['priority']} raised against {service.name}: {arguments['summary']}",
            discloses=[*evidence, state.id],
        )
        return ToolResult(
            accepted=True,
            event_ids=[event.id],
            fact_ids=[state.id],
            message_ids=[message.id],
        )


class UpdateIncident(Tool):
    """Move the ticket's state. The previous state is superseded, never overwritten."""

    name = "update_incident"
    domain = "operations"
    summary = "Move an incident to a new state, superseding the state it was in."
    arguments = (
        ArgumentSpec("service_id", "string", "The affected service."),
        ArgumentSpec(
            "state", "enum", "New incident state.",
            choices=("triage", "investigating", "workaround_applied", "resolved", "closed"),
        ),
        ArgumentSpec("note", "text", "Why it moved."),
    )

    def _current(self, ctx: ToolContext, service_id: str):  # type: ignore[no-untyped-def]
        candidates = [
            fact
            for fact in ctx.world.facts
            if fact.kind == "ops.incident_state"
            and fact.subject == service_id
            and not fact.is_superseded
        ]
        return candidates[-1] if candidates else None

    def validate(self, arguments: dict[str, Any], ctx: ToolContext) -> None:
        super().validate(arguments, ctx)
        if self._current(ctx, arguments["service_id"]) is None:
            raise ToolRejection(
                "no_open_incident",
                f"no incident is open against {arguments['service_id']}",
            )

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        current = self._current(ctx, arguments["service_id"])
        assert current is not None  # validate() proved it
        event = self.emit_event(
            ctx,
            kind="incident_updated",
            summary=f"Incident moved to {arguments['state']}: {arguments['note']}",
            services=[arguments["service_id"]],
        )
        fact = self.emit_fact(
            ctx,
            kind="ops.incident_state",
            subject=arguments["service_id"],
            text=arguments["state"],
            authority=Authority.SYSTEM_OF_RECORD,
            event_id=event.id,
            period=ctx.period,
            supersedes=current.id,
        )
        return ToolResult(accepted=True, event_ids=[event.id], fact_ids=[fact.id])


class AssignIncident(Tool):
    """Put a named person on the hook, and tell them.

    The assignment is the moment the assignee's observation changes, which is
    why it discloses the evidence rather than merely naming a person.
    """

    name = "assign_incident"
    domain = "operations"
    summary = "Assign the incident to an employee and disclose what is known to them."
    arguments = (
        ArgumentSpec("service_id", "string", "The affected service."),
        ArgumentSpec("assignee_role_key", "string", "Role key of the assignee."),
        ArgumentSpec("disclose_fact_ids", "fact_ids", "What to hand over."),
    )
    cites = ("disclose_fact_ids",)

    def idempotency_key(self, arguments: dict[str, Any], ctx: ToolContext) -> str:
        return f"assign_incident|{arguments['service_id']}|{arguments['assignee_role_key']}"

    def validate(self, arguments: dict[str, Any], ctx: ToolContext) -> None:
        super().validate(arguments, ctx)
        role_key = arguments["assignee_role_key"]
        if role_key not in ctx.roles:
            raise ToolRejection("unknown_role", f"{role_key} is not a role in this world")
        ctx.person(ctx.roles[role_key])

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        assignee = ctx.person(ctx.roles[arguments["assignee_role_key"]])
        event = self.emit_event(
            ctx,
            kind="incident_assigned",
            summary=f"Incident assigned to {assignee.title}.",
            actors=[ctx.actor.id, assignee.id],
            services=[arguments["service_id"]],
        )
        fact = self.emit_fact(
            ctx,
            kind="ops.incident_assignee",
            subject=arguments["service_id"],
            text=assignee.title,
            authority=Authority.SYSTEM_OF_RECORD,
            event_id=event.id,
            period=ctx.period,
        )
        message = self.emit_message(
            ctx,
            kind="assignment",
            recipients=[assignee.id],
            text=f"Assigning this to you. {len(arguments['disclose_fact_ids'])} record(s) attached.",
            discloses=arguments["disclose_fact_ids"],
        )
        task = self.emit_task(
            ctx,
            kind="incident_response",
            title=f"Respond to the incident on {arguments['service_id']}",
            owner_id=assignee.id,
            domain="operations",
            fact_ids=arguments["disclose_fact_ids"],
        )
        return ToolResult(
            accepted=True,
            event_ids=[event.id],
            fact_ids=[fact.id],
            task_ids=[task.id],
            message_ids=[message.id],
        )


class AddWorkNote(Tool):
    """The running commentary a ticket accumulates.

    A fact rather than only a message, because a work note is how an incident
    record carries what people believed at each point — and the RCA has to be
    able to cite it. Its authority is ``working_document``: a note is not the
    system of record even when it is written into one.
    """

    name = "add_work_note"
    domain = "operations"
    summary = "Add a work note to the incident, optionally disclosing facts to named roles."
    arguments = (
        ArgumentSpec("service_id", "string", "The affected service."),
        ArgumentSpec("note", "text", "The note, as it appears on the ticket."),
        ArgumentSpec("cite_fact_ids", "fact_ids", "Facts the note rests on.", required=False),
        ArgumentSpec("notify_role_keys", "fact_ids", "Roles to copy.", required=False),
    )
    cites = ("cite_fact_ids",)

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        cited = arguments.get("cite_fact_ids", [])
        fact = self.emit_fact(
            ctx,
            kind="ops.work_note",
            subject=arguments["service_id"],
            text=arguments["note"],
            authority=Authority.WORKING_DOCUMENT,
            period=ctx.period,
        )
        recipients = [
            ctx.roles[key] for key in arguments.get("notify_role_keys", []) if key in ctx.roles
        ]
        message = self.emit_message(
            ctx,
            kind="work_note",
            recipients=recipients or [ctx.actor.id],
            text=arguments["note"],
            discloses=[*cited, fact.id],
        )
        return ToolResult(accepted=True, fact_ids=[fact.id], message_ids=[message.id])


class RequestEvidence(Tool):
    """Ask somebody to go and check. The incident commander's characteristic move."""

    name = "request_evidence"
    domain = "operations"
    summary = "Ask a named role to produce evidence for or against the current hypothesis."
    arguments = (
        ArgumentSpec("of_role_key", "string", "Who is being asked."),
        ArgumentSpec("question", "text", "What they are being asked to establish."),
        ArgumentSpec("about_fact_ids", "fact_ids", "The claim under test."),
    )
    cites = ("about_fact_ids",)

    def validate(self, arguments: dict[str, Any], ctx: ToolContext) -> None:
        super().validate(arguments, ctx)
        if arguments["of_role_key"] not in ctx.roles:
            raise ToolRejection("unknown_role", f"{arguments['of_role_key']} is not a role")

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        target = ctx.person(ctx.roles[arguments["of_role_key"]])
        task = self.emit_task(
            ctx,
            kind="evidence_request",
            title=arguments["question"],
            owner_id=target.id,
            domain="operations",
            fact_ids=arguments["about_fact_ids"],
        )
        message = self.emit_message(
            ctx,
            kind="evidence_request",
            recipients=[target.id],
            text=arguments["question"],
            discloses=arguments["about_fact_ids"],
        )
        return ToolResult(accepted=True, task_ids=[task.id], message_ids=[message.id])


class EscalateMajorIncident(Tool):
    """Declare a major incident. Denied to the analyst by name, not by omission."""

    name = "escalate_major_incident"
    domain = "operations"
    summary = "Declare a major incident, raising priority and widening the notification."
    arguments = (
        ArgumentSpec("service_id", "string", "The affected service."),
        ArgumentSpec("justification", "text", "Why this is major."),
        ArgumentSpec("cite_fact_ids", "fact_ids", "Facts supporting the declaration."),
    )
    cites = ("cite_fact_ids",)

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        event = self.emit_event(
            ctx,
            kind="major_incident_declared",
            summary=f"Major incident declared: {arguments['justification']}",
            services=[arguments["service_id"]],
        )
        fact = self.emit_fact(
            ctx,
            kind="ops.incident_priority",
            subject=arguments["service_id"],
            text="P1 major incident",
            authority=Authority.SYSTEM_OF_RECORD,
            event_id=event.id,
            period=ctx.period,
        )
        return ToolResult(accepted=True, event_ids=[event.id], fact_ids=[fact.id])


for _tool in (
    SearchIncidents(),
    CreateIncident(),
    UpdateIncident(),
    AssignIncident(),
    AddWorkNote(),
    RequestEvidence(),
    EscalateMajorIncident(),
):
    register(_tool)
