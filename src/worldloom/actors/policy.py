"""Role policies and decision rights.

Authority is enforced here and nowhere else. A tool asks whether the caller's
policy permits it; it never asks who the caller is. That indirection is what
makes the two exit-gate cases in ``docs/actor-simulation.md`` §A2 real rather
than incidental — the finance business partner cannot post a journal because
``post_journal`` is not in its policy, not because some branch somewhere checks
for a job title.

Policies are compiled from role definitions rather than written per person, for
the same reason the organisation generator keys everything on role keys: lore is
authored before the graph exists and cannot know who will hold a job. A
succession changes who is invoked, not what they are allowed to do.

Domains are coarse on purpose. ``finance``, ``operations``, ``engineering``,
``commercial``, ``governance``, ``people`` — six, matching the fact-kind
families the world actually generates. A finer taxonomy would be a guess about a
second vertical that does not exist yet, which is the same mistake as designing
a scenario DSL early.
"""

from __future__ import annotations

from .models import ActorPolicy, DecisionRight

#: Fact-kind prefix to the domain that owns it.
#:
#: Longest prefix wins, so ``close.decision`` can be governed separately from
#: ``close.due_date`` without either becoming a special case in a reader.
_DOMAIN_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("financial.", "finance"),
    ("close.decision", "governance"),
    ("close.dependency", "finance"),
    ("close.", "finance"),
    ("metric.", "commercial"),
    ("ops.remediation", "engineering"),
    ("ops.root_cause", "engineering"),
    ("ops.cause", "engineering"),
    ("ops.change", "engineering"),
    ("ops.mapping_table_owner", "engineering"),
    ("ops.", "operations"),
    ("decision.", "governance"),
    ("org.", "people"),
    ("people.", "people"),
)


def domain_of(fact_kind: str) -> str:
    """Which domain a fact kind belongs to. Longest matching prefix wins."""
    best, domain = "", "operations"
    for prefix, candidate in _DOMAIN_BY_PREFIX:
        if fact_kind.startswith(prefix) and len(prefix) > len(best):
            best, domain = prefix, candidate
    return domain


# ---------------------------------------------------------------------------
# The policies
# ---------------------------------------------------------------------------

#: Tools every actor may call, whatever its role.
#:
#: Read-only, and the way an actor discovers what it is looking at. Withholding
#: it would not restrict authority; it would produce an actor that has to guess,
#: and an actor that guesses is one that invents.
#:
#: Note what is *not* universal: ``add_work_note`` writes to the operations
#: domain, so it is granted per role rather than to everyone. A controller who
#: could annotate an incident ticket would be writing in a system they have no
#: standing in, which is a permission bug that reads as a convenience.
_UNIVERSAL: tuple[str, ...] = ("search_incidents",)


_POLICIES: tuple[ActorPolicy, ...] = (
    # -- service management --------------------------------------------------
    ActorPolicy(
        role_key="svc_desk",
        allowed_tools=[
            *_UNIVERSAL,
            "add_work_note",
            "create_incident",
            "update_incident",
            "assign_incident",
            "draft_artifact",
            "submit_for_review",
        ],
        readable_domains=["operations"],
        writable_domains=["operations"],
        # An analyst may open a P2. Declaring a major incident is somebody
        # else's call, and it is prohibited rather than merely absent so the
        # refusal names a rule instead of reading as an oversight.
        prohibited_actions=["escalate_major_incident", "approve_artifact"],
    ),
    ActorPolicy(
        role_key="svc_incident",
        allowed_tools=[
            *_UNIVERSAL,
            "add_work_note",
            "update_incident",
            "assign_incident",
            "escalate_major_incident",
            "request_evidence",
            "request_revision",
        ],
        readable_domains=["operations", "engineering"],
        writable_domains=["operations"],
        prohibited_actions=["approve_change", "post_journal"],
    ),
    # -- engineering ---------------------------------------------------------
    ActorPolicy(
        role_key="platform_senior",
        allowed_tools=[
            *_UNIVERSAL,
            "add_work_note",
            "query_logs",
            "inspect_dependencies",
            "record_hypothesis",
            "propose_change",
            "create_remediation_issue",
            "publish_runbook",
            "draft_artifact",
            "submit_for_review",
        ],
        readable_domains=["operations", "engineering"],
        writable_domains=["engineering", "operations"],
        required_evidence={
            # The A2 rule that has teeth. An engineer may record a hunch freely;
            # promoting one to a confirmed cause requires having actually looked,
            # and "looked" means an observation this actor gathered through a
            # tool rather than one it was told about.
            "record_hypothesis": ["system_of_record"],
        },
        # Proposing a production change is the engineer's job. Approving their
        # own proposal is the separation of duties this whole layer exists for.
        prohibited_actions=["approve_change", "post_journal", "decide_close_schedule"],
    ),
    ActorPolicy(
        role_key="platform_lead",
        allowed_tools=[
            *_UNIVERSAL,
            "add_work_note",
            "inspect_dependencies",
            "approve_change",
            "create_remediation_issue",
            "assign_task",
            "publish_runbook",
            "draft_artifact",
            "submit_for_review",
        ],
        readable_domains=["operations", "engineering"],
        writable_domains=["engineering", "operations"],
        approval_limits={"production_change": 1.0},
        prohibited_actions=["post_journal", "decide_close_schedule"],
    ),
    # -- finance -------------------------------------------------------------
    ActorPolicy(
        role_key="finance_business_partner",
        allowed_tools=[
            *_UNIVERSAL,
            "read_ledger",
            "query_budget",
            "query_forecast",
            "create_variance_analysis",
            "request_journal",
            "escalate_close_issue",
            "draft_artifact",
            "submit_for_review",
        ],
        readable_domains=["finance", "commercial", "operations"],
        writable_domains=["finance"],
        # The first half of the A2 exit gate. `request_journal` is granted;
        # `post_journal` is denied by name, so an attempt is refused with a rule
        # rather than with a lookup miss.
        prohibited_actions=["post_journal", "decide_close_schedule", "approve_artifact"],
    ),
    ActorPolicy(
        role_key="controller",
        allowed_tools=[
            *_UNIVERSAL,
            "read_ledger",
            "query_budget",
            "query_forecast",
            "create_variance_analysis",
            "request_journal",
            "post_journal",
            "escalate_close_issue",
            "decide_close_schedule",
            "draft_artifact",
            "submit_for_review",
            "approve_artifact",
        ],
        readable_domains=["finance", "commercial", "operations", "governance"],
        writable_domains=["finance", "governance"],
        approval_limits={"journal_posting": 500.0, "close_schedule": 1.0},
        required_evidence={
            # A close does not move on a rumour. The controller must have
            # observed the operational position before deciding the calendar,
            # which is what makes "who knew the root cause before the close
            # decision" a question with a checkable answer.
            "decide_close_schedule": ["system_of_record"],
        },
        prohibited_actions=["approve_change"],
    ),
    ActorPolicy(
        role_key="cfo",
        allowed_tools=[
            *_UNIVERSAL,
            "read_ledger",
            "query_budget",
            "escalate_close_issue",
            "decide_close_schedule",
            "draft_artifact",
            "submit_for_review",
            "approve_artifact",
        ],
        readable_domains=["finance", "commercial", "governance", "operations"],
        writable_domains=["finance", "governance"],
        approval_limits={"journal_posting": 5000.0, "close_schedule": 1.0},
        prohibited_actions=["approve_change", "post_journal"],
    ),
)


