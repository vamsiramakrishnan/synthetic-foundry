"""Engineering tools.

Investigation, and the separation of duties around a production change.

``record_hypothesis`` is where the policy layer earns its place. Recording a
guess is free; promoting one to a confirmed cause is gated on evidence the actor
gathered itself through ``query_logs`` or ``inspect_dependencies``. That is not
decoration — it is what makes "who knew the root cause before the close decision"
a question with a checkable answer, because the confirmation carries a timestamp
that could not have been earlier than the looking.

Note what these tools do *not* do: none of them decides what was actually wrong.
The stale hierarchy mapping is the world's, decided deterministically and
traceable to a 2024 lore commitment. An engineer here discovers it, states it,
and is right — but an engineer who searched a world where something else broke
would state that instead.
"""

from __future__ import annotations

from typing import Any, ClassVar

from ...models import Authority
from ..models import ToolResult
from .base import ArgumentSpec, Tool, ToolContext, ToolRejection, register


class QueryLogs(Tool):
    """Read what a system recorded. The engineer's evidence-gathering primitive."""

    name = "query_logs"
    domain = "engineering"
    mutates = False
    summary = (
        "Read the records a named system produced up to now. Discloses them to you, "
        "and counts as evidence you gathered yourself."
    )
    arguments = (
        ArgumentSpec("system_id", "string", "The system whose records to read."),
    )
    grants_evidence = "system_of_record"

    def validate(self, arguments: dict[str, Any], ctx: ToolContext) -> None:
        super().validate(arguments, ctx)
        if ctx.world.systems.get(arguments["system_id"]) is None:
            raise ToolRejection("unknown_system", f"{arguments['system_id']} is not a system")

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        system = ctx.world.systems.by_id(arguments["system_id"])
        from ..policy import domain_of

        # Bounded three ways: the system must have been the source, the record
        # must already exist, and the domain must be one this role may read.
        # Drop the third and querying a log becomes a way to read the group's
        # margin out of the ERP, which is exactly the omniscience the
        # observation ledger exists to prevent.
        found = [
            fact.id
            for fact in ctx.world.facts
            if fact.source_system == system.id
            and fact.valid_from <= ctx.at
            and domain_of(fact.kind) in ctx.policy.readable_domains
        ]
        message = self.emit_message(
            ctx,
            kind="system_response",
            recipients=[ctx.actor.id],
            text=f"Read {len(found)} record(s) from {system.name}.",
            discloses=found,
        )
        return ToolResult(accepted=True, message_ids=[message.id])


class InspectDependencies(Tool):
    """Walk a service's dependency edge. How the failure is localised."""

    name = "inspect_dependencies"
    domain = "engineering"
    mutates = False
    summary = (
        "Inspect a service and everything it depends on. Discloses what is recorded "
        "against them, and counts as evidence you gathered yourself."
    )
    arguments = (
        ArgumentSpec("service_id", "string", "The service to inspect."),
    )
    grants_evidence = "system_of_record"

    def validate(self, arguments: dict[str, Any], ctx: ToolContext) -> None:
        super().validate(arguments, ctx)
        if ctx.world.services.get(arguments["service_id"]) is None:
            raise ToolRejection("unknown_service", f"{arguments['service_id']} is not a service")

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        from ..policy import domain_of

        service = ctx.world.services.by_id(arguments["service_id"])
        # One hop. A transitive walk would reach the whole estate from any
        # service in a tier-one world, which is a search that always returns
        # everything and therefore discloses everything.
        scope = {service.id, service.system_id, *service.depends_on}
        found = [
            fact.id
            for fact in ctx.world.facts
            if fact.valid_from <= ctx.at
            and (fact.subject in scope or fact.source_system in scope)
            and domain_of(fact.kind) in ctx.policy.readable_domains
        ]
        message = self.emit_message(
            ctx,
            kind="system_response",
            recipients=[ctx.actor.id],
            text=f"Inspected {service.name} and {len(scope) - 1} dependency record set(s).",
            discloses=found,
        )
        return ToolResult(accepted=True, message_ids=[message.id])


