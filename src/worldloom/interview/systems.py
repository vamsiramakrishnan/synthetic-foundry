"""The systems an interviewed process can touch, and where each one keeps a step.

A system name is a connector the emulator serves. A *step* on a system is the
record that system holds for one process event: a ServiceNow change request,
a Salesforce case, a Slack message, a Jira issue. Jira and email already carry
one record per world event (``connector_data.generate_jira`` /
``generate_email``), so a step there enriches the record the engine already
projects rather than minting a second; every other system gets a record of
its own carrying the event's facts and ids. Documents live where the engine's
artifact projection already puts them (SharePoint, Confluence, Drive).
"""

from __future__ import annotations

#: System name -> (connector, the entity one process step leaves there).
STEP_ENTITIES: dict[str, tuple[str, str]] = {
    "confluence": ("confluence", "page"),
    "email": ("email", "message"),
    "jira": ("jira", "issue"),
    "outlook": ("outlook", "message"),
    "salesforce": ("salesforce", "case"),
    "servicenow": ("servicenow", "change_request"),
    "sharepoint": ("sharepoint", "list_item"),
    "slack": ("slack", "message"),
}

#: Systems whose engine projection already holds one record per world event.
EVENT_PROJECTED: frozenset[str] = frozenset({"jira", "email"})

#: Systems the engine's artifact projection publishes documents on, and the
#: entity a search for a document names there.
DOCUMENT_ENTITIES: dict[str, str] = {
    "confluence": "page",
    "drive": "file",
    "sharepoint": "file",
}

#: Every system an interview may name.
SYSTEMS: tuple[str, ...] = tuple(sorted(set(STEP_ENTITIES) | set(DOCUMENT_ENTITIES)))


def step_entity(system: str) -> tuple[str, str]:
    """``(connector, entity)`` for a step on *system*; ``KeyError`` for a system with no steps."""
    return STEP_ENTITIES[system]


def writable(system: str, entity: str, operation: str, output_format: str = "record") -> str:
    """Why *system* cannot perform *operation* on *entity* (or its *output_format* member); empty when it can.

    The compiler's own rule (``enterprise_rows._tool_name``): an alias entity
    (Jira's ``issue``, SharePoint's ``file``) needs a concrete member named by
    the format before anything is created in it.
    """
    from ..connector_definition import load_connector_definition

    try:
        definition = load_connector_definition(system)
        members = definition.entity_members(entity)
        concrete = output_format if output_format in members else entity
        definition.tool_for(concrete, operation)
    except (KeyError, ValueError):
        return f"{system} has no tool to {operation} a {entity}"
    if len(members) > 1 and concrete == entity and operation in {"create", "draft", "send", "post", "upload"}:
        return f"{system} {entity} is one of {', '.join(members)}; name the one to {operation} as `format`"
    return ""


__all__ = ["DOCUMENT_ENTITIES", "EVENT_PROJECTED", "STEP_ENTITIES", "SYSTEMS", "step_entity", "writable"]