_BY_ROLE: dict[str, ActorPolicy] = {policy.role_key: policy for policy in _POLICIES}


#: Business-unit finance partners share one policy. The organisation generator
#: mints a role key per unit (``food_bp``, ``digital_bp``), and every one of them
#: is the same job — writing a policy per unit would be five copies that drift.
_ROLE_ALIASES: tuple[tuple[str, str], ...] = (
    ("_bp", "finance_business_partner"),
)


def policy_role(role_key: str) -> str:
    """The policy role a world role key resolves to."""
    if role_key in _BY_ROLE:
        return role_key
    for suffix, target in _ROLE_ALIASES:
        if role_key.endswith(suffix):
            return target
    return role_key


def policy_for(role_key: str) -> ActorPolicy | None:
    """The compiled policy for *role_key*, or ``None`` if the role has none.

    ``None`` means "this role is not an actor", which is the ordinary case: most
    employees are records, and the roadmap's fifth design rule says so. A missing
    policy is not an error and must not be substituted with a permissive default
    — a role nobody wrote a policy for should be unable to act, not able to do
    anything.
    """
    return _BY_ROLE.get(policy_role(role_key))


def policies() -> tuple[ActorPolicy, ...]:
    """Every compiled policy, in a stable order."""
    return _POLICIES


# ---------------------------------------------------------------------------
# Decision rights
# ---------------------------------------------------------------------------

_DECISION_RIGHTS: tuple[DecisionRight, ...] = (
    DecisionRight(
        decision_type="close_schedule",
        accountable_role="controller",
        approver_roles=["cfo"],
        consulted_roles=["reporting_manager", "svc_incident"],
    ),
    DecisionRight(
        decision_type="production_change",
        accountable_role="platform_lead",
        approver_roles=["platform_lead"],
        veto_roles=["svc_incident"],
        consulted_roles=["platform_senior"],
    ),
    DecisionRight(
        decision_type="journal_posting",
        accountable_role="controller",
        approver_roles=["controller"],
        consulted_roles=["finance_business_partner"],
    ),
    DecisionRight(
        decision_type="major_incident_declaration",
        accountable_role="svc_incident",
        approver_roles=["svc_lead"],
    ),
    DecisionRight(
        decision_type="remediation_ownership",
        accountable_role="platform_lead",
        approver_roles=["platform_lead"],
        consulted_roles=["merch_lead", "audit"],
    ),
)

_RIGHT_BY_TYPE: dict[str, DecisionRight] = {r.decision_type: r for r in _DECISION_RIGHTS}


def decision_right(decision_type: str) -> DecisionRight | None:
    """The decision right for *decision_type*, if one is declared."""
    return _RIGHT_BY_TYPE.get(decision_type)


def decision_rights() -> tuple[DecisionRight, ...]:
    """Every declared decision right, in a stable order."""
    return _DECISION_RIGHTS


__all__ = [
    "decision_right",
    "decision_rights",
    "domain_of",
    "policies",
    "policy_for",
    "policy_role",
]
