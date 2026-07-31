"""Actor providers.

A provider turns one bounded observation into one chosen action. That is the
entire interface, and it is deliberately the same size as ``narrative.Provider``
for the same reason: a real adapter — Claude Code, Codex, the Antigravity SDK,
anything that can read JSON and answer with JSON — should be a thin wrapper over
whatever it already has, not an integration.

No real adapter ships here, and the reason is the same as it is for narration.
The contract plus a deterministic fake is the useful thing to land first: the
whole runtime — observation projection, policy checks, tool validation, ledger
write and replay — is then testable with no key, no network, and no spend, and
the first real adapter is written against a contract that already works.

**Why there is no batch handshake yet.** Narration hands an agent every request
at once because the requests are independent. Actor decisions are not: what the
controller sees at 09:40 depends on whether the business partner escalated at
09:12, so a batch of invocations cannot be prepared in advance without deciding
the episode first. A turn-by-turn handshake is the honest shape and it is real
work — a CLI that suspends an episode mid-flight, serialises the world, and
resumes it. Until that exists, an agent drives an episode by implementing
``act`` in process, or by replaying decisions it made earlier through
``TranscriptActorProvider``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..ids import content_key
from .models import ActorAction, ActorInvocation
from .tools.base import ToolSpec

#: Bumped when the observation payload's *shape* changes.
#:
#: Part of every actor ledger key, exactly as ``prompts.SECTION_PROSE.key`` is
#: part of every narration key. Changing what an actor is shown changes what it
#: would decide, so it must change what a seed means — explicitly, by
#: regenerating, rather than silently by replaying decisions taken on a
#: different view.
OBSERVATION_VERSION = "actor-observation-v1"


class ActorProviderError(Exception):
    """Raised when a provider cannot answer."""


@dataclass(frozen=True)
class ObservationView:
    """What an actor reads. Built from an ``ActorObservation`` and nothing else.

    There is no ``World`` on this object and no accessor that could reach one.
    That is the enforcement: "actors receive only role-scoped observations" is
    not a rule the provider is asked to respect, it is the only thing a provider
    is given.

    Three things here are *not* fact-scoped and it is worth being explicit about
    why. ``entities`` and ``roles`` are the org chart and the systems list, which
    an employee knows by working somewhere; neither carries a value, a date, or
    a state, so knowing them discloses nothing about the period. ``resources``
    is the same list keyed the way tools take it. Facts remain the only thing
    scoped, because facts are the only thing an evaluation can ask about.
    """

    invocation: ActorInvocation
    actor_title: str
    persona_voice: str
    period: str
    trigger: dict[str, str]
    facts: tuple[dict[str, Any], ...]
    messages: tuple[dict[str, Any], ...]
    tasks: tuple[dict[str, Any], ...]
    artifacts: tuple[dict[str, Any], ...]
    entities: dict[str, str]
    """Entity id to the name a person uses for it."""
    roles: dict[str, str]
    """Role key to job title, for the roles that name people."""
    resources: dict[str, str]
    """Role key to entity id, for the roles that name systems, services, and
    units — ``sys_erp``, ``svc_valuation``, ``unit_food``. What tools taking a
    ``system_id`` or ``service_id`` are filled in from."""
    turn: int
    calls_used: int

    # -- reading helpers ---------------------------------------------------
    # So a provider does not re-implement "find the fact about X" five times.
    # Every one of them filters what is already in view; none can widen it.

    def of_kind(self, *prefixes: str, subject: str | None = None) -> tuple[dict[str, Any], ...]:
        """Visible facts whose kind starts with any of *prefixes*, oldest first.

        ``subject`` narrows to one entity, and an actor drafting anything for an
        executive audience needs it. A world reports revenue at group, division,
        category, and store; by the time the CFO is woken every one of those has
        reached them through the ordinary flow of work, and a summary that cited
        all of them would be a spreadsheet with a covering letter.
        """
        return tuple(
            fact
            for fact in self.facts
            if any(fact["kind"].startswith(prefix) for prefix in prefixes)
            and (subject is None or fact["subject"] == subject)
        )

    def ids_of_kind(self, *prefixes: str, subject: str | None = None) -> list[str]:
        return [fact["id"] for fact in self.of_kind(*prefixes, subject=subject)]

    def latest(self, *prefixes: str) -> dict[str, Any] | None:
        found = self.of_kind(*prefixes)
        return found[-1] if found else None

    def id_of(self, *prefixes: str) -> str | None:
        found = self.latest(*prefixes)
        return None if found is None else found["id"]

    def subject_of(self, *prefixes: str) -> str | None:
        found = self.latest(*prefixes)
        return None if found is None else found["subject"]

    def known_roles(self, *role_keys: str) -> list[str]:
        """Those of *role_keys* this world actually has, in the order given."""
        return [key for key in role_keys if key in self.roles]

    def mine(self, artifact_type: str) -> str | None:
        """The id of an artifact of this type this actor drafted, if any."""
        for artifact in self.artifacts:
            if artifact["artifact_type"] == artifact_type and artifact["mine"]:
                return artifact["id"]
        return None

    def digest(self) -> str:
        """A content address for everything this actor can see.

        Part of the ledger key. Values are included, not only ids: a corrected
        figure has to change the key, or an episode replays a decision taken on
        a number the corpus no longer holds.
        """
        parts = [
            self.invocation.role_key,
            self.trigger.get("kind", ""),
            str(self.turn),
            *(
                f"{f['id']}|{f['kind']}|{f['statement']}|{f['authority']}|{f['learned_at']}"
                for f in self.facts
            ),
            *(f"MSG|{m['id']}|{m['kind']}" for m in self.messages),
            *(f"TASK|{t['id']}|{t['state']}|{t['owner'] or ''}" for t in self.tasks),
            *(f"ART|{a['id']}|{a['artifact_type']}" for a in self.artifacts),
        ]
        return content_key(*parts)

    def to_payload(self) -> dict[str, Any]:
        """The JSON an out-of-process agent would receive.

        A method rather than something the caller assembles, so an in-process
        provider and a remote one look at the same bytes — otherwise the ledger
        key computed from this view would not describe what an external agent
        was actually shown.
        """
        return {
            "invocation_id": self.invocation.id,
            "role": self.invocation.role_key,
            "title": self.actor_title,
            "voice": self.persona_voice,
            "period": self.period,
            "turn": self.turn,
            "calls_used": self.calls_used,
            "max_tool_calls": self.invocation.max_tool_calls,
            "deadline": self.invocation.deadline.isoformat(),
            "trigger": dict(self.trigger),
            "facts": [dict(fact) for fact in self.facts],
            "messages": [dict(message) for message in self.messages],
            "tasks": [dict(task) for task in self.tasks],
            "artifacts": [dict(artifact) for artifact in self.artifacts],
            "entities": dict(self.entities),
            "roles": dict(self.roles),
            "resources": dict(self.resources),
        }


@runtime_checkable
class ActorProvider(Protocol):
    """Anything that can choose one action from one observation."""

    id: str
    """Actor model identifier. Part of the ledger key, so changing it changes the
    episode — explicitly, the same contract narration has."""

    def act(self, view: ObservationView, tools: tuple[ToolSpec, ...]) -> ActorAction:
        """Choose a tool call, or abstain with a reason."""
        ...


# ---------------------------------------------------------------------------
# The deterministic fake
# ---------------------------------------------------------------------------


def _abstain(view: ObservationView, reason: str) -> ActorAction:
    return ActorAction(
        invocation_id=view.invocation.id, tool_name=None, abstention_reason=reason, confidence=1.0
    )


def _call(view: ObservationView, tool: str, **arguments: Any) -> ActorAction:
    return ActorAction(
        invocation_id=view.invocation.id, tool_name=tool, arguments=arguments, confidence=0.9
    )


def _service_desk_triage(view: ObservationView) -> list[ActorAction]:
    """Look for precedent, raise the ticket, put up a status page."""
    symptom = view.latest("ops.feed_status")
    if symptom is None:
        return []
    plays = [
        _call(view, "search_incidents", query="valuation"),
        _call(
            view,
            "create_incident",
            service_id=symptom["subject"],
            priority="P2",
            summary="Inventory valuation pipeline failed; stock cannot be valued for the period.",
            evidence_fact_ids=[symptom["id"]],
            notify_role_keys=view.known_roles("svc_incident", "platform_senior"),
        ),
    ]
    # The status page is raised at triage and built only from what is known now:
    # the symptom and the ticket. That it never gains the confirmed cause is the
    # corpus's oldest deliberate imperfection, and it survives here honestly —
    # the analyst has not been told yet.
    page = view.ids_of_kind("ops.feed_status", "ops.incident_opened", "ops.incident_state")
    if page:
        plays.append(
            _call(
                view,
                "draft_artifact",
                artifact_type="confluence_page",
                cite_fact_ids=page,
                rationale=(
                    "A status page is raised at triage, before the cause is known, so the "
                    "rest of the business can see the outage."
                ),
            )
        )
    return plays


def _service_desk_record(view: ObservationView) -> list[ActorAction]:
    """Once engineering has said what it was, the ticket becomes the record."""
    state = view.latest("ops.incident_state")
    if state is None:
        return []
    plays = [
        _call(
            view,
            "update_incident",
            service_id=state["subject"],
            state="investigating",
            note="Cause identified by the data platform team; workaround in progress.",
        )
    ]
    record = view.ids_of_kind(
        "ops.feed_status",
        "ops.incident_opened",
        "ops.incident_state",
        "ops.incident_assignee",
        "ops.cause_assessment",
        "ops.work_note",
    )
    if record:
        plays.append(
            _call(
                view,
                "draft_artifact",
                artifact_type="servicenow_incident",
                cite_fact_ids=record,
                rationale=(
                    "The incident record is the system of record for the operational "
                    "timeline, and now carries the assessment as well as the symptom."
                ),
            )
        )
    return plays


def _engineer_first_look(view: ObservationView) -> list[ActorAction]:
    """Inspect, then say what you think — at the standing inspecting supports."""
    symptom = view.latest("ops.feed_status")
    if symptom is None:
        return []
    service = symptom["subject"]
    return [
        _call(view, "inspect_dependencies", service_id=service),
        _call(
            view,
            "record_hypothesis",
            service_id=service,
            status="hypothesis",
            assessment=(
                "Valuation depends on the hierarchy sync; the failure looks upstream of "
                "the valuation service rather than in it."
            ),
            cite_fact_ids=[symptom["id"]],
        ),
        _call(
            view,
            "add_work_note",
            service_id=service,
            note="Working the dependency chain; will confirm or rule out the upstream feed.",
            cite_fact_ids=view.ids_of_kind("ops.cause_assessment"),
            notify_role_keys=view.known_roles("svc_desk", "svc_incident"),
        ),
    ]


def _engineer_confirm(view: ObservationView) -> list[ActorAction]:
    """Read the logs, confirm, tell the ticket, propose the fix, write the RCA."""
    symptom = view.latest("ops.feed_status")
    cause = view.latest("ops.cause")
    if symptom is None or cause is None:
        return []
    service = symptom["subject"]
    plays: list[ActorAction] = []
    erp = view.resources.get("sys_erp")
    if erp:
        plays.append(_call(view, "query_logs", system_id=erp))
    earlier = view.of_kind("ops.cause_assessment")
    plays.append(
        _call(
            view,
            "record_hypothesis",
            service_id=service,
            status="confirmed",
            assessment=(
                "Confirmed: the legacy-to-new hierarchy mapping is stale, so a block of "
                "SKUs cannot be valued. The valuation service itself is healthy."
            ),
            cite_fact_ids=[cause["id"], symptom["id"]],
            **({"supersedes_fact_id": earlier[-1]["id"]} if earlier else {}),
        )
    )
    plays.append(
        _call(
            view,
            "add_work_note",
            service_id=service,
            note="Root cause confirmed and recorded against the incident.",
            cite_fact_ids=view.ids_of_kind("ops.cause_assessment", "ops.cause"),
            notify_role_keys=view.known_roles("svc_desk", "svc_incident", "platform_lead"),
        )
    )
    plays.append(
        _call(
            view,
            "propose_change",
            service_id=service,
            change="Validate the hierarchy mapping before the valuation run, and fail loudly.",
            cite_fact_ids=[cause["id"]],
        )
    )
    runbook = view.ids_of_kind("ops.cause", "ops.affected_records", "ops.workaround",
                               "ops.mapping_table_owner")
    if runbook:
        plays.append(
            _call(
                view,
                "publish_runbook",
                title="Recovering inventory valuation after a stale hierarchy mapping",
                cite_fact_ids=runbook,
            )
        )
    return plays


def _incident_commander(view: ObservationView) -> list[ActorAction]:
    """Test the hypothesis by asking somebody to go and check, and name an owner."""
    hypothesis = view.latest("ops.cause")
    state = view.latest("ops.incident_state")
    if hypothesis is None or state is None:
        return []
    return [
        _call(
            view,
            "request_evidence",
            of_role_key="platform_senior",
            question=(
                "Confirm or rule out the recorded cause against the source system logs "
                "before we brief finance."
            ),
            about_fact_ids=[hypothesis["id"]],
        ),
        _call(
            view,
            "assign_incident",
            service_id=state["subject"],
            assignee_role_key="platform_senior",
            disclose_fact_ids=view.ids_of_kind(
                "ops.feed_status", "ops.incident_opened", "ops.cause"
            ),
        ),
    ]


def _finance_partner(view: ObservationView) -> list[ActorAction]:
    """Connect an operational failure to the close calendar. Nobody else will."""
    incident = view.latest("ops.incident_opened", "ops.feed_status")
    if incident is None:
        return []
    company = view.resources.get("company")
    plays: list[ActorAction] = []
    if company:
        plays.append(_call(view, "read_ledger", subject_id=company))
    plays.append(
        _call(
            view,
            "escalate_close_issue",
            dependency=(
                "Inventory valuation is unavailable, so stock cannot be reported and the "
                "close cannot be signed on the committed date."
            ),
            to_role_keys=view.known_roles("controller", "reporting_manager"),
            cite_fact_ids=[incident["id"], *view.ids_of_kind("close.due_date")],
        )
    )
    return plays


def _controller_briefed(view: ObservationView) -> list[ActorAction]:
    """Read the position yourself, then write the note you will decide from."""
    company = view.resources.get("company")
    plays: list[ActorAction] = []
    if company:
        plays.append(_call(view, "read_ledger", subject_id=company))
    note = view.ids_of_kind("close.", "ops.incident_opened")
    if note:
        plays.append(
            _call(
                view,
                "draft_artifact",
                artifact_type="working_note",
                cite_fact_ids=note,
                rationale="The controller keeps a running note through a disrupted close.",
            )
        )
    return plays


def _controller_decides(view: ObservationView) -> list[ActorAction]:
    """The episode's consequential decision, on evidence read first-hand."""
    company = view.resources.get("company")
    plays: list[ActorAction] = []
    if company:
        plays.append(_call(view, "read_ledger", subject_id=company))
    evidence = view.ids_of_kind("close.status", "close.revised_date", "close.dependency")
    if not evidence:
        return plays
    plays.append(
        _call(
            view,
            "decide_close_schedule",
            decision="delay_one_business_day",
            rationale=(
                "Stock could not be valued in the window, so the ledger cannot be signed "
                "on the committed date. One business day recovers the position without "
                "reporting an unvalued balance."
            ),
            cite_fact_ids=evidence,
            **({"approver_role_key": "cfo"} if "cfo" in view.roles else {}),
        )
    )
    return plays


