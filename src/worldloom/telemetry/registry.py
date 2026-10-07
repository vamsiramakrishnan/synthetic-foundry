"""Matching the catalogue's words against what Worldloom can emulate.

The catalogue records what a customer's assistant *did*, in that customer's
vocabulary: connector keys, entity names and operation names exactly as their
tool calls spelled them. Worldloom knows what it can *fake*. These are two
vocabularies, and this module introduces them.

Four questions per step, asked in order, each with its own refusal::

    jira . issue . create
      │      │       │
      │      │       ├─ operation_unsupported   no record type behind the name
      │      │       │                          offers that operation
      │      │       └─ operation_ambiguous     an alias's members disagree on
      │      │                                  which tool performs it
      │      └───────── entity_unresolved       no record type, by name or alias
      └──────────────── connector_not_emulated  Worldloom has no such system

An entity is tried two ways: its exact name, then an alias — Jira's ``issue``
is not a record type at all, it stands for epic, story, bug, task and subtask.

A journey is matched exactly as the customer recorded it, or refused. It is
never rewritten to fit what Worldloom models today. An earlier version folded
a lookup of something Worldloom did not model — a Jira project — into a field
on a later step. That broke the catalogue's own invariants (a phrasing slot
and two failure modes were left pointing at a deleted step, and the journey's
id no longer hashed from its steps), and it quietly lost the failures the
customer had recorded against that lookup: "picked the wrong project" is
exactly the case a test should cover.

So instead of reshaping the journey, matching says what Worldloom would need
to import it properly. :attr:`MatchedCatalogue.missing` lists every missing
connector, entity and operation, with the journeys that need it and their
share of real traffic, largest first::

    jira.project   entity   search   cuj_9636dd61a048   22 sessions, 22.9%

That list is a to-do list for the connector definitions, prioritised by real
usage. Adding the entity — the way Jira already models ``sprint`` — makes the
journey match unchanged.

Refusal is per journey: one journey needing a missing entity does not stop the
others. ``worldloom telemetry import --strict`` turns any refusal into a
refused import.

This module reads Worldloom's own shipped connector definitions, once per
:func:`match_catalogue` call, so every journey in a run is matched against the
same definitions and a renamed entity cannot go unnoticed between runs. It
never opens the customer's catalogue; those bytes arrive already parsed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ..connector_definition import is_reference_connector, load_connector_definition
from ..models import Model
from .catalogue import Cuj
from .report import Finding, ImportReport, hard

if TYPE_CHECKING:
    from ..connector_definition import ConnectorDefinition
    from .catalogue import Catalogue

    #: Connector definitions already loaded in this run, ``None`` for a
    #: connector Worldloom does not have.
    Definitions = dict[str, ConnectorDefinition | None]

    Gap = Literal["connector", "entity", "operation"]


# --------------------------------------------------------------------------
# The shared vocabulary this module adds to ``Finding.code``.
# --------------------------------------------------------------------------

CONNECTOR_NOT_EMULATED = "connector_not_emulated"
"""Worldloom has no connector of that name, shipped or packaged."""

ENTITY_UNRESOLVED = "entity_unresolved"
"""The connector exists but has no such record type, by name or alias."""

OPERATION_UNSUPPORTED = "operation_unsupported"
"""The record type exists but none of what it stands for offers that
operation."""

OPERATION_AMBIGUOUS = "operation_ambiguous"
"""An alias whose members map the operation to different tools, so there is
no single tool to call. A fault in the connector definition, not a gap in it,
which is why it is not reported as unsupported."""


# --------------------------------------------------------------------------
# What matching produces.
# --------------------------------------------------------------------------


class MissingCapability(Model):
    """One thing Worldloom would need before some journeys can be imported."""

    kind: Literal["connector", "entity", "operation"]
    connector: str
    entity: str = ""
    operations: tuple[str, ...] = ()
    """The operations the journeys asked of it."""

    cuj_ids: tuple[str, ...] = ()
    """Every journey refused for want of this."""

    sessions: int = 0
    share: float = 0.0
    """Of real traffic, summed over those journeys. What to add first."""

    @property
    def name(self) -> str:
        return ".".join(part for part in (self.connector, self.entity) if part)


class MatchedCatalogue(Model):
    """Which journeys Worldloom can build, and what it would need for the rest."""

    cujs: tuple[Cuj, ...] = ()
    """The journeys that matched, exactly as the catalogue recorded them."""

    refused: tuple[str, ...] = ()
    """Ids of the journeys that did not. One hard finding each, at least,
    explains why."""

    missing: tuple[MissingCapability, ...] = ()
    """What Worldloom would need to import the refused journeys, largest
    share of traffic first."""

    report: ImportReport = ImportReport()
    """Every finding, in the order produced."""


# --------------------------------------------------------------------------
# Matching one step.
# --------------------------------------------------------------------------


def _definition(connector: str, loaded: Definitions) -> ConnectorDefinition | None:
    """The definition for *connector*, loaded at most once per run.

    Once per run rather than once per step: every journey in one import is
    then matched against the same definitions, and a catalogue of forty
    journeys does not read the same file forty times.
    """
    if connector not in loaded:
        loaded[connector] = (load_connector_definition(connector)
                             if is_reference_connector(connector) else None)
    return loaded[connector]


def _members(definition: ConnectorDefinition, entity: str) -> tuple[str, ...]:
    """The record types *entity* names, directly or through an alias; empty
    when it names none."""
    try:
        return definition.entity_members(entity)
    except KeyError:
        return ()


def _tools(definition: ConnectorDefinition, members: tuple[str, ...],
           operation: str) -> set[str]:
    """Every tool the members map *operation* to. One is a match; none is
    unsupported; more than one is ambiguous. ``tool_for`` raises the same
    ``KeyError`` for the last two, so they are told apart here."""
    return {definition.entities[member].ops[operation]
            for member in members
            if operation in definition.entities[member].ops}


def _step_findings(cuj: Cuj, loaded: Definitions) -> list[Finding]:
    findings: list[Finding] = []
    for step in cuj.steps:
        # A capability step calls nothing, so there is nothing to match. The
        # three-way test narrows the optional fields for the checker too.
        if step.connector is None or step.entity is None or step.operation is None:
            continue
        where = {"step_id": step.id, "connector": step.connector}

        definition = _definition(step.connector, loaded)
        if definition is None:
            findings.append(hard(
                CONNECTOR_NOT_EMULATED,
                f"Worldloom has no connector named {step.connector!r}, so "
                f"step {step.id!r} cannot be built",
                cuj_id=cuj.id, detail={**where, "operation": step.operation}))
            continue

        members = _members(definition, step.entity)
        if not members:
            findings.append(hard(
                ENTITY_UNRESOLVED,
                f"{step.connector} has no record type {step.entity!r}, by name "
                f"or alias, so step {step.id!r} cannot be built. Add it to the "
                f"{step.connector} connector definition to import this journey",
                cuj_id=cuj.id,
                detail={**where, "entity": step.entity,
                        "operation": step.operation}))
            continue

        tools = _tools(definition, members, step.operation)
        if len(tools) > 1:
            findings.append(hard(
                OPERATION_AMBIGUOUS,
                f"{step.connector}.{step.entity} stands for {', '.join(members)}, "
                f"which map {step.operation!r} to different tools "
                f"({', '.join(sorted(tools))}); step {step.id!r} has no single "
                "tool to call",
                cuj_id=cuj.id,
                detail={**where, "entity": step.entity,
                        "operation": step.operation,
                        "tools": ",".join(sorted(tools))}))
        elif not tools:
            findings.append(hard(
                OPERATION_UNSUPPORTED,
                f"{step.connector}.{step.entity} does not support "
                f"{step.operation!r}, so step {step.id!r} cannot be built",
                cuj_id=cuj.id,
                detail={**where, "entity": step.entity,
                        "operation": step.operation}))
    return findings


# --------------------------------------------------------------------------
# Matching a journey, and a whole catalogue.
# --------------------------------------------------------------------------


def match_cuj(cuj: Cuj, *, definitions: Definitions | None = None,
              ) -> tuple[Cuj | None, tuple[Finding, ...]]:
    """Check one journey against Worldloom.

    Returns the journey unchanged and no findings, or ``None`` and every
    reason it was refused. Every step is checked before the journey is
    refused, so a journey with two problems reports both — the same courtesy
    ``load_catalogue`` extends in W1.

    *definitions* carries connector definitions between journeys of one run;
    :func:`match_catalogue` passes one in.
    """
    findings = _step_findings(cuj, {} if definitions is None else definitions)
    return (None, tuple(findings)) if findings else (cuj, ())


def _missing(catalogue: Catalogue,
             findings: list[Finding]) -> tuple[MissingCapability, ...]:
    """Every refusal, grouped by what Worldloom would need to add.

    An ambiguous operation is not here: the record type and the operation
    both exist, and what needs fixing is the definition's mapping, not a
    gap in what it covers.
    """
    kinds: dict[str, Gap] = {CONNECTOR_NOT_EMULATED: "connector",
                             ENTITY_UNRESOLVED: "entity",
                             OPERATION_UNSUPPORTED: "operation"}
    support = {cuj.id: cuj.support for cuj in catalogue.cujs}
    grouped: dict[tuple[Gap, str, str], tuple[set[str], set[str]]] = {}
    for finding in findings:
        kind = kinds.get(finding.code)
        if kind is None:
            continue
        entity = "" if kind == "connector" else finding.detail.get("entity", "")
        operations, journeys = grouped.setdefault(
            (kind, finding.detail["connector"], entity), (set(), set()))
        operations.add(finding.detail.get("operation", ""))
        journeys.add(finding.cuj_id)

    missing = [
        MissingCapability(
            kind=kind, connector=connector, entity=entity,
            operations=tuple(sorted(op for op in operations if op)),
            cuj_ids=tuple(sorted(journeys)),
            sessions=sum(support[cuj_id].sessions for cuj_id in journeys),
            share=round(sum(support[cuj_id].share for cuj_id in journeys), 6))
        for (kind, connector, entity), (operations, journeys) in grouped.items()]
    return tuple(sorted(missing, key=lambda item: (-item.share, item.name,
                                                   item.kind)))


def match_catalogue(catalogue: Catalogue) -> MatchedCatalogue:
    """Check every journey in *catalogue* against Worldloom.

    One journey's refusal does not stop the others: a catalogue naming a
    connector we do not have should still yield the journeys that only use
    connectors we do. What the refused ones would need is collected into
    :attr:`MatchedCatalogue.missing`.
    """
    loaded: Definitions = {}
    built: list[Cuj] = []
    refused: list[str] = []
    findings: list[Finding] = []

    for cuj in catalogue.cujs:
        matched, cuj_findings = match_cuj(cuj, definitions=loaded)
        findings.extend(cuj_findings)
        if matched is None:
            refused.append(cuj.id)
        else:
            built.append(matched)

    return MatchedCatalogue(cujs=tuple(built), refused=tuple(refused),
                            missing=_missing(catalogue, findings),
                            report=ImportReport(findings=tuple(findings)))