class RecordHypothesis(Tool):
    """State what you think is wrong, at the standing your evidence supports.

    Three statuses, three authorities, and the runtime picks the authority from
    the status rather than letting the actor claim one. An actor able to declare
    its own guess ``confirmed`` would be able to out-rank the system of record by
    typing a word.
    """

    name = "record_hypothesis"
    domain = "engineering"
    summary = (
        "Record an assessment of the cause at one of three standings. A confirmed "
        "assessment requires evidence you gathered through query_logs or "
        "inspect_dependencies."
    )
    arguments = (
        ArgumentSpec("service_id", "string", "The service under investigation."),
        ArgumentSpec(
            "status", "enum", "How strongly this is held.",
            choices=("hypothesis", "ruled_out", "confirmed"),
        ),
        ArgumentSpec("assessment", "text", "The assessment, in the engineer's words."),
        ArgumentSpec("cite_fact_ids", "fact_ids", "The evidence it rests on."),
        ArgumentSpec("supersedes_fact_id", "fact_id", "An earlier assessment this replaces.",
                     required=False),
    )
    cites = ("cite_fact_ids", "supersedes_fact_id")

    #: Standing follows evidence, not assertion.
    _AUTHORITY: ClassVar[dict[str, Authority]] = {
        "hypothesis": Authority.INITIAL_HYPOTHESIS,
        "ruled_out": Authority.WORKING_DOCUMENT,
        "confirmed": Authority.CONFIRMED,
    }

    def evidence_needed(self, arguments: dict[str, Any], ctx: ToolContext) -> tuple[str, ...]:
        # A hunch is free. A confirmation is not. Anything else and the tool
        # either blocks the first assessment of every incident, or lets an actor
        # confirm a cause it never looked into.
        if arguments.get("status") != "confirmed":
            return ()
        return super().evidence_needed(arguments, ctx)

    def validate(self, arguments: dict[str, Any], ctx: ToolContext) -> None:
        super().validate(arguments, ctx)
        if not arguments["cite_fact_ids"]:
            raise ToolRejection("no_evidence", "an assessment must cite what it rests on")
        if arguments["status"] != "confirmed":
            return

        # A confirmation has to rest on the cause the world actually established.
        #
        # Without this the evidence gate is the only thing standing between an
        # actor and an `Authority.CONFIRMED` fact saying whatever it likes: call
        # `query_logs`, then confirm a network outage in a world whose cause is a
        # stale mapping table, and it lands in the RCA with the standing of a
        # confirmed finding. That is an actor authoring canonical truth, which is
        # the one thing this package exists to prevent.
        #
        # What is checked is *standing*, not wording. Comparing the engineer's
        # sentence against the canonical text would need semantics nothing here
        # has; requiring the confirmation to cite the deterministic finding is
        # both checkable and the right constraint — the account is the engineer's,
        # the authority comes from the world.
        canonical = [
            ctx.world.facts.by_id(fact_id)
            for fact_id in arguments["cite_fact_ids"]
        ]
        established = [
            fact
            for fact in canonical
            if fact.kind == "ops.cause"
            and fact.authority is Authority.CONFIRMED
            and not fact.is_superseded
        ]
        if not established:
            raise ToolRejection(
                "unfounded_confirmation",
                "a confirmed assessment must cite the confirmed cause the world has"
                " established; record this as a hypothesis until one exists",
            )

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        status = arguments["status"]
        event = self.emit_event(
            ctx,
            kind="assessment_recorded",
            summary=f"{ctx.actor.title} recorded a {status} assessment: {arguments['assessment']}",
            services=[arguments["service_id"]],
        )
        # A confirmation is sourced to the system that established the cause, not
        # to the engineer who wrote it up. That is what makes the provenance of a
        # confirmed finding traceable past the person who typed it.
        source = next(
            (
                ctx.world.facts.by_id(f).source_system
                for f in arguments["cite_fact_ids"]
                if ctx.world.facts.by_id(f).kind == "ops.cause"
                and ctx.world.facts.by_id(f).authority is Authority.CONFIRMED
            ),
            None,
        ) if status == "confirmed" else None
        fact = self.emit_fact(
            ctx,
            kind="ops.cause_assessment",
            subject=arguments["service_id"],
            text=arguments["assessment"],
            authority=self._AUTHORITY[status],
            event_id=event.id,
            source_system=source,
            period=ctx.period,
            supersedes=arguments.get("supersedes_fact_id"),
        )
        message = self.emit_message(
            ctx,
            kind="work_note",
            recipients=[ctx.actor.id],
            text=arguments["assessment"],
            discloses=[*arguments["cite_fact_ids"], fact.id],
        )
        return ToolResult(
            accepted=True,
            event_ids=[event.id],
            fact_ids=[fact.id],
            message_ids=[message.id],
        )