def _platform_lead_review(view: ObservationView) -> list[ActorAction]:
    """Establish the control failure, and tell the engineer who found the fault.

    The work note is the load-bearing step. The classification and the missing
    owner are recorded against an event the engineer was not on, so without
    somebody passing them along the RCA written two days later cannot mention
    the condition that allowed any of it — which is the finding, not a detail.
    """
    classification = view.latest("ops.root_cause_classification")
    if classification is None:
        return []
    return [
        _call(view, "inspect_dependencies", service_id=classification["subject"]),
        _call(
            view,
            "add_work_note",
            service_id=classification["subject"],
            note=(
                "Review finding: the mapping table has no registered owner and no "
                "required reviewer. Treat this as a control failure, not a defect."
            ),
            cite_fact_ids=view.ids_of_kind(
                "ops.root_cause_classification", "ops.mapping_table_owner"
            ),
            notify_role_keys=view.known_roles("platform_senior", "svc_incident"),
        ),
    ]


def _platform_lead_remediate(view: ObservationView) -> list[ActorAction]:
    """Raise the two fixes, and refuse to let them be mistaken for each other."""
    classification = view.latest("ops.root_cause_classification")
    if classification is None:
        return []
    justification = view.ids_of_kind(
        "ops.root_cause_classification", "ops.mapping_table_owner", "ops.remediation"
    )
    plays: list[ActorAction] = [
        _call(
            view,
            "create_remediation_issue",
            title="Register an owner for the hierarchy mapping table, with a mandatory reviewer.",
            addresses="control",
            cite_fact_ids=justification,
            **({"owner_role_key": "merch_lead"} if "merch_lead" in view.roles else {}),
        ),
        _call(
            view,
            "create_remediation_issue",
            title="Automate validation of the mapping table before each valuation run.",
            addresses="detection",
            cite_fact_ids=justification,
            **(
                {"owner_role_key": "platform_engineer"}
                if "platform_engineer" in view.roles
                else {}
            ),
        ),
    ]
    proposal = view.latest("ops.change_proposal")
    if proposal is not None:
        plays.append(
            _call(
                view,
                "approve_change",
                proposal_fact_id=proposal["id"],
                note="Approved. Ship behind the existing pre-run gate.",
            )
        )
    tickets = view.ids_of_kind(
        "ops.remediation", "ops.root_cause_classification", "ops.mapping_table_owner"
    )
    if tickets:
        plays.append(
            _call(
                view,
                "draft_artifact",
                artifact_type="jira_issues",
                cite_fact_ids=tickets,
                rationale=(
                    "Remediation is tracked as work, separating the control fix from the "
                    "detection fix so neither is mistaken for the other."
                ),
            )
        )
    return plays


