"""Matching the catalogue's words against what Worldloom can emulate.

The catalogue records what a customer's assistant *did*, in that customer's
vocabulary: connector keys, entity names and operation names exactly as their
tool calls spelled them. Worldloom knows what it can *fake*. These are two
vocabularies, and this module introduces them.

Three questions per step, asked in order, each with its own refusal::

    jira . issue . create
      │      │       │
      │      │       └─ operation_unsupported   the record type lacks that op
      │      └───────── entity_unresolved       no record type, alias or fold
      └──────────────── connector_not_emulated  Worldloom has no such system

An entity is tried three ways: its exact name, an alias (Jira's ``issue``
stands for epic, story, bug, task and subtask), then :data:`FOLDS`.

A fold is the one thing here that *rewrites* a journey rather than asking a
question about it. Real people look up things Worldloom does not model as
records — a Jira project is not a record, it is a field on an issue. Rather
than refuse the journey, the lookup step is deleted and its value survives as
a field on the step that consumed it::

    BEFORE                            AFTER
    search jira project       ──▶     (gone)
    create jira issue                 create jira issue, now also carrying
      depends_on find_project           the field "project"

Anything that depended on the deleted step inherits what *it* depended on, so
the graph stays connected. Every fold leaves an ``info`` finding behind.

:data:`FOLDS` is hand-reviewed data and is deliberately incomplete. A pair
that is neither known nor folded is refused loudly, by name; the table grows
one reviewed entry at a time. That asymmetry is the whole point — a missing
entry costs a message, a wrong entry silently rewrites someone's journey into
a different one.

This module reads Worldloom's own shipped connector definitions, fresh on
every call, so a renamed entity cannot go unnoticed. It never opens the
customer's catalogue; those bytes arrive already parsed.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, NamedTuple

from ..connector_definition import is_reference_connector, load_connector_definition
from ..models import Model
from .catalogue import Cuj, Step
from .report import Finding, ImportReport, Severity, hard, info

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ..connector_definition import ConnectorDefinition
    from .catalogue import Catalogue


# --------------------------------------------------------------------------
# The shared vocabulary this module adds to ``Finding.code``.
# --------------------------------------------------------------------------

CONNECTOR_NOT_EMULATED = "connector_not_emulated"
"""Worldloom has no connector of that name, shipped or packaged."""

ENTITY_UNRESOLVED = "entity_unresolved"
"""The connector exists but has no such record type, by name, alias or fold."""

OPERATION_UNSUPPORTED = "operation_unsupported"
"""The record type exists but does not offer that operation."""

STEP_FOLDED = "step_folded"
"""A lookup step was removed and its value moved onto a later step."""


# --------------------------------------------------------------------------
# The fold table.
# --------------------------------------------------------------------------


class FoldTarget(NamedTuple):
    """Where a folded lookup's value goes: an entity, and a field on it."""

    entity: str
    field: str


FOLDS: Mapping[tuple[str, str], FoldTarget] = MappingProxyType({
    # All three are the same situation: people really do search Jira for these,
    # and Jira's emulator models none of them as a record. Each is a field on
    # an issue instead. ``project`` and ``issuetype`` are in the entity's
    # ``required_on_create``; ``assignee`` is a connector-level query field.
    # ``test_fold_fields_exist_in_the_live_definition`` holds all three to that.
    ("jira", "project"): FoldTarget("issue", "project"),
    ("jira", "issue_type"): FoldTarget("issue", "issuetype"),
    ("jira", "user"): FoldTarget("issue", "assignee"),
})
"""Lookups Worldloom does not model as records, and the field each becomes.

Hand-reviewed, and incomplete on purpose. See the module docstring for why a
missing entry is the cheap mistake and a wrong one is the expensive mistake.
"""


# --------------------------------------------------------------------------
# What matching produces.
# --------------------------------------------------------------------------


class MatchedCatalogue(Model):
    """Which journeys Worldloom can build, and what it had to say about them."""

    cujs: tuple[Cuj, ...] = ()
    """Buildable journeys, with every fold already applied. These are the
    graphs W3 builds from, so nothing in them still needs removing."""

    refused: tuple[str, ...] = ()
    """Ids of the journeys that were not built. One hard finding each, at
    least, explains why."""

    report: ImportReport = ImportReport()
    """Every finding, refusals and folds alike, in the order produced."""


