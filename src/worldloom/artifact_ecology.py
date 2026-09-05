"""Deterministic enterprise artifact ecology.

One business episode should leave different, coherent traces in documents,
workbooks, decks, tickets, pages, and mail. This module owns presentation and
workflow policy only. It never mints business facts or numeric values.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import Field, model_validator

from .ids import content_key
from .models import ArtifactIR, Lifecycle, Model
from .rng import Rng

if TYPE_CHECKING:  # pragma: no cover
    from .models import ArtifactIntent, ArtifactManifestEntry
    from .world import World


class Surface(StrEnum):
    PPTX = "pptx"
    DOCX = "docx"
    PDF = "pdf"
    MARKDOWN = "markdown"
    XLSX = "xlsx"
    SERVICENOW = "servicenow"
    JIRA = "jira"
    CONFLUENCE = "confluence"
    EMAIL = "email"


class DocumentGenre(StrEnum):
    EXECUTIVE_REVIEW = "executive_review"
    OPERATING_REVIEW = "operating_review"
    DECISION_MEMO = "decision_memo"
    INCIDENT_RCA = "incident_rca"
    CONTROLLED_DOCUMENT = "controlled_document"
    WORKING_NOTE = "working_note"
    ANALYST_MODEL = "analyst_model"
    KNOWLEDGE_PAGE = "knowledge_page"
    SERVICE_RECORD = "service_record"
    ENGINEERING_WORK = "engineering_work"
    CONVERSATION = "conversation"


class OrganisationDNA(Model):
    key: str
    visual_archetype: Literal[
        "finance_compact", "editorial_neutral", "executive_sparse",
        "operating_review", "technical_architecture",
    ]
    density: Literal["airy", "balanced", "compact"]
    chart_preference: Literal["bar", "column", "line_first", "table_first"]
    title_register: Literal["sentence", "label", "assertion"]
    memo_register: Literal["terse", "procedural", "narrative"]
    workbook_register: Literal["controller", "analyst", "operations"]
    ticket_register: Literal["operational", "technical", "governance"]
    email_register: Literal["terse", "mixed", "formal"]
    footer_policy: Literal["minimal", "document_control", "confidentiality"]
    revision_form: Literal["vN", "date_vN", "status_vN"]
    style_seed: int


class DepartmentDNA(Model):
    key: str
    function: str
    density_shift: int = Field(ge=-1, le=1)
    voice: Literal["executive", "finance", "engineering", "operations", "risk"]
    review_depth: int = Field(ge=0, le=3)
    prefers_appendix: bool
    prefers_tables: bool
    email_brevity: int = Field(ge=0, le=2)


class LifecycleStep(Model):
    state: Lifecycle
    at: str
    actor_id: str
    note: str


class ArtifactLifecycle(Model):
    artifact_id: str
    revision: int = Field(ge=1)
    created_at: str
    current: Lifecycle
    author_id: str
    approver_id: str | None = None
    predecessor_id: str | None = None
    history: tuple[LifecycleStep, ...]

    @model_validator(mode="after")
    def _chronological(self) -> ArtifactLifecycle:
        times = [step.at for step in self.history]
        if times != sorted(times):
            raise ValueError(f"{self.artifact_id}: lifecycle is not chronological")
        if not self.history or self.history[-1].state != self.current:
            raise ValueError(f"{self.artifact_id}: lifecycle final state mismatch")
        return self


class SurfacePlan(Model):
    artifact_id: str
    surface: Surface
    genre: DocumentGenre
    family: str
    density: Literal["airy", "balanced", "compact"]
    voice: str
    structural_roles: tuple[str, ...] = ()
    metadata: dict[str, str] = Field(default_factory=dict)


class EvidenceNode(Model):
    id: str
    episode_id: str
    surface: Surface
    artifact_id: str | None = None
    record_id: str | None = None
    fact_ids: tuple[str, ...] = ()
    event_ids: tuple[str, ...] = ()
    created_at: str
    actor_id: str | None = None


class EvidenceEdge(Model):
    source: str
    target: str
    kind: Literal[
        "causes", "references", "attached_to", "derived_from", "supersedes",
        "reply_to", "documents", "remediates", "links",
    ]


class EpisodeGraph(Model):
    episode_id: str
    nodes: tuple[EvidenceNode, ...]
    edges: tuple[EvidenceEdge, ...] = ()

    @model_validator(mode="after")
    def _closed(self) -> EpisodeGraph:
        ids = {node.id for node in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError("duplicate evidence node ids")
        if any(edge.source not in ids or edge.target not in ids for edge in self.edges):
            raise ValueError("evidence graph contains a dangling edge")
        return self


class RealismProfile(Model):
    organisation: OrganisationDNA
    departments: tuple[DepartmentDNA, ...]
    lifecycles: tuple[ArtifactLifecycle, ...]
    plans: tuple[SurfacePlan, ...]
    graph: EpisodeGraph


def organisation_dna(seed: int, company_id: str, industry: str = "") -> OrganisationDNA:
    """Stable company habits. Adding an artifact cannot perturb these draws."""
    rng = Rng(seed).derive(f"artifact-ecology/organisation/{company_id}")
    visual = rng.choice((
        "finance_compact", "editorial_neutral", "executive_sparse",
        "operating_review", "technical_architecture",
    ))
    if "bank" in industry.lower() and rng.chance(0.55):
        visual = "finance_compact"
    return OrganisationDNA(
        key=content_key("organisation-dna", seed, company_id, industry),
        visual_archetype=cast(Any, visual),
        density=cast(Any, rng.weighted(("airy", "balanced", "compact"), (0.2, 0.55, 0.25))),
        chart_preference=cast(Any, rng.choice(("bar", "column", "line_first", "table_first"))),
        title_register=cast(Any, rng.choice(("sentence", "label", "assertion"))),
        memo_register=cast(Any, rng.weighted(("terse", "procedural", "narrative"), (0.4, 0.4, 0.2))),
        workbook_register=cast(Any, rng.choice(("controller", "analyst", "operations"))),
        ticket_register=cast(Any, rng.choice(("operational", "technical", "governance"))),
        email_register=cast(Any, rng.weighted(("terse", "mixed", "formal"), (0.35, 0.5, 0.15))),
        footer_policy=cast(Any, rng.choice(("minimal", "document_control", "confidentiality"))),
        revision_form=cast(Any, rng.choice(("vN", "date_vN", "status_vN"))),
        style_seed=int(content_key(seed, company_id, "style")[:8], 16),
    )


def department_dna(seed: int, company_id: str, function: str) -> DepartmentDNA:
    rng = Rng(seed).derive(f"artifact-ecology/department/{company_id}/{function.lower()}")
    lower = function.lower()
    if any(x in lower for x in ("finance", "account", "treasury")):
        voice = "finance"
    elif any(x in lower for x in ("engineer", "technology", "platform", "data")):
        voice = "engineering"
    elif any(x in lower for x in ("risk", "legal", "compliance", "audit")):
        voice = "risk"
    elif any(x in lower for x in ("operations", "store", "service")):
        voice = "operations"
    else:
        voice = "executive"
    return DepartmentDNA(
        key=content_key("department-dna", seed, company_id, function),
        function=function,
        density_shift=rng.choice((-1, 0, 0, 0, 1)),
        voice=cast(Any, voice),
        review_depth=rng.choice((0, 1, 1, 2, 2, 3)),
        prefers_appendix=rng.chance(0.55 if voice in {"finance", "risk"} else 0.3),
        prefers_tables=rng.chance(0.75 if voice == "finance" else 0.4),
        email_brevity=rng.choice((0, 1, 1, 2)),
    )


def _surface(artifact_type: str) -> Surface:
    value = artifact_type.lower()
    if "workbook" in value or value.endswith("_xlsx"):
        return Surface.XLSX
    if "servicenow" in value:
        return Surface.SERVICENOW
    if "jira" in value:
        return Surface.JIRA
    if "confluence" in value or "knowledge" in value:
        return Surface.CONFLUENCE
    if "email" in value:
        return Surface.EMAIL
    if "executive" in value or "deck" in value or "board" in value:
        return Surface.PPTX
    return Surface.DOCX


def _genre(artifact_type: str, surface: Surface) -> DocumentGenre:
    value = artifact_type.lower()
    if surface == Surface.XLSX:
        return DocumentGenre.ANALYST_MODEL
    if surface == Surface.EMAIL:
        return DocumentGenre.CONVERSATION
    if surface == Surface.SERVICENOW:
        return DocumentGenre.SERVICE_RECORD
    if surface == Surface.JIRA:
        return DocumentGenre.ENGINEERING_WORK
    if surface == Surface.CONFLUENCE:
        return DocumentGenre.KNOWLEDGE_PAGE
    if "rca" in value or "incident" in value:
        return DocumentGenre.INCIDENT_RCA
    if "policy" in value or "sop" in value or "procedure" in value:
        return DocumentGenre.CONTROLLED_DOCUMENT
    if "memo" in value:
        return DocumentGenre.DECISION_MEMO
    if "executive" in value or "board" in value:
        return DocumentGenre.EXECUTIVE_REVIEW
    if "working" in value or "note" in value:
        return DocumentGenre.WORKING_NOTE
    return DocumentGenre.OPERATING_REVIEW


_FAMILIES: dict[Surface, tuple[str, ...]] = {
    Surface.PPTX: ("decision_story", "operating_review", "metric_narrative", "incident_brief", "board_update"),
    Surface.DOCX: ("memo", "operating_pack", "controlled_document", "rca", "brief"),
    Surface.PDF: ("memo", "operating_pack", "controlled_document", "rca", "brief"),
    Surface.MARKDOWN: ("memo", "working_note", "knowledge_note"),
    Surface.XLSX: ("controller_model", "analyst_model", "operational_tracker", "reconciliation_pack"),
    Surface.SERVICENOW: ("major_incident", "standard_incident", "problem_change_chain"),
    Surface.JIRA: ("delivery_issue", "defect_remediation", "control_remediation"),
    Surface.CONFLUENCE: ("knowledge_tree", "rca_space", "operating_handbook"),
    Surface.EMAIL: ("working_thread", "escalation_thread", "approval_thread", "handoff_thread"),
}


def lifecycle_for(world: World, intent: ArtifactIntent, manifest: ArtifactManifestEntry | None = None) -> ArtifactLifecycle:
    """Derive review history from simulated time, never wall clock."""
    # Intent declares that an artifact should exist; only the compiled manifest
    # owns its timestamp, revision and lifecycle. Looking for these fields on
    # ArtifactIntent invents a second contract and crashes before compilation.
    manifest = manifest or world.artifacts.get(intent.id)
    if manifest is None:
        raise ValueError(f"{intent.id}: lifecycle requires a compiled artifact manifest")
    if manifest.id != intent.id:
        raise ValueError(f"{intent.id}: lifecycle manifest belongs to another artifact")
    created = manifest.created_at
    author = intent.author_id
    revision = manifest.version
    current = manifest.lifecycle
    approver = intent.approver_id
    history = [LifecycleStep(state=Lifecycle.DRAFT, at=created.isoformat(), actor_id=author, note="Authored from resolved source evidence.")]
    sequence = [Lifecycle.REVIEWED, Lifecycle.APPROVED, Lifecycle.PUBLISHED]
    if current in sequence or current in {Lifecycle.SUPERSEDED, Lifecycle.ARCHIVED}:
        upto = sequence.index(current) + 1 if current in sequence else len(sequence)
        actor = approver or author
        for index, state in enumerate(sequence[:upto], start=1):
            history.append(LifecycleStep(state=state, at=(created + timedelta(minutes=30 * index)).isoformat(), actor_id=actor, note=f"{state.value.replace('_', ' ').title()} in simulated workflow."))
    if current in {Lifecycle.SUPERSEDED, Lifecycle.ARCHIVED}:
        history.append(LifecycleStep(state=current, at=(created + timedelta(hours=3)).isoformat(), actor_id=approver or author, note=f"Artifact {current.value}."))
    return ArtifactLifecycle(
        artifact_id=intent.id, revision=max(1, int(revision)), created_at=created.isoformat(), current=current,
        author_id=author, approver_id=approver, predecessor_id=getattr(intent, "supersedes", None), history=tuple(history),
    )


def plan_for(world: World, intent: ArtifactIntent, ir: ArtifactIR, surface: Surface | None = None) -> SurfacePlan:
    surface = surface or _surface(intent.artifact_type)
    org = organisation_dna(world.seed or 0, world.company.id, world.company.industry)
    person = world.people.get(intent.author_id)
    function = person.function if person else "Executive"
    dept = department_dna(world.seed or 0, world.company.id, function)
    rng = Rng(world.seed or 0).derive(f"artifact-ecology/plan/{intent.id}/{surface.value}")
    family = rng.choice(_FAMILIES[surface])
    density_order = ("airy", "balanced", "compact")
    idx = max(0, min(2, density_order.index(org.density) + dept.density_shift))
    density = density_order[idx]
    roles: dict[Surface, tuple[str, ...]] = {
        Surface.PPTX: ("title", "section", "kpi", "chart", "table", "decision", "timeline", "appendix"),
        Surface.XLSX: ("inputs", "detail", "calculation", "summary", "reconciliation", "reference"),
        Surface.SERVICENOW: ("incident", "state_history", "work_notes", "sla", "problem", "change"),
        Surface.JIRA: ("issue", "status_history", "comments", "links", "worklog"),
        Surface.CONFLUENCE: ("space", "page", "ancestor", "version", "backlink", "macro"),
        Surface.EMAIL: ("message", "reply", "forward", "attachment", "escalation"),
        Surface.DOCX: ("cover", "summary", "section", "table", "callout", "document_control"),
        Surface.PDF: ("cover", "summary", "section", "table", "callout", "document_control"),
        Surface.MARKDOWN: ("summary", "section", "table", "references"),
    }
    return SurfacePlan(
        artifact_id=intent.id, surface=surface, genre=_genre(intent.artifact_type, surface), family=family,
        density=cast(Any, density), voice=dept.voice, structural_roles=roles[surface],
        metadata={"organisation_style": org.key, "department_style": dept.key, "chart_preference": org.chart_preference},
    )


def enrich_ir(world: World, intent: ArtifactIntent, ir: ArtifactIR) -> ArtifactIR:
    """Add style/lifecycle metadata only; sections, facts and formulas remain untouched."""
    org = organisation_dna(world.seed or 0, world.company.id, world.company.industry)
    plan = plan_for(world, intent, ir)
    lifecycle = lifecycle_for(world, intent, world.artifacts.get(intent.id))
    metadata = dict(ir.metadata)
    metadata.update({
        "realism_profile": "ecology/v1", "style_seed": str(org.style_seed),
        "style_archetype": org.visual_archetype, "artifact_family": plan.family,
        "artifact_density": plan.density, "artifact_voice": plan.voice,
        "artifact_type": intent.artifact_type, "artifact_surface": plan.surface.value,
        "artifact_genre": plan.genre.value, "title_register": org.title_register,
        "chart_preference": org.chart_preference,
        "lifecycle": lifecycle.current.value, "revision": str(lifecycle.revision),
        "department_style": plan.metadata["department_style"],
    })
    return ir.model_copy(update={"metadata": metadata})


def enrich_world(world: World) -> World:
    staged = world if world.artifact_irs else world.compile()
    irs = tuple(enrich_ir(staged, staged.artifact_intents.by_id(ir.intent_id), ir) for ir in staged.artifact_irs)
    recipe = dict(staged.recipe)
    recipe["artifact_realism"] = "ecology/v1"
    from dataclasses import replace

    return replace(staged, _artifact_irs=irs, _recipe=recipe)


def episode_graph(world: World) -> EpisodeGraph:
    staged = world if world.artifact_irs else world.compile()
    episode_id = f"EP-{content_key(staged.seed, staged.company.id, staged.period or 'current')[:12].upper()}"
    nodes: list[EvidenceNode] = []
    edges: list[EvidenceEdge] = []
    artifact_nodes: dict[str, str] = {}
    for ir in sorted(staged.artifact_irs, key=lambda item: item.id):
        intent = staged.artifact_intents.by_id(ir.intent_id)
        life = lifecycle_for(staged, intent, staged.artifacts.get(intent.id))
        node_id = f"EVID-{content_key(episode_id, intent.id)[:12].upper()}"
        artifact_nodes[intent.id] = node_id
        nodes.append(EvidenceNode(id=node_id, episode_id=episode_id, surface=_surface(intent.artifact_type), artifact_id=intent.id,
            fact_ids=tuple(sorted(intent.required_fact_ids)), event_ids=tuple(sorted(getattr(intent, "event_ids", ()) or ())),
            created_at=life.created_at, actor_id=intent.author_id))
    for ir in staged.artifact_irs:
        intent = staged.artifact_intents.by_id(ir.intent_id)
        target = artifact_nodes[intent.id]
        for source in getattr(intent, "derived_from", ()) or ():
            if source in artifact_nodes:
                edges.append(EvidenceEdge(source=artifact_nodes[source], target=target, kind="derived_from"))
        predecessor = getattr(intent, "supersedes", None)
        if predecessor in artifact_nodes:
            edges.append(EvidenceEdge(source=artifact_nodes[predecessor], target=target, kind="supersedes"))
    artifact_list = [node for node in nodes if node.artifact_id]
    for index, later in enumerate(artifact_list):
        for earlier in artifact_list[:index]:
            if earlier.surface != later.surface and set(earlier.fact_ids) & set(later.fact_ids):
                edges.append(EvidenceEdge(source=earlier.id, target=later.id, kind="references"))
    prior: dict[str, str] = {}
    for message in sorted(staged.messages, key=lambda item: (item.sent_at, item.id)):
        node_id = f"EVID-{content_key(episode_id, message.id)[:12].upper()}"
        nodes.append(EvidenceNode(id=node_id, episode_id=episode_id, surface=Surface.EMAIL, record_id=message.id,
            fact_ids=tuple(sorted(message.disclosed_fact_ids)), created_at=message.sent_at.isoformat(), actor_id=message.sender_id))
        subject = message.subject_ref or message.kind
        if subject in prior:
            edges.append(EvidenceEdge(source=prior[subject], target=node_id, kind="reply_to"))
        prior[subject] = node_id
        for artifact_id, artifact_node in artifact_nodes.items():
            intent = staged.artifact_intents.by_id(artifact_id)
            if set(intent.required_fact_ids) & set(message.disclosed_fact_ids):
                edges.append(EvidenceEdge(source=artifact_node, target=node_id, kind="attached_to"))
    unique = {(edge.source, edge.target, edge.kind): edge for edge in edges}
    return EpisodeGraph(episode_id=episode_id, nodes=tuple(nodes), edges=tuple(unique[key] for key in sorted(unique)))


def profile(world: World) -> RealismProfile:
    staged = world if world.artifact_irs else world.compile()
    functions = sorted({person.function for person in staged.people})
    plans: list[SurfacePlan] = []
    lifecycles: list[ArtifactLifecycle] = []
    for ir in staged.artifact_irs:
        intent = staged.artifact_intents.by_id(ir.intent_id)
        plans.append(plan_for(staged, intent, ir))
        lifecycles.append(lifecycle_for(staged, intent, staged.artifacts.get(intent.id)))
    return RealismProfile(
        organisation=organisation_dna(staged.seed or 0, staged.company.id, staged.company.industry),
        departments=tuple(department_dna(staged.seed or 0, staged.company.id, f) for f in functions),
        lifecycles=tuple(lifecycles), plans=tuple(plans), graph=episode_graph(staged),
    )


class ArtifactProposal(Model):
    artifact_id: str
    surface: Surface
    family: str
    density: Literal["airy", "balanced", "compact"]
    title_register: Literal["sentence", "label", "assertion"]
    copy_blocks: tuple[str, ...] = ()
    source_fact_ids: tuple[str, ...] = ()


class ProposalFinding(Model):
    code: str
    message: str


def review_proposal(world: World, proposal: ArtifactProposal) -> tuple[ProposalFinding, ...]:
    intent = world.artifact_intents.get(proposal.artifact_id)
    if intent is None:
        return (ProposalFinding(code="unknown_artifact", message=proposal.artifact_id),)
    findings: list[ProposalFinding] = []
    invented = set(proposal.source_fact_ids) - set(intent.required_fact_ids)
    if invented:
        findings.append(ProposalFinding(code="unsupported_fact_reference", message=f"facts outside artifact evidence: {sorted(invented)}"))
    if not proposal.family.strip():
        findings.append(ProposalFinding(code="missing_family", message="layout family is required"))
    numeric = re.compile(r"(?<![A-Za-z0-9_-])(?:[$£€]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[$£€]?\d+\.\d+%?)(?![A-Za-z0-9_-])")
    if any(numeric.search(block) for block in proposal.copy_blocks):
        findings.append(ProposalFinding(code="bare_numeric_claim", message="model copy must resolve numeric claims from facts"))
    return tuple(findings)


def enrich_connector_records(world: World, records: list[Any]) -> list[Any]:
    """Add product-specific workflow detail only when artifact realism is enabled."""
    if world.recipe.get("artifact_realism") != "ecology/v1":
        return records
    out: list[Any] = []
    for record in records:
        fields = dict(record.fields)
        rng = Rng(world.seed or 0).derive(f"artifact-ecology/connector/{record.id}")
        if record.connector == "servicenow":
            opened = fields.get("opened_at") or fields.get("created_at")
            anchor = datetime.fromisoformat(str(opened)) if opened else (world.timeline()[0].occurred_at if world.timeline() else None)
            def at(minutes: int, base=anchor) -> str | None:
                return (base + timedelta(minutes=minutes)).isoformat() if base else None

            final = str(fields.get("state", "")).lower()
            states = ["New", "In Progress"] + (["Resolved", "Closed"] if final in {"resolved", "closed", "complete"} else [])
            fields.setdefault("impact", rng.choice(("1", "2", "2", "3")))
            fields.setdefault("urgency", rng.choice(("1", "2", "2", "3")))
            fields.setdefault("business_service", (fields.get("related_service_ids") or [None])[0])
            fields.setdefault("sla", {"name": "P1 Restoration" if str(fields.get("priority")) == "1" else "Standard Resolution", "breached": False})
            fields.setdefault("state_history", [{"state": state, "sequence": i, "at": at(i * 30)} for i, state in enumerate(states)])
            fields.setdefault("work_notes", [
                {"sequence": 1, "at": at(10), "kind": "triage", "text": "Impact confirmed; investigation opened."},
                {"sequence": 2, "at": at(45), "kind": "diagnosis", "text": "Evidence linked to correlated business event."},
                {"sequence": 3, "at": at(120), "kind": "closure", "text": "Resolution recorded against source evidence."},
            ])
            fields.setdefault("related_records", {"problem": f"PRB-{content_key(record.id, 'problem')[:10].upper()}", "change": f"CHG-{content_key(record.id, 'change')[:10].upper()}"})
        elif record.connector == "jira":
            status = fields.get("status", "To Do")
            created = fields.get("created_at")
            anchor = datetime.fromisoformat(str(created)) if created else (world.timeline()[0].occurred_at if world.timeline() else None)
            def jira_at(minutes: int, base=anchor) -> str | None:
                return (base + timedelta(minutes=minutes)).isoformat() if base else None

            history = [{"from": None, "to": "To Do", "sequence": 0, "at": jira_at(0)}]
            if status != "To Do":
                history.append({"from": "To Do", "to": "In Progress", "sequence": 1, "at": jira_at(20)})
            if status == "Done":
                history.append({"from": "In Progress", "to": "Done", "sequence": 2, "at": jira_at(180)})
            fields.setdefault("status_history", history)
            fields.setdefault("links", [{"type": "relates to", "target": event_id} for event_id in record.event_ids])
            fields.setdefault("activity", [{"kind": "comment", "sequence": 1, "at": jira_at(35), "text": "Scope confirmed against source evidence."}])
        elif record.connector == "confluence":
            page_id = fields.get("page_id", record.external_id)
            fields.setdefault("space_key", "OPS" if "ops" in record.title.lower() else "KNOW")
            fields.setdefault("ancestor_ids", [])
            fields.setdefault("labels", ["generated", "controlled-content"])
            fields.setdefault("version_history", [{"version": 1, "status": "draft"}, {"version": int(fields.get("version", 1)), "status": "current"}])
            fields.setdefault("backlinks", [{"kind": "source_artifact", "id": source} for source in record.source_artifact_ids])
            fields.setdefault("macros", [{"type": "status", "value": "CURRENT"}])
            fields.setdefault("canonical_url", f"/spaces/{fields['space_key']}/pages/{page_id}")
        elif record.connector == "email" and record.entity == "message":
            fields.setdefault("cc", [])
            fields.setdefault("reply_type", "reply" if fields.get("in_reply_to") else "new")
            fields.setdefault("importance", rng.weighted(("normal", "high"), (0.8, 0.2)))
            fields.setdefault("client", rng.choice(("outlook-desktop", "outlook-web", "mobile")))
            fields.setdefault("conversation_index", content_key(fields.get("thread_id"), record.id)[:20])
            fields.setdefault("quoted_history", bool(fields.get("in_reply_to")) and rng.chance(0.7))
            fields.setdefault("signature_style", rng.choice(("full", "short", "none")))
        out.append(record.model_copy(update={"fields": fields}))
    return out