def _engineer_rca(view: ObservationView) -> list[ActorAction]:
    """The review, written once the control finding and the actions exist.

    Deliberately not written on the day the cause was confirmed. An RCA composed
    before the review has happened is missing the condition that allowed the
    failure to persist, which is the only part of it anybody acts on.
    """
    material = view.ids_of_kind("ops.", "close.")
    if not material:
        return []
    return [
        _call(
            view,
            "draft_artifact",
            artifact_type="incident_rca",
            cite_fact_ids=material,
            rationale=(
                "A P2 incident that delayed the close warrants a reviewed RCA, written "
                "after the control review rather than on the day of the outage."
            ),
        )
    ]


def _chief_financial_officer(view: ObservationView) -> list[ActorAction]:
    """The short paper. What it leaves out is the choice being made."""
    company = view.resources.get("company")
    plays: list[ActorAction] = []
    if company:
        plays.append(_call(view, "read_ledger", subject_id=company))
    # Group result, the close's own status, and the decision — and deliberately
    # not the control failure. The omission is a citation the CFO does not make,
    # not a rule in a template, which is what makes "what did the executive
    # summary leave out" answerable by comparing two fact sets.
    material = view.ids_of_kind(
        "financial.revenue", "financial.gross_margin_pct", "financial.incident_pl_impact",
        "close.status", "close.delay", "close.decision",
        subject=company,
    )
    if material:
        plays.append(
            _call(
                view,
                "draft_artifact",
                artifact_type="executive_summary",
                cite_fact_ids=material,
                rationale=(
                    "The executive committee receives a short summary of the period and "
                    "whether anything requires them."
                ),
            )
        )
    return plays


