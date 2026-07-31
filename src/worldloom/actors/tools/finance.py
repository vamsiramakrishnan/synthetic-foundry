"""Finance tools.

The reads are how a finance actor comes to know a number without being handed the
ledger; the writes are where authority is at its sharpest.

``request_journal`` and ``post_journal`` are the same act split in two, and the
split is the point. A business partner may raise an adjustment and cannot book
one; the controller can do both. Modelling this as one tool with a permission
flag would put the authority boundary inside an argument, where an actor could
reach it.

``decide_close_schedule`` is the episode's consequential decision. It is gated
three ways — the policy must grant the tool, the decision right must name the
role, and the actor must have gone and looked at the ledger — because "who was
entitled to move the close, and what did they know when they did" is the question
the whole retail-close episode exists to pose.
"""

from __future__ import annotations

from typing import Any

from ...models import Authority
from ..models import ToolResult
from .base import ArgumentSpec, Tool, ToolContext, ToolRejection, register


class _FinanceRead(Tool):
    """Shared shape for the three finance reads.

    One class rather than three near-copies: they differ only in which fact kinds
    they surface, and three bodies that differ by a tuple is three places for the
    domain gate to be forgotten.
    """

    domain = "finance"
    mutates = False
    grants_evidence = "system_of_record"
    kinds: tuple[str, ...] = ()
    arguments = (
        ArgumentSpec("subject_id", "string", "Company, business unit, category, or site."),
    )

    def validate(self, arguments: dict[str, Any], ctx: ToolContext) -> None:
        super().validate(arguments, ctx)
        subject = arguments["subject_id"]
        known = (
            subject == ctx.world.company.id
            or ctx.world.business_units.get(subject) is not None
            or ctx.world.categories.get(subject) is not None
            or ctx.world.sites.get(subject) is not None
        )
        if not known:
            raise ToolRejection("unknown_subject", f"{subject} is not a reportable subject")

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        from ..policy import domain_of

        subject = arguments["subject_id"]
        found = [
            fact.id
            for fact in ctx.world.facts
            if fact.subject == subject
            and fact.valid_from <= ctx.at
            and any(fact.kind.startswith(prefix) for prefix in self.kinds)
            and domain_of(fact.kind) in ctx.policy.readable_domains
        ]
        message = self.emit_message(
            ctx,
            kind="system_response",
            recipients=[ctx.actor.id],
            text=f"{self.name} on {subject} returned {len(found)} record(s).",
            discloses=found,
        )
        return ToolResult(accepted=True, message_ids=[message.id])


class ReadLedger(_FinanceRead):
    name = "read_ledger"
    summary = "Read the posted position for a subject, and the close's own status."
    kinds = ("financial.", "close.")


class QueryBudget(_FinanceRead):
    name = "query_budget"
    summary = "Read budget and variance lines for a subject."
    kinds = ("financial.revenue.budget", "financial.gross_profit.budget",
             "financial.gross_margin_pct.budget", "financial.revenue.variance",
             "financial.gross_profit.variance")


class QueryForecast(_FinanceRead):
    name = "query_forecast"
    summary = "Read forecast lines and the operating metrics behind them."
    kinds = ("metric.",)


class CreateVarianceAnalysis(Tool):
    """Write the assessment down, so a later document can cite it rather than redo it."""

    name = "create_variance_analysis"
    domain = "finance"
    summary = "Record a variance assessment against the facts it rests on."
    arguments = (
        ArgumentSpec("subject_id", "string", "What the assessment is about."),
        ArgumentSpec("assessment", "text", "The assessment, in the author's words."),
        ArgumentSpec("cite_fact_ids", "fact_ids", "The figures it rests on."),
    )
    cites = ("cite_fact_ids",)

    def validate(self, arguments: dict[str, Any], ctx: ToolContext) -> None:
        super().validate(arguments, ctx)
        if not arguments["cite_fact_ids"]:
            raise ToolRejection("no_evidence", "a variance assessment must cite figures")

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        fact = self.emit_fact(
            ctx,
            kind="close.assessment",
            subject=arguments["subject_id"],
            text=arguments["assessment"],
            authority=Authority.WORKING_DOCUMENT,
            period=ctx.period,
        )
        return ToolResult(accepted=True, fact_ids=[fact.id])


