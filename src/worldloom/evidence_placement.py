"""Where a record write keeps its evidence: the connector's declared place, read by planner, emulator and grader.

A gold plan that writes a record carries the evidence it rests on. It used to
carry it as two fields no vendor has (``evidence``, ``evidence_count``): the
emulator's own tools took any field, so every case proved on the native
surface, and a Graph driveItem ``PATCH``, a Confluence page ``PUT`` and a
Salesforce sObject ``PATCH`` carried neither, so the same plans failed on the
contract surface. A competent employee puts evidence where the product keeps
it: a SharePoint or Drive file's description, a Confluence page's body, a
ServiceNow record's work notes.

The place is data (``ConnectorEvidencePlacement``, under a connector
definition's ``catalog.evidence`` or one catalog entity's ``evidence``), so a
connector declares its own and nothing here names a vendor:

- the planner (``enterprise_dag_planning``) renders the evidence as a
  document (``outline`` over the evidence, the case's sections or one
  ``Evidence`` section, in the place's format) and binds it to
  ``fields.<place>``; a place that ``read_first`` reads the record before
  the write; a place the shipped contract cannot carry (``unserved``) is not
  planned at all;
- the emulator keeps the write where the tool puts it, on both surfaces,
  because the contract surface dispatches to the same connector tool with
  the same fields;
- the output grade (``evalrun.stages``) reads every bound ``fields.*``
  value back from the written record, so it reads the evidence from the
  place the plan put it.

A connector that declares no place keeps the generic fields, which only the
emulator's own tools take: a pack connector written before places existed
still plans and runs on the native surface.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .connector_definition import ConnectorDefinition, ConnectorEvidencePlacement

#: Writes whose content is a message body, not a record's fields.
MESSAGE_OPERATIONS = frozenset({"reply", "forward", "comment"})
#: Writes that carry no content at all: the tool takes the record id (and a parent).
CONTENTLESS_OPERATIONS = frozenset({"delete", "move"})
#: The section an evidence document has when the case names none.
EVIDENCE_SECTION = "Evidence"
#: The fields a write of a connector that declares no place carries.
LEGACY_FIELDS = ("evidence", "evidence_count")


def carries_evidence(operation: str) -> bool:
    """Whether a write of *operation* carries the evidence as record fields (not a message body, not nothing)."""

    return operation not in MESSAGE_OPERATIONS and operation not in CONTENTLESS_OPERATIONS


@lru_cache(maxsize=256)
def placement(connector: str, entity: str) -> ConnectorEvidencePlacement | None:
    """The declared place for a write of *connector*'s *entity*, or ``None`` when it declares none.

    A connector the installed definitions do not know has no place, as a
    connector that declares none has not.
    """

    from .connector_definition import load_connector_definition

    try:
        definition = load_connector_definition(connector)
    except (KeyError, ValueError):
        return None
    return definition.evidence_placement(entity)


def plannable(connector: str, entity: str, operation: str) -> bool:
    """Whether an evidence write of *operation* on *connector*'s *entity* may be planned.

    Refused only for a declared place the shipped contract cannot carry
    (``unserved``): the vendor keeps evidence there, and no agent on the
    contract surface could put it there, so a case that asked would be
    unsolvable by construction.
    """

    if not carries_evidence(operation):
        return True
    found = placement(connector, entity)
    return found is None or found.unserved is None


def contract_gap(definition: ConnectorDefinition, entity: str, operation: str) -> str | None:
    """Why the shipped contract surface cannot carry an evidence write to *entity*'s place, or ``None``.

    A representative write (a create names a file with its extension; an
    update addresses a record the vendor numbers) is carried through the
    connector's shipped surface (``ContractSurface.carry``). ``None`` also
    when the connector ships no surface or declares no place. The schema
    check that decides some gaps (Confluence's body union) needs
    ``jsonschema``; without it the answer can only be more permissive, which
    is why the planner reads the declared ``unserved`` instead of this, and
    the test holds the two together.
    """

    from .connectors.surface import SurfaceError, shipped_surface, shipped_surfaces
    from .enterprise_rows import create_payload
    from .enterprise_runner import canonical_operation

    found = definition.evidence_placement(entity)
    if found is None or definition.connector not in shipped_surfaces():
        return None
    surface = shipped_surface(definition.connector)
    members = definition.entity_members(entity)
    listed = definition.catalog_entities().get(entity)
    formats = [item for item in listed.formats if item in members] if listed is not None else []
    concrete = (formats or list(members) or [entity])[0]
    fields = {found.field: "## Evidence\n\n- probe"}
    preexisting = (True, False) if operation == "upsert" else (operation not in {"create", "draft", "send", "post", "upload"},)
    for existing in preexisting:
        canonical = canonical_operation(operation, preexisting_record=existing)
        try:
            tool = definition.tool_for(concrete, canonical)
        except (KeyError, ValueError) as error:
            return str(error)
        op = definition.tool(tool).op
        record: Mapping[str, Any] | None = None
        if op in {"create", "send", "post", "upload"}:
            payload = create_payload(definition, concrete, "evidence-probe", "write")
            args: dict[str, Any] = {**payload, "entity": concrete, "fields": {**payload["fields"], **fields}}
            args = {key: value for key, value in args.items() if key in definition.tool(tool).params}
        else:
            args = {"id": "1001", "fields": fields}
            record = {"fid": "1001", "id": "1001", "ident": "1001", "external_id": "1001", "server": definition.connector,
                      "entity": concrete, "title": "Probe", "name": "Probe", "version": 1}
        try:
            surface.carry(tool, args, definition, record=record)
        except SurfaceError as error:
            return str(error)
    return None


def document_arguments(sections: tuple[str, ...], fmt: str, note: str | None = None) -> dict[str, Any]:
    """The ``outline`` transform's arguments for an evidence document: the case's sections, else one."""

    arguments: dict[str, Any] = {"sections": sections or (EVIDENCE_SECTION,), "format": fmt}
    if note:
        arguments["note"] = note
    return arguments


__all__ = [
    "CONTENTLESS_OPERATIONS",
    "EVIDENCE_SECTION",
    "LEGACY_FIELDS",
    "MESSAGE_OPERATIONS",
    "carries_evidence",
    "contract_gap",
    "document_arguments",
    "placement",
    "plannable",
]