#: (policy role, trigger event kind) → the steps that role takes.
#:
#: Data rather than branching, so "what does the incident commander do when a
#: hypothesis is recorded" is one lookup rather than a walk through a function.
_SCRIPT: dict[tuple[str, str], Any] = {
    ("svc_desk", "pipeline_failed"): _service_desk_triage,
    ("svc_desk", "root_cause_confirmed"): _service_desk_record,
    ("platform_senior", "incident_opened"): _engineer_first_look,
    ("platform_senior", "root_cause_confirmed"): _engineer_confirm,
    ("svc_incident", "hypothesis_recorded"): _incident_commander,
    ("finance_business_partner", "incident_opened"): _finance_partner,
    ("controller", "close_dependency_raised"): _controller_briefed,
    ("controller", "close_delayed"): _controller_decides,
    ("platform_lead", "control_failure_identified"): _platform_lead_review,
    ("platform_lead", "remediation_created"): _platform_lead_remediate,
    ("platform_senior", "remediation_created"): _engineer_rca,
    ("cfo", "close_finalised"): _chief_financial_officer,
}


class ScriptedActorProvider:
    """A provider with no model behind it.

    The CI reference, and — like ``DeterministicProvider`` — explicitly not a
    stand-in for judgement. It encodes what each role does when woken, reading
    only what its observation actually contains, and it abstains when the facts
    it would need are not in view. That last property is what makes it a fixture
    rather than a script: run it against a world where nobody told the analyst
    about the failure and it opens no incident, because it cannot see one.

    Given the same view it returns the same action, always. No clock, no
    randomness.
    """

    id = "scripted-actor-1"

    def __init__(self) -> None:
        self.calls = 0
        """How many times this provider was actually asked. A replay leaves it at zero."""

    def act(self, view: ObservationView, tools: tuple[ToolSpec, ...]) -> ActorAction:
        from .policy import policy_role

        self.calls += 1
        play = _SCRIPT.get((policy_role(view.invocation.role_key), view.trigger.get("kind", "")))
        if play is None:
            return _abstain(view, "this role has no scripted response to this trigger")

        granted = {spec.name for spec in tools}
        # Steps naming a tool this role does not hold are dropped rather than
        # attempted. A fixture that spent its budget on refusals would be testing
        # the policy layer by accident and the episode not at all — the rejection
        # paths have their own tests, where the rejection is the assertion.
        legal = [action for action in play(view) if action.tool_name in granted]
        if view.turn < len(legal):
            return legal[view.turn]
        return _abstain(view, "nothing further this role can usefully do with what it can see")

    def __repr__(self) -> str:
        return f"ScriptedActorProvider(calls={self.calls})"