class RequestJournal(Tool):
    """Raise an adjustment. Granted to the business partner; posting is not."""

    name = "request_journal"
    domain = "finance"
    summary = "Request a journal adjustment. It is routed to whoever may post it."
    arguments = (
        ArgumentSpec("subject_id", "string", "The subject the adjustment affects."),
        ArgumentSpec("narrative", "text", "What the adjustment is for."),
        ArgumentSpec("amount", "number", "Magnitude, in the corpus currency unit."),
        ArgumentSpec("cite_fact_ids", "fact_ids", "Facts justifying it."),
    )
    cites = ("cite_fact_ids",)

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        fact = self.emit_fact(
            ctx,
            kind="close.journal_request",
            subject=arguments["subject_id"],
            text=f"{arguments['narrative']} (requested by {ctx.actor.title})",
            authority=Authority.WORKING_DOCUMENT,
            period=ctx.period,
        )
        approver = ctx.person(ctx.roles["controller"])
        task = self.emit_task(
            ctx,
            kind="journal_approval",
            title=f"Post or reject: {arguments['narrative']}",
            owner_id=approver.id,
            domain="finance",
            fact_ids=[fact.id, *arguments["cite_fact_ids"]],
        )
        message = self.emit_message(
            ctx,
            kind="escalation",
            recipients=[approver.id],
            text=arguments["narrative"],
            discloses=[fact.id, *arguments["cite_fact_ids"]],
        )
        return ToolResult(
            accepted=True, fact_ids=[fact.id], task_ids=[task.id], message_ids=[message.id]
        )


class PostJournal(Tool):
    """Book the adjustment. The other half of the A2 exit gate."""

    name = "post_journal"
    domain = "finance"
    summary = "Post a requested journal to the ledger."
    arguments = (
        ArgumentSpec("request_fact_id", "fact_id", "The request being posted."),
        ArgumentSpec("amount", "number", "Magnitude, in the corpus currency unit."),
    )
    cites = ("request_fact_id",)

    def validate(self, arguments: dict[str, Any], ctx: ToolContext) -> None:
        super().validate(arguments, ctx)
        request = ctx.fact(arguments["request_fact_id"])
        if request.kind != "close.journal_request":
            raise ToolRejection(
                "wrong_fact_kind", f"{request.id} is a {request.kind}, not a journal request"
            )
        # An approval limit is a number the policy holds, not a number the actor
        # asserts. A controller may post up to their limit and no further,
        # whatever the request says.
        limit = ctx.policy.approval_limits.get("journal_posting")
        if limit is not None and abs(arguments["amount"]) > limit:
            raise ToolRejection(
                "over_approval_limit",
                f"{ctx.role_key} may post up to {limit:g}; this is {abs(arguments['amount']):g}",
            )

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        request = ctx.fact(arguments["request_fact_id"])
        event = self.emit_event(
            ctx,
            kind="journal_posted",
            summary=f"{ctx.actor.title} posted the requested adjustment.",
            systems=[ctx.roles["sys_erp"]],
        )
        fact = self.emit_fact(
            ctx,
            kind="close.journal_posted",
            subject=request.subject,
            text=f"Posted: {request.text_value}",
            authority=Authority.SYSTEM_OF_RECORD,
            event_id=event.id,
            source_system=ctx.roles["sys_erp"],
            period=ctx.period,
            supersedes=request.id,
        )
        return ToolResult(accepted=True, event_ids=[event.id], fact_ids=[fact.id])


class EscalateCloseIssue(Tool):
    """Say that something operational is now a close problem.

    The tool that makes the finance half of the episode start: until somebody in
    finance connects a failed pipeline to the close calendar, the incident is
    engineering's problem and nobody has told the controller.
    """

    name = "escalate_close_issue"
    domain = "finance"
    summary = "Raise an operational issue as a dependency of the close, to named roles."
    arguments = (
        ArgumentSpec("dependency", "text", "What the close now depends on."),
        ArgumentSpec("to_role_keys", "fact_ids", "Roles to escalate to."),
        ArgumentSpec("cite_fact_ids", "fact_ids", "Facts establishing the dependency."),
    )
    cites = ("cite_fact_ids",)

    def validate(self, arguments: dict[str, Any], ctx: ToolContext) -> None:
        super().validate(arguments, ctx)
        unknown = [k for k in arguments["to_role_keys"] if k not in ctx.roles]
        if unknown:
            raise ToolRejection("unknown_role", f"not roles in this world: {unknown}")
        if not arguments["cite_fact_ids"]:
            raise ToolRejection("no_evidence", "an escalation must cite what it rests on")

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        event = self.emit_event(
            ctx,
            kind="close_dependency_raised",
            summary=f"{ctx.actor.title} raised a close dependency: {arguments['dependency']}",
        )
        fact = self.emit_fact(
            ctx,
            kind="close.dependency",
            subject=ctx.world.company.id,
            text=arguments["dependency"],
            authority=Authority.WORKING_DOCUMENT,
            event_id=event.id,
            period=ctx.period,
        )
        recipients = [ctx.person(ctx.roles[k]).id for k in arguments["to_role_keys"]]
        message = self.emit_message(
            ctx,
            kind="escalation",
            recipients=recipients,
            text=arguments["dependency"],
            discloses=[fact.id, *arguments["cite_fact_ids"]],
        )
        return ToolResult(
            accepted=True, event_ids=[event.id], fact_ids=[fact.id], message_ids=[message.id]
        )