# --------------------------------------------------------------------------
# Matching one step.
# --------------------------------------------------------------------------


def _definition(connector: str) -> ConnectorDefinition | None:
    """The live definition for *connector*, or ``None`` if there is no such
    connector. Read fresh every time: a hard-coded list would go stale, and
    going stale here means silently matching against a Worldloom that has
    moved on."""
    if not is_reference_connector(connector):
        return None
    try:
        return load_connector_definition(connector)
    except ValueError:  # pragma: no cover - is_reference_connector just said yes
        return None


def _known_entity(definition: ConnectorDefinition, entity: str) -> bool:
    """Whether *entity* names a record type, directly or through an alias."""
    try:
        definition.entity_members(entity)
    except KeyError:
        return False
    return True


def _hosts(step: Step, connector: str, target: FoldTarget) -> bool:
    """Whether *step* is the right place to put a folded value.

    It must be a tool step on the same connector, aimed at the fold's target
    entity — either by the same name, or as one of the concrete types that
    name stands for, so a step creating an ``epic`` can host a fold targeting
    ``issue``.
    """
    if step.connector != connector or step.entity is None:
        return False
    if step.entity == target.entity:
        return True
    definition = _definition(connector)
    if definition is None:  # pragma: no cover - the caller already loaded it
        return False
    try:
        return definition.entity_matches(target.entity, step.entity)
    except KeyError:
        return False


# --------------------------------------------------------------------------
# Folding.
# --------------------------------------------------------------------------


def _rewire(depends_on: Sequence[str], dropped: str,
            inherited: Sequence[str]) -> tuple[str, ...]:
    """*depends_on* with *dropped* removed and its own dependencies put in its
    place, order preserved and no duplicates — ``Step.depends_on`` is unique."""
    kept = [dep for dep in depends_on if dep != dropped]
    kept.extend(dep for dep in inherited if dep not in kept)
    return tuple(kept)


def _with_field(fields: Sequence[str], added: str) -> tuple[str, ...]:
    """*fields* plus *added*, unless it is already there."""
    return tuple(fields) if added in fields else (*fields, added)


def _apply_fold(cuj_id: str, steps: tuple[Step, ...], folded: Step,
                target: FoldTarget) -> tuple[tuple[Step, ...], tuple[Finding, ...]]:
    """Delete *folded* and move its value onto the step that consumed it.

    The value has to land somewhere. If nothing downstream can hold it, the
    fold cannot happen and the pair is simply unresolved — reported with the
    same code as any other unmatched entity, because that is what it is.
    """
    assert folded.connector is not None
    host = next((step for step in steps
                 if folded.id in step.depends_on
                 and _hosts(step, folded.connector, target)), None)
    if host is None:
        return steps, (hard(
            ENTITY_UNRESOLVED,
            f"{folded.connector} has no record type {folded.entity!r}; it "
            f"folds into {target.entity!r}.{target.field}, but no later step "
            f"in this journey uses {target.entity!r}, so the value has "
            "nowhere to go",
            cuj_id=cuj_id,
            detail={"step_id": folded.id, "connector": folded.connector,
                    "entity": str(folded.entity), "fold_target": target.entity}),)

    rebuilt: list[Step] = []
    for step in steps:
        if step.id == folded.id:
            continue
        if folded.id in step.depends_on:
            step = step.model_copy(update={
                "depends_on": _rewire(step.depends_on, folded.id,
                                      folded.depends_on)})
        if step.id == host.id:
            step = step.model_copy(update={
                "argument_fields": _with_field(step.argument_fields,
                                               target.field)})
        rebuilt.append(step)

    return tuple(rebuilt), (info(
        STEP_FOLDED,
        f"step {folded.id!r} looked up {folded.connector}.{folded.entity}, "
        f"which Worldloom models as the field {target.field!r} on "
        f"{target.entity!r}; the step was removed and the field added to "
        f"step {host.id!r}",
        cuj_id=cuj_id,
        detail={"step_id": folded.id, "host_step_id": host.id,
                "connector": folded.connector, "entity": str(folded.entity),
                "field": target.field}),)


