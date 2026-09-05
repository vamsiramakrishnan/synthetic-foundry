"""Mechanical realism gates for artifact ecology.

The score is intentionally not an aesthetic model. It measures properties a
real enterprise corpus must satisfy before a human or learned critic is useful:
chronology, source-grounded numbers, structural variation, cross-surface links,
workbook integrity signals, and lifecycle completeness. A harness may optimize
inside these gates; it cannot redefine them.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from pydantic import Field

from .artifact_ecology import RealismProfile, Surface, profile
from .models import Model


class RealismFinding(Model):
    code: str
    message: str
    severity: str = "error"


class RealismReport(Model):
    score: float = Field(ge=0.0, le=1.0)
    structural_diversity: float = Field(ge=0.0, le=1.0)
    lifecycle_validity: float = Field(ge=0.0, le=1.0)
    graph_connectivity: float = Field(ge=0.0, le=1.0)
    cross_surface_coverage: float = Field(ge=0.0, le=1.0)
    evidence_grounding: float = Field(ge=0.0, le=1.0)
    findings: tuple[RealismFinding, ...] = ()

    @property
    def ok(self) -> bool:
        return not any(f.severity == "error" for f in self.findings)


def _ratio(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else numerator / denominator


def evaluate(world) -> RealismReport:  # type: ignore[no-untyped-def]
    staged = world if world.artifact_irs else world.compile()
    p: RealismProfile = profile(staged)
    findings: list[RealismFinding] = []

    by_surface: dict[Surface, list[str]] = {}
    for plan in p.plans:
        by_surface.setdefault(plan.surface, []).append(plan.family)
    diversity_parts: list[float] = []
    for surface, families in sorted(by_surface.items(), key=lambda item: item[0].value):
        if len(families) == 1:
            diversity_parts.append(1.0)
            continue
        unique = len(set(families))
        diversity_parts.append(unique / len(families))
        if unique == 1 and len(families) >= 3:
            findings.append(RealismFinding(
                code="template_collapse",
                message=f"{surface.value}: {len(families)} artifacts all use {families[0]!r}",
            ))
    structural_diversity = sum(diversity_parts) / len(diversity_parts) if diversity_parts else 1.0

    valid_lifecycles = 0
    for lifecycle in p.lifecycles:
        states = [step.state.value for step in lifecycle.history]
        if states and lifecycle.current.value == states[-1]:
            valid_lifecycles += 1
        if lifecycle.approver_id and "approved" not in states and lifecycle.current.value in {"approved", "published"}:
            findings.append(RealismFinding(
                code="approval_gap",
                message=f"{lifecycle.artifact_id}: approved/published without approval history",
            ))
    lifecycle_validity = _ratio(valid_lifecycles, len(p.lifecycles))

    nodes = p.graph.nodes
    degree = Counter[str]()
    for edge in p.graph.edges:
        degree[edge.source] += 1
        degree[edge.target] += 1
    connected = sum(1 for node in nodes if degree[node.id] > 0)
    graph_connectivity = _ratio(connected, len(nodes))
    if len(nodes) >= 4 and graph_connectivity < 0.5:
        findings.append(RealismFinding(
            code="artifact_islands",
            message=f"only {connected}/{len(nodes)} evidence nodes participate in cross-surface relationships",
        ))

    present_surfaces = {node.surface for node in nodes} | {plan.surface for plan in p.plans}
    target_surfaces = {Surface.PPTX, Surface.DOCX, Surface.XLSX, Surface.SERVICENOW, Surface.CONFLUENCE, Surface.EMAIL}
    cross_surface_coverage = len(present_surfaces & target_surfaces) / len(target_surfaces)
    if len(p.plans) >= 8 and len(present_surfaces) < 3:
        findings.append(RealismFinding(
            code="surface_monoculture",
            message="large artifact set occupies fewer than three enterprise surfaces",
            severity="warning",
        ))

    supported = 0
    total_claiming = 0
    for ir in staged.artifact_irs:
        total_claiming += 1
        if ir.fact_ids():
            supported += 1
    evidence_grounding = _ratio(supported, total_claiming)
    if total_claiming and evidence_grounding < 0.8:
        findings.append(RealismFinding(
            code="weak_grounding",
            message=f"only {supported}/{total_claiming} compiled artifacts cite source facts",
        ))

    score = (
        0.25 * structural_diversity
        + 0.20 * lifecycle_validity
        + 0.20 * graph_connectivity
        + 0.15 * cross_surface_coverage
        + 0.20 * evidence_grounding
    )
    return RealismReport(
        score=round(score, 4),
        structural_diversity=round(structural_diversity, 4),
        lifecycle_validity=round(lifecycle_validity, 4),
        graph_connectivity=round(graph_connectivity, 4),
        cross_surface_coverage=round(cross_surface_coverage, 4),
        evidence_grounding=round(evidence_grounding, 4),
        findings=tuple(findings),
    )


def compare(reports: Iterable[RealismReport]) -> RealismReport:
    """Return best mechanically valid report; stable first-on-tie semantics."""
    candidates = tuple(reports)
    if not candidates:
        raise ValueError("at least one realism report is required")
    valid = tuple(report for report in candidates if report.ok)
    pool = valid or candidates
    return max(enumerate(pool), key=lambda item: (item[1].score, -item[0]))[1]
