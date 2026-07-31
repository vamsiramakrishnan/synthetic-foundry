"""Artifact tools.

``draft_artifact`` produces an ``ArtifactIntent`` and stops. That boundary is the
whole reason this package can exist without becoming a document generator: the
artifact compiler still decides the outline, the narrative compiler still writes
the body under fact constraints, and the renderers still make the files. An actor
that produced a finished document would be choosing its structure, its claims,
and its numbers in one step, with none of the three checked by anything.

So what an actor actually decides here is the interesting part and only the
interesting part: that a document should exist, what type it is, who it is for,
and — the load-bearing choice — which of the facts it has observed belong in it.
The executive summary omitting the control failure is not a rule in a template.
It is the CFO citing four facts and not a fifth.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ...documents import standing
from ...models import Authority
from ..models import ToolResult
from .base import ArgumentSpec, Tool, ToolContext, ToolRejection, register

#: Which artifact types an actor may draft, and the audience each is for.
#:
#: Closed, and checked. An open list would let an actor invent an artifact type
#: no compiler can outline and no renderer can spell, which fails much later and
#: much less legibly than a rejection here.
DRAFTABLE: dict[str, tuple[str, str, str]] = {
    # artifact_type: (domain, default audience, size profile)
    "servicenow_incident": ("operations", "technology", "medium"),
    "confluence_page": ("operations", "all_staff", "small"),
    "working_note": ("finance", "finance", "small"),
    "incident_rca": ("engineering", "technology", "long"),
    "jira_issues": ("engineering", "technology", "small"),
    "knowledge_article": ("operations", "technology", "medium"),
    "executive_summary": ("strategy", "executive_committee", "small"),
    "cfo_variance_memo": ("finance", "group_cfo", "medium"),
}

#: The most facts an actor may put into one document.
#:
#: A bound on narrative fan-out, not on ambition. A world reports revenue at
#: group, division, category, and store; an actor woken late enough has observed
#: all of them, and an executive summary citing four hundred figures produces
#: four hundred narrative requests to write three sentences. The deterministic
#: planner solves the same problem by splitting headline facts from the whole
#: hierarchy (see `generators/finance.py`); an actor has to be told.
#:
#: The workbook is the one artifact that legitimately cites thousands, and it is
#: not in `DRAFTABLE` — it is a standing output of the close, planned every
#: period whether or not anything happened.
MAX_CITED_FACTS = 40


class DraftArtifact(Tool):
    """Decide a document should exist, and which observed facts belong in it."""

    name = "draft_artifact"
    domain = "operations"
    summary = (
        "Plan a document of a permitted type, citing facts you have observed. "
        "Structure and prose are produced downstream; you choose type, audience, "
        "and contents."
    )
    arguments = (
        ArgumentSpec(
            "artifact_type", "enum", "What kind of document.",
            choices=tuple(sorted(DRAFTABLE)),
        ),
        ArgumentSpec("cite_fact_ids", "fact_ids", "The facts it must be able to cite."),
        ArgumentSpec("rationale", "text", "Why this document is warranted."),
        ArgumentSpec("audience", "string", "Override the default audience.", required=False),
        ArgumentSpec("derived_from_artifact_id", "string", "An earlier document this builds on.",
                     required=False),
    )
    cites = ("cite_fact_ids",)

    @classmethod
    def spec_for(cls, policy):  # type: ignore[no-untyped-def]
        """Only the artifact types this role may actually author.

        Without this an actor is offered eight types, may write three, and finds
        out which by being refused. The check in `validate` stays — narrowing
        what is *offered* is a courtesy, and a courtesy is not a permission
        boundary.
        """
        writable = {*policy.writable_domains}
        allowed = tuple(
            sorted(
                artifact_type
                for artifact_type, (domain, _, _) in DRAFTABLE.items()
                if domain in writable or _ARTIFACT_DOMAIN_ALIASES.get(domain) in writable
            )
        )
        base = cls.spec()
        return replace(
            base,
            arguments=tuple(
                replace(argument, choices=allowed)
                if argument.name == "artifact_type"
                else argument
                for argument in base.arguments
            ),
        )

    def authorise(self, ctx: ToolContext) -> None:
        # `draft_artifact` is domain-agnostic on purpose: the domain that matters
        # is the *artifact's*, not the tool's, and that is checked in `validate`
        # where the argument is visible. Running the base check with this class's
        # nominal domain would refuse a finance controller drafting a working
        # note because "operations" is not in their writable domains.
        if not ctx.policy.permits(self.name):
            raise ToolRejection(
                "not_authorised", f"{ctx.role_key} may not call {self.name}"
            )

    def validate(self, arguments: dict[str, Any], ctx: ToolContext) -> None:
        artifact_type = arguments["artifact_type"]
        domain, _, _ = DRAFTABLE[artifact_type]
        # Shape first, contents second. An actor that handed over four hundred
        # facts should be told to choose, not walked through which of the four
        # hundred it had not seen — the useful correction is the smaller one.
        if not arguments["cite_fact_ids"]:
            raise ToolRejection(
                "artifact_without_facts",
                f"a {artifact_type} citing nothing has no date and nothing to say",
            )
        if len(arguments["cite_fact_ids"]) > MAX_CITED_FACTS:
            raise ToolRejection(
                "too_many_facts",
                f"a {artifact_type} may cite at most {MAX_CITED_FACTS} facts;"
                f" this cites {len(arguments['cite_fact_ids'])}. Choose what matters.",
            )
        super().validate(arguments, ctx)
        # An author must be able to read what they are writing about. Without
        # this an actor could compile a document out of facts it observed
        # through one channel into an audience it has no standing with — which
        # is how a corpus grows a memo its own author could not have filed.
        writable = {*ctx.policy.writable_domains}
        if domain not in writable and _ARTIFACT_DOMAIN_ALIASES.get(domain) not in writable:
            raise ToolRejection(
                "domain_not_writable",
                f"{ctx.role_key} may not author a {artifact_type} ({domain})",
            )
        # The same visibility check the other three artifact tools use. Existence
        # is not visibility: deriving from a document this actor cannot read
        # would let it claim lineage from a paper it has no standing with, by
        # guessing an id.
        parent = arguments.get("derived_from_artifact_id")
        if parent is not None:
            _visible_intent(parent, ctx)

        # An author has to be able to read what they wrote. The audience decides
        # the access policy, so an override can put a document outside its own
        # author's reach — and the failure lands as `author_cannot_see_own_artifact`
        # at validation time, after the corpus has been exported. Refusing here
        # costs one lookup and turns a post-hoc corpus defect into a rejection the
        # actor can act on.
        audience = arguments.get("audience")
        if audience is not None:
            policy_id = ctx.world._policy_for(audience)
            policy = next(
                (p for p in ctx.world.access_policies if p.id == policy_id), None
            )
            if policy is not None and not policy.permits(ctx.actor):
                raise ToolRejection(
                    "author_excluded_by_audience",
                    f"an audience of {audience!r} resolves to {policy.label!r}, which"
                    f" does not admit {ctx.role_key}; you cannot file a document you"
                    " could not then read",
                )

    def idempotency_key(self, arguments: dict[str, Any], ctx: ToolContext) -> str:
        # One document of a type per author per episode. A second draft is a
        # revision, which is a different tool's job.
        return f"draft_artifact|{ctx.actor.id}|{arguments['artifact_type']}"

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        artifact_type = arguments["artifact_type"]
        domain, audience, size = DRAFTABLE[artifact_type]
        intent = self.emit_intent(
            ctx,
            artifact_type=artifact_type,
            domain=domain,
            audience=arguments.get("audience") or audience,
            fact_ids=arguments["cite_fact_ids"],
            event_ids=[ctx.observation.trigger_event_id or ""],
            size=size,
            rationale=arguments["rationale"],
            derived_from=[arguments["derived_from_artifact_id"]]
            if arguments.get("derived_from_artifact_id")
            else None,
        )
        return ToolResult(accepted=True, artifact_intent_ids=[intent.id])


#: Authoring a strategy paper is a governance act; there is no `strategy`
#: writable domain and inventing one for a single artifact type would be a sixth
#: domain that exists to satisfy one lookup.
_ARTIFACT_DOMAIN_ALIASES = {"strategy": "governance"}


def _visible_intent(artifact_id: str, ctx: ToolContext):  # type: ignore[no-untyped-def]
    """A planned artifact this actor can actually see.

    The artifact counterpart of ``ToolContext.fact``. Existence is not
    visibility: a document whose access policy excludes this employee is one
    they must not be able to submit, approve, or return, and checking only that
    it exists would let an actor act on a paper it could not read.
    """
    intent = ctx.world.artifact_intents.get(artifact_id)
    if intent is None:
        raise ToolRejection("unknown_artifact", f"{artifact_id} is not a planned artifact")
    if artifact_id not in ctx.observation.visible_artifact_ids:
        raise ToolRejection(
            "unobserved_artifact", f"{artifact_id} is not visible to {ctx.actor.id}"
        )
    return intent


class SubmitForReview(Tool):
    """Hand a draft to a named reviewer, and put them on the hook for it."""

    name = "submit_for_review"
    domain = "operations"
    summary = "Submit a drafted artifact to a reviewer."
    arguments = (
        ArgumentSpec("artifact_id", "string", "The drafted artifact."),
        ArgumentSpec("reviewer_role_key", "string", "Who is to review it."),
    )

    def authorise(self, ctx: ToolContext) -> None:
        if not ctx.policy.permits(self.name):
            raise ToolRejection("not_authorised", f"{ctx.role_key} may not call {self.name}")

    def validate(self, arguments: dict[str, Any], ctx: ToolContext) -> None:
        super().validate(arguments, ctx)
        intent = _visible_intent(arguments["artifact_id"], ctx)
        if intent.author_id != ctx.actor.id:
            raise ToolRejection(
                "not_the_author",
                f"{arguments['artifact_id']} was drafted by {intent.author_id}",
            )
        if arguments["reviewer_role_key"] not in ctx.roles:
            raise ToolRejection("unknown_role", f"{arguments['reviewer_role_key']} is not a role")

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        reviewer = ctx.person(ctx.roles[arguments["reviewer_role_key"]])
        intent = ctx.world.artifact_intents.by_id(arguments["artifact_id"])
        task = self.emit_task(
            ctx,
            kind="artifact_review",
            title=f"Review {intent.artifact_type} {intent.id}",
            owner_id=reviewer.id,
            domain="governance",
            fact_ids=list(intent.required_fact_ids),
        )
        message = self.emit_message(
            ctx,
            kind="work_note",
            recipients=[reviewer.id],
            text=f"{intent.artifact_type} {intent.id} is ready for your review.",
            discloses=list(intent.required_fact_ids),
            subject_ref=intent.id,
        )
        return ToolResult(accepted=True, task_ids=[task.id], message_ids=[message.id])


class ApproveArtifact(Tool):
    """Approve a submitted artifact. Only a role whose policy grants governance."""

    name = "approve_artifact"
    domain = "governance"
    summary = "Approve a submitted artifact, recording who approved it and when."
    arguments = (
        ArgumentSpec("artifact_id", "string", "The artifact being approved."),
        ArgumentSpec("note", "text", "The approval note."),
    )

    def validate(self, arguments: dict[str, Any], ctx: ToolContext) -> None:
        super().validate(arguments, ctx)
        intent = _visible_intent(arguments["artifact_id"], ctx)
        if intent.author_id == ctx.actor.id:
            raise ToolRejection(
                "self_approval",
                f"{ctx.actor.id} drafted {intent.id} and may not also approve it",
            )
        authority, _ = standing(intent.artifact_type)
        if authority is Authority.SYSTEM_OF_RECORD:
            raise ToolRejection(
                "not_approvable",
                f"a {intent.artifact_type} is a system record, not a document under review",
            )

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        intent = ctx.world.artifact_intents.by_id(arguments["artifact_id"])
        event = self.emit_event(
            ctx,
            kind="artifact_approved",
            summary=f"{ctx.actor.title} approved {intent.artifact_type} {intent.id}.",
        )
        fact = self.emit_fact(
            ctx,
            kind="decision.artifact_approved",
            subject=ctx.world.company.id,
            text=f"{intent.artifact_type} {intent.id} approved by {ctx.actor.title}: {arguments['note']}",
            authority=Authority.APPROVED_REPORT,
            event_id=event.id,
            period=ctx.period,
        )
        return ToolResult(accepted=True, event_ids=[event.id], fact_ids=[fact.id])


class RequestRevision(Tool):
    """Send it back, saying what is missing. The reviewer's other option."""

    name = "request_revision"
    domain = "operations"
    summary = "Return an artifact to its author with what must change."
    arguments = (
        ArgumentSpec("artifact_id", "string", "The artifact being returned."),
        ArgumentSpec("required_change", "text", "What must change."),
    )

    def validate(self, arguments: dict[str, Any], ctx: ToolContext) -> None:
        super().validate(arguments, ctx)
        intent = _visible_intent(arguments["artifact_id"], ctx)
        if intent.author_id == ctx.actor.id:
            raise ToolRejection("self_review", "an author cannot return their own draft")

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        intent = ctx.world.artifact_intents.by_id(arguments["artifact_id"])
        task = self.emit_task(
            ctx,
            kind="artifact_revision",
            title=arguments["required_change"],
            owner_id=intent.author_id,
            domain="operations",
            fact_ids=list(intent.required_fact_ids),
        )
        message = self.emit_message(
            ctx,
            kind="work_note",
            recipients=[intent.author_id],
            text=arguments["required_change"],
            subject_ref=intent.id,
        )
        return ToolResult(accepted=True, task_ids=[task.id], message_ids=[message.id])


