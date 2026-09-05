"""Native payload shaping driven by connector definitions.

The canonical record remains small and truth-oriented. Wide product payloads are
projections of that record plus its field manifest, so a 300-field Jira issue or
a Microsoft Graph message can stress an agent without inventing a second truth
model.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from hashlib import md5, sha1
from typing import Any

from .connector_definition import ConnectorDefinition, ConnectorFieldDefinition
from .ids import content_key


def _fid(record: Mapping[str, Any]) -> str:
    return str(record.get("fid") or record.get("id") or record.get("external_id") or "record")


def _name(record: Mapping[str, Any]) -> str:
    return str(
        record.get("name")
        or record.get("title")
        or record.get("summary")
        or record.get("subject")
        or _fid(record)
    )


def _entity(record: Mapping[str, Any]) -> str:
    return str(record.get("entity") or "record")


def _text(record: Mapping[str, Any]) -> str:
    if isinstance(record.get("body"), str):
        return str(record["body"])
    if isinstance(record.get("text"), str):
        return str(record["text"])
    content = record.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, Mapping):
        sections = content.get("sections")
        if isinstance(sections, Mapping):
            return "\n".join(f"{title}: {len(values) if isinstance(values, Sequence) and not isinstance(values, str) else 1} items" for title, values in sections.items())
    return ""


def _manifest_value(
    definition: ConnectorDefinition,
    record: Mapping[str, Any],
    field: ConnectorFieldDefinition,
) -> Any:
    for key in (field.canonical, field.id, field.payload_name):
        if key and key in record:
            return record[key]
    chooser = int(content_key("field-population", _fid(record), field.id)[:12], 16)
    if chooser % 10_000 >= int(field.fill_rate * 10_000):
        return None
    token = content_key("field-value", _fid(record), field.id)
    if field.field_type in {"option", "multi_option", "cascading"}:
        if not field.options:
            return None
        first = field.options[int(token[:8], 16) % len(field.options)]
        if field.field_type == "multi_option":
            second = field.options[int(token[8:16], 16) % len(field.options)]
            return [first] if second == first else [first, second]
        if field.field_type == "cascading":
            child = field.options[int(token[16:24], 16) % len(field.options)]
            return {"value": first, "child": {"value": child}}
        return first
    if field.field_type == "integer":
        return int(token[:8], 16) % 10_000
    if field.field_type == "number":
        return round((int(token[:8], 16) % 1_000_000) / 100.0, 2)
    if field.field_type == "boolean":
        return bool(int(token[:2], 16) % 2)
    if field.field_type in {"date", "datetime"}:
        base = datetime.fromisoformat(definition.clock)
        value = base - timedelta(days=int(token[:8], 16) % 730)
        return value.date().isoformat() if field.field_type == "date" else value.isoformat()
    if field.field_type in {"user", "multi_user"}:
        user = {"id": f"user-{token[:12]}", "displayName": f"Synthetic User {token[:6]}"}
        return [user] if field.field_type == "multi_user" else user
    if field.field_type == "reference":
        return f"ref:{token[:16]}"
    if field.field_type == "url":
        return f"https://example.invalid/{token[:20]}"
    if field.field_type == "json":
        return {"key": token[:12], "source": "synthetic-shape"}
    base = f"{field.name} {token[:12]}"
    if field.field_type == "rich_text":
        repetitions = max(1, field.average_bytes // max(1, len(base) + 1))
        return " ".join(base for _ in range(repetitions))[: field.average_bytes]
    return base


def _wide_fields(definition: ConnectorDefinition, record: Mapping[str, Any]) -> dict[str, Any]:
    entity = _entity(record)
    return {
        field.payload_name or field.id: _manifest_value(definition, record, field)
        for field in definition.fields_for(entity)
    }


def _shape_jira(definition: ConnectorDefinition, r: Mapping[str, Any]) -> dict[str, Any]:
    entity = _entity(r)
    status = str(r.get("status") or "todo")
    fields = {
        "summary": r.get("summary") or _name(r),
        "issuetype": {"name": entity.replace("_", " ").title()},
        "status": {"name": {"todo": "To Do", "open": "In Progress", "review": "In Review", "done": "Done", "blocked": "Blocked"}.get(status, status)},
        "priority": {"name": r.get("priority", "Medium")},
        "assignee": ({"displayName": r["assignee"]} if r.get("assignee") else None),
        "labels": r.get("labels", []),
        "project": {"key": r.get("project") or r.get("project_key")},
        "created": r.get("created_at", definition.clock),
        "updated": r.get("modified_at", definition.clock),
        "parent": ({"key": r["parent"]} if r.get("parent") else None),
        "duedate": r.get("due_days") or r.get("due_at"),
    }
    for canonical, payload_name in definition.custom_fields.items():
        if payload_name not in fields:
            fields[payload_name] = r.get(canonical)
    fields.update(_wide_fields(definition, r))
    key = str(r.get("ident") or r.get("external_id") or r.get("key") or _fid(r))
    return {
        "id": str(int(content_key("jira-id", _fid(r))[:10], 16)),
        "key": key,
        "self": f"https://jira.example/rest/api/3/issue/{key}",
        "fields": fields,
    }


def _shape_servicenow(definition: ConnectorDefinition, r: Mapping[str, Any]) -> dict[str, Any]:
    entity = _entity(r)
    state = str(r.get("state") or "new")
    codes = definition.state_codes.get(entity, {})
    assignment = r.get("assignment_group")
    return {
        "sys_id": md5(_fid(r).encode()).hexdigest(),
        "number": r.get("ident") or r.get("external_id"),
        "short_description": r.get("short") or _name(r),
        "description": _text(r),
        "state": codes.get(state, state),
        "dv_state": {"new": "New", "open": "In Progress", "hold": "On Hold", "resolved": "Resolved", "closed": "Closed"}.get(state, state),
        "priority": r.get("priority"),
        "assignment_group": ({"value": md5(str(assignment).encode()).hexdigest(), "display_value": assignment} if assignment else ""),
        "cmdb_ci": {"display_value": r.get("ci")},
        "sys_created_on": r.get("created_at", definition.clock),
        "sys_updated_on": r.get("modified_at", definition.clock),
        **_wide_fields(definition, r),
    }


def _shape_salesforce(definition: ConnectorDefinition, r: Mapping[str, Any]) -> dict[str, Any]:
    entity = _entity(r)
    typ = definition.query_name_for(entity)
    sid = str(r.get("ident") or r.get("external_id") or (sha1(_fid(r).encode()).hexdigest()[:15].upper() + "AAA"))
    out: dict[str, Any] = {
        "attributes": {"type": typ, "url": f"/services/data/v61.0/sobjects/{typ}/{sid}"},
        "Id": sid,
        "Name": _name(r),
        "LastModifiedDate": r.get("modified_at", definition.clock),
    }
    mappings = {
        "stage": "StageName",
        "amount": "Amount",
        "close": "CloseDate",
        "closed": "IsClosed",
        "next_step": "NextStep",
        "company": "AccountName",
        "subject": "Subject",
        "status": "Status",
        "severity": "Priority",
        "region": "BillingCountry",
        "title": "Title",
        "source": "LeadSource",
    }
    for source, target in mappings.items():
        if source in r:
            out[target] = r[source]
    out.update(_wide_fields(definition, r))
    return out


def _shape_confluence(definition: ConnectorDefinition, r: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(r.get("ident") or abs(int(content_key("conf", _fid(r))[:12], 16)) % 10**8),
        "type": definition.query_name_for(_entity(r)),
        "status": "archived" if r.get("archived") else "current",
        "title": _name(r),
        "space": {"key": r.get("space")},
        "version": {"number": 1 + len(r.get("updates", []))},
        "ancestors": ([{"title": r["parent"]}] if r.get("parent") else []),
        "body": {"storage": {"value": "<p>" + _text(r).replace("\n", "</p><p>") + "</p>", "representation": "storage"}},
        **_wide_fields(definition, r),
    }


def _mime(entity: str) -> str | None:
    return {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "pdf": "application/pdf",
        "gdoc": "application/vnd.google-apps.document",
        "gsheet": "application/vnd.google-apps.spreadsheet",
        "gslides": "application/vnd.google-apps.presentation",
        "folder": "application/vnd.google-apps.folder",
    }.get(entity)


def _shape_sharepoint(definition: ConnectorDefinition, r: Mapping[str, Any]) -> dict[str, Any]:
    entity = _entity(r)
    item_id = str(r.get("ident") or r.get("external_id") or md5(_fid(r).encode()).hexdigest().upper()[:34])
    out: dict[str, Any] = {
        "id": item_id,
        "name": _name(r),
        "webUrl": r.get("web_url") or f"https://contoso.sharepoint.com/{item_id}",
        "lastModifiedDateTime": r.get("modified_at", definition.clock),
        "parentReference": {"path": r.get("parent") or r.get("parent_path")},
    }
    mime = _mime(entity)
    if mime:
        out["file"] = {"mimeType": mime}
        out["content"] = _text(r)
    if entity == "folder":
        out["folder"] = {"childCount": int(r.get("child_count", 0))}
    out.update(_wide_fields(definition, r))
    return out


def _shape_drive(definition: ConnectorDefinition, r: Mapping[str, Any]) -> dict[str, Any]:
    item_id = str(r.get("ident") or r.get("external_id") or sha1(_fid(r).encode()).hexdigest()[:33])
    return {
        "id": item_id,
        "name": _name(r),
        "mimeType": _mime(_entity(r)) or r.get("mime_type") or "application/octet-stream",
        "parents": [r.get("folder") or r.get("parent")],
        "modifiedTime": r.get("modified_at", definition.clock),
        "webViewLink": f"https://docs.google.com/d/{item_id}",
        "content": None if _entity(r) == "folder" else _text(r),
        **_wide_fields(definition, r),
    }


def _shape_outlook(definition: ConnectorDefinition, r: Mapping[str, Any]) -> dict[str, Any]:
    message_id = str(r.get("ident") or r.get("external_id") or sha1(_fid(r).encode()).hexdigest())
    sender = str(r.get("sender") or r.get("from") or "sender@example.invalid")
    recipients = r.get("recipients") or r.get("to") or []
    if isinstance(recipients, str):
        recipients = [recipients]
    return {
        "id": message_id,
        "conversationId": r.get("conversation") or r.get("thread_id"),
        "subject": r.get("subject") or _name(r),
        "bodyPreview": _text(r)[:255],
        "body": {"contentType": "html", "content": _text(r)},
        "from": {"emailAddress": {"address": sender, "name": r.get("sender_name")}},
        "toRecipients": [{"emailAddress": {"address": str(value)}} for value in recipients],
        "receivedDateTime": r.get("received_at") or r.get("created_at", definition.clock),
        "sentDateTime": r.get("sent_at") or r.get("created_at", definition.clock),
        "isRead": bool(r.get("is_read", False)),
        "hasAttachments": bool(r.get("attachments")),
        "importance": r.get("importance", "normal"),
        **_wide_fields(definition, r),
    }


def _shape_onedrive(definition: ConnectorDefinition, r: Mapping[str, Any]) -> dict[str, Any]:
    item_id = str(r.get("ident") or r.get("external_id") or sha1(_fid(r).encode()).hexdigest()[:34])
    entity = _entity(r)
    out: dict[str, Any] = {
        "id": item_id,
        "name": _name(r),
        "size": int(r.get("size", r.get("file_size_bytes", 0)) or 0),
        "createdDateTime": r.get("created_at", definition.clock),
        "lastModifiedDateTime": r.get("modified_at", definition.clock),
        "parentReference": {"path": r.get("parent") or r.get("folder")},
        "webUrl": r.get("web_url") or f"https://onedrive.example/{item_id}",
    }
    if entity == "folder":
        out["folder"] = {"childCount": int(r.get("child_count", 0))}
    else:
        out["file"] = {"mimeType": _mime(entity) or r.get("mime_type") or "application/octet-stream"}
        out["content"] = _text(r)
    out.update(_wide_fields(definition, r))
    return out


def _shape_teams(definition: ConnectorDefinition, r: Mapping[str, Any]) -> dict[str, Any]:
    record_id = str(r.get("ident") or r.get("external_id") or content_key("teams", _fid(r))[:24])
    entity = _entity(r)
    if entity in {"team", "channel", "chat", "member"}:
        return {
            "id": record_id,
            "displayName": _name(r),
            "description": r.get("description"),
            "membershipType": r.get("membership_type"),
            **_wide_fields(definition, r),
        }
    return {
        "id": record_id,
        "replyToId": r.get("reply_to") or r.get("thread_ts"),
        "chatId": r.get("chat"),
        "channelIdentity": {"teamId": r.get("team"), "channelId": r.get("channel")},
        "createdDateTime": r.get("created_at", definition.clock),
        "lastModifiedDateTime": r.get("modified_at", definition.clock),
        "from": {"user": {"displayName": r.get("sender")}},
        "body": {"contentType": "html", "content": _text(r)},
        "importance": r.get("importance", "normal"),
        "mentions": r.get("mentions", []),
        "attachments": r.get("attachments", []),
        **_wide_fields(definition, r),
    }


def _shape_slack(definition: ConnectorDefinition, r: Mapping[str, Any]) -> dict[str, Any]:
    ts = str(r.get("ts") or r.get("ident") or r.get("external_id") or f"{int(content_key('slack', _fid(r))[:10], 16)}.000001")
    return {
        "type": "message",
        "ts": ts,
        "thread_ts": r.get("thread_ts") or r.get("reply_to"),
        "channel": r.get("channel"),
        "user": r.get("sender") or r.get("user"),
        "text": _text(r) or _name(r),
        "files": r.get("attachments", []),
        "reactions": r.get("reactions", []),
        **_wide_fields(definition, r),
    }


def _shape_teamwork_graph(definition: ConnectorDefinition, r: Mapping[str, Any]) -> dict[str, Any]:
    ari = str(r.get("ari") or r.get("ident") or r.get("external_id") or f"ari:cloud:worldloom::{_entity(r)}/{content_key(_fid(r))[:16]}")
    return {
        "id": ari,
        "ari": ari,
        "__typename": definition.query_name_for(_entity(r)),
        "displayName": _name(r),
        "description": _text(r),
        "url": r.get("url"),
        "createdAt": r.get("created_at", definition.clock),
        "updatedAt": r.get("modified_at", definition.clock),
        "relationships": r.get("relationships", []),
        **_wide_fields(definition, r),
    }


def _shape_rovo(definition: ConnectorDefinition, r: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": r.get("ari") or r.get("ident") or r.get("external_id") or _fid(r),
        "type": definition.query_name_for(_entity(r)),
        "title": _name(r),
        "text": _text(r),
        "source": r.get("source") or r.get("server") or r.get("connector"),
        "url": r.get("url"),
        "author": r.get("author") or r.get("sender"),
        "modifiedAt": r.get("modified_at", definition.clock),
        **_wide_fields(definition, r),
    }


_SHAPERS = {
    "jira_issue": _shape_jira,
    "servicenow_record": _shape_servicenow,
    "salesforce_sobject": _shape_salesforce,
    "confluence_page": _shape_confluence,
    "sharepoint_item": _shape_sharepoint,
    "drive_file": _shape_drive,
    "msgraph_message": _shape_outlook,
    "msgraph_drive_item": _shape_onedrive,
    "msgraph_chat_message": _shape_teams,
    "slack_message": _shape_slack,
    "atlassian_graph_object": _shape_teamwork_graph,
    "rovo_search_result": _shape_rovo,
}


def shape_payload(
    definition: ConnectorDefinition,
    record: Mapping[str, Any],
    fields: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Project one canonical record into the connector's native payload shape."""

    try:
        out = _SHAPERS[definition.payload_shape](definition, record)
    except KeyError as error:
        raise ValueError(f"unsupported payload shape {definition.payload_shape!r}") from error
    if not fields:
        return out
    requested = set(fields)
    if definition.payload_shape == "jira_issue":
        nested = out.get("fields", {})
        out = dict(out)
        out["fields"] = {key: value for key, value in nested.items() if key in requested}
        return out
    identity = {"id", "Id", "sys_id", "key", "number", "attributes", "ts", "ari", "type"}
    return {key: value for key, value in out.items() if key in requested or key in identity}


__all__ = ["shape_payload"]