class ProposeChange(Tool):
    """Propose a production change. Deliberately cannot approve one."""

    name = "propose_change"
    domain = "engineering"
    summary = "Propose a production change. It waits for an approver; you are not one."
    arguments = (
        ArgumentSpec("service_id", "string", "The service the change touches."),
        ArgumentSpec("change", "text", "What the change does."),
        ArgumentSpec("cite_fact_ids", "fact_ids", "Why it is needed."),
    )
    cites = ("cite_fact_ids",)

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        fact = self.emit_fact(
            ctx,
            kind="ops.change_proposal",
            subject=arguments["service_id"],
            text=arguments["change"],
            authority=Authority.WORKING_DOCUMENT,
            period=ctx.period,
        )
        task = self.emit_task(
            ctx,
            kind="change_approval",
            title=f"Approve or reject: {arguments['change']}",
            owner_id=None,
            domain="engineering",
            fact_ids=[fact.id, *arguments["cite_fact_ids"]],
        )
        return ToolResult(accepted=True, fact_ids=[fact.id], task_ids=[task.id])


class ApproveChange(Tool):
    """Approve a proposed change. Only a role holding the decision right may."""

    name = "approve_change"
    domain = "engineering"
    summary = "Approve a proposed production change."
    arguments = (
        ArgumentSpec("proposal_fact_id", "fact_id", "The proposal being approved."),
        ArgumentSpec("note", "text", "The approval note."),
    )
    cites = ("proposal_fact_id",)

    def validate(self, arguments: dict[str, Any], ctx: ToolContext) -> None:
        super().validate(arguments, ctx)
        from ..policy import decision_right, policy_role

        right = decision_right("production_change")
        assert right is not None  # declared in policy.py
        role = policy_role(ctx.role_key)
        if role not in {right.accountable_role, *right.approver_roles}:
            raise ToolRejection(
                "no_decision_right",
                f"{ctx.role_key} is not accountable for or an approver of production_change",
            )
        proposal = ctx.fact(arguments["proposal_fact_id"])
        if proposal.kind != "ops.change_proposal":
            raise ToolRejection(
                "wrong_fact_kind",
                f"{proposal.id} is a {proposal.kind}, not a change proposal",
            )
        already = any(
            fact.kind == "ops.change_approval" and fact.subject == proposal.subject
            and fact.valid_from >= proposal.valid_from
            for fact in ctx.world.facts
        )
        if already:
            raise ToolRejection(
                "already_approved",
                f"a change on {proposal.subject} has already been approved",
            )

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        proposal = ctx.fact(arguments["proposal_fact_id"])
        event = self.emit_event(
            ctx,
            kind="change_approved",
            summary=f"{ctx.actor.title} approved the change: {arguments['note']}",
        )
        fact = self.emit_fact(
            ctx,
            kind="ops.change_approval",
            subject=proposal.subject,
            text=arguments["note"],
            authority=Authority.APPROVED_REPORT,
            event_id=event.id,
            period=ctx.period,
        )
        return ToolResult(accepted=True, event_ids=[event.id], fact_ids=[fact.id])