class AssignTask(Tool):
    """Put an owner on an existing task. Assignment is itself an authority act."""

    name = "assign_task"
    domain = "engineering"
    summary = "Assign an existing open task to a named role."
    arguments = (
        ArgumentSpec("task_id", "task_id", "The task to assign."),
        ArgumentSpec("owner_role_key", "string", "Role that will own it."),
    )

    def validate(self, arguments: dict[str, Any], ctx: ToolContext) -> None:
        super().validate(arguments, ctx)
        task = next((t for t in ctx.tasks if t.id == arguments["task_id"]), None)
        if task is None:
            raise ToolRejection("unknown_task", f"{arguments['task_id']} does not exist")
        if task.id not in ctx.observation.task_ids:
            raise ToolRejection(
                "unobserved_task", f"{task.id} is not visible to {ctx.actor.id}"
            )
        if arguments["owner_role_key"] not in ctx.roles:
            raise ToolRejection("unknown_role", f"{arguments['owner_role_key']} is not a role")

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        task = next(t for t in ctx.tasks if t.id == arguments["task_id"])
        owner = ctx.person(ctx.roles[arguments["owner_role_key"]])
        # Tasks are frozen. Assignment produces a replacement carrying the same
        # id, which the runtime merges by id — the same rule `World.extend` uses
        # for a person who leaves. The obligation is the same obligation; only
        # who is on the hook for it changed.
        ctx.new_tasks.append(task.model_copy(update={"owner_id": owner.id, "state": "assigned"}))
        message = self.emit_message(
            ctx,
            kind="assignment",
            recipients=[owner.id],
            text=f"{task.title} is yours.",
            discloses=list(task.fact_ids),
            subject_ref=task.id,
        )
        return ToolResult(accepted=True, task_ids=[task.id], message_ids=[message.id])


for _tool in (
    DraftArtifact(),
    SubmitForReview(),
    ApproveArtifact(),
    RequestRevision(),
    AssignTask(),
):
    register(_tool)


__all__ = ["DRAFTABLE"]