class UnreachableActorProvider:
    """A provider that refuses to answer.

    Used to prove replay: regenerate an episode whose ledger is present, hand it
    this, and every decision must come from the ledger. A single
    ``ActorProviderError`` means replay is incomplete.
    """

    id = "scripted-actor-1"
    """Matches the fake's id on purpose — a replay must hit the same keys."""

    def act(self, view: ObservationView, tools: tuple[ToolSpec, ...]) -> ActorAction:
        raise ActorProviderError(
            f"provider unreachable, and no ledger entry for {view.invocation.id}"
            f" turn {view.turn}. Replay is incomplete."
        )


class TranscriptActorProvider:
    """Decisions an agent already made, keyed by invocation and turn.

    The actor counterpart of ``narrative.ResponseProvider``, and the way an
    external agent — Claude Code, Codex, the Antigravity SDK — drives an episode
    without this library owning credentials or a network stack. The agent runs
    the episode once, reads each observation, writes its choices out, and this
    serves them back so validation, rejection, and the ledger all run unchanged.
    """

    def __init__(self, actions: dict[str, dict[str, Any]], *, model_id: str = "agent") -> None:
        self.actions = actions
        self.id = model_id
        self.calls = 0

    @staticmethod
    def key(invocation_id: str, turn: int) -> str:
        return f"{invocation_id}#{turn}"

    def act(self, view: ObservationView, tools: tuple[ToolSpec, ...]) -> ActorAction:
        self.calls += 1
        row = self.actions.get(self.key(view.invocation.id, view.turn))
        if row is None:
            raise ActorProviderError(
                f"no action supplied for {self.key(view.invocation.id, view.turn)}."
                " Every turn of every invocation must be answered."
            )
        return ActorAction(
            invocation_id=view.invocation.id,
            tool_name=row.get("tool_name"),
            arguments=row.get("arguments", {}),
            confidence=float(row.get("confidence", 1.0)),
            abstention_reason=row.get("abstention_reason"),
        )


__all__ = [
    "OBSERVATION_VERSION",
    "ActorProvider",
    "ActorProviderError",
    "ObservationView",
    "ScriptedActorProvider",
    "TranscriptActorProvider",
    "UnreachableActorProvider",
]