class CreateRemediationIssue(Tool):
    """Raise remediation work, saying which failure it actually addresses.

    ``addresses`` is required and enumerated because the corpus's sharpest
    evaluation case turns on it: one ticket fixes the control, the other only
    improves detection, and a reader who cannot tell them apart approves the
    cheaper one. Leaving it free text would let an actor blur exactly the
    distinction the RCA is required to make.
    """

    name = "create_remediation_issue"
    domain = "engineering"
    summary = "Raise a remediation issue, stating whether it fixes the control or only detection."
    arguments = (
        ArgumentSpec("title", "text", "The issue title."),
        ArgumentSpec(
            "addresses", "enum", "What this actually fixes.",
            choices=("control", "detection"),
        ),
        ArgumentSpec("owner_role_key", "string", "Role that will own it.", required=False),
        ArgumentSpec("cite_fact_ids", "fact_ids", "Facts justifying the work."),
    )
    cites = ("cite_fact_ids",)

    def idempotency_key(self, arguments: dict[str, Any], ctx: ToolContext) -> str:
        # One remediation per thing-being-fixed. Two tickets that both claim to
        # fix the control are a duplicate, whatever they are called.
        return f"create_remediation_issue|{arguments['addresses']}"

    def validate(self, arguments: dict[str, Any], ctx: ToolContext) -> None:
        super().validate(arguments, ctx)
        role_key = arguments.get("owner_role_key")
        if role_key is not None:
            if role_key not in ctx.roles:
                raise ToolRejection("unknown_role", f"{role_key} is not a role")
            ctx.person(ctx.roles[role_key])

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        role_key = arguments.get("owner_role_key")
        owner = ctx.person(ctx.roles[role_key]) if role_key else None
        event = self.emit_event(
            ctx,
            kind="remediation_raised",
            summary=(
                f"Remediation raised ({arguments['addresses']}): {arguments['title']}"
                + (f", owned by {owner.title}" if owner else ", unowned")
            ),
            actors=[ctx.actor.id, *([owner.id] if owner else [])],
        )
        fact = self.emit_fact(
            ctx,
            kind="ops.remediation_owner",
            subject=ctx.roles["svc_hierarchy"],
            text=(
                f"{arguments['title']} — addresses the {arguments['addresses']} failure; "
                + (f"owned by {owner.title}" if owner else "no owner assigned")
            ),
            authority=Authority.SYSTEM_OF_RECORD,
            event_id=event.id,
            period=ctx.period,
        )
        task = self.emit_task(
            ctx,
            kind="remediation",
            title=arguments["title"],
            owner_id=owner.id if owner else None,
            domain="engineering",
            fact_ids=[fact.id, *arguments["cite_fact_ids"]],
            addresses=arguments["addresses"],
        )
        return ToolResult(
            accepted=True,
            event_ids=[event.id],
            fact_ids=[fact.id],
            task_ids=[task.id],
        )


class PublishRunbook(Tool):
    """Write the workaround down, so the next person at 2am does not rediscover it."""

    name = "publish_runbook"
    domain = "engineering"
    summary = "Publish a knowledge article covering a repeatable workaround."
    arguments = (
        ArgumentSpec("title", "text", "Article title."),
        ArgumentSpec("cite_fact_ids", "fact_ids", "Facts the article covers."),
    )
    cites = ("cite_fact_ids",)

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        intent = self.emit_intent(
            ctx,
            artifact_type="knowledge_article",
            domain="operations",
            audience="technology",
            fact_ids=arguments["cite_fact_ids"],
            event_ids=[ctx.observation.trigger_event_id or ""],
            size="medium",
            rationale=(
                "The workaround is repeatable and was undocumented, so the engineer "
                "who applied it wrote it up."
            ),
        )
        return ToolResult(accepted=True, artifact_intent_ids=[intent.id])


for _tool in (
    QueryLogs(),
    InspectDependencies(),
    RecordHypothesis(),
    ProposeChange(),
    ApproveChange(),
    CreateRemediationIssue(),
    PublishRunbook(),
):
    register(_tool)
