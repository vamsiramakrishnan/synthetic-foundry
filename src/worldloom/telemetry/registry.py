"""Matching the catalogue's words against what Worldloom can emulate.

The catalogue records what a customer's assistant *did*, in that customer's
vocabulary: connector keys, entity names and operation names exactly as their
tool calls spelled them. Worldloom knows what it can *fake*. These are two
vocabularies, and this module introduces them.

Three questions per step, asked in order, each with its own refusal::

    jira . issue . create
      │      │       │
      │      │       └─ operation_unsupported   the record type lacks that op
      │      └───────── entity_unresolved       no record type and no alias
      └──────────────── connector_not_emulated  Worldloom has no such system

An entity is tried two ways: its exact name, then an alias — Jira's ``issue``
is not a record type at all, it stands for epic, story, bug, task and subtask.
A write accepts the alias as readily as a read does, so matching has nothing
to choose here; picking which concrete type to create is choosing an argument
value, which belongs with every other argument value in W3.

Every step is checked before any journey is refused, so a journey with two
problems reports both. That is the courtesy ``load_catalogue`` already
extends, and whoever has to fix a catalogue would rather see the whole list.

This module reads Worldloom's own shipped connector definitions, fresh on
every call, so a renamed entity cannot go unnoticed. It never opens the
customer's catalogue; those bytes arrive already parsed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..connector_definition import is_reference_connector, load_connector_definition
from ..models import Model
from .catalogue import Cuj
from .report import Finding, ImportReport, Severity, hard

if TYPE_CHECKING:
    from ..connector_definition import ConnectorDefinition
    from .catalogue import Catalogue


# --------------------------------------------------------------------------
# The shared vocabulary this module adds to ``Finding.code``.
# --------------------------------------------------------------------------

CONNECTOR_NOT_EMULATED = "connector_not_emulated"
"""Worldloom has no connector of that name, shipped or packaged."""

ENTITY_UNRESOLVED = "entity_unresolved"
"""The connector exists but has no such record type, by name or alias."""

OPERATION_UNSUPPORTED = "operation_unsupported"
"""The record type exists but does not offer that operation."""


# --------------------------------------------------------------------------
# What matching produces.
# --------------------------------------------------------------------------


class MatchedCatalogue(Model):
    """Which journeys Worldloom can build, and what it had to say about them."""

    cujs: tuple[Cuj, ...] = ()
    """The journeys Worldloom can build. These are what W3 builds from."""

    refused: tuple[str, ...] = ()
    """Ids of the journeys that were not built. One hard finding each, at
    least, explains why."""

    report: ImportReport = ImportReport()
    """Every finding, in the order produced."""


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


# --------------------------------------------------------------------------
# Matching a journey, and a whole catalogue.
# --------------------------------------------------------------------------


def match_cuj(cuj: Cuj) -> tuple[Cuj | None, tuple[Finding, ...]]:
    """Check one journey against Worldloom.

    Returns the journey to build and every finding, or ``None`` and the
    reasons it was refused.
    """
    findings: list[Finding] = []

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
            findings.append(hard(
                ENTITY_UNRESOLVED,
                f"{step.connector} has no record type {step.entity!r}, by "
                f"name or alias; step {step.id!r} cannot be built",
                cuj_id=cuj.id,
                detail={"step_id": step.id, "connector": step.connector,
                        "entity": step.entity}))
            # The operation cannot be checked: there is no record type to
            # check it against.
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
    return cuj, tuple(findings)


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