# --------------------------------------------------------------------------
# Matching a journey, and a whole catalogue.
# --------------------------------------------------------------------------


def match_cuj(cuj: Cuj) -> tuple[Cuj | None, tuple[Finding, ...]]:
    """Check one journey against Worldloom, folding what can be folded.

    Returns the journey to build and every finding, or ``None`` and the
    reasons it was refused. Every step is checked before anything is rewritten,
    so a journey with two problems reports both rather than stopping at the
    first — the same courtesy ``load_catalogue`` extends in W1.
    """
    findings: list[Finding] = []
    folds: list[tuple[Step, FoldTarget]] = []

    for step in cuj.steps:
        # A capability step calls nothing, so there is nothing to match. The
        # three-way test narrows the optional fields for the checker too.
        if step.connector is None or step.entity is None or step.operation is None:
            continue

        definition = _definition(step.connector)
        if definition is None:
            findings.append(hard(
                CONNECTOR_NOT_EMULATED,
                f"Worldloom has no connector named {step.connector!r}, so "
                f"step {step.id!r} cannot be built",
                cuj_id=cuj.id,
                detail={"step_id": step.id, "connector": step.connector}))
            continue

        if not _known_entity(definition, step.entity):
            target = FOLDS.get((step.connector, step.entity))
            if target is None:
                findings.append(hard(
                    ENTITY_UNRESOLVED,
                    f"{step.connector} has no record type {step.entity!r}, by "
                    f"name or alias, and no fold is defined for it; step "
                    f"{step.id!r} cannot be built",
                    cuj_id=cuj.id,
                    detail={"step_id": step.id, "connector": step.connector,
                            "entity": step.entity}))
            else:
                folds.append((step, target))
            # Either way the operation cannot be checked: there is no record
            # type to check it against.
            continue

        try:
            definition.tool_for(step.entity, step.operation)
        except KeyError as error:
            findings.append(hard(
                OPERATION_UNSUPPORTED,
                f"{step.connector}.{step.entity} does not support "
                f"{step.operation!r}, so step {step.id!r} cannot be built",
                cuj_id=cuj.id,
                detail={"step_id": step.id, "connector": step.connector,
                        "entity": step.entity, "operation": step.operation,
                        "reason": str(error)}))

    if any(finding.severity is Severity.HARD for finding in findings):
        return None, tuple(findings)

    steps = cuj.steps
    for folded, target in folds:
        steps, fold_findings = _apply_fold(cuj.id, steps, folded, target)
        findings.extend(fold_findings)
    if any(finding.severity is Severity.HARD for finding in findings):
        return None, tuple(findings)

    # ``Cuj`` validates that a tool_signature journey has at least one tool
    # step. Folding is the only thing that can take the last one away, and
    # ``model_copy`` does not re-run validators, so the check is made here
    # rather than discovered as an exception later.
    if cuj.anchor == "tool_signature" and not any(s.is_tool_step for s in steps):
        return None, (*findings, hard(
            ENTITY_UNRESOLVED,
            f"every tool step in {cuj.id} folded away, leaving a journey "
            "identified by a tool signature it no longer has",
            cuj_id=cuj.id))

    matched = cuj if steps == cuj.steps else cuj.model_copy(update={"steps": steps})
    return matched, tuple(findings)


def match_catalogue(catalogue: Catalogue) -> MatchedCatalogue:
    """Check every journey in *catalogue* against Worldloom.

    One journey's refusal does not stop the others: a catalogue naming a
    connector we do not have should still yield the journeys that only use
    connectors we do.
    """
    built: list[Cuj] = []
    refused: list[str] = []
    findings: list[Finding] = []

    for cuj in catalogue.cujs:
        matched, cuj_findings = match_cuj(cuj)
        findings.extend(cuj_findings)
        if matched is None:
            refused.append(cuj.id)
        else:
            built.append(matched)

    return MatchedCatalogue(cujs=tuple(built), refused=tuple(refused),
                            report=ImportReport(findings=tuple(findings)))