class DecideCloseSchedule(Tool):
    """Move the close, or hold it. The episode's consequential decision.

    The decision does not change the close date the operational generator
    already produced — the calendar is world state and the runtime owns it. What
    the actor produces is the *decision record*: who decided, on what evidence,
    at what moment, and with which approver named. That record is the thing an
    evaluation can ask about and the deterministic calendar cannot answer.
    """

    name = "decide_close_schedule"
    domain = "governance"
    summary = (
        "Record the decision to hold or move the close, naming the evidence and "
        "the approver. Requires that you have read the ledger yourself."
    )
    arguments = (
        ArgumentSpec(
            "decision", "enum", "What was decided.",
            choices=("hold", "delay_one_business_day", "delay_further"),
        ),
        ArgumentSpec("rationale", "text", "Why."),
        ArgumentSpec("cite_fact_ids", "fact_ids", "The evidence relied on."),
        ArgumentSpec("approver_role_key", "string", "Role approving the decision.", required=False),
    )
    cites = ("cite_fact_ids",)

    def validate(self, arguments: dict[str, Any], ctx: ToolContext) -> None:
        super().validate(arguments, ctx)
        from ..policy import decision_right, policy_role

        right = decision_right("close_schedule")
        assert right is not None  # declared in policy.py
        role = policy_role(ctx.role_key)
        if role not in {right.accountable_role, *right.approver_roles}:
            raise ToolRejection(
                "no_decision_right",
                f"{ctx.role_key} holds no decision right over close_schedule",
            )
        approver = arguments.get("approver_role_key")
        if approver is not None:
            if policy_role(approver) not in right.approver_roles:
                raise ToolRejection(
                    "wrong_approver",
                    f"{approver} is not an approver of close_schedule "
                    f"(approvers: {right.approver_roles})",
                )
            if approver not in ctx.roles:
                raise ToolRejection("unknown_role", f"{approver} is not a role in this world")
        if not arguments["cite_fact_ids"]:
            raise ToolRejection("no_evidence", "a close decision must cite what it rests on")

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        approver_key = arguments.get("approver_role_key")
        approver = ctx.person(ctx.roles[approver_key]) if approver_key else None
        event = self.emit_event(
            ctx,
            kind="close_decision_made",
            summary=(
                f"{ctx.actor.title} decided: {arguments['decision']}. {arguments['rationale']}"
                + (f" Approved by {approver.title}." if approver else "")
            ),
            actors=[ctx.actor.id, *([approver.id] if approver else [])],
        )
        fact = self.emit_fact(
            ctx,
            kind="close.decision",
            subject=ctx.world.company.id,
            text=(
                f"{arguments['decision']} — {arguments['rationale']}"
                + (f" Approved by {approver.title}." if approver else " No approver recorded.")
            ),
            authority=Authority.APPROVED_REPORT,
            event_id=event.id,
            period=ctx.period,
        )
        recipients = sorted({ctx.roles["cfo"], ctx.roles["reporting_manager"]})
        message = self.emit_message(
            ctx,
            kind="decision",
            recipients=recipients,
            text=arguments["rationale"],
            discloses=[fact.id, *arguments["cite_fact_ids"]],
        )
        return ToolResult(
            accepted=True, event_ids=[event.id], fact_ids=[fact.id], message_ids=[message.id]
        )


for _tool in (
    ReadLedger(),
    QueryBudget(),
    QueryForecast(),
    CreateVarianceAnalysis(),
    RequestJournal(),
    PostJournal(),
    EscalateCloseIssue(),
    DecideCloseSchedule(),
):
    register(_tool)
